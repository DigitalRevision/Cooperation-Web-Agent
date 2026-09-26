"""Кто обращается к API: сессия браузера или служебный токен.

Сессия браузера. При первом заходе сайт вызывает POST /api/v1/session и получает случайный токен; в базе sm01_accounts
хранится только его SHA-256. Так заявки, регистрации и цепочки пользователя сохраняются на сервере, модератор видит их
сразу, а пользователь может вернуться к ним после перезагрузки страницы.

Служебные токены (PK_TOKENS, JSON {"токен": "роль"}) — для администраторов и модераторов. Идентификатор такого
пользователя — staff-<начало хеша токена>: сам токен не попадает ни в базу, ни в поле «автор» записей.
Роль пользователя сессии меняет администратор: python -m pkdb.admin set-role <id> moderator.
"""
from __future__ import annotations
import hashlib
import json
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request

from pkdb import tx

ROLES = {"user": 1, "company_admin": 2, "moderator": 3, "admin": 4}
# Без PK_TOKENS работают только локальные dev-токены; в docker-compose по умолчанию токенов нет (PK_TOKENS='{}'),
# чтобы развёрнутый сервер не пускал по общеизвестному dev-admin
TOKENS = json.loads(os.environ.get("PK_TOKENS", '{"dev-user":"user","dev-admin":"admin"}'))
if not isinstance(TOKENS, dict) or any(r not in ROLES for r in TOKENS.values()):
    raise RuntimeError("PK_TOKENS: ожидается JSON-объект {токен: роль}, роли: " + ", ".join(ROLES))

SESSIONS_PER_HOUR = int(os.environ.get("PK_SESSIONS_PER_HOUR", "30"))
_new_sessions: dict[str, deque] = defaultdict(deque)
_staff_known: set[tuple[str, str]] = set()


def token_hash(tok: str) -> str:
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()


def staff_id(tok: str) -> str:
    return "staff-" + token_hash(tok)[:16]


def _bearer(authorization: str | None) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def resolve(tok: str) -> dict | None:
    if not tok:
        return None
    if tok in TOKENS:
        uid, role = staff_id(tok), TOKENS[tok]
        if (uid, role) not in _staff_known:   # запись пользователя для служебного токена заводится один раз
            with tx("accounts") as c:
                c.execute("INSERT INTO app_user (id, role, kind) VALUES (%s, %s, 'staff') ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role, "
                          "last_seen_at = now()", (uid, role))
            _staff_known.add((uid, role))
        return {"id": uid, "role": role, "kind": "staff"}
    with tx("accounts") as c:
        r = c.execute("SELECT u.id, u.role, u.kind FROM user_session s JOIN app_user u ON u.id = s.user_id WHERE s.token_hash = %s",
                      (token_hash(tok),)).fetchone()
    return dict(r) if r else None


def optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    return resolve(_bearer(authorization))


def user(authorization: str | None = Header(default=None)) -> dict:
    u = resolve(_bearer(authorization))
    if not u:
        raise HTTPException(401, "Требуется авторизация")
    return u


def role(min_role: str):
    def dep(u: dict = Depends(user)):
        if ROLES[u["role"]] < ROLES[min_role]:
            raise HTTPException(403, "Недостаточно прав")
        return u
    return dep


def is_moderator(u: dict | None) -> bool:
    return bool(u) and ROLES[u["role"]] >= ROLES["moderator"]


def create_session(request: Request) -> dict:
    """Новый пользователь и сессия. Не больше PK_SESSIONS_PER_HOUR новых сессий в час с одного адреса."""
    ip = request.client.host if request.client else "anon"
    q, now = _new_sessions[ip], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= SESSIONS_PER_HOUR:
        raise HTTPException(429, "Слишком много новых сессий с этого адреса. Повторите позже.")
    q.append(now)
    uid, tok = secrets.token_hex(12), secrets.token_urlsafe(32)
    with tx("accounts") as c:
        c.execute("INSERT INTO app_user (id) VALUES (%s)", (uid,))
        c.execute("INSERT INTO user_session (token_hash, user_id, user_agent) VALUES (%s, %s, %s)",
                  (token_hash(tok), uid, (request.headers.get("user-agent") or "")[:300]))
    return {"token": tok, "user": {"id": uid, "role": "user"}}
