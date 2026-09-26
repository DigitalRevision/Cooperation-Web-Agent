"""Пользовательские данные сайта в базах разделов: биржа, модерация, личный кабинет, цепочки.

Сайт работает с коллекциями документов (offers, requests, registrations, …) — так было устроено хранилище в браузере.
Здесь каждая коллекция отображается на таблицы своей базы, а права доступа проверяет сервер:
  offers, requests, responses — видны всем (отклонённые модератором — только автору и модераторам);
                                 менять и удалять может автор или модератор;
  reports                      — сообщения об ошибках и журнал действий: модератор видит все, пользователь — свои;
  registrations, moderation    — пользователь видит только свою запись, модератор — все; решение пишет модератор;
  reps, overrides, decisions,
  sourceflags                  — видны всем, пишет только модератор;
  product_edits                — видны всем, каждый пишет только свой документ (id = id пользователя).
Автор записи всегда тот, кто её отправил: поле author из запроса не принимается.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from pkdb import tx

from .auth import is_moderator
from . import notify as nt

# ---------- значения ----------


def s(v):
    """Строка из формы: пустая → None."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return str(v)


def num(v) -> tuple[Decimal | None, str | None]:
    """Число из формы («1 000,5»). Второе значение — исходный текст, если он не число (сохраняется как есть)."""
    if v in (None, ""):
        return None, None
    if isinstance(v, bool):
        return None, str(v)
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)), None
    t = re.sub(r"[\s ]", "", str(v)).replace(",", ".")
    try:
        x = Decimal(t)
        return (x, None) if x.is_finite() else (None, str(v))
    except InvalidOperation:
        return None, str(v)


