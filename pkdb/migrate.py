"""Создание баз разделов и применение схем.

  python -m pkdb.migrate            # создать недостающие базы и применить схемы (повторный запуск ничего не ломает)
  python -m pkdb.migrate --roles    # и создать роли сервисов с доступом только к своим базам
  python -m pkdb.migrate --seed     # и заполнить пустой каталог начальным набором (pkdb/seed)

Схема базы — pkdb/schema/<раздел>.sql (версия 001). Последующие изменения — файлы pkdb/schema/<раздел>/NNN_*.sql,
каждый применяется один раз; применённые версии записаны в таблице schema_migrations каждой базы.

Роли (--roles, пароли из окружения):
  pk_api     (PK_API_DB_PASSWORD)     — каталог только на чтение; запросы запуска сбора и задачи обхода;
                                         пользователи, биржа, цепочки, модерация — чтение и запись;
  pk_sync    (PK_SYNC_DB_PASSWORD)    — каталог и сбор данных; к персональным данным доступа нет;
  pk_crawler (PK_CRAWLER_DB_PASSWORD) — журнал и результаты обхода; каталог только на чтение.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from .db import DATABASES, db_name, dsn, server_url

SCHEMA = Path(__file__).parent / "schema"

# роль → база → права: "read" — только SELECT, "write" — SELECT/INSERT/UPDATE/DELETE, список — запись только в эти таблицы
ROLES = {
    "pk_api": {"catalog": "read", "ingest": ["sync_request", "crawl_job", "site_discovery"],
               "accounts": "write", "market": "write", "chains": "write", "moderation": "write"},
    "pk_sync": {"catalog": "write", "ingest": "write"},
    "pk_crawler": {"catalog": "read", "ingest": ["crawl_log", "crawl_page", "crawl_job", "site_discovery", "site_search"]},
}
ROLE_PASSWORD_ENV = {"pk_api": "PK_API_DB_PASSWORD", "pk_sync": "PK_SYNC_DB_PASSWORD", "pk_crawler": "PK_CRAWLER_DB_PASSWORD"}


def log(*a):
    print(*a, flush=True)


def ensure_database(name: str) -> None:
    """Создать базу раздела, если её нет. Для баз со своим адресом (PK_DB_URL_…) только проверяет подключение."""
    try:
        psycopg.connect(dsn(name)).close()
        return
    except psycopg.OperationalError as e:
        if os.environ.get(f"PK_DB_URL_{name.upper()}"):
            raise SystemExit(f"Нет подключения к базе {name}: {e}")
    with psycopg.connect(server_url(), autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(db_name(name))))
    log(f"  создана база {db_name(name)}")


def migrations(name: str) -> list[tuple[str, str]]:
    out = [("001_init", (SCHEMA / f"{name}.sql").read_text(encoding="utf-8"))]
    d = SCHEMA / name
    if d.is_dir():
        out += [(p.stem, p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.sql"))]
    return out


def apply(name: str) -> list[str]:
    done = []
    with psycopg.connect(dsn(name)) as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        have = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
        for version, text in migrations(name):
            if version in have:
                continue
            c.execute(text)
            c.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            done.append(version)
        if name == "catalog":
            # поиск по подстроке (триграммы) — если расширение есть на сервере; без него работает полнотекстовый поиск
            try:
                with c.transaction():
                    c.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                    c.execute("CREATE INDEX IF NOT EXISTS company_name_trgm ON company USING gin (name gin_trgm_ops)")
                    c.execute("CREATE INDEX IF NOT EXISTS product_name_trgm ON product USING gin (name gin_trgm_ops)")
            except psycopg.Error:
                pass
    return done


def ensure_roles() -> None:
    with psycopg.connect(server_url(), autocommit=True) as c:
        for role, env in ROLE_PASSWORD_ENV.items():
            pw = os.environ.get(env)
            if not pw:
                log(f"  роль {role}: пароль {env} не задан, пропущена")
                continue
            exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            q = "ALTER ROLE {} WITH LOGIN PASSWORD {}" if exists else "CREATE ROLE {} WITH LOGIN PASSWORD {}"
            c.execute(sql.SQL(q).format(sql.Identifier(role), sql.Literal(pw)))
    for name in DATABASES:
        with psycopg.connect(dsn(name), autocommit=True) as c:
            c.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(db_name(name))))
            c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            for role, grants in ROLES.items():
                if not c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                    continue
                r = sql.Identifier(role)
                c.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(r))
                g = grants.get(name)
                if g is None:
                    c.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(sql.Identifier(db_name(name)), r))
                    continue
                c.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db_name(name)), r))
                c.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r))
                c.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(r))
                if g == "write":
                    c.execute(sql.SQL("GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(r))
                    c.execute(sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {}").format(r))
                elif isinstance(g, list):
                    for t in g:
                        c.execute(sql.SQL("GRANT INSERT, UPDATE, DELETE ON {} TO {}").format(sql.Identifier(t), r))
                    c.execute(sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {}").format(r))
    log("  роли и права доступа обновлены")


def role_url(role: str, name: str) -> str:
    """Адрес базы раздела для роли сервиса (подсказка для .env)."""
    u = urlsplit(dsn(name))
    host = u.hostname + (f":{u.port}" if u.port else "")
    return urlunsplit((u.scheme, f"{role}:***@{host}", u.path, u.query, u.fragment))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pkdb.migrate", description="Создание баз разделов и применение схем")
    ap.add_argument("--roles", action="store_true", help="создать роли сервисов pk_api, pk_sync, pk_crawler и выдать права")
    ap.add_argument("--seed", action="store_true", help="заполнить пустой каталог начальным набором (28 предприятий первичного сбора)")
    ap.add_argument("--only", help="разделы через запятую, по умолчанию все: " + ",".join(DATABASES))
    args = ap.parse_args(argv)
    names = args.only.split(",") if args.only else list(DATABASES)
    for name in names:
        ensure_database(name)
        done = apply(name)
        log(f"{db_name(name)}: " + (f"применено {', '.join(done)}" if done else "схема актуальна"))
    if args.seed and "catalog" in names:
        from . import seed
        n = seed.load()
        log(f"каталог: загружен начальный набор, {n} предприятий" if n else "каталог: не пуст, начальный набор не нужен")
    if args.roles:
        ensure_roles()
    return 0


if __name__ == "__main__":
    sys.exit(main())
