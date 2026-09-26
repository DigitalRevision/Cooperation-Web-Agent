"""Каталог предприятий (база sm01_catalog): карточка предприятия ⇄ строки таблиц.

Карточка в памяти — тот же словарь, что раньше лежал в data/companies/<id>/company.json, продукция и источники —
отдельными списками (products.json, sources.json). Поэтому правила сбора (sync/merge.py), подбор поставщиков
(backend/app/matching.py) и сайт работают с привычной структурой, а хранится она в нормализованных таблицах.
Поля, которых нет в схеме, сохраняются в столбцах extra и возвращаются в карточку без потерь.
"""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal

from psycopg.types.json import Jsonb

# ---------- преобразования значений ----------


def d(v):
    """Дата из JSON (ГГГГ-ММ-ДД) → date. Пустое → None."""
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def iso(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return v.isoformat() if isinstance(v, date) else v


def num(v):
    """numeric из базы → int, если целое, иначе float (как было в JSON)."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() and abs(v) < 2**53 else float(v)
    return v


def split(obj: dict, known: tuple, where: str, strict: bool = False) -> dict:
    """Поля, которых нет в схеме. strict — таблица без столбца extra: неизвестное поле — ошибка, а не тихая потеря."""
    extra = {k: v for k, v in obj.items() if k not in known}
    if strict and extra:
        raise ValueError(f"{where}: поля {sorted(extra)} не предусмотрены схемой")
    return extra


def J(v):
    return Jsonb(v) if v is not None else None


# ---------- карточка предприятия ----------

COMPANY_KEYS = ("id", "name", "short", "legal_name", "inn", "ogrn", "kpp", "okpo", "reg_date", "legal_status", "status_code",
                "region", "city", "address", "site", "phones", "emails", "okved_main", "okved_extra", "industry", "subindustry",
                "description", "technologies", "materials", "capacities", "sites", "certificates", "verification_status",
                "discrepancies", "origin", "added_at", "ro_member", "sync", "history", "risk_signals", "registry",
                "capabilities_declared", "products", "sources")
SYNC_KEYS = ("checked_at", "status_by", "sources", "girbo_id")
REGISTRY_KEYS = ("arrears", "arrears_date", "tax_mode", "headcount", "headcount_year", "taxes_paid", "taxes_year", "msp",
                 "capital", "head", "checked_at", "deep_checked_at", "source_ids", "finance")
FINANCE_KEYS = ("year", "revenue", "net_profit", "assets", "equity")
PRODUCT_KEYS = ("id", "company_id", "name", "kind", "category", "description", "okpd2", "params", "materials", "price", "volume",
                "min_batch", "lead_time_production", "lead_time_delivery", "availability", "warehouse_id", "photo", "source_id",
                "last_verified_at")
PRICE_KEYS = ("value", "currency", "unit", "date", "source_id")
SOURCE_KEYS = ("id", "source_url", "source_type", "source_title", "priority", "source_date", "last_verified_at", "confirms",
               "fetch_status", "note", "company_id")

# дочерние таблицы, которые перезаписываются целиком при сохранении карточки
CHILD_TABLES = ("company_okved", "company_technology", "company_material", "company_capacity", "company_certificate",
                "company_site", "company_capability", "company_discrepancy_value", "company_discrepancy", "company_risk_signal",
                "company_finance", "company_registry", "company_history")


def _company_row(c: dict) -> dict:
    extra = split(c, COMPANY_KEYS, c["id"])
    sync = c.get("sync")
    if sync:
        sx = split(sync, SYNC_KEYS, c["id"] + ".sync")
        if sx:
            extra["sync"] = sx
    return {
        "id": c["id"], "name": c["name"], "short_name": c.get("short"), "legal_name": c.get("legal_name"),
        "inn": c.get("inn") or None, "ogrn": c.get("ogrn") or None, "kpp": c.get("kpp"), "okpo": c.get("okpo"),
        "reg_date": d(c.get("reg_date")), "legal_status": c.get("legal_status"), "status_code": c.get("status_code"),
        "region_code": c.get("region"), "city": c.get("city"), "address": c.get("address"), "site": c.get("site"),
        "phones": list(c.get("phones") or []), "emails": list(c.get("emails") or []), "okved_main": c.get("okved_main"),
        "industry": c.get("industry"), "subindustry": c.get("subindustry"), "description": c.get("description"),
        "verification_status": c.get("verification_status") or "UNVERIFIED", "origin": c.get("origin"),
        "added_at": d(c.get("added_at")), "ro_member": c.get("ro_member"),
        "sync_checked_at": d((sync or {}).get("checked_at")), "sync_status_by": (sync or {}).get("status_by"),
        "sync_sources": J((sync or {}).get("sources")), "girbo_id": (sync or {}).get("girbo_id"),
        "extra": Jsonb(extra),
    }


COMPANY_COLS = ("id", "name", "short_name", "legal_name", "inn", "ogrn", "kpp", "okpo", "reg_date", "legal_status", "status_code",
                "region_code", "city", "address", "site", "phones", "emails", "okved_main", "industry", "subindustry",
                "description", "verification_status", "origin", "added_at", "ro_member", "sync_checked_at", "sync_status_by",
                "sync_sources", "girbo_id", "extra")


def _children(c: dict) -> dict[str, list[tuple]]:
    cid, out = c["id"], {t: [] for t in CHILD_TABLES}
    for i, code in enumerate(c.get("okved_extra") or []):
        out["company_okved"].append((cid, code, i))
    for key, table in (("technologies", "company_technology"), ("materials", "company_material"), ("certificates", "company_certificate")):
        for i, x in enumerate(c.get(key) or []):
            out[table].append((cid, i, x["name"], x.get("source_id"), Jsonb(split(x, ("name", "source_id"), f"{cid}.{key}"))))
    for i, x in enumerate(c.get("capacities") or []):
        known = ("text", "value", "qualifier", "unit", "historical", "source_id")
        out["company_capacity"].append((cid, i, x["text"], x.get("value"), x.get("qualifier"), x.get("unit"), x.get("historical"),
                                        x.get("source_id"), Jsonb(split(x, known, f"{cid}.capacities"))))
    for i, x in enumerate(c.get("sites") or []):
        known = ("name", "type", "address", "area", "source_id")
        out["company_site"].append((cid, i, x.get("name"), x.get("type"), x.get("address"), x.get("area"), x.get("source_id"),
                                    Jsonb(split(x, known, f"{cid}.sites"))))
    for i, x in enumerate(c.get("capabilities_declared") or []):
        split(x, ("name", "okved"), f"{cid}.capabilities_declared", strict=True)
        out["company_capability"].append((cid, i, x["name"], list(x.get("okved") or [])))
    for i, x in enumerate(c.get("discrepancies") or []):
        out["company_discrepancy"].append((cid, i, x["field"], x.get("note"), Jsonb(split(x, ("field", "note", "values"), f"{cid}.discrepancies"))))
        for j, v in enumerate(x.get("values") or []):
            split(v, ("value", "source_id"), f"{cid}.discrepancies.values", strict=True)
            out["company_discrepancy_value"].append((cid, i, j, v.get("value"), v.get("source_id")))
    for i, x in enumerate(c.get("risk_signals") or []):
        known = ("code", "level", "title", "text", "source", "source_id")
        out["company_risk_signal"].append((cid, x["code"], i, x["level"], x["title"], x.get("text"), x.get("source"), x.get("source_id"),
                                           Jsonb(split(x, known, f"{cid}.risk_signals"))))
    reg = c.get("registry")
    if reg is not None:
        rx = split(reg, REGISTRY_KEYS, f"{cid}.registry")
        head = reg.get("head")
        if head is not None:
            hx = split(head, ("name", "position"), f"{cid}.registry.head")
            if hx:
                rx["head_extra"] = hx
        if "finance" not in reg:
            rx["no_finance"] = True   # поле отсутствовало (а не пустой список): вернуть без него
        out["company_registry"].append((cid, reg.get("arrears"), d(reg.get("arrears_date")), reg.get("tax_mode"), reg.get("headcount"),
                                        reg.get("headcount_year"), reg.get("taxes_paid"), reg.get("taxes_year"), reg.get("msp"),
                                        reg.get("capital"), (head or {}).get("name"), (head or {}).get("position"),
                                        d(reg.get("checked_at")), d(reg.get("deep_checked_at")), J(reg.get("source_ids")), Jsonb(rx)))
        for i, f in enumerate(reg.get("finance") or []):
            split(f, FINANCE_KEYS, f"{cid}.registry.finance", strict=True)
            out["company_finance"].append((cid, f["year"], i, f.get("revenue"), f.get("net_profit"), f.get("assets"), f.get("equity")))
    for i, h in enumerate(c.get("history") or []):
        split(h, ("date", "kind", "field", "old", "new"), f"{cid}.history", strict=True)
        out["company_history"].append((cid, i, d(h.get("date")), h["kind"], h.get("field"), _txt(h.get("old")), _txt(h.get("new"))))
    return out


def _txt(v):
    return None if v is None else str(v)


CHILD_INSERT = {
    "company_okved": "INSERT INTO company_okved (company_id, okved_code, pos) VALUES (%s,%s,%s)",
    "company_technology": "INSERT INTO company_technology (company_id, pos, name, source_id, extra) VALUES (%s,%s,%s,%s,%s)",
    "company_material": "INSERT INTO company_material (company_id, pos, name, source_id, extra) VALUES (%s,%s,%s,%s,%s)",
    "company_certificate": "INSERT INTO company_certificate (company_id, pos, name, source_id, extra) VALUES (%s,%s,%s,%s,%s)",
    "company_capacity": "INSERT INTO company_capacity (company_id, pos, text, value, qualifier, unit, historical, source_id, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    "company_site": "INSERT INTO company_site (company_id, pos, name, type, address, area, source_id, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
    "company_capability": "INSERT INTO company_capability (company_id, pos, name, okved) VALUES (%s,%s,%s,%s)",
    "company_discrepancy": "INSERT INTO company_discrepancy (company_id, pos, field, note, extra) VALUES (%s,%s,%s,%s,%s)",
    "company_discrepancy_value": "INSERT INTO company_discrepancy_value (company_id, discrepancy_pos, pos, value, source_id) VALUES (%s,%s,%s,%s,%s)",
    "company_risk_signal": "INSERT INTO company_risk_signal (company_id, code, pos, level, title, text, source_key, source_id, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    "company_registry": "INSERT INTO company_registry (company_id, arrears, arrears_date, tax_mode, headcount, headcount_year, taxes_paid, taxes_year, msp, capital, head_name, head_position, checked_at, deep_checked_at, source_ids, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    "company_finance": "INSERT INTO company_finance (company_id, year, pos, revenue, net_profit, assets, equity) VALUES (%s,%s,%s,%s,%s,%s,%s)",
    "company_history": "INSERT INTO company_history (company_id, pos, date, kind, field, old, new) VALUES (%s,%s,%s,%s,%s,%s,%s)",
}
# порядок вставки: сначала родительские строки
INSERT_ORDER = ("company_okved", "company_technology", "company_material", "company_certificate", "company_capacity", "company_site",
                "company_capability", "company_discrepancy", "company_discrepancy_value", "company_risk_signal", "company_registry",
                "company_finance", "company_history")


def _source_row(cid: str, i: int, s: dict) -> tuple:
    x = split(s, SOURCE_KEYS, f"{cid}.sources.{s.get('id')}")
    return (s["id"], cid, i, s.get("source_url"), s["source_type"], s.get("source_title"), s.get("priority"), d(s.get("source_date")),
            d(s.get("last_verified_at")), s.get("confirms"), s.get("fetch_status"), s.get("note"), Jsonb(x))


def _product_rows(cid: str, i: int, p: dict) -> tuple[tuple, list, list]:
    x = split(p, PRODUCT_KEYS, f"{cid}.products.{p['id']}")
    o, price = p.get("okpd2"), p.get("price")
    if o:
        ox = split(o, ("code", "name", "status"), f"{p['id']}.okpd2")
        if ox:
            x["okpd2_extra"] = ox
        x["okpd2_name"] = o.get("name")   # название из источника; при выдаче сверяется со справочником
    if price:
        px = split(price, PRICE_KEYS, f"{p['id']}.price")
        if px:
            x["price_extra"] = px
    row = (p["id"], cid, i, p["name"], p["kind"], p.get("category"), p.get("description"), (o or {}).get("code"), (o or {}).get("status"),
           (price or {}).get("value"), (price or {}).get("currency"), (price or {}).get("unit"), d((price or {}).get("date")),
           (price or {}).get("source_id"), _txt(p.get("volume")), _txt(p.get("min_batch")), p.get("lead_time_production"), p.get("lead_time_delivery"),
           _txt(p.get("availability")), _txt(p.get("warehouse_id")), p.get("photo"), p["source_id"], d(p.get("last_verified_at")), Jsonb(x))
    params = []
    for j, pr in enumerate(p.get("params") or []):
        split(pr, ("name", "value"), f"{p['id']}.params", strict=True)
        params.append((p["id"], j, pr["name"], _txt(pr.get("value"))))
    mats = []
    for j, m in enumerate(p.get("materials") or []):
        split(m, ("name", "source_id"), f"{p['id']}.materials", strict=True)
        mats.append((p["id"], j, m["name"], m.get("source_id")))
    return row, params, mats


def ensure_okved(conn, codes) -> None:
    """Коды, на которые ссылаются карточки, но которых нет в справочнике: заводятся без названия (NULL), не выдумываются."""
    codes = sorted({c for c in codes if c})
    if codes:
        conn.cursor().executemany("INSERT INTO okved (code, name) VALUES (%s, NULL) ON CONFLICT DO NOTHING", [(c,) for c in codes])


def save_companies(conn, companies: list[dict], sources: dict[str, list] | None = None, products: dict[str, list] | None = None) -> None:
    """Записать карточки (со всеми дочерними строками). sources/products — только для перечисленных в словаре компаний."""
    if not companies:
        return
    rows = [_company_row(c) for c in companies]
    ids = [r["id"] for r in rows]
    ensure_okved(conn, [c.get("okved_main") for c in companies] + [x for c in companies for x in (c.get("okved_extra") or [])])
    cur = conn.cursor()
    cols = ", ".join(COMPANY_COLS)
    upd = ", ".join(f"{k} = EXCLUDED.{k}" for k in COMPANY_COLS if k != "id")
    cur.executemany(f"INSERT INTO company ({cols}) VALUES ({', '.join('%(' + k + ')s' for k in COMPANY_COLS)}) "
                    f"ON CONFLICT (id) DO UPDATE SET {upd}, updated_at = now()", rows)
    for t in ("company_discrepancy_value",) + tuple(x for x in CHILD_TABLES if x != "company_discrepancy_value"):
        cur.execute(f"DELETE FROM {t} WHERE company_id = ANY(%s)", (ids,))
    kids = {t: [] for t in CHILD_TABLES}
    for c in companies:
        for t, lst in _children(c).items():
            kids[t] += lst
    for t in INSERT_ORDER:
        if kids[t]:
            cur.executemany(CHILD_INSERT[t], kids[t])
    if sources:
        sids = list(sources)
        srows = [_source_row(cid, i, s) for cid in sids for i, s in enumerate(sources[cid])]
        cur.execute("DELETE FROM source WHERE company_id = ANY(%s) AND NOT (id = ANY(%s))", (sids, [r[0] for r in srows]))
        if srows:
            cur.executemany("INSERT INTO source (id, company_id, pos, source_url, source_type, source_title, priority, source_date, last_verified_at, "
                            "confirms, fetch_status, note, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
                            "company_id = EXCLUDED.company_id, pos = EXCLUDED.pos, source_url = EXCLUDED.source_url, source_type = EXCLUDED.source_type, "
                            "source_title = EXCLUDED.source_title, priority = EXCLUDED.priority, source_date = EXCLUDED.source_date, "
                            "last_verified_at = EXCLUDED.last_verified_at, confirms = EXCLUDED.confirms, fetch_status = EXCLUDED.fetch_status, "
                            "note = EXCLUDED.note, extra = EXCLUDED.extra", srows)
    if products:
        pids = list(products)
        prows, params, mats = [], [], []
        for cid in pids:
            for i, p in enumerate(products[cid]):
                r, pa, ma = _product_rows(cid, i, p)
                prows.append(r); params += pa; mats += ma
        ensure_okpd2 = sorted({r[7] for r in prows if r[7]})
        if ensure_okpd2:
            names = {p["okpd2"]["code"]: p["okpd2"].get("name") for cid in pids for p in products[cid] if p.get("okpd2")}
            cur.executemany("INSERT INTO okpd2 (code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            [(c, names.get(c) or None) for c in ensure_okpd2])   # название неизвестно — NULL
        cur.execute("DELETE FROM product WHERE company_id = ANY(%s) AND NOT (id = ANY(%s))", (pids, [r[0] for r in prows]))
        cur.execute("DELETE FROM product_param WHERE product_id = ANY(%s)", ([r[0] for r in prows],))
        cur.execute("DELETE FROM product_material WHERE product_id = ANY(%s)", ([r[0] for r in prows],))
        if prows:
            pcols = ("id, company_id, pos, name, kind, category, description, okpd2_code, okpd2_status, price_value, price_currency, price_unit, "
                     "price_date, price_source_id, volume, min_batch, lead_time_production, lead_time_delivery, availability, warehouse_id, photo, "
                     "source_id, last_verified_at, extra")
            pupd = ", ".join(f"{k.strip()} = EXCLUDED.{k.strip()}" for k in pcols.split(",")[1:])
            cur.executemany(f"INSERT INTO product ({pcols}) VALUES ({', '.join(['%s'] * 24)}) ON CONFLICT (id) DO UPDATE SET {pupd}", prows)
        if params:
            cur.executemany("INSERT INTO product_param (product_id, pos, name, value) VALUES (%s,%s,%s,%s)", params)
        if mats:
            cur.executemany("INSERT INTO product_material (product_id, pos, name, source_id) VALUES (%s,%s,%s,%s)", mats)


# ---------- чтение ----------


def _group(rows, key="company_id"):
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


def _with_extra(base: dict, extra) -> dict:
    return {**base, **(extra or {})}


def load_companies(conn, ids: list[str] | None = None) -> tuple[dict[str, dict], dict[str, list], dict[str, list]]:
    """Карточки, продукция и источники. ids=None — весь каталог (несколько запросов на всю базу, без N+1)."""
    where, args = ("WHERE company_id = ANY(%s)", (ids,)) if ids is not None else ("", ())
    cwhere = "WHERE id = ANY(%s)" if ids is not None else ""
    q = lambda sql: conn.execute(sql, args).fetchall()
    comps = q(f"SELECT {', '.join(COMPANY_COLS)} FROM company {cwhere} ORDER BY id")
    okv = _group(q(f"SELECT company_id, okved_code FROM company_okved {where} ORDER BY company_id, pos"))
    simple = {k: _group(q(f"SELECT * FROM {t} {where} ORDER BY company_id, pos")) for k, t in
              (("technologies", "company_technology"), ("materials", "company_material"), ("certificates", "company_certificate"),
               ("capacities", "company_capacity"), ("sites", "company_site"), ("capabilities_declared", "company_capability"),
               ("discrepancies", "company_discrepancy"), ("risk_signals", "company_risk_signal"), ("history", "company_history"))}
    dvals = _group(q(f"SELECT * FROM company_discrepancy_value {where} ORDER BY company_id, discrepancy_pos, pos"))
    reg = {r["company_id"]: r for r in q(f"SELECT * FROM company_registry {where}")}
    fin = _group(q(f"SELECT * FROM company_finance {where} ORDER BY company_id, pos"))
    srcs = _group(q(f"SELECT * FROM source {where} ORDER BY company_id, pos"))
    prods = _group(q(f"SELECT * FROM product {where} ORDER BY company_id, pos"))
    pids = [p["id"] for lst in prods.values() for p in lst]
    params = _group(conn.execute("SELECT * FROM product_param WHERE product_id = ANY(%s) ORDER BY product_id, pos", (pids,)).fetchall(), "product_id")
    pmats = _group(conn.execute("SELECT * FROM product_material WHERE product_id = ANY(%s) ORDER BY product_id, pos", (pids,)).fetchall(), "product_id")
    okpd2 = {r["code"]: r["name"] for r in conn.execute("SELECT code, name FROM okpd2")}

    companies, products, sources = {}, {}, {}
    for r in comps:
        cid = r["id"]
        extra = dict(r["extra"] or {})
        sync_extra = extra.pop("sync", None)
        c = {"id": cid, "name": r["name"], "short": r["short_name"], "legal_name": r["legal_name"], "inn": r["inn"], "ogrn": r["ogrn"],
             "kpp": r["kpp"], "okpo": r["okpo"], "reg_date": iso(r["reg_date"]), "legal_status": r["legal_status"], "region": r["region_code"],
             "city": r["city"], "address": r["address"], "site": r["site"], "phones": list(r["phones"] or []), "emails": list(r["emails"] or []),
             "okved_main": r["okved_main"], "okved_extra": [x["okved_code"] for x in okv.get(cid, [])], "industry": r["industry"],
             "subindustry": r["subindustry"], "description": r["description"],
             "technologies": [_with_extra({"name": x["name"], "source_id": x["source_id"]}, x["extra"]) for x in simple["technologies"].get(cid, [])],
             "materials": [_with_extra({"name": x["name"], "source_id": x["source_id"]}, x["extra"]) for x in simple["materials"].get(cid, [])],
             "capacities": [_with_extra(_drop_none({"text": x["text"], "value": num(x["value"]), "qualifier": x["qualifier"], "unit": x["unit"],
                                                    "historical": x["historical"], "source_id": x["source_id"]}, keep=("value", "unit", "source_id")), x["extra"])
                            for x in simple["capacities"].get(cid, [])],
             "sites": [_with_extra({"name": x["name"], "type": x["type"], "address": x["address"], "area": x["area"], "source_id": x["source_id"]}, x["extra"])
                       for x in simple["sites"].get(cid, [])],
             "certificates": [_with_extra({"name": x["name"], "source_id": x["source_id"]}, x["extra"]) for x in simple["certificates"].get(cid, [])],
             "verification_status": r["verification_status"],
             "discrepancies": [_with_extra({"field": x["field"], "values": [{"value": v["value"], "source_id": v["source_id"]}
                                                                          for v in dvals.get(cid, []) if v["discrepancy_pos"] == x["pos"]],
                                            "note": x["note"]}, x["extra"]) for x in simple["discrepancies"].get(cid, [])],
             }
        if r["origin"] is not None:
            c["origin"] = r["origin"]
        if r["added_at"] is not None:
            c["added_at"] = iso(r["added_at"])
        if r["status_code"] is not None:
            c["status_code"] = r["status_code"]
        if r["ro_member"] is not None:
            c["ro_member"] = r["ro_member"]
        if r["sync_checked_at"] or r["sync_status_by"] is not None or r["sync_sources"] is not None or r["girbo_id"] or sync_extra:
            s = {}
            if r["sync_status_by"] is not None:
                s["status_by"] = list(r["sync_status_by"])
            if r["sync_checked_at"]:
                s["checked_at"] = iso(r["sync_checked_at"])
            if r["sync_sources"] is not None:
                s["sources"] = r["sync_sources"]
            if r["girbo_id"]:
                s["girbo_id"] = r["girbo_id"]
            c["sync"] = {**s, **(sync_extra or {})}
        c["history"] = [{"date": iso(h["date"]), "kind": h["kind"], "field": h["field"], "old": h["old"], "new": h["new"]}
                        for h in simple["history"].get(cid, [])]
        c["risk_signals"] = [_with_extra({"code": x["code"], "level": x["level"], "title": x["title"], "text": x["text"], "source": x["source_key"],
                                          "source_id": x["source_id"]}, x["extra"]) for x in simple["risk_signals"].get(cid, [])]
        g = reg.get(cid)
        if g is not None:
            rx = dict(g["extra"] or {})
            head_extra, no_fin = rx.pop("head_extra", None), rx.pop("no_finance", False)
            rg = {}
            for k, v in (("arrears", num(g["arrears"])), ("arrears_date", iso(g["arrears_date"])), ("tax_mode", g["tax_mode"]),
                         ("headcount", g["headcount"]), ("headcount_year", g["headcount_year"]), ("taxes_paid", num(g["taxes_paid"])),
                         ("taxes_year", g["taxes_year"]), ("msp", g["msp"]), ("capital", num(g["capital"])),
                         ("checked_at", iso(g["checked_at"])), ("deep_checked_at", iso(g["deep_checked_at"])), ("source_ids", g["source_ids"])):
                if v is not None:
                    rg[k] = v
            if g["head_name"] is not None or g["head_position"] is not None or head_extra:
                rg["head"] = {"name": g["head_name"], "position": g["head_position"], **(head_extra or {})}
            if not no_fin:
                rg["finance"] = [{"year": f["year"], "revenue": num(f["revenue"]), "net_profit": num(f["net_profit"]), "assets": num(f["assets"]),
                                  "equity": num(f["equity"])} for f in fin.get(cid, [])]
            c["registry"] = {**rg, **rx}
        c["capabilities_declared"] = [{"name": x["name"], "okved": list(x["okved"] or [])} for x in simple["capabilities_declared"].get(cid, [])]
        c.update(extra)
        companies[cid] = c
        sources[cid] = [_with_extra({"id": s["id"], "source_url": s["source_url"], "source_type": s["source_type"], "source_title": s["source_title"],
                                     "priority": s["priority"], "source_date": iso(s["source_date"]), "last_verified_at": iso(s["last_verified_at"]),
                                     "confirms": s["confirms"], "fetch_status": s["fetch_status"], "note": s["note"]}, s["extra"])
                        for s in srcs.get(cid, [])]
        plist = []
        for p in prods.get(cid, []):
            x = dict(p["extra"] or {})
            okpd2_name, okpd2_extra, price_extra = x.pop("okpd2_name", None), x.pop("okpd2_extra", None), x.pop("price_extra", None)
            price = None
            if p["price_value"] is not None or p["price_currency"] or p["price_unit"] or p["price_date"] or p["price_source_id"] or price_extra:
                price = {"value": num(p["price_value"]), "currency": p["price_currency"], "unit": p["price_unit"], "date": iso(p["price_date"]),
                         "source_id": p["price_source_id"], **(price_extra or {})}
            plist.append({
                "id": p["id"], "name": p["name"], "kind": p["kind"], "category": p["category"],
                "okpd2": {"code": p["okpd2_code"], "name": okpd2_name if okpd2_name is not None else okpd2.get(p["okpd2_code"]),
                          "status": p["okpd2_status"], **(okpd2_extra or {})} if p["okpd2_code"] else None,
                "description": p["description"],
                "params": [{"name": a["name"], "value": a["value"]} for a in params.get(p["id"], [])],
                "materials": [{"name": m["name"], "source_id": m["source_id"]} for m in pmats.get(p["id"], [])],
                "price": price, "volume": p["volume"], "min_batch": p["min_batch"], "lead_time_production": p["lead_time_production"],
                "lead_time_delivery": p["lead_time_delivery"], "availability": p["availability"], "warehouse_id": p["warehouse_id"],
                "photo": p["photo"], "source_id": p["source_id"], "last_verified_at": iso(p["last_verified_at"]), "company_id": cid, **x})
        products[cid] = plist
    return companies, products, sources


def _drop_none(obj: dict, keep=()) -> dict:
    return {k: v for k, v in obj.items() if v is not None or k in keep}


# ---------- справочники ----------


def _okved_key(code: str):
    return [int(x) if x.isdigit() else 0 for x in code.split(".")]


def load_dictionaries(conn) -> dict:
    return {
        "okved": {r["code"]: r["name"] for r in sorted(conn.execute("SELECT code, name FROM okved").fetchall(), key=lambda r: _okved_key(r["code"]))},
        "okpd2": {r["code"]: r["name"] for r in conn.execute("SELECT code, name FROM okpd2 ORDER BY code")},
        "regions": {r["code"]: {"code": r["code"], "name": r["name"], "pilot": r["is_pilot"]}
                    for r in conn.execute("SELECT * FROM region ORDER BY NOT is_pilot, code")},
        "cities": {r["name"]: [r["lat"], r["lon"]] for r in conn.execute("SELECT * FROM city ORDER BY name")},
        "cities_full": [dict(city=r["name"], lat=r["lat"], lon=r["lon"], note=r["note"]) for r in conn.execute("SELECT * FROM city ORDER BY name")],
        "relations": [{"id": r["id"], "from": r["from_company"], "from_product": r["from_product"], "to": r["to_company"],
                       "to_product": r["to_product"], "type": r["type"], "basis": r["basis"]}
                      for r in conn.execute("SELECT * FROM relation ORDER BY pos, id")],
        "materials": [r["name"] for r in conn.execute("SELECT name FROM material ORDER BY name")],
        "technologies": [r["name"] for r in conn.execute("SELECT name FROM technology ORDER BY name")],
    }


def save_okved(conn, okved: dict[str, str | None]) -> None:
    conn.cursor().executemany("INSERT INTO okved (code, name) VALUES (%s, %s) ON CONFLICT (code) DO UPDATE SET name = COALESCE(EXCLUDED.name, okved.name)",
                              list(okved.items()))


def save_okpd2(conn, okpd2: dict[str, str | None]) -> None:
    """Коды ОКПД2 и названия: новые коды добавляются, у известных заполняется только пустое название."""
    conn.cursor().executemany("INSERT INTO okpd2 (code, name) VALUES (%s, %s) ON CONFLICT (code) DO UPDATE SET name = COALESCE(okpd2.name, EXCLUDED.name)",
                              list(okpd2.items()))


def save_regions(conn, regions: dict[str, dict]) -> None:
    conn.cursor().executemany("INSERT INTO region (code, name, is_pilot) VALUES (%s, %s, %s) ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, "
                              "is_pilot = EXCLUDED.is_pilot", [(r["code"], r["name"], bool(r.get("pilot"))) for r in regions.values()])


def revision(conn) -> int:
    return conn.execute("SELECT revision FROM catalog_revision").fetchone()["revision"]


def bump_revision(conn, note: str | None = None) -> int:
    return conn.execute("UPDATE catalog_revision SET revision = revision + 1, updated_at = now(), note = %s RETURNING revision",
                        (note,)).fetchone()["revision"]
