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
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial

import psycopg

from . import config, control, merge, sitecrawl
from .http import Http, SourceError
from .providers import checko, egrul, fedresurs, girbo, minpromtorg, opendata, pb, rmsp
from .risks import status, status_of_text
from .store import I_CHECKED, I_MINPROM, Store

DEEP_EVERY_DAYS = 7
CHECK_CHUNK = 1000  # компаний за порцию проверки: карточки порции загружаются, проверяются, пишутся в базу и выгружаются
MINPROM_CHUNK = (
    250  # предприятий за порцию продукции из реестра Минпромторга: у крупных заводов тысячи позиций
)


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
                errors.append(
                    {"source": "girbo", "where": f"поиск {reg['name']}, ОКВЭД {d}", "error": str(e)}
                )
        log(f"поиск: {reg['name']} — {len(found) - n0} организаций")
    return found


def save_found(
    path: str, regions: list[str] | None = None, divisions: list[str] | None = None
) -> dict:
    """Поиск по регионам — в файл JSON (ИНН → строка ГИР БО): идёт без блокировки сбора, параллельно с другим запуском."""
    errors: list = []
    found = discover(
        Http(), regions or config.SYNC_REGIONS, divisions or config.OKVED_DIVISIONS, errors
    )
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


def check(
    http: Http,
    inn: str,
    deep: bool,
    girbo_row: dict | None,
    girbo_id: str | None,
    od: dict | None = None,
) -> dict:
    res = {"inn": inn, "girbo_row": girbo_row, "ok": [], "not_found": [], "errors": {}}
    if od:
        res["opendata"] = opendata.lookup(od, inn)
        res["ok"].append("opendata")
    steps = [
        ("egrul", lambda: egrul.fetch(http, inn)),
        ("fedresurs", lambda: fedresurs.fetch(http, inn)),
    ]
    if deep and not http.blocked(pb.URL) and PB_BUDGET.take():
        steps.append(("pb", lambda: pb.fetch(http, inn)))
    if deep:
        steps.append(
            (
                "girbo",
                lambda: girbo.fetch(http, inn, girbo_id or (res.get("pb") or {}).get("girbo_id")),
            )
        )
        if checko.enabled():
            steps.append(("checko", lambda: checko.fetch(http, inn)))
    for key, fn in steps:
        try:
            data = fn()
        except SourceError as e:
            res["errors"][key] = str(e)
            continue
        except Exception as e:  # noqa: BLE001  # неожиданный формат ответа не должен останавливать весь проход
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
        years = [
            {
                "year": int(row["period"]),
                "revenue": row["revenue_k"],
                "net_profit": None,
                "assets": None,
                "equity": None,
                "liabilities": None,
            }
        ]
    except (TypeError, ValueError):
        years = []
    g = {
        "girbo_id": row["girbo_id"],
        "url": f"{girbo.URL}/organizations-card/{row['girbo_id']}",
        "years": years,
        "okpo": None,
        "okved_main": row.get("okved_main"),
        "okved_main_name": None,
    }
    res = {
        "inn": row["inn"],
        "girbo_row": row,
        "girbo": g,
        "ok": ["girbo"],
        "not_found": [],
        "errors": {},
        "region": row["region"],
    }
    if od:
        res["opendata"] = opendata.lookup(od, row["inn"])
        res["ok"].append("opendata")
    return res


def needs_deep(c: dict, today: date, force: bool) -> bool:
    if force:
        return True
    last = (c.get("registry") or {}).get("deep_checked_at")
    return not last or date.fromisoformat(last) <= today - timedelta(days=DEEP_EVERY_DAYS)


@dataclass(frozen=True)
class CompanyWorkset:
    """Набор компаний и данных, подготовленный к одному проходу синхронизации."""

    regions: list[str]
    found: dict[str, dict]
    existing: list[str]
    fresh: list[dict]
    skipped_new: int
    open_data: dict


