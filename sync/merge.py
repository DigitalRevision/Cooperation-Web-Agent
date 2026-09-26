"""Слияние ответов реестров с базой: новые компании, обновление реквизитов, статус закрытия, риски, журнал изменений.

Правила:
  - реквизиты (ОГРН, КПП, ОКПО, юр. название, дата регистрации, основной ОКВЭД) берутся из реестров ФНС;
  - название для каталога (name, short), сайт, контакты, продукция, технологии, заведённые вручную, не меняются;
  - адрес обновляется, только если отличаются числа (индекс, дом): разный формат записи изменением не считается;
  - статус понижается (например, «банкротство» → «действующее») только если ответили все источники, на которых он держался;
  - ликвидированная компания получает verification_status = OUTDATED;
  - сигналы риска от источника, который не ответил, сохраняются с прошлого запуска.
"""
from __future__ import annotations
import re
from datetime import date

from . import capabilities, config, risks
from .providers import checko, egrul, fedresurs, girbo, minpromtorg, opendata, pb, rmsp
from .providers.util import city_from_address, same_address, nice_address, nice_city, nice_name

SRC = {  # ключ → (тип, название, приоритет, что подтверждает)
    "egrul": ("FNS_EGRUL", egrul.TITLE, 5, ["юр. название", "ИНН", "ОГРН", "КПП", "дата регистрации", "статус", "дата прекращения деятельности"]),
    "pb": ("FNS_PB", pb.TITLE, 5, ["статус", "юр. адрес", "коды ОКВЭД", "недостоверность сведений", "задолженность по налогам",
                                  "численность", "уплаченные налоги", "массовый адрес и руководитель"]),
    "girbo": ("FNS_GIRBO", girbo.TITLE, 5, ["бухгалтерская отчётность", "ОКПО"]),
    "fedresurs": ("EFRSB", fedresurs.TITLE, 5, ["банкротство: дела и сообщения", "намерения кредиторов"]),
    "opendata": ("FNS_OPENDATA", opendata.TITLE, 5, ["задолженность по налогам и взносам", "среднесписочная численность",
                                                  "уплаченные налоги", "налоговый режим"]),
    "checko": ("CHECKO", checko.TITLE, 5, ["арбитражные дела", "исполнительные производства ФССП", "реестр недобросовестных поставщиков"]),
}
HISTORY_MAX = 30
FIELD_TITLES = {"legal_name": "Юр. название", "ogrn": "ОГРН", "kpp": "КПП", "okpo": "ОКПО", "reg_date": "Дата регистрации",
                "address": "Юр. адрес", "okved_main": "Основной ОКВЭД", "okved_extra": "Доп. ОКВЭД", "legal_status": "Статус"}


def _norm_name(s: str | None) -> str:
    return re.sub(r"[^А-ЯЁA-Z0-9]", "", (s or "").upper())


def _src_url(key: str, inn: str, res: dict) -> str:
    if key == "girbo":
        return res["girbo"]["url"]
    if key == "fedresurs":
        return res["fedresurs"]["url"]
    return {"egrul": "https://egrul.nalog.ru/", "pb": "https://pb.nalog.ru/", "opendata": "https://www.nalog.gov.ru/opendata/", "checko": f"https://checko.ru/search?query={inn}"}[key]


def _upsert_sources(sources: list[dict], cid: str, res: dict, today: str) -> dict[str, str]:
    """Обновляет записи источников реестров, возвращает ключ источника → id записи."""
    ids = {}
    for key, (stype, title, prio, confirms) in SRC.items():
        sid = f"{cid}-{key}"
        cur = next((s for s in sources if s["id"] == sid), None)
        if key in res["ok"]:
            rec = {"id": sid, "source_url": _src_url(key, res["inn"], res), "source_type": stype, "source_title": title,
                   "priority": prio, "source_date": None, "last_verified_at": today, "confirms": confirms,
                   "fetch_status": "OK", "note": f"Запрос по ИНН {res['inn']}"}
            if cur:
                cur.update(rec)
            else:
                sources.append(rec)
        elif cur and key in res["errors"]:
            cur["fetch_status"], cur["note"] = "FAILED", res["errors"][key]
        if any(s["id"] == sid for s in sources):
            ids[key] = sid
    return ids


