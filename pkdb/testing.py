"""Тестовые базы: отдельный набор баз с префиксом sm01test_ и небольшой каталог первичного сбора (28 предприятий).

Сервер PostgreSQL для тестов:
  PK_TEST_PG_URL — адрес сервера (например, postgresql://postgres:…@127.0.0.1:5432/postgres);
  иначе, если установлен пакет pgserver, поднимается встроенный PostgreSQL в каталоге пользователя.
Рабочие базы (sm01_*) тесты не трогают.
"""
from __future__ import annotations
import os
from pathlib import Path

import psycopg
from psycopg import sql

from . import db
from . import seed

SEED = seed.SEED
PREFIX = "sm01test_"
USER_TABLES = {
    "accounts": "inbox_notice, notify_event, notify_channel, warehouse, company_claim, saved_search, user_compare, user_favorite, "
                "user_company, user_profile, user_account, user_session, app_user, telegram_link",
    "market": "request_response, request_supplier, purchase_request, offer",
    "chains": "chain_edge, chain_node_history, chain_node, chain",
    "moderation": "audit_log, report, source_flag, product_edit, item_decision, status_override, company_rep, registration_decision, registration",
}
_ready = False


def server_url() -> str | None:
    url = os.environ.get("PK_TEST_PG_URL")
    if url:
        return url
    try:
        import pgserver
    except ImportError:
        return None
    d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "sm01-pg-test"
    return pgserver.get_server(str(d), cleanup_mode=None).get_uri()


def setup() -> bool:
    """Пересоздать тестовые базы (один раз за сеанс тестов). False — сервера нет, тесты с базой пропускаются."""
    global _ready
    if _ready:
        return True
    url = server_url()
    if not url:
        return False
    os.environ["PK_PG_URL"] = url
    os.environ["PK_DB_PREFIX"] = PREFIX
    for n in db.DATABASES:
        os.environ.pop(f"PK_DB_URL_{n.upper()}", None)
    db.reset()
    with psycopg.connect(url, autocommit=True) as c:
        for n in db.DATABASES:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(PREFIX + n)))
    from . import migrate
    for n in db.DATABASES:
        migrate.ensure_database(n)
        migrate.apply(n)
    _ready = True
    return True


def load_seed() -> None:
    """Каталог — начальный набор (28 предприятий первичного сбора); журналы сбора и состояние — пустые."""
    seed.load(replace=True)
    with db.connect("ingest") as g:
        g.execute("TRUNCATE sync_change, sync_error, sync_run, sync_lock, sync_request, crawl_log, crawl_page, crawl_job, site_discovery, "
                  "site_search RESTART IDENTITY")
        g.execute("UPDATE sync_state SET status = '{}'")
        g.commit()


def clear_user_data() -> None:
    for name, tables in USER_TABLES.items():
        with db.connect(name) as c:
            c.execute(f"TRUNCATE {tables} RESTART IDENTITY")
            c.commit()
