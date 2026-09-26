"""Личный кабинет (sm01_accounts) и производственные цепочки (sm01_chains) пользователя.

Сайт хранит профиль одним документом (избранное, сравнение, сохранённые поиски, привязанные предприятия, склады,
учётная запись, компания, настройки уведомлений, лента, служебное состояние). Здесь он раскладывается по таблицам и
собирается обратно. Лента уведомлений не перезаписывается целиком: уведомления, которые сервер добавил после того,
как сайт прочитал профиль, при сохранении не теряются.
"""
from __future__ import annotations
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from pkdb import tx

from .userstore import out_ts, rest, s, ts

PROFILE_KNOWN = ("favorites", "compare", "saved", "city", "companies", "warehouses", "account", "company", "notify", "inbox", "seen", "signedOut")
ACCOUNT_KNOWN = ("fio", "position", "email", "phone", "registered_at", "consent")
COMPANY_FIELDS = ("name", "legal_name", "inn", "ogrn", "kpp", "okpo", "okved_main", "reg_date", "address", "postal_address", "site", "phone", "email")
COMPANY_KNOWN = COMPANY_FIELDS + ("base_id", "from_base", "status", "submitted_at", "updated_at", "moderator_comment", "decided_at")
INBOX_MAX = 200


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def load_profile(uid: str) -> dict | None:
    with tx("accounts") as a:
        p = a.execute("SELECT * FROM user_profile WHERE user_id = %s", (uid,)).fetchone()
        if not p:
            return None
        acc = a.execute("SELECT * FROM user_account WHERE user_id = %s", (uid,)).fetchone()
        co = a.execute("SELECT * FROM user_company WHERE user_id = %s", (uid,)).fetchone()
        fav = [r["entity"] for r in a.execute("SELECT entity FROM user_favorite WHERE user_id = %s ORDER BY pos", (uid,))]
        cmp = [r["entity"] for r in a.execute("SELECT entity FROM user_compare WHERE user_id = %s ORDER BY pos", (uid,))]
        saved = [{"text": r["text"], "at": out_ts(r["at"]), **(r["extra"] or {})} for r in a.execute("SELECT * FROM saved_search WHERE user_id = %s ORDER BY pos", (uid,))]
        claims = [_clean({"company_id": r["company_id"], "role": r["role"], "status": r["status"]}) | (r["extra"] or {})
                  for r in a.execute("SELECT * FROM company_claim WHERE user_id = %s ORDER BY pos", (uid,))]
        whs = [_clean({"id": r["id"], "name": r["name"], "type": r["type"], "address": r["address"], "city": r["city"], "capacity": r["capacity"],
                       "available": r["available"]}) | (r["extra"] or {}) for r in a.execute("SELECT * FROM warehouse WHERE user_id = %s ORDER BY pos", (uid,))]
        chans = a.execute("SELECT * FROM notify_channel WHERE user_id = %s", (uid,)).fetchall()
        evs = a.execute("SELECT * FROM notify_event WHERE user_id = %s", (uid,)).fetchall()
        inbox = [inbox_item(r, site=True) for r in a.execute("SELECT * FROM inbox_notice WHERE user_id = %s ORDER BY at DESC LIMIT %s", (uid, INBOX_MAX))]
    prof = {"favorites": fav, "compare": cmp, "saved": saved, "companies": claims, "warehouses": whs, "inbox": inbox,
            "signedOut": p["signed_out"], **(p["extra"] or {})}
    if p["city"] is not None:
        prof["city"] = p["city"]
    if p["seen"] is not None:
        prof["seen"] = p["seen"]
    if acc:
        prof["account"] = _clean({"fio": acc["fio"], "position": acc["position"], "email": acc["email"], "phone": acc["phone"],
                                  "registered_at": out_ts(acc["registered_at"])}) | (acc["extra"] or {})
    if co:
        prof["company"] = _clean({**{k: co[k] for k in COMPANY_FIELDS}, "base_id": co["base_company_id"], "from_base": list(co["from_base"] or []),
                                  "status": co["status"], "submitted_at": out_ts(co["submitted_at"]), "updated_at": out_ts(co["updated_at"]),
                                  "moderator_comment": co["moderator_comment"], "decided_at": out_ts(co["decided_at"])}) | (co["extra"] or {})
    if chans or evs:
        prof["notify"] = {"channels": {r["channel"]: {"on": r["enabled"], "contact": r["contact"]} for r in chans}, "events": {}}
        for r in evs:
            prof["notify"]["events"].setdefault(r["event"], {})[r["channel"]] = r["enabled"]
    return prof