def _okved(res: dict, store) -> tuple[str | None, list[str]]:
    p, g = res.get("pb"), res.get("girbo") or {}
    if g.get("okved_main") and g.get("okved_main_name"):
        store.okved.setdefault(g["okved_main"], g["okved_main_name"])
    if not p:
        return g.get("okved_main"), []
    for code, name in p["okved_all"]:
        store.okved.setdefault(code, name)
    if p.get("okved_main") and p.get("okved_main_name"):
        store.okved.setdefault(p["okved_main"], p["okved_main_name"])
    main = p.get("okved_main")
    return main, [c for c, _ in p["okved_all"] if c != main]


def _signals(c: dict, res: dict, code: str | None, ids: dict, today: date) -> list[dict]:
    fresh = risks.signals(res.get("pb"), res.get("fedresurs"), res.get("girbo"), res.get("checko"), code or c.get("status_code"), today,
                          res.get("opendata"))
    for s in fresh:
        s["source_id"] = ids.get(s["source"])
    # сигналы источников, которые в этом запуске не опрашивались или не ответили, остаются прежними
    kept = [s for s in c.get("risk_signals") or [] if s.get("source") not in res["ok"]]
    codes = {s["code"] for s in fresh}
    kept = [s for s in kept if s["code"] not in codes and not (s["code"] == "TAX_ARREARS" and "opendata" in res["ok"])]
    if code == "BANKRUPTCY":
        kept = [s for s in kept if s["code"] != "BANKRUPTCY_INTENT"]
    order = {"high": 0, "mid": 1, "low": 2}
    return sorted(fresh + kept, key=lambda s: order[s["level"]])


def _change(out: list, c: dict, kind: str, field: str | None, old, new, today: str):
    ch = {"date": today, "company_id": c["id"], "inn": c.get("inn"), "name": c.get("name"), "kind": kind,
          "field": FIELD_TITLES.get(field, field), "old": old, "new": new}
    out.append(ch)
    c.setdefault("history", []).insert(0, {k: ch[k] for k in ("date", "kind", "field", "old", "new")})
    del c["history"][HISTORY_MAX:]


def update(store, cid: str, res: dict, today: date) -> list[dict]:
    """Обновляет существующую компанию по ответам источников. Возвращает список изменений."""
    c, day = store.companies[cid], today.isoformat()
    changes: list[dict] = []
    ids = _upsert_sources(store.sources[cid], cid, res, day)
    e, p, g = res.get("egrul") or {}, res.get("pb") or {}, res.get("girbo") or {}

    def setf(field, new, cmp=lambda a, b: a == b):
        old = c.get(field)
        if new in (None, "", []) or old == new or (old is not None and cmp(old, new)):
            return
        c[field] = new
        if old not in (None, "", []):
            _change(changes, c, "updated", field, old, new, day)

    setf("ogrn", e.get("ogrn") or p.get("ogrn"))
    setf("kpp", e.get("kpp") or p.get("kpp"))
    setf("okpo", g.get("okpo"))
    # в ЕГРЮЛ у предприятий до 2002 года это дата присвоения ОГРН, а не исходной регистрации: только заполняем пустое
    if not c.get("reg_date"):
        c["reg_date"] = p.get("reg_date") or e.get("reg_date")
    setf("legal_name", e.get("legal_name") or p.get("legal_name"), lambda a, b: _norm_name(a) == _norm_name(b))
    # адрес: «Прозрачный бизнес», если он ответил, иначе адрес ЕГРЮЛ из Федресурса
    addr = nice_address(p.get("address") or (res.get("fedresurs") or {}).get("address"))
    region = config.REGIONS.get(c.get("region") or "")
    if addr and ("филиал" in (c.get("name") or "").lower() or (region and region["query"].lower() not in addr.lower())):
        addr = None   # адрес вне региона карточки: это головная компания филиала, адрес площадки не трогаем
    setf("address", addr, same_address)
    if not c.get("city") and addr:
        c["city"] = city_from_address(addr) or ""
    main, extra = _okved(res, store)
    setf("okved_main", main)
    if "pb" in res["ok"]:
        old_extra = c.get("okved_extra") or []
        if sorted(old_extra) != sorted(extra):
            c["okved_extra"] = extra
            if old_extra:
                _change(changes, c, "updated", "okved_extra", ", ".join(old_extra), ", ".join(extra), day)
        c["capabilities_declared"] = capabilities.declared(p["okved_all"])

    # статус и метка закрытия
    code, text, by = risks.status(res.get("egrul"), res.get("pb"), res.get("fedresurs"), res.get("girbo_row"))
    old_code = c.get("status_code") or risks.status_of_text(c.get("legal_status"))
    old_by = (c.get("sync") or {}).get("status_by") or ["egrul", "pb", "fedresurs"]
    if code and code != old_code:
        downgrade = old_code and risks.RANK[code] < risks.RANK[old_code]
        if not downgrade or all(k in res["ok"] for k in old_by):
            old_text = c.get("legal_status")
            c["legal_status"], c["status_code"] = text, code
            c.setdefault("sync", {})["status_by"] = by
            if code == "LIQUIDATED":
                c["verification_status"] = "OUTDATED"
            _change(changes, c, "status" if risks.RANK[code] > risks.RANK.get(old_code or "ACTIVE", 0) else "updated", "legal_status", old_text, text, day)
    elif code:
        c["status_code"] = code
        c.setdefault("sync", {})["status_by"] = by
        if not c.get("legal_status"):
            c["legal_status"] = text

    # риски и показатели
    old_sig = {s["code"]: s for s in c.get("risk_signals") or []}
    c["risk_signals"] = _signals(c, res, c.get("status_code"), ids, today)
    new_sig = {s["code"]: s for s in c["risk_signals"]}
    for k in new_sig.keys() - old_sig.keys():
        _change(changes, c, "risk_added", new_sig[k]["title"], None, new_sig[k]["text"], day)
    for k in old_sig.keys() - new_sig.keys():
        _change(changes, c, "risk_removed", old_sig[k]["title"], old_sig[k]["text"], None, day)
    if {"pb", "girbo", "opendata"} & set(res["ok"]):
        reg = dict(c.get("registry") or {})
        if "girbo" in res["ok"]:
            reg.pop("finance", None)
        reg.update(risks.facts(res.get("pb"), res.get("girbo"), res.get("opendata")))
        reg["checked_at"] = day
        if "pb" in res["ok"]:
            reg["deep_checked_at"] = day
        reg["source_ids"] = {k: v for k, v in ids.items() if k in ("pb", "girbo", "opendata")}
        c["registry"] = reg
    sync = c.setdefault("sync", {})
    sync["checked_at"] = day
    sync["sources"] = {k: "OK" for k in res["ok"]} | {k: "NOT_FOUND" for k in res["not_found"]} | {k: v for k, v in res["errors"].items()}
    store.dirty.add(cid)
    return changes


