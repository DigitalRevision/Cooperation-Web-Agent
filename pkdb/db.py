"""Адреса баз и подключения.

Адрес базы раздела:
  PK_DB_URL_<РАЗДЕЛ>  — полный адрес, например PK_DB_URL_CATALOG=postgresql://pk_sync:…@db/sm01_catalog.
                        Так каждому сервису выдаётся своя роль с доступом только к нужным базам;
  иначе               — сервер из PK_PG_URL и имя базы PK_DB_PREFIX + раздел (по умолчанию sm01_catalog и т. д.).
"""
from __future__ import annotations
import os
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row

DATABASES = ("catalog", "ingest", "accounts", "market", "chains", "moderation")
DEFAULT_SERVER = "postgresql://postgres@127.0.0.1:5432/postgres"


def server_url() -> str:
    return os.environ.get("PK_PG_URL", DEFAULT_SERVER)


def db_name(name: str) -> str:
    return os.environ.get("PK_DB_PREFIX", "sm01_") + name


def dsn(name: str) -> str:
    if name not in DATABASES:
        raise ValueError(f"Неизвестная база раздела: {name}")
    own = os.environ.get(f"PK_DB_URL_{name.upper()}")
    if own:
        return own
    u = urlsplit(server_url())
    return urlunsplit((u.scheme, u.netloc, "/" + db_name(name), u.query, u.fragment))


def connect(name: str, autocommit: bool = False) -> psycopg.Connection:
    """Отдельное подключение (скрипты, миграции). Строки приходят словарями."""
    return psycopg.connect(dsn(name), autocommit=autocommit, row_factory=dict_row)


_pools: dict[str, object] = {}
_lock = threading.Lock()


def _pool(name: str):
    with _lock:
        p = _pools.get(name)
        if p is None:
            from psycopg_pool import ConnectionPool
            p = ConnectionPool(dsn(name), min_size=1, max_size=int(os.environ.get("PK_DB_POOL", "8")),
                               kwargs={"row_factory": dict_row}, open=True, name=f"pk-{name}")
            _pools[name] = p
        return p


@contextmanager
def tx(name: str):
    """Подключение из пула в транзакции: фиксируется при выходе без ошибки, иначе откатывается."""
    with _pool(name).connection() as conn:
        yield conn


def reset() -> None:
    """Закрыть пулы (тесты и смена адресов баз)."""
    with _lock:
        for p in _pools.values():
            p.close()
        _pools.clear()
