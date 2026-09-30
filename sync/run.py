"""Запуск синхронизации.

Один проход:
  1. Поиск: ГИР БО по классам ОКВЭД 10–33 в каждом субъекте РФ → действующие промышленные компании.
  2. Отбор новых: ИНН юрлица, статус «действует», выручка не ниже порога, не больше MAX_NEW_PER_RUN за запуск
     (самые крупные первыми: первый обход растягивается на несколько дней).
  3. Проверка каждой компании базы и каждой новой:
       ежедневно — ЕГРЮЛ (статус, реквизиты) и Федресурс (банкротство);
       раз в неделю, для новых и при смене статуса — «Прозрачный бизнес», ГИР БО и Checko (если задан ключ).
  4. Слияние и запись в PostgreSQL: карточки и справочники — база sm01_catalog (ревизия каталога растёт, API
     перечитывает данные сам), журнал прохода — база sm01_ingest. Файлов и коммитов в Git сбор не создаёт.

Примеры:
  python -m sync                     # полный проход
  python -m sync --dry-run --limit 5 # проверить 5 компаний базы без записи
  python -m sync --no-discover       # только обновить компании, которые уже в базе
  python -m sync --daemon            # каждый день в 00:01 и по кнопке «Запустить сбор» в админ-панели
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import config, control, merge, sitecrawl
from .http import Http, SourceError
from .providers import checko, egrul, fedresurs, girbo, minpromtorg, opendata, pb, rmsp
from .risks import status, status_of_text
from .store import Store

DEEP_EVERY_DAYS = 7


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def discover(http: Http, regions: list[str], divisions: list[str], errors: list) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for rc in regions:
        reg = config.REGIONS[rc]
        n0 = len(found)
        for d in divisions:
            try:
                for row in girbo.discover(http, d, reg):
                    if row["inn"]:
                        found.setdefault(row["inn"], dict(row, region=rc))
            except SourceError as e:
                errors.append({"source": "girbo", "where": f"поиск {reg['name']}, ОКВЭД {d}", "error": str(e)})
        log(f"поиск: {reg['name']} — {len(found) - n0} организаций")
    return found


def save_found(path: str, regions: list[str] | None = None, divisions: list[str] | None = None) -> dict:
    """Поиск по регионам — в файл JSON (ИНН → строка ГИР БО): идёт без блокировки сбора, параллельно с другим запуском."""
    errors: list = []
    found = discover(Http(), regions or config.SYNC_REGIONS, divisions or config.OKVED_DIVISIONS, errors)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False)
    os.replace(tmp, path)
    log(f"поиск сохранён: {len(found)} организаций → {path}; ошибок: {len(errors)}")
    return found


class Budget:
    """Ограничение числа обращений к медленному источнику за запуск (потокобезопасно)."""
    def __init__(self, n: int):
        self.left, self.lock = n, threading.Lock()

    def take(self) -> bool:
        with self.lock:
            if self.left <= 0:
                return False
            self.left -= 1
            return True


PB_BUDGET = Budget(config.PB_PER_RUN)


def check(http: Http, inn: str, deep: bool, girbo_row: dict | None, girbo_id: str | None, od: dict | None = None) -> dict:
    res = {"inn": inn, "girbo_row": girbo_row, "ok": [], "not_found": [], "errors": {}}
    if od:
        res["opendata"] = opendata.lookup(od, inn)
        res["ok"].append("opendata")
    steps = [("egrul", lambda: egrul.fetch(http, inn)), ("fedresurs", lambda: fedresurs.fetch(http, inn))]
    if deep and not http.blocked(pb.URL) and PB_BUDGET.take():
        steps.append(("pb", lambda: pb.fetch(http, inn)))
    if deep:
        steps.append(("girbo", lambda: girbo.fetch(http, inn, girbo_id or (res.get("pb") or {}).get("girbo_id"))))
        if checko.enabled():
            steps.append(("checko", lambda: checko.fetch(http, inn)))
    for key, fn in steps:
        try:
            data = fn()
        except SourceError as e:
            res["errors"][key] = str(e)
            continue
        except Exception as e:   # неожиданный формат ответа не должен останавливать весь проход
            res["errors"][key] = f"{type(e).__name__}: {e}"
            continue
        if data is None:
            res["not_found"].append(key)
        else:
            res[key] = data
            res["ok"].append(key)
    return res


def fast_res(row: dict, od: dict | None) -> dict:
    """Новая компания без запросов по ИНН (--fast): строка поиска ГИР БО (ИНН, ОГРН, название, ОКВЭД, статус, выручка)
    и открытые данные ФНС. ЕГРЮЛ, Федресурс и полную отчётность карточка получит в следующих сборах."""
    try:
        years = [{"year": int(row["period"]), "revenue": row["revenue_k"], "net_profit": None, "assets": None, "equity": None,
                  "liabilities": None}]
    except (TypeError, ValueError):
        years = []
    g = {"girbo_id": row["girbo_id"], "url": f"{girbo.URL}/organizations-card/{row['girbo_id']}", "years": years, "okpo": None,
         "okved_main": row.get("okved_main"), "okved_main_name": None}
    res = {"inn": row["inn"], "girbo_row": row, "girbo": g, "ok": ["girbo"], "not_found": [], "errors": {}, "region": row["region"]}
    if od:
        res["opendata"] = opendata.lookup(od, row["inn"])
        res["ok"].append("opendata")
    return res


def needs_deep(c: dict, today: date, force: bool) -> bool:
    if force:
        return True
    last = (c.get("registry") or {}).get("deep_checked_at")
    return not last or date.fromisoformat(last) <= today - timedelta(days=DEEP_EVERY_DAYS)


def run(args, trigger: str = "вручную из командной строки") -> dict | None:
    """Один проход сбора. Два прохода одновременно не запускаются: они испортили бы файлы базы."""
    if args.dry_run:
        return _run(args, lambda **kw: None, trigger)
    if not control.acquire({"trigger": trigger}):
        log("сбор уже идёт в другом процессе, этот запуск пропущен")
        return None
    started = control.now_iso()
    report = lambda **kw: control.update_status(**kw)
    report(state="running", trigger=trigger, started_at=started, stage="поиск новых компаний", done=0, total=None, error=None)
    doc = None
    try:
        with control.Heartbeat():
            doc = _run(args, report, trigger)
        return doc
    except Exception as e:
        report(error=f"{type(e).__name__}: {e}")
        raise
    finally:
        control.release()
        last = {k: doc[k] for k in ("at", "finished", "found", "queued_new", "stats")} if doc else None
        report(state="idle", stage=None, done=None, total=None, last_run=last, last_trigger=trigger, last_started_at=started)


def _run(args, report, trigger: str | None = None) -> dict:
    today = date.fromisoformat(args.today) if args.today else date.today()
    PB_BUDGET.left = args.pb_limit
    started = datetime.now()
    http = Http(delay=args.delay)
    store = Store()
    errors: list[dict] = []
    regions = args.regions.split(",") if args.regions else config.SYNC_REGIONS
    divisions = args.okved.split(",") if args.okved else config.OKVED_DIVISIONS

    if args.found:   # результат поиска, сохранённый заранее (save_found): без повторного обхода ГИР БО
        with open(args.found, encoding="utf-8") as f:
            found = json.load(f)
        log(f"поиск: {len(found)} организаций из файла {args.found}")
    else:
        found = {} if args.no_discover else discover(http, regions, divisions, errors)
    by_inn = store.by_inn()

    # новые компании: самые крупные по выручке первыми
    min_revenue = max(1, args.min_revenue)   # компании без выручки не добавляются ни при каких настройках
    fresh = [r for inn, r in found.items() if inn not in by_inn and len(inn) == 10 and r["status"] == "ACTIVE"
             and (r["revenue_k"] or 0) >= min_revenue]
    fresh.sort(key=lambda r: -(r["revenue_k"] or 0))
    eligible = len(fresh)   # все подходящие новые: что не войдёт в этот запуск, остаётся в очереди
    if args.per_region:   # не больше N новых на регион, самые крупные первыми: быстро заполнить все регионы
        taken: dict[str, int] = {}
        fresh = [r for r in fresh if taken.setdefault(r["region"], 0) < args.per_region and not taken.update({r["region"]: taken[r["region"]] + 1})]
    fresh = fresh[:args.max_new]
    skipped_new = eligible - len(fresh)

    existing = [] if args.only_new else [cid for cid, c in store.companies.items() if c.get("inn") and len(c["inn"]) in (10, 12)]
    if args.max_check and len(existing) > args.max_check:   # по кругу: давно проверенные первыми, остальные — в следующие запуски
        existing.sort(key=lambda cid: (store.companies[cid].get("registry") or {}).get("checked_at") or "")
        existing = existing[:args.max_check]
    if args.limit:
        existing, fresh = existing[:args.limit], fresh[:max(0, args.limit - len(existing))]
    # открытые данные ФНС: один раз на запуск для всех проверяемых ИНН
    od = {}
    if not args.no_opendata:
        od, od_err = opendata.load(http, {store.companies[cid]["inn"] for cid in existing} | {r["inn"] for r in fresh}, log=log)
        errors += [{"source": "opendata", "where": ds, "error": e} for ds, e in od_err.items()]
    jobs = [("upd", cid, store.companies[cid]["inn"], needs_deep(store.companies[cid], today, args.deep)) for cid in existing]
    if not args.fast:
        jobs += [("new", None, r["inn"], True) for r in fresh]
    log(f"проверка: {len(existing)} в базе, {len(fresh)} новых" + (f" (ещё {skipped_new} в очереди на следующие запуски)" if skipped_new else "")
        + (" — новые без запросов по ИНН (--fast)" if args.fast else ""))
    report(stage="проверка компаний", found=len(found), existing=len(existing), new=len(fresh), done=0, total=len(jobs))

    def work(job):
        kind, cid, inn, deep = job
        row = found.get(inn)
        gid = (row or {}).get("girbo_id") or ((store.companies.get(cid) or {}).get("sync") or {}).get("girbo_id")
        res = check(http, inn, deep, row, gid, od)
        # статус изменился по ежедневным источникам → сразу подробная проверка
        if not deep and cid:
            code = status(res.get("egrul"), None, res.get("fedresurs"))[0]
            old = store.companies[cid].get("status_code") or status_of_text(store.companies[cid].get("legal_status"))
            if code and old and code != old:
                res = check(http, inn, True, row, gid, od)
        return job, res

    changes: list[dict] = []
    stats = {"checked": 0, "added": 0, "updated": 0, "closed": 0, "risks_added": 0, "failed": 0}
    if args.fast:
        # названия кодов ОКВЭД, которых нет в справочнике: по одной карточке ГИР БО на код
        missing = {}
        for r in fresh:
            if r.get("okved_main") and not store.okved.get(r["okved_main"]):
                missing.setdefault(r["okved_main"], r["girbo_id"])
        report(stage=f"названия кодов ОКВЭД ({len(missing)})")
        for code, gid in missing.items():
            try:
                o = http.json("GET", f"{girbo.URL}/nbo/organizations/{gid}").get("okved2") or {}
            except SourceError:
                continue
            if o.get("id") == code and o.get("name"):
                store.okved[code] = o["name"]
        log(f"названия кодов ОКВЭД: {sum(1 for c in missing if store.okved.get(c))} из {len(missing)}")
        report(stage="добавление новых компаний")
        for r in fresh:
            try:
                new_id, ch = merge.create(store, fast_res(r, od), today)
            except Exception:
                errors.append({"source": "merge", "where": f"ИНН {r['inn']}", "error": traceback.format_exc(limit=3)})
                continue
            c = store.companies[new_id]
            c.setdefault("sync", {})["girbo_id"] = r["girbo_id"]
            (c.get("registry") or {}).pop("checked_at", None)   # ЕГРЮЛ ещё не спрашивали: ночной сбор проверит такие карточки первыми
            stats["added"] += 1
            changes += ch
        log(f"добавлено без запросов по ИНН: {stats['added']}")
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for (kind, cid, inn, deep), res in pool.map(work, jobs):
            done += 1
            if res["errors"]:
                for k, v in res["errors"].items():
                    errors.append({"source": k, "where": f"ИНН {inn}", "error": v})
            if not set(res["ok"]) - {"opendata"}:
                stats["failed"] += 1
                continue
            stats["checked"] += 1
            try:
                if kind == "new":
                    if not (res.get("egrul") or res.get("pb")):
                        continue   # без ФНС не заводим: нечем подтвердить реквизиты
                    if status(res.get("egrul"), res.get("pb"), res.get("fedresurs"), res.get("girbo_row"))[0] != "ACTIVE":
                        continue
                    main = (res.get("pb") or {}).get("okved_main") or (res.get("girbo") or {}).get("okved_main") or (found.get(inn) or {}).get("okved_main")
                    if main not in store.okved and not ((res.get("pb") or {}).get("okved_main_name") or (res.get("girbo") or {}).get("okved_main_name")):
                        continue   # название основного ОКВЭД неизвестно (ГИР БО не ответил): добавим в следующий запуск
                    res["region"] = (found.get(inn) or {}).get("region")
                    new_id, ch = merge.create(store, res, today)
                    store.companies[new_id].setdefault("sync", {})["girbo_id"] = (res.get("girbo") or {}).get("girbo_id") or (found.get(inn) or {}).get("girbo_id")
                    stats["added"] += 1
                else:
                    ch = merge.update(store, cid, res, today)
                    if res.get("girbo"):
                        store.companies[cid].setdefault("sync", {})["girbo_id"] = res["girbo"]["girbo_id"]
                    if any(x["kind"] == "updated" for x in ch):
                        stats["updated"] += 1
                    if any(x["kind"] == "status" for x in ch):
                        stats["closed"] += 1
                stats["risks_added"] += sum(1 for x in ch if x["kind"] == "risk_added")
                changes += ch
            except Exception:
                errors.append({"source": "merge", "where": f"ИНН {inn}", "error": traceback.format_exc(limit=3)})
            if done % 25 == 0:
                log(f"  {done}/{len(jobs)}, запросов: {http.requests}")
                report(done=done, added=stats["added"])

    # продукция из реестра МСП: архив раз в месяц, по ИНН всех предприятий базы (и добавленных в этом проходе)
    stats["products_updated"] = 0
    # реестр МСП: продукцию в нём указывают около 0,15 % предприятий, архив около 2 ГБ в месяц — включается явно
    if args.rmsp and not args.no_opendata:
        report(stage="продукция из реестра МСП")
        try:
            inns = {c["inn"]: cid for cid, c in store.companies.items() if c.get("inn") and len(c["inn"]) == 10}
            rs = rmsp.load(http, set(inns), log=log)
            n = merge.apply_okpd2_names(store, rs.get("okpd2") or {})
            if n:
                log(f"справочник ОКПД2: {n} названий кодов из реестра МСП")
            for inn, cid in inns.items():
                rec = rs["records"].get(inn)
                if rec or any(s["id"] == f"{cid}-rmsp" for s in store.sources[cid]):
                    ch = merge.apply_rmsp(store, cid, rec, today)
                    if ch:
                        stats["products_updated"] += 1
                        changes += ch
        except (SourceError, OSError) as e:
            errors.append({"source": "rmsp", "where": "реестр МСП", "error": str(e)})

    # продукция из реестра российской промышленной продукции Минпромторга: файл раз в неделю, по ИНН всех предприятий базы
    if not (args.no_minprom or args.no_opendata):
        report(stage="продукция из реестра Минпромторга")
        try:
            inns = {c["inn"]: cid for cid, c in store.companies.items() if c.get("inn")}
            mp = minpromtorg.load(http, set(inns), today, log=log)
            for inn, cid in inns.items():
                recs = mp["records"].get(inn)
                if recs or any(s["id"] == f"{cid}-minprom" for s in store.sources[cid]):
                    ch = merge.apply_minprom(store, cid, recs, mp["as_of"], today)
                    if ch:
                        stats["products_updated"] += 1
                        changes += ch
        except (SourceError, OSError) as e:
            errors.append({"source": "minpromtorg", "where": "реестр промышленной продукции", "error": str(e)})

    # сайты и продукция, найденные краулером (crawler/, результаты в sm01_ingest): подтверждённые сайты и позиции со страниц
    # каталога официальных сайтов — в карточки. Разбираются только предприятия со страницами новее прошлого разбора
    crawl_mark, crawl_from = None, datetime.now().astimezone()
    if not args.no_crawl:
        report(stage="сайты и продукция с официальных сайтов")
        try:
            last = control.read_status().get("crawl_applied_at")
            res = sitecrawl.apply_new(store, today.isoformat(), since=datetime.fromisoformat(last) if last else None, log=log, changes=changes)
            stats["sites_added"], stats["products_from_sites"] = len(res["sites"]), res["products"]
            crawl_mark = res["upto"]
        except Exception as e:   # база обхода недоступна или повреждённая страница: сбор из реестров не прерывается
            errors.append({"source": "crawler", "where": "сайты и продукция с официальных сайтов", "error": f"{type(e).__name__}: {e}"})

    summary = {"at": started.isoformat(timespec="seconds"), "finished": datetime.now().isoformat(timespec="seconds"),
               "regions": regions, "found": len(found), "queued_new": skipped_new, "requests": http.requests, "stats": stats}
    log_doc = dict(summary, changes=changes, errors=errors[:500])
    if args.dry_run:
        log("dry-run: изменения не записаны")
    else:
        report(stage="запись базы", done=len(jobs))
        store.save(f"сбор {today.isoformat()}: {stats}")
        store.write_log(f"{today.isoformat()}_{started:%H%M}", dict(log_doc, trigger=trigger))   # несколько запусков в день не затирают друг друга
        if crawl_mark:
            control.update_status(crawl_applied_at=crawl_mark.isoformat())
        if not args.no_crawl:
            control.crawl_applied_before(crawl_from)
    log(f"готово: {stats}, ошибок источников: {len(errors)}")
    for ch in changes[:40]:
        log(f"  [{ch['kind']}] {ch['name']}: {ch['field'] or ''} {ch['old'] or ''} → {ch['new'] or ''}")
    return log_doc


def apply_crawl(rid: int) -> dict | None:
    """Найденное краулером — в карточки сразу после его запуска (crawler/daemon.py), без сбора из реестров: минуты, а не часы.
    None — идёт сбор из реестров: его этап «сайты и продукция с официальных сайтов» перенесёт то же самое."""
    if not control.acquire({"trigger": f"после обхода сайтов (запуск краулера {rid})"}):
        return None
    try:
        with control.Heartbeat():
            store = Store()
            last = control.read_status().get("crawl_applied_at")
            res = sitecrawl.apply_new(store, date.today().isoformat(), since=datetime.fromisoformat(last) if last else None, log=log, changes=[])
            if res["sites"] or res["products"]:
                store.save(f"краулер: сайтов +{len(res['sites'])}, позиций +{res['products']}")
            if res["upto"]:
                control.update_status(crawl_applied_at=res["upto"].isoformat())
            applied = {"sites": len(res["sites"]), "products": res["products"], "sites_to_moderate": len(res["candidate_sites"])}
            control.crawl_applied(rid, applied)
            log(f"после обхода сайтов (запуск {rid}) перенесено в карточки: сайтов {applied['sites']}, позиций {applied['products']}")
            return applied
    finally:
        control.release()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="python -m sync", description="Синхронизация базы предприятий с реестрами ФНС и Федресурса")
    ap.add_argument("--regions", help="коды регионов через запятую, по умолчанию все субъекты РФ (или PK_SYNC_REGIONS)")
    ap.add_argument("--max-check", type=int, default=config.MAX_CHECK_PER_RUN, help="сколько компаний базы перепроверить за запуск, 0 — все")
    ap.add_argument("--okved", help="классы ОКВЭД через запятую, по умолчанию " + ",".join(config.OKVED_DIVISIONS))
    ap.add_argument("--min-revenue", type=int, default=config.MIN_REVENUE_K, help="порог выручки новой компании, тыс. руб.; не меньше 1 — компании без выручки не добавляются")
    ap.add_argument("--max-new", type=int, default=config.MAX_NEW_PER_RUN, help="сколько новых компаний добавить за запуск")
    ap.add_argument("--no-discover", action="store_true", help="не искать новые компании")
    ap.add_argument("--per-region", type=int, help="не больше N новых компаний на регион (крупнейшие по выручке)")
    ap.add_argument("--only-new", action="store_true", help="только добавить новые компании, не перепроверяя базу")
    ap.add_argument("--found", help="взять результат поиска из файла JSON (sync.run.save_found), не обходя ГИР БО заново")
    ap.add_argument("--fast", action="store_true", help="новые компании — сразу из поиска ГИР БО и открытых данных ФНС, без запросов по ИНН "
                                                         "(ЕГРЮЛ и Федресурс — в следующих сборах)")
    ap.add_argument("--no-opendata", action="store_true", help="не загружать открытые данные ФНС")
    ap.add_argument("--no-minprom", action="store_true", help="не загружать продукцию из реестра Минпромторга (файл около 420 МБ раз в неделю)")
    ap.add_argument("--no-crawl", action="store_true", help="не переносить в карточки сайты и продукцию, найденные краулером")
    ap.add_argument("--rmsp", action="store_true", default=os.environ.get("PK_SYNC_RMSP") == "1",
                    help="загрузить продукцию из реестра МСП (архив около 2 ГБ раз в месяц; также PK_SYNC_RMSP=1)")
    ap.add_argument("--pb-limit", type=int, default=config.PB_PER_RUN, help="сколько карточек «Прозрачного бизнеса» запросить за запуск")
    ap.add_argument("--deep", action="store_true", help="подробная проверка всех компаний, а не раз в неделю")
    ap.add_argument("--limit", type=int, help="проверить не больше N компаний (для отладки)")
    ap.add_argument("--dry-run", action="store_true", help="ничего не записывать")
    ap.add_argument("--delay", type=float, default=config.DELAY, help="пауза между запросами к одному сайту, с")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--today", help="дата запуска ГГГГ-ММ-ДД (для тестов)")
    ap.add_argument("--daemon", action="store_true", help="работать постоянно: запуск каждый день и по кнопке в админ-панели")
    ap.add_argument("--at", default=config.DAILY_AT, help="время ежедневного запуска в режиме --daemon, по умолчанию " + config.DAILY_AT)
    return ap.parse_args(argv)


def next_run(at: str, now: datetime) -> datetime:
    hh, mm = map(int, at.split(":"))
    nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return nxt if nxt > now else nxt + timedelta(days=1)


def main(argv=None):
    args = parse_args(argv)
    if not args.daemon:
        run(args)
        return
    nxt = next_run(args.at, datetime.now())
    log(f"планировщик: ежедневно в {args.at}, следующий запуск {nxt:%d.%m.%Y %H:%M}; ручной запуск — кнопкой в админ-панели")
    while True:
        try:
            control.update_status(daemon_at=control.now_iso(), schedule=args.at, next_run=nxt.astimezone().isoformat(timespec="minutes"))
            req = control.take_request()
        except Exception as e:   # база недоступна (перезапуск PostgreSQL): ждём и пробуем снова
            log(f"нет связи с базой: {type(e).__name__}: {e}")
            time.sleep(15)
            continue
        trigger = f"кнопкой в админ-панели ({req.get('requested_by') or 'администратор'})" if req else "по расписанию" if datetime.now() >= nxt else None
        if trigger:
            try:
                run(args, trigger)
            except Exception:
                traceback.print_exc()
            if trigger == "по расписанию":
                nxt = next_run(args.at, datetime.now())
            log(f"следующий запуск {nxt:%d.%m.%Y %H:%M}")
            continue
        # краулер закончил запуск (после этого сбора или по заданиям из админ-панели) — найденное сразу в карточки
        if not args.no_crawl:
            try:
                rid = control.crawl_to_apply()
                if rid and apply_crawl(rid) is not None:
                    continue
            except Exception:
                traceback.print_exc()
        time.sleep(15)


if __name__ == "__main__":
    sys.exit(main())
