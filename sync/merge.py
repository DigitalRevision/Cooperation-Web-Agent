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
from .providers import checko, egrul, fedresurs, girbo, opendata, pb
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