def _prepare_workset(args, http: Http, store: Store, errors: list[dict]) -> CompanyWorkset:
    """Загружает результаты поиска и выбирает компании для текущего прохода.

    Отдельный этап фиксирует границу между поиском/планированием и обновлением карточек.
    Лимиты применяются в прежнем порядке: лимит региона, лимит новых записей, затем общий лимит.
    """
    regions = args.regions.split(",") if args.regions else config.SYNC_REGIONS
    divisions = args.okved.split(",") if args.okved else config.OKVED_DIVISIONS
    if args.found:
        with open(args.found, encoding="utf-8") as source:
            found = json.load(source)
        log(f"поиск: {len(found)} организаций из файла {args.found}")
    else:
        found = {} if args.no_discover else discover(http, regions, divisions, errors)

    by_inn = store.by_inn()
    min_revenue = max(1, args.min_revenue)
    fresh = [
        row
        for inn, row in found.items()
        if inn not in by_inn
        and len(inn) == 10
        and row["status"] == "ACTIVE"
        and (row["revenue_k"] or 0) >= min_revenue
    ]
    fresh.sort(key=lambda row: -(row["revenue_k"] or 0))
    eligible = len(fresh)

    if args.per_region:
        taken: dict[str, int] = {}
        limited: list[dict] = []
        for row in fresh:
            region = row["region"]
            if taken.get(region, 0) >= args.per_region:
                continue
            taken[region] = taken.get(region, 0) + 1
            limited.append(row)
        fresh = limited

    fresh = fresh[: args.max_new]
    skipped_new = eligible - len(fresh)
    existing = (
        []
        if args.only_new
        else [
            company_id for company_id in store.ids() if len(store.inn(company_id) or "") in (10, 12)
        ]
    )
    if args.max_check and len(existing) > args.max_check:
        existing.sort(key=lambda company_id: store.index[company_id][I_CHECKED] or "")
        existing = existing[: args.max_check]
    if args.limit:
        existing, fresh = existing[: args.limit], fresh[: max(0, args.limit - len(existing))]

    open_data = {}
    if not args.no_opendata:
        open_data, source_errors = opendata.load(
            http,
            {store.inn(company_id) for company_id in existing} | {row["inn"] for row in fresh},
            log=log,
        )
        errors.extend(
            {"source": "opendata", "where": dataset, "error": error}
            for dataset, error in source_errors.items()
        )

    return CompanyWorkset(regions, found, existing, fresh, skipped_new, open_data)


def run(args, trigger: str = "вручную из командной строки") -> dict | None:
    """Один проход сбора. Два прохода одновременно не запускаются: они испортили бы файлы базы."""
    if args.dry_run:
        return _run(args, lambda **kw: None, trigger)
    if not control.acquire({"trigger": trigger}):
        log("сбор уже идёт в другом процессе, этот запуск пропущен")
        return None
    started = control.now_iso()
    report = control.update_status
    report(
        state="running",
        trigger=trigger,
        started_at=started,
        stage="поиск новых компаний",
        done=0,
        total=None,
        error=None,
    )
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
        last = (
            {k: doc[k] for k in ("at", "finished", "found", "queued_new", "stats")} if doc else None
        )
        report(
            state="idle",
            stage=None,
            done=None,
            total=None,
            last_run=last,
            last_trigger=trigger,
            last_started_at=started,
        )


def _add_fast_companies(
    fresh: list[dict],
    store: Store,
    http: Http,
    report,
    errors: list[dict],
    stats: dict[str, int],
    changes: list[dict],
    today: date,
    open_data: dict,
) -> None:
    """Добавляет найденные компании в быстром режиме без запросов по ИНН."""
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
            new_id, ch = merge.create(store, fast_res(r, open_data), today)
        except Exception:  # noqa: BLE001
            errors.append(
                {
                    "source": "merge",
                    "where": f"ИНН {r['inn']}",
                    "error": traceback.format_exc(limit=3),
                }
            )
            continue
        c = store.companies[new_id]
        c["origin"] = (
            "registry_fast"  # без ЕГРЮЛ; в памяти API — только с продукцией или сайтом (pkdb.catalog.CORE_SQL)
        )
        c.setdefault("sync", {})["girbo_id"] = r["girbo_id"]
        (c.get("registry") or {}).pop(
            "checked_at", None
        )  # ЕГРЮЛ ещё не спрашивали: ночной сбор проверит такие карточки первыми
        stats["added"] += 1
        changes += ch
        store.flush()  # по FLUSH_AT карточек: по всей стране их больше 150 тысяч
    log(f"добавлено без запросов по ИНН: {stats['added']}")