def create(store, res: dict, today: date) -> tuple[str, list[dict]]:
    """Новая компания из реестров. Реквизиты подтверждены ФНС, продукция и контакты ещё нет."""
    e, p, row = res.get("egrul") or {}, res.get("pb") or {}, res.get("girbo_row") or {}
    name, short = nice_name(e.get("short_name") or p.get("short_name") or row.get("short_name"), e.get("legal_name") or p.get("legal_name"))
    cid = store.new_id(short)
    region = p.get("region_code") or res.get("region")
    if region and region not in store.regions:
        store.regions[region] = {"code": region, "name": config.REGIONS.get(region, {}).get("name", region), "pilot": False}
    g = res.get("girbo") or {}
    main = p.get("okved_main") or g.get("okved_main") or row.get("okved_main")
    c = {
        "id": cid, "name": name, "short": short,
        "legal_name": e.get("legal_name") or p.get("legal_name"), "inn": res["inn"], "ogrn": e.get("ogrn") or p.get("ogrn") or row.get("ogrn"),
        "kpp": e.get("kpp") or p.get("kpp"), "okpo": None, "reg_date": p.get("reg_date") or e.get("reg_date"),
        "legal_status": None, "region": region,
        "city": nice_city(p.get("city") or row.get("city")) or city_from_address(nice_address(p.get("address") or (res.get("fedresurs") or {}).get("address"))) or "",
        "address": nice_address(p.get("address") or (res.get("fedresurs") or {}).get("address")), "site": None, "phones": [], "emails": [],
        "okved_main": main, "okved_extra": [],
        "industry": config.INDUSTRY_BY_DIVISION.get((main or "")[:2], "Прочие производства"),
        "subindustry": p.get("okved_main_name") or g.get("okved_main_name") or store.okved.get(main or "", "Не указано"),
        "description": None, "technologies": [], "materials": [], "capacities": [], "sites": [], "certificates": [],
        "verification_status": "PARTIALLY_VERIFIED", "discrepancies": [],
        "origin": "registry_sync", "added_at": today.isoformat(),
    }
    store.add(c, [])
    changes = update(store, cid, res, today)
    c["history"] = []
    ch = {"date": today.isoformat(), "company_id": cid, "inn": c["inn"], "name": c["name"], "kind": "added", "field": None,
          "old": None, "new": f"{c['legal_status'] or ''}, ОКВЭД {main or '—'}, {c['city'] or ''}".strip(", ")}
    c["history"].insert(0, {k: ch[k] for k in ("date", "kind", "field", "old", "new")})
    return cid, [ch]


