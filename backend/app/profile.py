"""Личный кабинет пользователя.

Сайт хранит профиль одним документом (избранное, сравнение, сохранённые поиски, привязанные предприятия, склады,
учётная запись, компания, настройки уведомлений, лента, служебное состояние). Здесь он раскладывается по таблицам и
собирается обратно. Лента уведомлений не перезаписывается целиком: уведомления, которые сервер добавил после того,
как сайт прочитал профиль, при сохранении не теряются.
"""

from __future__ import annotations

from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from pkdb import tx

from .userstore import out_ts, rest, s, ts

PROFILE_KNOWN = (
    "favorites",
    "compare",
    "saved",
    "city",
    "companies",
    "warehouses",
    "account",
    "company",
    "notify",
    "inbox",
    "seen",
    "signedOut",
)
ACCOUNT_KNOWN = ("fio", "position", "email", "phone", "registered_at", "consent")
COMPANY_FIELDS = (
    "name",
    "legal_name",
    "inn",
    "ogrn",
    "kpp",
    "okpo",
    "okved_main",
    "reg_date",
    "address",
    "postal_address",
    "site",
    "phone",
    "email",
)
COMPANY_KNOWN = COMPANY_FIELDS + (
    "base_id",
    "from_base",
    "status",
    "submitted_at",
    "updated_at",
    "moderator_comment",
    "decided_at",
)
INBOX_MAX = 200


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def load_profile(uid: str) -> dict | None:
    """Собирает профиль пользователя и связанные списки из схемы учётных записей.

    Чтение нескольких таблиц выполняется в одной транзакции, поэтому профиль
    и его коллекции возвращаются из согласованного снимка.
    """
    with tx("accounts") as a:
        p = a.execute("SELECT * FROM user_profile WHERE user_id = %s", (uid,)).fetchone()
        if not p:
            return None
        acc = a.execute("SELECT * FROM user_account WHERE user_id = %s", (uid,)).fetchone()
        co = a.execute("SELECT * FROM user_company WHERE user_id = %s", (uid,)).fetchone()
        fav = [
            r["entity"]
            for r in a.execute(
                "SELECT entity FROM user_favorite WHERE user_id = %s ORDER BY pos", (uid,)
            )
        ]
        cmp = [
            r["entity"]
            for r in a.execute(
                "SELECT entity FROM user_compare WHERE user_id = %s ORDER BY pos", (uid,)
            )
        ]
        saved = [
            {"text": r["text"], "at": out_ts(r["at"]), **(r["extra"] or {})}
            for r in a.execute("SELECT * FROM saved_search WHERE user_id = %s ORDER BY pos", (uid,))
        ]
        claims = [
            _clean({"company_id": r["company_id"], "role": r["role"], "status": r["status"]})
            | (r["extra"] or {})
            for r in a.execute(
                "SELECT * FROM company_claim WHERE user_id = %s ORDER BY pos", (uid,)
            )
        ]
        whs = [
            _clean(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "type": r["type"],
                    "address": r["address"],
                    "city": r["city"],
                    "capacity": r["capacity"],
                    "available": r["available"],
                }
            )
            | (r["extra"] or {})
            for r in a.execute("SELECT * FROM warehouse WHERE user_id = %s ORDER BY pos", (uid,))
        ]
        chans = a.execute("SELECT * FROM notify_channel WHERE user_id = %s", (uid,)).fetchall()
        evs = a.execute("SELECT * FROM notify_event WHERE user_id = %s", (uid,)).fetchall()
        inbox = [
            inbox_item(r, site=True)
            for r in a.execute(
                "SELECT * FROM inbox_notice WHERE user_id = %s ORDER BY at DESC LIMIT %s",
                (uid, INBOX_MAX),
            )
        ]
    prof = {
        "favorites": fav,
        "compare": cmp,
        "saved": saved,
        "companies": claims,
        "warehouses": whs,
        "inbox": inbox,
        "signedOut": p["signed_out"],
        **(p["extra"] or {}),
    }
    if p["city"] is not None:
        prof["city"] = p["city"]
    if p["seen"] is not None:
        prof["seen"] = p["seen"]
    if acc:
        prof["account"] = _clean(
            {
                "fio": acc["fio"],
                "position": acc["position"],
                "email": acc["email"],
                "phone": acc["phone"],
                "registered_at": out_ts(acc["registered_at"]),
            }
        ) | (acc["extra"] or {})
    if co:
        prof["company"] = _clean(
            {
                **{k: co[k] for k in COMPANY_FIELDS},
                "base_id": co["base_company_id"],
                "from_base": list(co["from_base"] or []),
                "status": co["status"],
                "submitted_at": out_ts(co["submitted_at"]),
                "updated_at": out_ts(co["updated_at"]),
                "moderator_comment": co["moderator_comment"],
                "decided_at": out_ts(co["decided_at"]),
            }
        ) | (co["extra"] or {})
    if chans or evs:
        prof["notify"] = {
            "channels": {
                r["channel"]: {"on": r["enabled"], "contact": r["contact"]} for r in chans
            },
            "events": {},
        }
        for r in evs:
            prof["notify"]["events"].setdefault(r["event"], {})[r["channel"]] = r["enabled"]
    return prof