def _check_job(
    job: tuple[str, str | None, str, bool],
    *,
    http: Http,
    store: Store,
    found: dict[str, dict],
    open_data: dict,
    today: date,
) -> tuple[tuple[str, str | None, str, bool], dict]:
    """Проверяет компанию и запускает глубокую проверку при смене статуса."""
    kind, cid, inn, deep = job
    row = found.get(inn)
    gid = (row or {}).get("girbo_id") or ((store.companies.get(cid) or {}).get("sync") or {}).get(
        "girbo_id"
    )
    res = check(http, inn, deep, row, gid, open_data)
    # статус изменился по ежедневным источникам → сразу подробная проверка
    if not deep and cid:
        code = status(res.get("egrul"), None, res.get("fedresurs"))[0]
        old = store.companies[cid].get("status_code") or status_of_text(
            store.companies[cid].get("legal_status")
        )
        if code and old and code != old:
            res = check(http, inn, True, row, gid, open_data)
    return job, res


def _prepare_new_company(
    inn: str,
    result: dict,
    *,
    found: dict[str, dict],
    store: Store,
) -> dict | None:
    """Отбрасывает новые записи без подтверждённых реквизитов или названия ОКВЭД."""
    if not (result.get("egrul") or result.get("pb")):
        return None
    if (
        status(
            result.get("egrul"),
            result.get("pb"),
            result.get("fedresurs"),
            result.get("girbo_row"),
        )[0]
        != "ACTIVE"
    ):
        return None

    main_okved = (
        (result.get("pb") or {}).get("okved_main")
        or (result.get("girbo") or {}).get("okved_main")
        or (found.get(inn) or {}).get("okved_main")
    )
    has_okved_name = (result.get("pb") or {}).get("okved_main_name") or (
        result.get("girbo") or {}
    ).get("okved_main_name")
    if main_okved not in store.okved and not has_okved_name:
        return None

    result["region"] = (found.get(inn) or {}).get("region")
    return result


def _apply_checked_job(
    kind: str,
    company_id: str | None,
    inn: str,
    result: dict,
    *,
    found: dict[str, dict],
    store: Store,
    today: date,
    stats: dict[str, int],
    errors: list[dict],
) -> list[dict]:
    """Проверяет пригодность результата источников и применяет его к каталогу."""
    if result["errors"]:
        errors.extend(
            {"source": source, "where": f"ИНН {inn}", "error": error}
            for source, error in result["errors"].items()
        )
    if not set(result["ok"]) - {"opendata"}:
        stats["failed"] += 1
        return []

    stats["checked"] += 1
    try:
        if kind == "new":
            company = _prepare_new_company(inn, result, found=found, store=store)
            if company is None:
                return []
            new_id, changes = merge.create(store, company, today)
            store.companies[new_id].setdefault("sync", {})["girbo_id"] = (
                company.get("girbo") or {}
            ).get("girbo_id") or (found.get(inn) or {}).get("girbo_id")
            stats["added"] += 1
        else:
            changes = merge.update(store, company_id, result, today)
            if result.get("girbo"):
                store.companies[company_id].setdefault("sync", {})["girbo_id"] = result["girbo"][
                    "girbo_id"
                ]
            if any(change["kind"] == "updated" for change in changes):
                stats["updated"] += 1
            if any(change["kind"] == "status" for change in changes):
                stats["closed"] += 1
        stats["risks_added"] += sum(1 for change in changes if change["kind"] == "risk_added")
        return changes
    except Exception:  # noqa: BLE001  # Ошибка одной записи не должна прерывать обработку партии.
        errors.append(
            {
                "source": "merge",
                "where": f"ИНН {inn}",
                "error": traceback.format_exc(limit=3),
            }
        )
        return []