# ---------- продукция из Единого реестра субъектов МСП ----------

def _rmsp_kind(code: str | None, name: str) -> str:
    n = name.lower()
    return "service" if (code or "").startswith("33.") or n.startswith(("услуг", "работ")) else "product"


def rmsp_products(cid: str, rec: dict) -> list[dict]:
    """Позиции продукции, которые предприятие указало в реестре МСП: код ОКПД2 из реестра (status SOURCE)."""
    sid, out, seen = f"{cid}-rmsp", [], set()
    for p in rec.get("products") or []:
        code = (p.get("code") or "").strip() or None
        name = rmsp.clean_name(p.get("name"))
        if not name:
            continue
        key = (code, name.lower())
        if key in seen:
            continue
        seen.add(key)
        pid = f"{cid}-okpd2-{code.replace('.', '-')}" if code else f"{cid}-rmsp-{len(out) + 1}"
        while any(x["id"] == pid for x in out):
            pid += "-2"
        out.append({"id": pid, "name": name[:1].upper() + name[1:], "kind": _rmsp_kind(code, name),
                    "category": config.INDUSTRY_BY_DIVISION.get((code or "")[:2], "Продукция"),
                    "okpd2": {"code": code, "name": name, "status": "SOURCE"} if code else None,
                    "description": "Предприятие указало эту продукцию в Едином реестре субъектов МСП ФНС."
                                   + (" Отмечена как инновационная или высокотехнологичная." if p.get("innovative") else ""),
                    "params": [], "materials": [], "price": None, "volume": None, "min_batch": None, "lead_time_production": None,
                    "lead_time_delivery": None, "availability": None, "warehouse_id": None, "photo": None,
                    "source_id": sid, "last_verified_at": rec.get("date"), "company_id": cid})
    return out


def apply_rmsp(store, cid: str, rec: dict | None, today: date) -> list[dict]:
    """Продукция из реестра МСП заменяет только прежние позиции того же источника; остальная продукция не трогается.
    rec None — предприятия нет в реестре или продукция не указана: позиции этого источника снимаются."""
    c, day, sid = store.companies[cid], today.isoformat(), f"{cid}-rmsp"
    old = [p for p in store.products[cid] if p.get("source_id") == sid]
    new = rmsp_products(cid, rec) if rec else []
    if [(p["id"], p["name"]) for p in old] == [(p["id"], p["name"]) for p in new] and (not rec or any(s["id"] == sid for s in store.sources[cid])):
        return []
    changes: list[dict] = []
    store.products[cid] = [p for p in store.products[cid] if p.get("source_id") != sid] + new
    store.sources[cid] = [s for s in store.sources[cid] if s["id"] != sid]
    if rec:
        store.sources[cid].append({"id": sid, "source_url": rmsp.URL, "source_type": "FNS_RMSP", "source_title": rmsp.TITLE, "priority": 5,
                                   "source_date": rec.get("date"), "last_verified_at": rec.get("date"),
                                   "confirms": ["производимая продукция", "коды ОКПД2"], "fetch_status": "OK",
                                   "note": f"Сведения, указанные предприятием в реестре МСП (ИНН {c.get('inn')})"})
    added = len({p["id"] for p in new} - {p["id"] for p in old})
    removed = len({p["id"] for p in old} - {p["id"] for p in new})
    if added or removed:
        _change(changes, c, "products", "Продукция (реестр МСП)", f"{len(old)} поз." if old else None, f"{len(new)} поз.", day)
    store.dirty.add(cid)
    store.products_dirty.add(cid)
    return changes


# ---------- продукция из реестра российской промышленной продукции Минпромторга ----------

def _ru(d: str | None) -> str | None:
    return f"{d[8:10]}.{d[5:7]}.{d[:4]}" if d and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else d


def is_branch(c: dict) -> bool:
    """Филиал заведён с ИНН головной компании: записи реестра по этому ИНН относятся ко всем её заводам."""
    return "филиал" in f"{c.get('name') or ''} {c.get('legal_name') or ''}".lower()