def inbox_item(r, site: bool) -> dict:
    """Уведомление ленты: для сайта поле события — ev и время ISO, для API — event и секунды."""
    base = {
        "id": r["id"],
        "title": r["title"],
        "text": r["text"],
        "link": r["link"] or "",
        "read": r["read"],
        "via": r["via"] or [],
    }
    if site:
        return {**base, "ev": r["event"], "at": out_ts(r["at"])}
    return {**base, "event": r["event"], "at": r["at"].timestamp()}


def save_profile(uid: str, prof: dict) -> None:
    """Сохраняет профиль и его дочерние коллекции в транзакции аккаунта пользователя.

    Поля, управляемые сервером, отделяются от дополнительных полей клиента;
    подчинённые списки заменяются внутри той же транзакции.
    """
    extra = rest(prof, PROFILE_KNOWN)
    with tx("accounts") as a:
        a.execute(
            "INSERT INTO app_user (id, kind) VALUES (%s, 'legacy') ON CONFLICT DO NOTHING", (uid,)
        )
        a.execute(
            "INSERT INTO user_profile (user_id, city, signed_out, seen, extra, updated_at) VALUES (%s,%s,%s,%s,%s, now()) "
            "ON CONFLICT (user_id) DO UPDATE SET city = EXCLUDED.city, signed_out = EXCLUDED.signed_out, seen = EXCLUDED.seen, "
            "extra = EXCLUDED.extra, updated_at = now()",
            (
                uid,
                s(prof.get("city")),
                bool(prof.get("signedOut")),
                Jsonb(prof["seen"]) if prof.get("seen") is not None else None,
                Jsonb(extra),
            ),
        )
        acc = prof.get("account")
        if acc:
            a.execute(
                "INSERT INTO user_account (user_id, fio, position, email, phone, registered_at, extra) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (user_id) DO UPDATE SET fio = EXCLUDED.fio, position = EXCLUDED.position, email = EXCLUDED.email, "
                "phone = EXCLUDED.phone, registered_at = EXCLUDED.registered_at, extra = EXCLUDED.extra",
                (
                    uid,
                    s(acc.get("fio")),
                    s(acc.get("position")),
                    s(acc.get("email")),
                    s(acc.get("phone")),
                    ts(acc.get("registered_at")),
                    Jsonb(rest(acc, ACCOUNT_KNOWN)),
                ),
            )
        co = prof.get("company")
        if co:
            vals = {k: s(co.get(k)) for k in COMPANY_FIELDS}
            vals.update(
                base_company_id=s(co.get("base_id")),
                from_base=list(co.get("from_base") or []),
                status=s(co.get("status")),
                submitted_at=ts(co.get("submitted_at")),
                updated_at=ts(co.get("updated_at")),
                moderator_comment=s(co.get("moderator_comment")),
                decided_at=ts(co.get("decided_at")),
                extra=Jsonb(rest(co, COMPANY_KNOWN)),
            )
            cols = ["user_id", *vals]
            a.execute(
                f"INSERT INTO user_company ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT (user_id) DO UPDATE SET "
                + ", ".join(f"{k} = EXCLUDED.{k}" for k in vals),
                (uid, *vals.values()),
            )
        else:
            a.execute("DELETE FROM user_company WHERE user_id = %s", (uid,))
        cur = a.cursor()
        for table in (
            "user_favorite",
            "user_compare",
            "saved_search",
            "company_claim",
            "warehouse",
            "notify_channel",
            "notify_event",
        ):
            cur.execute(f"DELETE FROM {table} WHERE user_id = %s", (uid,))
        cur.executemany(
            "INSERT INTO user_favorite (user_id, pos, entity) VALUES (%s,%s,%s)",
            [(uid, i, str(x)) for i, x in enumerate(prof.get("favorites") or [])],
        )
        cur.executemany(
            "INSERT INTO user_compare (user_id, pos, entity) VALUES (%s,%s,%s)",
            [(uid, i, str(x)) for i, x in enumerate(prof.get("compare") or [])],
        )
        cur.executemany(
            "INSERT INTO saved_search (user_id, pos, text, at, extra) VALUES (%s,%s,%s,%s,%s)",
            [
                (uid, i, x.get("text") or "", ts(x.get("at")), Jsonb(rest(x, ("text", "at"))))
                for i, x in enumerate(prof.get("saved") or [])
            ],
        )
        seen_claims = set()
        claims = []
        for i, x in enumerate(prof.get("companies") or []):
            if x.get("company_id") and x["company_id"] not in seen_claims:
                seen_claims.add(x["company_id"])
                claims.append(
                    (
                        uid,
                        x["company_id"],
                        i,
                        s(x.get("role")),
                        s(x.get("status")),
                        Jsonb(rest(x, ("company_id", "role", "status"))),
                    )
                )
        cur.executemany(
            "INSERT INTO company_claim (user_id, company_id, pos, role, status, extra) VALUES (%s,%s,%s,%s,%s,%s)",
            claims,
        )
        whs = {}
        for i, x in enumerate(prof.get("warehouses") or []):
            wid = str(x.get("id") or f"w{i}")
            whs[wid] = (
                uid,
                wid,
                i,
                s(x.get("name")),
                s(x.get("type")),
                s(x.get("address")),
                s(x.get("city")),
                s(x.get("capacity")),
                s(x.get("available")),
                Jsonb(rest(x, ("name", "type", "address", "city", "capacity", "available"))),
            )
        cur.executemany(
            "INSERT INTO warehouse (user_id, id, pos, name, type, address, city, capacity, available, extra) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            list(whs.values()),
        )
        n = prof.get("notify")
        if n:
            cur.executemany(
                "INSERT INTO notify_channel (user_id, channel, enabled, contact) VALUES (%s,%s,%s,%s)",
                [
                    (uid, ch, bool(cfg.get("on", cfg.get("enabled"))), cfg.get("contact") or "")
                    for ch, cfg in (n.get("channels") or {}).items()
                    if ch in ("telegram", "vk")
                ],
            )
            cur.executemany(
                "INSERT INTO notify_event (user_id, event, channel, enabled) VALUES (%s,%s,%s,%s)",
                [
                    (uid, ev, ch, bool(v))
                    for ev, per in (n.get("events") or {}).items()
                    for ch, v in (per or {}).items()
                    if ch in ("telegram", "vk")
                ],
            )
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
        rows.append(
            (
                uid,
                str(x["id"]),
                x.get("ev") or x.get("event"),
                x.get("title"),
                x.get("text"),
                x.get("link") or "",
                ts(x.get("at")) or datetime.now(UTC),
                bool(x.get("read")),
                Jsonb(x.get("via") or []),
            )
        )
    if not rows:
        a.execute(
            "DELETE FROM inbox_notice WHERE user_id = %s AND at <= now() - interval '1 minute'",
            (uid,),
        )
    a.cursor().executemany(
        "INSERT INTO inbox_notice (user_id, id, event, title, text, link, at, read, via) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (user_id, id) DO UPDATE SET read = inbox_notice.read OR EXCLUDED.read, title = EXCLUDED.title, "
        "text = EXCLUDED.text, link = EXCLUDED.link",
        rows,
    )
    a.execute(
        "DELETE FROM inbox_notice WHERE user_id = %s AND id IN (SELECT id FROM inbox_notice WHERE user_id = %s ORDER BY at DESC OFFSET %s)",
        (uid, uid, INBOX_MAX),
    )