def out_num(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def ts(v) -> datetime | None:
    """Метка времени: ISO-строка браузера («…Z»), число секунд (API) или пусто."""
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    t = str(v).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(t)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def out_ts(v: datetime | None) -> str | None:
    """Как new Date().toISOString() в браузере: одинаковый формат для сортировки и сравнения строк."""
    if v is None:
        return None
    return v.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def dt(v) -> tuple[date | None, str | None]:
    if v in (None, ""):
        return None, None
    try:
        return date.fromisoformat(str(v)[:10]), None
    except ValueError:
        return None, str(v)


def out_date(v):
    return v.isoformat() if isinstance(v, date) else v


def rest(doc: dict, known) -> dict:
    return {k: v for k, v in doc.items() if k not in known and k != "id"}


def keep_raw(extra: dict, key: str, raw):
    if raw is not None:
        extra[f"{key}_raw"] = raw


# ---------- описание коллекции ----------


@dataclass
class Coll:
    name: str
    db: str
    read: Callable            # (conn, user) -> list[doc]
    put: Callable             # (conn, user, id, doc) -> doc
    delete: Callable          # (conn, user, id) -> None
    notify: Callable | None = None   # (user, id, doc, created) -> list[уведомление]
    extra: dict = field(default_factory=dict)


def forbid(msg="Недостаточно прав"):
    raise HTTPException(403, msg)


def need_moderator(u):
    if not is_moderator(u):
        forbid("Изменять эти данные может только модератор")


# ---------- биржа: предложения ----------

OFFER_KNOWN = ("title", "kind_label", "company_name", "company_id", "description", "material", "okpd2", "specs", "qty", "unit", "price", "country",
               "min_batch", "lead_prod", "lead_deliv", "city", "warehouse", "terms", "docs", "author", "status", "created_at", "updated_at")


def offer_row(doc: dict) -> dict:
    extra = rest(doc, OFFER_KNOWN)
    qty, qraw = num(doc.get("qty"))
    keep_raw(extra, "qty", qraw)
    price = doc.get("price") or None
    pv = pd = None
    if price:
        pv, praw = num(price.get("value"))
        keep_raw(extra, "price_value", praw)
        pd, draw = dt(price.get("date"))
        keep_raw(extra, "price_date", draw)
        px = rest(price, ("value", "currency", "unit", "date", "negotiable", "source"))
        if px:
            extra["price_extra"] = px
    title = s(doc.get("title"))
    if not title:
        raise HTTPException(422, "Укажите название предложения")
    return {"title": title, "category": s(doc.get("kind_label")), "company_name": s(doc.get("company_name")), "company_id": s(doc.get("company_id")),
            "description": s(doc.get("description")), "material": s(doc.get("material")), "okpd2": s(doc.get("okpd2")), "specs": s(doc.get("specs")),
            "qty": qty, "unit": s(doc.get("unit")), "price_value": pv, "price_currency": s((price or {}).get("currency")),
            "price_unit": s((price or {}).get("unit")), "price_date": pd, "price_negotiable": (price or {}).get("negotiable") if price else None,
            "price_source": "SELLER" if pv is not None else None, "country": s(doc.get("country")), "min_batch": s(doc.get("min_batch")),
            "lead_time_production": s(doc.get("lead_prod")), "lead_time_delivery": s(doc.get("lead_deliv")), "city": s(doc.get("city")),
            "warehouse": s(doc.get("warehouse")), "terms": s(doc.get("terms")), "docs": s(doc.get("docs")),
            "status": s(doc.get("status")) or "NEW", "created_at": ts(doc.get("created_at")), "extra": extra}


def offer_doc(r: dict) -> dict:
    x = dict(r["extra"] or {})
    price_extra = x.pop("price_extra", None)
    qty_raw, pv_raw, pd_raw = x.pop("qty_raw", None), x.pop("price_value_raw", None), x.pop("price_date_raw", None)
    price = None
    if r["price_value"] is not None or pv_raw is not None or price_extra:
        price = {"value": out_num(r["price_value"]) if r["price_value"] is not None else pv_raw, "currency": r["price_currency"],
                 "unit": r["price_unit"], "date": out_date(r["price_date"]) or pd_raw, "negotiable": r["price_negotiable"], **(price_extra or {})}
    return {"id": r["id"], "title": r["title"], "kind_label": r["category"], "company_name": r["company_name"], "company_id": r["company_id"],
            "description": r["description"], "material": r["material"], "okpd2": r["okpd2"], "specs": r["specs"],
            "qty": out_num(r["qty"]) if r["qty"] is not None else qty_raw, "unit": r["unit"], "price": price, "country": r["country"],
            "min_batch": r["min_batch"], "lead_prod": r["lead_time_production"], "lead_deliv": r["lead_time_delivery"], "city": r["city"],
            "warehouse": r["warehouse"], "terms": r["terms"], "docs": r["docs"], "author": r["author_id"], "status": r["status"],
            "created_at": out_ts(r["created_at"]), **x}


def offer_api(r: dict) -> dict:
    """Предложение в формате API (POST /api/v1/offers)."""
    return {"id": r["id"], "title": r["title"], "category": r["category"], "organization_id": r["company_id"], "description": r["description"],
            "material": r["material"], "okpd2": r["okpd2"], "quantity": out_num(r["qty"]), "unit": r["unit"], "price_value": out_num(r["price_value"]),
            "price_currency": r["price_currency"], "price_unit": r["price_unit"], "min_batch": r["min_batch"],
            "lead_time_production": r["lead_time_production"], "lead_time_delivery": r["lead_time_delivery"], "city": r["city"],
            "country": r["country"], "price_negotiable": r["price_negotiable"], "author": r["author_id"], "moderation_status": r["status"],
            "price_source": r["price_source"], "created_at": r["created_at"].timestamp()}


OFFER_COLS = ("title", "category", "company_name", "company_id", "description", "material", "okpd2", "specs", "qty", "unit", "price_value",
              "price_currency", "price_unit", "price_date", "price_negotiable", "price_source", "country", "min_batch", "lead_time_production",
              "lead_time_delivery", "city", "warehouse", "terms", "docs", "status", "extra")


def insert_offer(c, oid: str, author: str, row: dict) -> dict:
    row = dict(row, extra=Jsonb(row["extra"]))
    created = row.pop("created_at") or datetime.now(timezone.utc)
    cols = ", ".join(OFFER_COLS)
    return c.execute(f"INSERT INTO offer (id, author_id, created_at, {cols}) VALUES (%(id)s, %(author)s, %(created)s, "
                     f"{', '.join('%(' + k + ')s' for k in OFFER_COLS)}) RETURNING *", {**row, "id": oid, "author": author, "created": created}).fetchone()


def _decisions(conn_mod, coll: str) -> dict[str, str]:
    return {r["item_id"]: r["status"] for r in conn_mod.execute("SELECT item_id, status FROM item_decision WHERE coll = %s", (coll,))}


def _visible(u, rows, coll):
    """Отклонённые модератором записи видят только автор и модераторы."""
    if is_moderator(u):
        return rows
    with tx("moderation") as m:
        dec = _decisions(m, coll)
    uid = (u or {}).get("id")
    return [r for r in rows if dec.get(r["id"]) != "REJECTED" or r["author_id"] == uid]


def read_offers(c, u):
    return [offer_doc(r) for r in _visible(u, c.execute("SELECT * FROM offer ORDER BY created_at DESC").fetchall(), "offers")]


def _own_or_mod(u, author):
    if author != u["id"] and not is_moderator(u):
        forbid("Изменять запись может только её автор")


def put_offer(c, u, oid, doc):
    row = offer_row(doc)
    cur = c.execute("SELECT author_id, created_at FROM offer WHERE id = %s FOR UPDATE", (oid,)).fetchone()
    if cur is None:
        return offer_doc(insert_offer(c, oid, u["id"], row))
    _own_or_mod(u, cur["author_id"])
    row["created_at"] = row["created_at"] or cur["created_at"]
    row["extra"] = Jsonb(row["extra"])
    sets = ", ".join(f"{k} = %({k})s" for k in OFFER_COLS)
    return offer_doc(c.execute(f"UPDATE offer SET {sets}, created_at = %(created_at)s, updated_at = now() WHERE id = %(id)s RETURNING *",
                               {**row, "id": oid}).fetchone())


def delete_owned(table: str):
    def fn(c, u, rid):
        cur = c.execute(f"SELECT author_id FROM {table} WHERE id = %s", (rid,)).fetchone()
        if cur is None:
            return
        _own_or_mod(u, cur["author_id"])
        c.execute(f"DELETE FROM {table} WHERE id = %s", (rid,))
    return fn


# ---------- биржа: заявки ----------

REQUEST_KNOWN = ("target_company", "target_product", "what", "qty", "unit", "period", "material", "okpd2", "specs", "certs", "deadline", "region",
                 "region_name", "city", "max_distance", "budget", "extra", "author", "status", "created_at", "updated_at", "company_id")
REQUEST_COLS = ("company_id", "target_company_id", "target_product_id", "what", "qty", "unit", "period", "material", "okpd2", "specs", "certificates",
                "deadline", "region_code", "region_name", "city", "max_distance_km", "budget", "requirements", "status", "extra")


def request_row(doc: dict) -> dict:
    extra = rest(doc, REQUEST_KNOWN)
    qty, qraw = num(doc.get("qty"))
    keep_raw(extra, "qty", qraw)
    budget, braw = num(doc.get("budget"))
    keep_raw(extra, "budget", braw)
    dist, draw = num(doc.get("max_distance"))
    keep_raw(extra, "max_distance", draw)
    if dist is not None and dist != dist.to_integral_value():
        extra["max_distance_raw"], dist = str(doc.get("max_distance")), None
    dl, dlraw = dt(doc.get("deadline"))
    keep_raw(extra, "deadline", dlraw)
    what = s(doc.get("what"))
    if not what:
        raise HTTPException(422, "Укажите, что требуется")
    if budget is not None and budget < 0:
        extra["budget_raw"], budget = str(doc.get("budget")), None
    return {"company_id": s(doc.get("company_id")), "target_company_id": s(doc.get("target_company")), "target_product_id": s(doc.get("target_product")),
            "what": what, "qty": qty, "unit": s(doc.get("unit")), "period": s(doc.get("period")), "material": s(doc.get("material")),
            "okpd2": s(doc.get("okpd2")), "specs": s(doc.get("specs")), "certificates": s(doc.get("certs")), "deadline": dl,
            "region_code": s(doc.get("region")), "region_name": s(doc.get("region_name")), "city": s(doc.get("city")),
            "max_distance_km": int(dist) if dist is not None else None, "budget": budget, "requirements": s(doc.get("extra")),
            "status": s(doc.get("status")) or "NEW", "created_at": ts(doc.get("created_at")), "extra": extra}


def request_doc(r: dict) -> dict:
    x = dict(r["extra"] or {})
    raw = {k: x.pop(f"{k}_raw", None) for k in ("qty", "budget", "max_distance", "deadline")}
    val = lambda v, k: (out_num(v) if v is not None else raw[k])
    return {"id": r["id"], "target_company": r["target_company_id"] or "", "target_product": r["target_product_id"] or "", "what": r["what"],
            "qty": val(r["qty"], "qty"), "unit": r["unit"], "period": r["period"], "material": r["material"], "okpd2": r["okpd2"], "specs": r["specs"],
            "certs": r["certificates"], "deadline": out_date(r["deadline"]) or raw["deadline"], "region": r["region_code"], "region_name": r["region_name"],
            "city": r["city"], "max_distance": val(r["max_distance_km"], "max_distance"), "budget": val(r["budget"], "budget"),
            "extra": r["requirements"], "author": r["author_id"], "status": r["status"], "created_at": out_ts(r["created_at"]),
            "company_id": r["company_id"], **x}


def insert_request(c, rid: str, author: str, row: dict, parsed_query=None) -> dict:
    row = dict(row, extra=Jsonb(row["extra"]))
    created = row.pop("created_at") or datetime.now(timezone.utc)
    cols = ", ".join(REQUEST_COLS)
    return c.execute(f"INSERT INTO purchase_request (id, author_id, created_at, parsed_query, {cols}) VALUES (%(id)s, %(author)s, %(created)s, "
                     f"%(pq)s, {', '.join('%(' + k + ')s' for k in REQUEST_COLS)}) RETURNING *",
                     {**row, "id": rid, "author": author, "created": created, "pq": Jsonb(parsed_query) if parsed_query else None}).fetchone()


def read_requests(c, u):
    return [request_doc(r) for r in _visible(u, c.execute("SELECT * FROM purchase_request ORDER BY created_at DESC").fetchall(), "requests")]


def put_request(c, u, rid, doc):
    row = request_row(doc)
    cur = c.execute("SELECT author_id, created_at FROM purchase_request WHERE id = %s FOR UPDATE", (rid,)).fetchone()
    if cur is None:
        return request_doc(insert_request(c, rid, u["id"], row))
    _own_or_mod(u, cur["author_id"])
    row["created_at"] = row["created_at"] or cur["created_at"]
    row["extra"] = Jsonb(row["extra"])
    sets = ", ".join(f"{k} = %({k})s" for k in REQUEST_COLS)
    return request_doc(c.execute(f"UPDATE purchase_request SET {sets}, created_at = %(created_at)s, updated_at = now() WHERE id = %(id)s RETURNING *",
                                 {**row, "id": rid}).fetchone())


# ---------- биржа: отклики ----------

RESPONSE_KNOWN = ("request_id", "company", "text", "price", "author", "at")


def response_doc(r):
    return {"id": r["id"], "request_id": r["request_id"], "company": r["company"], "text": r["text"], "price": r["price"], "author": r["author_id"],
            "at": out_ts(r["at"]), **(r["extra"] or {})}


def read_responses(c, u):
    return [response_doc(r) for r in c.execute("SELECT * FROM request_response ORDER BY at")]


def put_response(c, u, rid, doc):
    req = s(doc.get("request_id"))
    if not req or not c.execute("SELECT 1 FROM purchase_request WHERE id = %s", (req,)).fetchone():
        raise HTTPException(404, "Заявка не найдена")
    cur = c.execute("SELECT author_id FROM request_response WHERE id = %s FOR UPDATE", (rid,)).fetchone()
    vals = (req, s(doc.get("company")), s(doc.get("text")), s(doc.get("price")), ts(doc.get("at")) or datetime.now(timezone.utc),
            Jsonb(rest(doc, RESPONSE_KNOWN)))
    if cur is None:
        r = c.execute("INSERT INTO request_response (id, author_id, request_id, company, text, price, at, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                      (rid, u["id"], *vals)).fetchone()
    else:
        _own_or_mod(u, cur["author_id"])
        r = c.execute("UPDATE request_response SET request_id=%s, company=%s, text=%s, price=%s, at=%s, extra=%s WHERE id=%s RETURNING *",
                      (*vals, rid)).fetchone()
    return response_doc(r)


# ---------- модерация: сообщения и журнал ----------

REPORT_KNOWN = ("kind", "company_id", "field", "text", "url", "author", "status", "created_at")


def report_doc(r):
    return {"id": r["id"], "kind": r["kind"], "company_id": r["company_id"], "field": r["field"], "text": r["text"], "url": r["url"],
            "author": r["author_id"], "status": r["status"], "created_at": out_ts(r["created_at"]), **(r["extra"] or {})}


def read_reports(c, u):
    if is_moderator(u):
        rows = c.execute("SELECT * FROM report ORDER BY created_at DESC LIMIT 2000").fetchall()
    else:
        rows = c.execute("SELECT * FROM report WHERE author_id = %s ORDER BY created_at DESC LIMIT 500", ((u or {}).get("id"),)).fetchall()
    return [_drop_none(report_doc(r)) for r in rows]


def put_report(c, u, rid, doc):
    kind = s(doc.get("kind"))
    if not kind:
        raise HTTPException(422, "Не указан вид записи")
    if kind == "override":
        need_moderator(u)
    cur = c.execute("SELECT author_id FROM report WHERE id = %s FOR UPDATE", (rid,)).fetchone()
    vals = (kind, s(doc.get("company_id")), s(doc.get("field")), s(doc.get("text")), s(doc.get("url")), s(doc.get("status")),
            ts(doc.get("created_at")) or datetime.now(timezone.utc), Jsonb(rest(doc, REPORT_KNOWN)))
    if cur is None:
        r = c.execute("INSERT INTO report (id, author_id, kind, company_id, field, text, url, status, created_at, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                      (rid, u["id"], *vals)).fetchone()
    else:
        _own_or_mod(u, cur["author_id"])
        r = c.execute("UPDATE report SET kind=%s, company_id=%s, field=%s, text=%s, url=%s, status=%s, created_at=%s, extra=%s WHERE id=%s RETURNING *",
                      (*vals, rid)).fetchone()
    return _drop_none(report_doc(r))


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


# ---------- модерация: отметки модератора (видны всем, пишет модератор) ----------


def simple_moderator_coll(name: str, table: str, key: str, cols: dict[str, str], ts_cols=(), default_ts=None):
    """Коллекция «видна всем, пишет модератор»: cols — поле документа → столбец."""
    def to_doc(r):
        d = {"id": r[key]}
        for f, col in cols.items():
            v = r[col]
            d[f] = out_ts(v) if col in ts_cols else v
        return _drop_none(d)

    def read(c, u):
        return [to_doc(r) for r in c.execute(f"SELECT * FROM {table}")]

    def put(c, u, rid, doc):
        need_moderator(u)
        vals = {}
        for f, col in cols.items():
            if col == key:
                continue   # ключ записи — её id
            v = doc.get(f)
            if col in ts_cols:
                v = ts(v) or (datetime.now(timezone.utc) if col == default_ts else None)
            elif f in ("author", "moderator"):
                v = u["id"]
            vals[col] = v
        colnames = [key, *vals]
        upd = ", ".join(f"{k} = EXCLUDED.{k}" for k in vals)
        r = c.execute(f"INSERT INTO {table} ({', '.join(colnames)}) VALUES ({', '.join(['%s'] * len(colnames))}) "
                      f"ON CONFLICT ({key}) DO UPDATE SET {upd} RETURNING *", (rid, *vals.values())).fetchone()
        return to_doc(r)

    def delete(c, u, rid):
        need_moderator(u)
        c.execute(f"DELETE FROM {table} WHERE {key} = %s", (rid,))

    return Coll(name, "moderation", read, put, delete)


def _check_status(doc, allowed):
    if doc.get("status") not in allowed:
        raise HTTPException(422, "Статус: " + ", ".join(allowed))


# ---------- модерация: регистрации представителей ----------

REG_COMPANY = ("name", "legal_name", "inn", "ogrn", "kpp", "okpo", "okved_main", "reg_date", "address", "postal_address", "site", "phone", "email")
REG_KNOWN = ("account", "company", "base_id", "base_company_id", "from_base", "status", "submitted_at", "edit", "data_checked", "user", "created_at")


def _accounts_of(uids: list[str]) -> dict[str, dict]:
    if not uids:
        return {}
    with tx("accounts") as a:
        return {r["user_id"]: r for r in a.execute("SELECT * FROM user_account WHERE user_id = ANY(%s)", (uids,))}


def registration_doc(r, acc: dict | None) -> dict:
    x = dict(r["extra"] or {})
    company = {k: r[k] for k in REG_COMPANY if r[k] is not None} | (x.pop("company_extra", None) or {})
    account = {"fio": acc["fio"], "position": acc["position"], "email": acc["email"], "phone": acc["phone"] or ""} if acc else {}
    return {"id": r["user_id"], "account": account, "company": company, "base_id": r["base_company_id"], "from_base": list(r["from_base"] or []),
            "status": r["status"], "submitted_at": out_ts(r["submitted_at"]), "edit": r["is_edit"], **x}


def read_registrations(c, u):
    if is_moderator(u):
        rows = c.execute("SELECT * FROM registration ORDER BY submitted_at DESC").fetchall()
    else:
        rows = c.execute("SELECT * FROM registration WHERE user_id = %s", ((u or {}).get("id"),)).fetchall()
    accs = _accounts_of([r["user_id"] for r in rows])
    return [registration_doc(r, accs.get(r["user_id"])) for r in rows]


def save_account(uid: str, acc: dict, consent: bool | None = None):
    """Контакты представителя — только в sm01_accounts (персональные данные)."""
    with tx("accounts") as a:
        a.execute("INSERT INTO app_user (id, kind) VALUES (%s, 'legacy') ON CONFLICT DO NOTHING", (uid,))
        a.execute("INSERT INTO user_account (user_id, fio, position, email, phone, consent_at) VALUES (%s,%s,%s,%s,%s, CASE WHEN %s THEN now() END) "
                  "ON CONFLICT (user_id) DO UPDATE SET fio = EXCLUDED.fio, position = EXCLUDED.position, email = EXCLUDED.email, phone = EXCLUDED.phone, "
                  "consent_at = COALESCE(EXCLUDED.consent_at, user_account.consent_at)",
                  (uid, s(acc.get("fio")), s(acc.get("position")), s(acc.get("email")), s(acc.get("phone")), bool(consent)))


def upsert_registration(c, uid: str, doc: dict) -> dict:
    co = doc.get("company") or {}
    extra = rest(doc, REG_KNOWN)
    cx = {k: v for k, v in co.items() if k not in REG_COMPANY}
    if cx:
        extra["company_extra"] = cx
    vals = {k: s(co.get(k)) for k in REG_COMPANY}
    vals.update(base_company_id=s(doc.get("base_id") or doc.get("base_company_id")), from_base=list(doc.get("from_base") or []),
                status=s(doc.get("status")) or "PENDING", is_edit=bool(doc.get("edit")), data_checked=doc.get("data_checked"),
                submitted_at=ts(doc.get("submitted_at")) or datetime.now(timezone.utc), extra=Jsonb(extra))
    cols = ["user_id", *vals]
    upd = ", ".join(f"{k} = EXCLUDED.{k}" for k in vals)
    return c.execute(f"INSERT INTO registration ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT (user_id) DO UPDATE SET {upd} "
                     "RETURNING *", (uid, *vals.values())).fetchone()


def put_registration(c, u, rid, doc):
    if rid != u["id"] and not is_moderator(u):
        forbid("Отправить регистрацию можно только от своего имени")
    if doc.get("account") is not None:
        save_account(rid, doc["account"], consent=True if rid == u["id"] else None)
    r = upsert_registration(c, rid, doc)
    return registration_doc(r, _accounts_of([rid]).get(rid))


def delete_registration(c, u, rid):
    if rid != u["id"] and not is_moderator(u):
        forbid()
    c.execute("DELETE FROM registration WHERE user_id = %s", (rid,))


MOD_COLS = {"status": "status", "comment": "comment", "decided_at": "decided_at", "submitted_at": "submitted_at", "moderator": "moderator_id",
            "company_name": "company_name"}


def moderation_doc(r):
    d = {"id": r["user_id"], "status": r["status"], "comment": r["comment"] or "", "decided_at": out_ts(r["decided_at"]),
         "submitted_at": out_ts(r["submitted_at"]), "moderator": r["moderator_id"], "company_name": r["company_name"]}
    return {**d, **(r["extra"] or {})}


def read_moderation(c, u):
    if is_moderator(u):
        return [moderation_doc(r) for r in c.execute("SELECT * FROM registration_decision")]
    return [moderation_doc(r) for r in c.execute("SELECT * FROM registration_decision WHERE user_id = %s", ((u or {}).get("id"),))]


def put_moderation(c, u, rid, doc):
    need_moderator(u)
    _check_status(doc, ("APPROVED", "REJECTED"))
    x = rest(doc, tuple(MOD_COLS))
    r = c.execute("INSERT INTO registration_decision (user_id, status, comment, decided_at, submitted_at, moderator_id, company_name, extra) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET status = EXCLUDED.status, comment = EXCLUDED.comment, "
                  "decided_at = EXCLUDED.decided_at, submitted_at = EXCLUDED.submitted_at, moderator_id = EXCLUDED.moderator_id, "
                  "company_name = EXCLUDED.company_name, extra = EXCLUDED.extra RETURNING *",
                  (rid, doc["status"], s(doc.get("comment")), ts(doc.get("decided_at")) or datetime.now(timezone.utc), ts(doc.get("submitted_at")),
                   u["id"], s(doc.get("company_name")), Jsonb(x))).fetchone()
    c.execute("UPDATE registration SET status = %s WHERE user_id = %s", (doc["status"], rid))
    return moderation_doc(r)


def delete_moderation(c, u, rid):
    need_moderator(u)
    c.execute("DELETE FROM registration_decision WHERE user_id = %s", (rid,))


# ---------- модерация: правки продукции ----------


def read_product_edits(c, u):
    docs: dict[str, dict] = {}
    for r in c.execute("SELECT * FROM product_edit ORDER BY user_id, product_id"):
        d = docs.setdefault(r["user_id"], {"id": r["user_id"], "company_id": r["company_id"], "items": {}})
        item = {"deleted": r["deleted"], "updated_at": out_ts(r["updated_at"])}
        if r["fields"] is not None:
            item["fields"] = r["fields"]
        d["items"][r["product_id"]] = item
    return list(docs.values())


def put_product_edits(c, u, rid, doc):
    if rid != u["id"] and not is_moderator(u):
        forbid("Правки продукции каждый пишет только от своего имени")
    items = doc.get("items") or {}
    c.execute("DELETE FROM product_edit WHERE user_id = %s AND NOT (product_id = ANY(%s))", (rid, list(items)))
    for pid, e in items.items():
        c.execute("INSERT INTO product_edit (user_id, product_id, company_id, deleted, fields, updated_at) VALUES (%s,%s,%s,%s,%s,%s) "
                  "ON CONFLICT (user_id, product_id) DO UPDATE SET company_id = EXCLUDED.company_id, deleted = EXCLUDED.deleted, "
                  "fields = EXCLUDED.fields, updated_at = EXCLUDED.updated_at",
                  (rid, pid, s(doc.get("company_id")), bool(e.get("deleted")), Jsonb(e["fields"]) if e.get("fields") is not None else None,
                   ts(e.get("updated_at")) or datetime.now(timezone.utc)))
    return next((d for d in read_product_edits(c, u) if d["id"] == rid), {"id": rid, "company_id": doc.get("company_id"), "items": {}})


def delete_product_edits(c, u, rid):
    if rid != u["id"] and not is_moderator(u):
        forbid()
    c.execute("DELETE FROM product_edit WHERE user_id = %s", (rid,))


# ---------- уведомления в мессенджеры о событиях сайта ----------
# Ленту на сайте для этих событий собирает сам сайт; сервер отправляет только копии в Telegram и ВКонтакте


def _notify_moderation(u, rid, doc, created):
    name = doc.get("company_name") or "Компания"
    text = f"{name}: " + ("данные подтверждены, права представителя подтверждены." if doc.get("status") == "APPROVED"
                         else "регистрация отклонена." + (f" Комментарий: {doc['comment']}" if doc.get("comment") else ""))
    return [("moderation", text, [rid], "#cabinet.company")]


def _notify_decision(u, rid, doc, created):
    coll, item = doc.get("coll"), doc.get("item_id")
    table = {"offers": "offer", "requests": "purchase_request"}.get(coll)
    if not table:
        return []
    with tx("market") as m:
        r = m.execute(f"SELECT author_id, {'title' if table == 'offer' else 'what'} AS t FROM {table} WHERE id = %s", (item,)).fetchone()
    if not r:
        return []
    what = ("Предложение" if coll == "offers" else "Заявка") + f" «{r['t']}»"
    ok = doc.get("status") == "APPROVED"
    text = f"{what}: {'одобрено модератором' if ok else 'отклонено модератором'}" + (f". Комментарий: {doc['comment']}" if doc.get("comment") else "")
    return [("moderation", text, [r["author_id"]], f"#{'sell' if coll == 'offers' else 'r.' + item}")]


def _notify_response(u, rid, doc, created):
    if not created:
        return []
    with tx("market") as m:
        r = m.execute("SELECT author_id, what FROM purchase_request WHERE id = %s", (doc.get("request_id"),)).fetchone()
    if not r or r["author_id"] == u["id"]:
        return []
    return [("responses", f"На заявку «{r['what']}» откликнулось предприятие {doc.get('company') or ''}".strip(), [r["author_id"]], f"#r.{doc.get('request_id')}")]


def _notify_request(u, rid, doc, created):
    """Новая заявка: копии подтверждённым представителям подобранных поставщиков (кроме автора)."""
    if not created:
        return []
    from .matching import parse_query, search
    from .repo import get_repo
    q = parse_query(" ".join(filter(None, [doc.get("what"), doc.get("material")])))
    if doc.get("region"):
        q.region = doc["region"]
    matched = {m["company_id"] for m in search(q, get_repo(), city=doc.get("city"))}
    if doc.get("target_company"):
        matched.add(doc["target_company"])
    with tx("moderation") as mo:
        reps = [r["user_id"] for r in mo.execute("SELECT user_id FROM company_rep WHERE company_id = ANY(%s)", (list(matched),)) if r["user_id"] != u["id"]]
    return [("new_requests", doc.get("what") or "", reps, f"#r.{rid}")] if reps else []


def send_notices(notices: list, inbox: bool = False) -> None:
    """Отправить уведомления (в фоне после ответа): настройки каналов берутся из sm01_accounts."""
    for event, text, uids, link in notices:
        recipients = nt.settings_for(uids)
        if recipients:
            nt.notifier.dispatch(event, text, recipients, link=link, inbox=inbox)


# ---------- реестр коллекций ----------

COLLECTIONS: dict[str, Coll] = {
    "offers": Coll("offers", "market", read_offers, put_offer, delete_owned("offer")),
    "requests": Coll("requests", "market", read_requests, put_request, delete_owned("purchase_request"), _notify_request),
    "responses": Coll("responses", "market", read_responses, put_response, delete_owned("request_response"), _notify_response),
    "reports": Coll("reports", "moderation", read_reports, put_report, delete_owned("report")),
    "sourceflags": simple_moderator_coll("sourceflags", "source_flag", "source_id", {"disabled": "disabled", "at": "at", "author": "author_id"},
                                         ts_cols=("at",), default_ts="at"),
    "reps": simple_moderator_coll("reps", "company_rep", "user_id", {"company_id": "company_id", "company_name": "company_name", "approved_at": "approved_at"},
                                  ts_cols=("approved_at",), default_ts="approved_at"),
    "overrides": simple_moderator_coll("overrides", "status_override", "company_id",
                                       {"company_id": "company_id", "status": "status", "note": "note", "author": "author_id", "created_at": "created_at"},
                                       ts_cols=("created_at",), default_ts="created_at"),
    "decisions": simple_moderator_coll("decisions", "item_decision", "key",
                                       {"coll": "coll", "item_id": "item_id", "status": "status", "comment": "comment", "decided_at": "decided_at",
                                        "moderator": "moderator_id"}, ts_cols=("decided_at",), default_ts="decided_at"),
    "registrations": Coll("registrations", "moderation", read_registrations, put_registration, delete_registration),
    "moderation": Coll("moderation", "moderation", read_moderation, put_moderation, delete_moderation, _notify_moderation),
    "product_edits": Coll("product_edits", "moderation", read_product_edits, put_product_edits, delete_product_edits),
}
COLLECTIONS["decisions"].notify = _notify_decision
# ревизия ручных статусов и отключённых источников: API перечитывает их поверх каталога
AFFECTS_CATALOG = {"overrides", "sourceflags"}


def coll(name: str) -> Coll:
    c = COLLECTIONS.get(name)
    if not c:
        raise HTTPException(404, "Неизвестная коллекция")
    return c


def read_all(u) -> dict[str, list]:
    out = {}
    for name, spec in COLLECTIONS.items():
        with tx(spec.db) as c:
            out[name] = spec.read(c, u)
    return out