def inbox_item(r, site: bool) -> dict:
    """Уведомление ленты: для сайта поле события — ev и время ISO, для API — event и секунды."""
    base = {"id": r["id"], "title": r["title"], "text": r["text"], "link": r["link"] or "", "read": r["read"], "via": r["via"] or []}
    if site:
        return {**base, "ev": r["event"], "at": out_ts(r["at"])}
    return {**base, "event": r["event"], "at": r["at"].timestamp()}


def save_profile(uid: str, prof: dict) -> None:
    extra = rest(prof, PROFILE_KNOWN)
    with tx("accounts") as a:
        a.execute("INSERT INTO app_user (id, kind) VALUES (%s, 'legacy') ON CONFLICT DO NOTHING", (uid,))
        a.execute("INSERT INTO user_profile (user_id, city, signed_out, seen, extra, updated_at) VALUES (%s,%s,%s,%s,%s, now()) "
                  "ON CONFLICT (user_id) DO UPDATE SET city = EXCLUDED.city, signed_out = EXCLUDED.signed_out, seen = EXCLUDED.seen, "
                  "extra = EXCLUDED.extra, updated_at = now()",
                  (uid, s(prof.get("city")), bool(prof.get("signedOut")), Jsonb(prof["seen"]) if prof.get("seen") is not None else None, Jsonb(extra)))
        acc = prof.get("account")
        if acc:
            a.execute("INSERT INTO user_account (user_id, fio, position, email, phone, registered_at, extra) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                      "ON CONFLICT (user_id) DO UPDATE SET fio = EXCLUDED.fio, position = EXCLUDED.position, email = EXCLUDED.email, "
                      "phone = EXCLUDED.phone, registered_at = EXCLUDED.registered_at, extra = EXCLUDED.extra",
                      (uid, s(acc.get("fio")), s(acc.get("position")), s(acc.get("email")), s(acc.get("phone")), ts(acc.get("registered_at")),
                       Jsonb(rest(acc, ACCOUNT_KNOWN))))
        co = prof.get("company")
        if co:
            vals = {k: s(co.get(k)) for k in COMPANY_FIELDS}
            vals.update(base_company_id=s(co.get("base_id")), from_base=list(co.get("from_base") or []), status=s(co.get("status")),
                        submitted_at=ts(co.get("submitted_at")), updated_at=ts(co.get("updated_at")), moderator_comment=s(co.get("moderator_comment")),
                        decided_at=ts(co.get("decided_at")), extra=Jsonb(rest(co, COMPANY_KNOWN)))
            cols = ["user_id", *vals]
            a.execute(f"INSERT INTO user_company ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT (user_id) DO UPDATE SET "
                      + ", ".join(f"{k} = EXCLUDED.{k}" for k in vals), (uid, *vals.values()))
        else:
            a.execute("DELETE FROM user_company WHERE user_id = %s", (uid,))
        cur = a.cursor()
        for table in ("user_favorite", "user_compare", "saved_search", "company_claim", "warehouse", "notify_channel", "notify_event"):
            cur.execute(f"DELETE FROM {table} WHERE user_id = %s", (uid,))
        cur.executemany("INSERT INTO user_favorite (user_id, pos, entity) VALUES (%s,%s,%s)", [(uid, i, str(x)) for i, x in enumerate(prof.get("favorites") or [])])
        cur.executemany("INSERT INTO user_compare (user_id, pos, entity) VALUES (%s,%s,%s)", [(uid, i, str(x)) for i, x in enumerate(prof.get("compare") or [])])
        cur.executemany("INSERT INTO saved_search (user_id, pos, text, at, extra) VALUES (%s,%s,%s,%s,%s)",
                        [(uid, i, x.get("text") or "", ts(x.get("at")), Jsonb(rest(x, ("text", "at")))) for i, x in enumerate(prof.get("saved") or [])])
        seen_claims = set()
        claims = []
        for i, x in enumerate(prof.get("companies") or []):
            if x.get("company_id") and x["company_id"] not in seen_claims:
                seen_claims.add(x["company_id"])
                claims.append((uid, x["company_id"], i, s(x.get("role")), s(x.get("status")), Jsonb(rest(x, ("company_id", "role", "status")))))
        cur.executemany("INSERT INTO company_claim (user_id, company_id, pos, role, status, extra) VALUES (%s,%s,%s,%s,%s,%s)", claims)
        whs = {}
        for i, x in enumerate(prof.get("warehouses") or []):
            wid = str(x.get("id") or f"w{i}")
            whs[wid] = (uid, wid, i, s(x.get("name")), s(x.get("type")), s(x.get("address")), s(x.get("city")), s(x.get("capacity")),
                        s(x.get("available")), Jsonb(rest(x, ("name", "type", "address", "city", "capacity", "available"))))
        cur.executemany("INSERT INTO warehouse (user_id, id, pos, name, type, address, city, capacity, available, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        list(whs.values()))
        n = prof.get("notify")
        if n:
            cur.executemany("INSERT INTO notify_channel (user_id, channel, enabled, contact) VALUES (%s,%s,%s,%s)",
                            [(uid, ch, bool(cfg.get("on", cfg.get("enabled"))), cfg.get("contact") or "")
                             for ch, cfg in (n.get("channels") or {}).items() if ch in ("telegram", "vk")])
            cur.executemany("INSERT INTO notify_event (user_id, event, channel, enabled) VALUES (%s,%s,%s,%s)",
                            [(uid, ev, ch, bool(v)) for ev, per in (n.get("events") or {}).items() for ch, v in (per or {}).items() if ch in ("telegram", "vk")])
        save_inbox(a, uid, prof.get("inbox"))


def save_inbox(a, uid: str, items: list | None) -> None:
    """Лента: переданные уведомления добавляются и обновляются (прочитано). Уведомления, которые добавил сервер, сохранение
    профиля не удаляет — сайт мог прочитать профиль раньше. Пустая лента — явная очистка (новая регистрация после выхода)."""
    if items is None:
        return
    rows = []
    for x in items:
        if not x.get("id"):
            continue
        rows.append((uid, str(x["id"]), x.get("ev") or x.get("event"), x.get("title"), x.get("text"), x.get("link") or "",
                     ts(x.get("at")) or datetime.now(timezone.utc), bool(x.get("read")), Jsonb(x.get("via") or [])))
    if not rows:
        a.execute("DELETE FROM inbox_notice WHERE user_id = %s AND at <= now() - interval '1 minute'", (uid,))
    a.cursor().executemany("INSERT INTO inbox_notice (user_id, id, event, title, text, link, at, read, via) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                           "ON CONFLICT (user_id, id) DO UPDATE SET read = inbox_notice.read OR EXCLUDED.read, title = EXCLUDED.title, "
                           "text = EXCLUDED.text, link = EXCLUDED.link", rows)
    a.execute("DELETE FROM inbox_notice WHERE user_id = %s AND id IN (SELECT id FROM inbox_notice WHERE user_id = %s ORDER BY at DESC OFFSET %s)",
              (uid, uid, INBOX_MAX))


# ---------- цепочки ----------

CHAIN_KNOWN = ("id", "title", "buyer_city", "nodes", "edges", "created_at", "updated_at", "kind", "owner")
NODE_KNOWN = ("id", "step", "req_text", "requirement", "company_id", "organization_id", "product_id", "status", "history")
EDGE_KNOWN = ("from", "to", "type", "relation", "qty", "unit", "price", "min_batch", "lead_prod", "lead_deliv")


def load_chains(owner: str, cid: str | None = None, api: bool = False) -> list[dict]:
    with tx("chains") as c:
        chains = c.execute("SELECT * FROM chain WHERE owner_id = %s" + (" AND id = %s" if cid else "") + " ORDER BY updated_at DESC",
                           (owner, cid) if cid else (owner,)).fetchall()
        ids = [x["id"] for x in chains]
        nodes = c.execute("SELECT * FROM chain_node WHERE chain_id = ANY(%s) ORDER BY chain_id, pos", (ids,)).fetchall()
        hist = c.execute("SELECT * FROM chain_node_history WHERE chain_id = ANY(%s) ORDER BY chain_id, node_id, pos", (ids,)).fetchall()
        edges = c.execute("SELECT * FROM chain_edge WHERE chain_id = ANY(%s) ORDER BY chain_id, pos", (ids,)).fetchall()
    out = []
    for ch in chains:
        def node(n):
            h = [x for x in hist if x["chain_id"] == ch["id"] and x["node_id"] == n["id"]]
            if api:
                return {"id": n["id"], "step": n["step"], "requirement": n["requirement"], "organization_id": n["company_id"], "product_id": n["product_id"],
                        "status": n["status"], "history": [{"from": x["from_company"], "to": x["to_company"], "reason": x["reason"],
                                                            "at": x["at"].timestamp() if x["at"] else None} for x in h]}
            return {"id": n["id"], "step": n["step"], "req_text": n["requirement"], "company_id": n["company_id"], "product_id": n["product_id"],
                    "status": n["status"], "history": [_clean({"company_id": x["from_company"], "to": x["to_company"], "reason": x["reason"],
                                                               "at": out_ts(x["at"])}) for x in h], **(n["extra"] or {})}

        def edge(e):
            if api:
                return {"from": e["from_node"], "to": e["to_node"], "relation": e["relation"]}
            return _clean({"from": e["from_node"], "to": e["to_node"], "type": e["relation"], "qty": e["qty"], "unit": e["unit"], "price": e["price"],
                           "min_batch": e["min_batch"], "lead_prod": e["lead_time_production"], "lead_deliv": e["lead_time_delivery"]}) | (e["extra"] or {})

        d = {"id": ch["id"], "title": ch["title"], "buyer_city": ch["buyer_city"],
             "nodes": [node(n) for n in nodes if n["chain_id"] == ch["id"]], "edges": [edge(e) for e in edges if e["chain_id"] == ch["id"]]}
        if api:
            d["owner"] = ch["owner_id"]
        else:
            d.update(kind="chain", created_at=out_ts(ch["created_at"]), updated_at=out_ts(ch["updated_at"]), **(ch["extra"] or {}))
        out.append(d)
    return out


def save_chain(owner: str, doc: dict) -> None:
    cid = str(doc["id"])
    title = s(doc.get("title")) or "Новая цепочка"
    with tx("chains") as c:
        cur = c.execute("SELECT owner_id FROM chain WHERE id = %s FOR UPDATE", (cid,)).fetchone()
        if cur and cur["owner_id"] != owner:
            from fastapi import HTTPException
            raise HTTPException(404, "Цепочка не найдена")
        c.execute("INSERT INTO chain (id, owner_id, title, buyer_city, created_at, updated_at, extra) VALUES (%s,%s,%s,%s,%s, COALESCE(%s, now()), %s) "
                  "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, buyer_city = EXCLUDED.buyer_city, updated_at = EXCLUDED.updated_at, "
                  "extra = EXCLUDED.extra",
                  (cid, owner, title, s(doc.get("buyer_city")), ts(doc.get("created_at")) or datetime.now(timezone.utc), ts(doc.get("updated_at")),
                   Jsonb(rest(doc, CHAIN_KNOWN))))
        c.execute("DELETE FROM chain_node WHERE chain_id = %s", (cid,))
        c.execute("DELETE FROM chain_edge WHERE chain_id = %s", (cid,))
        cur = c.cursor()
        seen, nodes, hist = set(), [], []
        for i, n in enumerate(doc.get("nodes") or []):
            nid = str(n.get("id") or f"n{i}")
            if nid in seen:
                continue
            seen.add(nid)
            company = s(n.get("company_id") or n.get("organization_id"))
            status = n.get("status") if n.get("status") in ("EMPTY", "SELECTED", "DECLINED", "CONFIRMED") else ("SELECTED" if company else "EMPTY")
            nodes.append((cid, nid, i, s(n.get("step")) or "Этап", s(n.get("req_text") or n.get("requirement")), company, s(n.get("product_id")), status,
                          Jsonb(rest(n, NODE_KNOWN))))
            for j, h in enumerate(n.get("history") or []):
                hist.append((cid, nid, j, s(h.get("company_id") or h.get("from")), s(h.get("to")), s(h.get("reason")), ts(h.get("at"))))
        cur.executemany("INSERT INTO chain_node (chain_id, id, pos, step, requirement, company_id, product_id, status, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", nodes)
        cur.executemany("INSERT INTO chain_node_history (chain_id, node_id, pos, from_company, to_company, reason, at) VALUES (%s,%s,%s,%s,%s,%s,%s)", hist)
        edges = []
        for i, e in enumerate(doc.get("edges") or []):
            rel = e.get("type") or e.get("relation")
            if rel not in ("CONFIRMED_RELATION", "POTENTIAL_RELATION", "INFERRED_RELATION"):
                rel = "INFERRED_RELATION"
            edges.append((cid, i, str(e.get("from")), str(e.get("to")), rel, s(e.get("qty")), s(e.get("unit")), s(e.get("price")), s(e.get("min_batch")),
                          s(e.get("lead_prod")), s(e.get("lead_deliv")), Jsonb(rest(e, EDGE_KNOWN))))
        cur.executemany("INSERT INTO chain_edge (chain_id, pos, from_node, to_node, relation, qty, unit, price, min_batch, lead_time_production, "
                        "lead_time_delivery, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", edges)


def delete_chain(owner: str, cid: str) -> None:
    with tx("chains") as c:
        c.execute("DELETE FROM chain WHERE id = %s AND owner_id = %s", (cid, owner))