def _apply_rmsp_registry(
    args,
    store: Store,
    http: Http,
    today: date,
    report,
    stats: dict[str, int],
    changes: list[dict],
    errors: list[dict],
) -> None:
    """Применяет данные реестра МСП порциями, не сохраняя всю выгрузку в памяти."""
    if args.rmsp and not args.no_opendata:
        report(stage="категории МСП и продукция из реестра ФНС")
        try:
            inns = {store.inn(cid): cid for cid in store.ids() if len(store.inn(cid) or "") == 10}
            rs = rmsp.load(http, set(inns), log=log)
            n = merge.apply_okpd2_names(store, rs.get("okpd2") or {})
            if n:
                log(f"справочник ОКПД2: {n} названий кодов из реестра МСП")
            # Отсутствие ИНН в полном архиве означает только «не найден в реестре», а не крупный бизнес.
            todo = list(inns.values())
            for i in range(0, len(todo), CHECK_CHUNK):
                store.load(todo[i : i + CHECK_CHUNK])
                for cid in todo[i : i + CHECK_CHUNK]:
                    rec = rs["records"].get(store.inn(cid))
                    before_registry = store.companies[cid].get("registry") or {}
                    before = (
                        before_registry.get("msp"),
                        before_registry.get("msp_status"),
                        before_registry.get("msp_as_of"),
                        before_registry.get("scale_estimate"),
                    )
                    ch = merge.apply_rmsp(store, cid, rec, today, as_of=rs.get("as_of"))
                    after_registry = store.companies[cid].get("registry") or {}
                    after = (
                        after_registry.get("msp"),
                        after_registry.get("msp_status"),
                        after_registry.get("msp_as_of"),
                        after_registry.get("scale_estimate"),
                    )
                    if before != after:
                        stats["business_scales_updated"] += 1
                    if ch:
                        stats["products_updated"] += 1
                        changes += ch
                store.unload(todo[i : i + CHECK_CHUNK])
                store.flush(force=True)
        except (SourceError, OSError) as e:
            errors.append({"source": "rmsp", "where": "реестр МСП", "error": str(e)})

    # продукция из реестра российской промышленной продукции Минпромторга: файл раз в неделю, по ИНН всех предприятий базы


def _apply_minprom_products(
    args,
    store: Store,
    http: Http,
    today: date,
    report,
    stats: dict[str, int],
    changes: list[dict],
    errors: list[dict],
) -> None:
    """Обновляет позиции каталога из реестра Минпромторга по частям компаний."""
    if not (args.no_minprom or args.no_opendata):
        report(stage="продукция из реестра Минпромторга")
        try:
            inns = {store.inn(cid): cid for cid in store.ids() if store.inn(cid)}
            path = minpromtorg.ensure(http, today)
            as_of, present = minpromtorg.present(path, set(inns), today)
            todo = [
                cid for inn, cid in inns.items() if inn in present or store.index[cid][I_MINPROM]
            ]
            log(
                f"реестр промышленной продукции на {as_of}: действующие записи у {len(present)} из {len(inns)} предприятий"
            )
            # порциями: записи реестра — только предприятий порции (весь реестр в памяти — сотни мегабайт), изменённые
            # карточки с продукцией пишутся в базу после каждой порции
            for i in range(0, len(todo), MINPROM_CHUNK):
                part = todo[i : i + MINPROM_CHUNK]
                _, recs = minpromtorg.scan(path, {store.inn(cid) for cid in part}, today)
                store.load(part)
                for cid in part:
                    ch = merge.apply_minprom(store, cid, recs.get(store.inn(cid)), as_of, today)
                    if ch:
                        stats["products_updated"] += 1
                        changes += ch
                del recs
                store.unload(part)
                store.flush(force=True)
        except (SourceError, OSError) as e:
            errors.append(
                {"source": "minpromtorg", "where": "реестр промышленной продукции", "error": str(e)}
            )

    # сайты и продукция, найденные краулером (crawler/, результаты в sm01_ingest): подтверждённые сайты и позиции со страниц
    # каталога официальных сайтов — в карточки. Разбираются только предприятия со страницами новее прошлого разбора