def minprom_products(cid: str, recs: list[dict], as_of: str | None) -> list[dict]:
    # одна реестровая запись может встречаться несколько раз — продления (новый акт ТПП и срок действия): берём самую свежую
    latest: dict[str, dict] = {}
    for r in recs:
        cur = latest.get(r["Registernumber"])
        if cur is None or (r.get("Docdate") or "", r.get("Docvalidtill") or "") > (cur.get("Docdate") or "", cur.get("Docvalidtill") or ""):
            latest[r["Registernumber"]] = r
    out = []
    for r in sorted(latest.values(), key=lambda r: (r.get("OKPD2") or "", r["Productname"])):
        pid = f"{cid}-rpp-{r['Registernumber']}"
        code = r.get("OKPD2")
        params = [{"name": "ТН ВЭД", "value": r.get("TNVED")}, {"name": "Нормативный документ", "value": r.get("Nameofregulations")},
                  {"name": "Реестровая запись Минпромторга", "value": r["Registernumber"]}]
        if r.get("Score"):
            params.append({"name": "Баллы локализации", "value": r["Score"].removesuffix(".0")})
        elif r.get("Percentage"):
            params.append({"name": "Доля локализации, %", "value": r["Percentage"].removesuffix(".0")})
        basis = " ".join(x for x in [r.get("Docname"), f"от {_ru(r.get('Docdatebasis'))}" if r.get("Docdatebasis") else None] if x)
        desc = ("Производство в России подтверждено" + (f": {basis.lower() if basis.isupper() else basis}" if basis else "") + ". "
                "Запись в реестре российской промышленной продукции" + (f" с {_ru(r.get('Docdate'))}" if r.get("Docdate") else "")
                + (f", действует до {_ru(r.get('Docvalidtill'))}" if r.get("Docvalidtill") else "") + ".")
        out.append({"id": pid, "name": r["Productname"], "kind": "product",
                    "category": config.INDUSTRY_BY_DIVISION.get((code or "")[:2], "Продукция"),
                    "okpd2": {"code": code, "name": None, "status": "SOURCE"} if code else None,
                    "description": desc, "params": [x for x in params if x["value"]], "materials": [], "price": None, "volume": None,
                    "min_batch": None, "lead_time_production": None, "lead_time_delivery": None, "availability": None, "warehouse_id": None,
                    "photo": None, "source_id": f"{cid}-minprom", "last_verified_at": as_of, "company_id": cid})
    return out


def apply_minprom(store, cid: str, recs: list[dict] | None, as_of: str | None, today: date) -> list[dict]:
    """Продукция из реестра Минпромторга заменяет только позиции того же источника; остальная продукция не трогается."""
    c, day, sid = store.companies[cid], today.isoformat(), f"{cid}-minprom"
    old = [p for p in store.products[cid] if p.get("source_id") == sid]
    new = minprom_products(cid, recs, as_of) if recs and not is_branch(c) else []
    key = lambda lst: [(p["id"], p["name"], (p.get("okpd2") or {}).get("code"), p.get("description")) for p in lst]
    has_src = any(s["id"] == sid for s in store.sources[cid])
    if key(old) == key(new) and has_src == bool(new):
        return []
    changes: list[dict] = []
    store.products[cid] = [p for p in store.products[cid] if p.get("source_id") != sid] + new
    store.sources[cid] = [s for s in store.sources[cid] if s["id"] != sid]
    if new:
        store.sources[cid].append({"id": sid, "source_url": minpromtorg.URL, "source_type": "MPT_REESTR", "source_title": minpromtorg.TITLE,
                                   "priority": 4, "source_date": as_of, "last_verified_at": as_of,
                                   "confirms": ["производство продукции в России", "коды ОКПД2 и ТН ВЭД", "технические условия и ГОСТ"],
                                   "fetch_status": "OK", "note": f"Открытые данные Минпромторга, записи по ИНН {c.get('inn')}"})
    if len(old) != len(new) or {p["id"] for p in old} != {p["id"] for p in new}:
        _change(changes, c, "products", "Продукция (реестр Минпромторга)", f"{len(old)} поз." if old else None, f"{len(new)} поз.", day)
    store.dirty.add(cid)
    store.products_dirty.add(cid)
    return changes


# ---------- справочник ОКПД2 ----------

OKPD2_CODE = re.compile(r"\d{2}(\.\d{1,2}){0,2}(\.\d{1,3})?")


def apply_okpd2_names(store, names: dict[str, str]) -> int:
    """Названия кодов ОКПД2 из реестра МСП: только кодам без названия — названия первичного сбора не перезаписываются.
    Коды не по формату классификатора (позиции каталога закупок вида 56.10.11.129-0000) пропускаются. Возвращает число заполненных."""
    n = 0
    for code, name in sorted(names.items()):
        if name and OKPD2_CODE.fullmatch(code) and not store.okpd2.get(code):
            store.okpd2[code] = name
            n += 1
    return n