def _apply_crawl_results(
    args,
    store: Store,
    today: date,
    report,
    changes: list[dict],
    stats: dict[str, int],
    errors: list[dict],
) -> tuple[datetime | None, datetime]:
    """Переносит в каталог подтверждённые результаты краулера, сохраняя метки времени применения."""
    crawl_mark, crawl_from = None, datetime.now().astimezone()
    if not args.no_crawl:
        report(stage="сайты и продукция с официальных сайтов")
        try:
            last = control.read_status().get("crawl_applied_at")
            res = sitecrawl.apply_new(
                store,
                today.isoformat(),
                since=datetime.fromisoformat(last) if last else None,
                log=log,
                changes=changes,
            )
            stats["sites_added"], stats["products_from_sites"] = len(res["sites"]), res["products"]
            stats["financial_activities_from_sites"] = res.get("financial_activities", 0)
            crawl_mark = res["upto"]
        except Exception as e:  # noqa: BLE001  # база обхода недоступна или повреждённая страница: сбор из реестров не прерывается
            errors.append(
                {
                    "source": "crawler",
                    "where": "сайты и продукция с официальных сайтов",
                    "error": f"{type(e).__name__}: {e}",
                }
            )
    return crawl_mark, crawl_from


def _persist_run(
    args,
    store: Store,
    report,
    total_jobs: int,
    today: date,
    started: datetime,
    trigger: str | None,
    log_doc: dict,
    stats: dict[str, int],
    crawl_mark: datetime | None,
    crawl_from: datetime,
) -> None:
    """Сохраняет итог прохода и обновляет контрольные отметки после записи."""
    if args.dry_run:
        log("dry-run: изменения не записаны")
    else:
        report(stage="запись базы", done=total_jobs)
        store.save(f"сбор {today.isoformat()}: {stats}")
        store.write_log(
            f"{today.isoformat()}_{started:%H%M}", dict(log_doc, trigger=trigger)
        )  # несколько запусков в день не затирают друг друга
        if crawl_mark:
            control.update_status(crawl_applied_at=crawl_mark.isoformat())
        if not args.no_crawl:
            control.crawl_applied_before(crawl_from)


def _run(args, report, trigger: str | None = None) -> dict:
    """Выполняет один проход синхронизации источников, объединения данных и обхода сайтов.

    Args:
        args: Параметры прохода, сформированные командной строкой или планировщиком.
        report: Функция публикации состояния прохода для административной панели.
        trigger: Причина запуска, включаемая в журнал выполнения.

    Returns:
        dict: Итоговые счётчики, ошибки и изменения карточек.
    """
    today = date.fromisoformat(args.today) if args.today else date.today()
    PB_BUDGET.left = args.pb_limit
    started = datetime.now()
    http = Http(delay=args.delay)
    store = Store(readonly=args.dry_run)
    errors: list[dict] = []
    workset = _prepare_workset(args, http, store, errors)
    regions = workset.regions
    found = workset.found
    existing = workset.existing
    fresh = workset.fresh
    skipped_new = workset.skipped_new
    od = workset.open_data
    new_jobs = [] if args.fast else [("new", None, r["inn"], True) for r in fresh]
    total_jobs = len(existing) + len(new_jobs)
    log(
        f"проверка: {len(existing)} в базе, {len(fresh)} новых"
        + (f" (ещё {skipped_new} в очереди на следующие запуски)" if skipped_new else "")
        + (" — новые без запросов по ИНН (--fast)" if args.fast else "")
    )
    report(
        stage="проверка компаний",
        found=len(found),
        existing=len(existing),
        new=len(fresh),
        done=0,
        total=total_jobs,
    )

    changes: list[dict] = []
    stats = {"checked": 0, "added": 0, "updated": 0, "closed": 0, "risks_added": 0, "failed": 0}
    if args.fast:
        _add_fast_companies(fresh, store, http, report, errors, stats, changes, today, od)
    done = 0

    def process(jobs):
        nonlocal done, changes
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            worker = partial(
                _check_job, http=http, store=store, found=found, open_data=od, today=today
            )
            for (kind, cid, inn, _deep), res in pool.map(worker, jobs):
                done += 1
                changes.extend(
                    _apply_checked_job(
                        kind,
                        cid,
                        inn,
                        res,
                        found=found,
                        store=store,
                        today=today,
                        stats=stats,
                        errors=errors,
                    )
                )
                if done % 25 == 0:
                    log(f"  {done}/{total_jobs}, запросов: {http.requests}")
                    report(done=done, added=stats["added"])

    # порциями: карточки порции загружаются, проверяются и пишутся в базу (без увеличения ревизии — она растёт в конце сбора)
    for i in range(0, len(existing), CHECK_CHUNK):
        ids = existing[i : i + CHECK_CHUNK]
        store.load(ids)
        process(
            [
                ("upd", cid, store.inn(cid), needs_deep(store.companies[cid], today, args.deep))
                for cid in ids
                if dict.__contains__(store.companies, cid)
            ]
        )
        store.flush(force=True)
    for i in range(0, len(new_jobs), CHECK_CHUNK):
        process(new_jobs[i : i + CHECK_CHUNK])
        store.flush(force=True)

    # Категории МСП ФНС и продукция: месячный архив читается только при включённом --rmsp.
    # Архив около 2 ГБ; PK_SYNC_RMSP=1 включает управляемую загрузку и проверку всех ИНН каталога.
    stats["products_updated"] = 0
    stats["business_scales_updated"] = 0
    _apply_rmsp_registry(args, store, http, today, report, stats, changes, errors)
    _apply_minprom_products(args, store, http, today, report, stats, changes, errors)
    crawl_mark, crawl_from = _apply_crawl_results(
        args, store, today, report, changes, stats, errors
    )

    summary = {
        "at": started.isoformat(timespec="seconds"),
        "finished": datetime.now().isoformat(timespec="seconds"),
        "regions": regions,
        "found": len(found),
        "queued_new": skipped_new,
        "requests": http.requests,
        "stats": stats,
    }
    log_doc = dict(summary, changes=changes, errors=errors[:500])
    _persist_run(
        args,
        store,
        report,
        total_jobs,
        today,
        started,
        trigger,
        log_doc,
        stats,
        crawl_mark,
        crawl_from,
    )
    log(f"готово: {stats}, ошибок источников: {len(errors)}")
    for ch in changes[:40]:
        log(
            f"  [{ch['kind']}] {ch['name']}: {ch['field'] or ''} {ch['old'] or ''} → {ch['new'] or ''}"
        )
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
            res = sitecrawl.apply_new(
                store,
                date.today().isoformat(),
                since=datetime.fromisoformat(last) if last else None,
                log=log,
                changes=[],
            )
            store.save(
                f"краулер: сайтов +{len(res['sites'])}, позиций +{res['products']}"
            )  # без изменений ничего не пишет
            if res["upto"]:
                control.update_status(crawl_applied_at=res["upto"].isoformat())
            applied = {
                "sites": len(res["sites"]),
                "products": res["products"],
                "sites_to_moderate": len(res["candidate_sites"]),
            }
            control.crawl_applied(rid, applied)
            log(
                f"после обхода сайтов (запуск {rid}) перенесено в карточки: сайтов {applied['sites']}, позиций {applied['products']}"
            )
            return applied
    finally:
        control.release()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m sync",
        description="Синхронизация базы предприятий с реестрами ФНС и Федресурса",
    )
    ap.add_argument(
        "--regions",
        help="коды регионов через запятую, по умолчанию все субъекты РФ (или PK_SYNC_REGIONS)",
    )
    ap.add_argument(
        "--max-check",
        type=int,
        default=config.MAX_CHECK_PER_RUN,
        help="сколько компаний базы перепроверить за запуск, 0 — все",
    )
    ap.add_argument(
        "--okved",
        help="классы ОКВЭД через запятую, по умолчанию " + ",".join(config.OKVED_DIVISIONS),
    )
    ap.add_argument(
        "--min-revenue",
        type=int,
        default=config.MIN_REVENUE_K,
        help="порог выручки новой компании, тыс. руб.; не меньше 1 — компании без выручки не добавляются",
    )
    ap.add_argument(
        "--max-new",
        type=int,
        default=config.MAX_NEW_PER_RUN,
        help="сколько новых компаний добавить за запуск",
    )
    ap.add_argument("--no-discover", action="store_true", help="не искать новые компании")
    ap.add_argument(
        "--per-region",
        type=int,
        help="не больше N новых компаний на регион (крупнейшие по выручке)",
    )
    ap.add_argument(
        "--only-new",
        action="store_true",
        help="только добавить новые компании, не перепроверяя базу",
    )
    ap.add_argument(
        "--found",
        help="взять результат поиска из файла JSON (sync.run.save_found), не обходя ГИР БО заново",
    )
    ap.add_argument(
        "--fast",
        action="store_true",
        help="новые компании — сразу из поиска ГИР БО и открытых данных ФНС, без запросов по ИНН "
        "(ЕГРЮЛ и Федресурс — в следующих сборах)",
    )
    ap.add_argument("--no-opendata", action="store_true", help="не загружать открытые данные ФНС")
    ap.add_argument(
        "--no-minprom",
        action="store_true",
        help="не загружать продукцию из реестра Минпромторга (файл около 420 МБ раз в неделю)",
    )
    ap.add_argument(
        "--no-crawl",
        action="store_true",
        help="не переносить в карточки сайты и продукцию, найденные краулером",
    )
    ap.add_argument(
        "--rmsp",
        action="store_true",
        default=os.environ.get("PK_SYNC_RMSP") == "1",
        help="загрузить продукцию из реестра МСП (архив около 2 ГБ раз в месяц; также PK_SYNC_RMSP=1)",
    )
    ap.add_argument(
        "--pb-limit",
        type=int,
        default=config.PB_PER_RUN,
        help="сколько карточек «Прозрачного бизнеса» запросить за запуск",
    )
    ap.add_argument(
        "--deep", action="store_true", help="подробная проверка всех компаний, а не раз в неделю"
    )
    ap.add_argument("--limit", type=int, help="проверить не больше N компаний (для отладки)")
    ap.add_argument("--dry-run", action="store_true", help="ничего не записывать")
    ap.add_argument(
        "--delay", type=float, default=config.DELAY, help="пауза между запросами к одному сайту, с"
    )
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--today", help="дата запуска ГГГГ-ММ-ДД (для тестов)")
    ap.add_argument(
        "--daemon",
        action="store_true",
        help="работать постоянно: запуск каждый день и по кнопке в админ-панели",
    )
    ap.add_argument(
        "--at",
        default=config.DAILY_AT,
        help="время ежедневного запуска в режиме --daemon, по умолчанию " + config.DAILY_AT,
    )
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
    log(
        f"планировщик: ежедневно в {args.at}, следующий запуск {nxt:%d.%m.%Y %H:%M}; ручной запуск — кнопкой в админ-панели"
    )
    while True:
        try:
            control.update_status(
                daemon_at=control.now_iso(),
                schedule=args.at,
                next_run=nxt.astimezone().isoformat(timespec="minutes"),
            )
            req = control.take_request()
        except psycopg.Error as e:  # база недоступна (перезапуск PostgreSQL): ждём и пробуем снова
            log(f"нет связи с базой: {type(e).__name__}: {e}")
            time.sleep(15)
            continue
        trigger = (
            f"кнопкой в админ-панели ({req.get('requested_by') or 'администратор'})"
            if req
            else "по расписанию"
            if datetime.now() >= nxt
            else None
        )
        if trigger:
            try:
                run(args, trigger)
            except Exception:  # noqa: BLE001
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
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        time.sleep(15)


if __name__ == "__main__":
    sys.exit(main())
