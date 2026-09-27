"""Сбор данных (база sm01_ingest): журналы запусков, состояние для админ-панели, блокировка, ручной запуск, журнал обхода."""
from __future__ import annotations
from datetime import datetime

from psycopg.types.json import Jsonb

from .catalog import d, iso

LOCK_STALE_S = 600          # блокировка без обновления 10 минут — процесс сбора завершился аварийно


def _ts(v):
    if v in (None, ""):
        return None
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


# ---------- журнал запуска ----------


def write_run(conn, name: str, doc: dict) -> int:
    """Журнал прохода: сводка, изменения, ошибки. Повторная запись с тем же именем заменяет прежнюю."""
    known = ("at", "finished", "regions", "found", "queued_new", "requests", "stats", "changes", "errors", "trigger")
    extra = {k: v for k, v in doc.items() if k not in known}
    conn.execute("DELETE FROM sync_run WHERE name = %s", (name,))
    rid = conn.execute("INSERT INTO sync_run (name, started_at, finished_at, trigger, regions, found, queued_new, requests, stats, extra) "
                       "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                       (name, _ts(doc.get("at")), _ts(doc.get("finished")), doc.get("trigger"), doc.get("regions") or [], doc.get("found"),
                        doc.get("queued_new"), doc.get("requests"), Jsonb(doc.get("stats") or {}), Jsonb(extra))).fetchone()["id"]
    cur = conn.cursor()
    ch = [(rid, i, d(x.get("date")), x.get("company_id"), x.get("inn"), x.get("name"), x["kind"], x.get("field"),
           None if x.get("old") is None else str(x["old"]), None if x.get("new") is None else str(x["new"]))
          for i, x in enumerate(doc.get("changes") or [])]
    if ch:
        cur.executemany("INSERT INTO sync_change (run_id, pos, date, company_id, inn, name, kind, field, old, new) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", ch)
    er = [(rid, i, x.get("source"), x.get("where"), x.get("error")) for i, x in enumerate(doc.get("errors") or [])]
    if er:
        cur.executemany("INSERT INTO sync_error (run_id, pos, source, place, error) VALUES (%s,%s,%s,%s,%s)", er)
    return rid


def _summary(r: dict) -> dict:
    return {"at": iso(r["started_at"].replace(tzinfo=None)) if r["started_at"] else None,
            "finished": iso(r["finished_at"].replace(tzinfo=None)) if r["finished_at"] else None,
            "regions": list(r["regions"] or []), "found": r["found"], "queued_new": r["queued_new"], "requests": r["requests"],
            "stats": r["stats"], **({"trigger": r["trigger"]} if r["trigger"] else {}), **(r["extra"] or {})}


def read_run(conn, name: str | None = None, changes_limit: int | None = None, with_errors: bool = True) -> dict | None:
    """Журнал прохода по имени; без имени — последний."""
    r = conn.execute("SELECT * FROM sync_run WHERE name = %s" if name else "SELECT * FROM sync_run ORDER BY started_at DESC, id DESC LIMIT 1",
                     (name,) if name else ()).fetchone()
    if not r:
        return None
    doc = _summary(r)
    lim = "" if changes_limit is None else f" LIMIT {int(changes_limit)}"
    doc["changes"] = [{"date": iso(x["date"]), "company_id": x["company_id"], "inn": x["inn"], "name": x["name"], "kind": x["kind"],
                       "field": x["field"], "old": x["old"], "new": x["new"]}
                      for x in conn.execute(f"SELECT * FROM sync_change WHERE run_id = %s ORDER BY pos{lim}", (r["id"],))]
    if with_errors:
        doc["errors"] = [{"source": x["source"], "where": x["place"], "error": x["error"]}
                         for x in conn.execute("SELECT * FROM sync_error WHERE run_id = %s ORDER BY pos", (r["id"],))]
    return doc


def run_names(conn) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM sync_run ORDER BY started_at, id")]


# ---------- состояние для админ-панели ----------


def read_status(conn) -> dict:
    return dict(conn.execute("SELECT status FROM sync_state").fetchone()["status"] or {})


def update_status(conn, fields: dict, now_iso: str) -> dict:
    """Дополняет состояние; None удаляет поле (как прежний status.json)."""
    st = conn.execute("SELECT status FROM sync_state FOR UPDATE").fetchone()["status"] or {}
    for k, v in fields.items():
        if v is None:
            st.pop(k, None)
        else:
            st[k] = v
    st["updated_at"] = now_iso
    conn.execute("UPDATE sync_state SET status = %s, updated_at = now()", (Jsonb(st),))
    return st


# ---------- блокировка запуска ----------


def lock_active(conn) -> bool:
    return bool(conn.execute("SELECT 1 FROM sync_lock WHERE heartbeat_at > now() - make_interval(secs => %s)", (LOCK_STALE_S,)).fetchone())


def acquire(conn, info: dict) -> bool:
    """Занять запуск. False — идёт другой сбор со свежей блокировкой."""
    r = conn.execute("INSERT INTO sync_lock (id, holder) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET holder = EXCLUDED.holder, "
                     "acquired_at = now(), heartbeat_at = now() WHERE sync_lock.heartbeat_at <= now() - make_interval(secs => %s) RETURNING id",
                     (Jsonb(info), LOCK_STALE_S)).fetchone()
    return r is not None


def touch(conn) -> None:
    conn.execute("UPDATE sync_lock SET heartbeat_at = now()")


def release(conn) -> None:
    conn.execute("DELETE FROM sync_lock")


# ---------- ручной запуск ----------


def request_run(conn, by: str | None) -> dict:
    r = conn.execute("INSERT INTO sync_request (requested_by) VALUES (%s) RETURNING requested_by, requested_at", (by,)).fetchone()
    return {"requested_by": r["requested_by"], "at": r["requested_at"].astimezone().isoformat(timespec="seconds")}


def request_pending(conn) -> bool:
    return bool(conn.execute("SELECT 1 FROM sync_request WHERE taken_at IS NULL LIMIT 1").fetchone())


def take_request(conn) -> dict | None:
    """Забрать самый ранний запрос ручного запуска; остальные ожидающие гасятся — один запуск их все выполнит."""
    r = conn.execute("SELECT id, requested_by, requested_at FROM sync_request WHERE taken_at IS NULL ORDER BY requested_at LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
    if not r:
        return None
    conn.execute("UPDATE sync_request SET taken_at = now() WHERE taken_at IS NULL")
    return {"requested_by": r["requested_by"], "at": r["requested_at"].astimezone().isoformat(timespec="seconds")}


# ---------- обход сайтов ----------


def write_crawl_log(conn, day: str, items: list[dict], start: int = 0) -> None:
    """Журнал обхода за день: по каждому URL остаётся последний результат. start — номер первой записи порции."""
    cur = conn.cursor()
    cur.executemany("INSERT INTO crawl_log (day, pos, url, status, note, fetched_at) VALUES (%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (day, url) DO UPDATE SET status = EXCLUDED.status, note = EXCLUDED.note, fetched_at = EXCLUDED.fetched_at",
                    [(d(day), start + i, x["url"], x.get("status"), x.get("note"), d(x.get("fetched_at"))) for i, x in enumerate(items)])


def read_crawl_log(conn, limit: int | None = None) -> list[dict]:
    """Журнал обхода; limit — только последние записи и столько же последних ошибок (для админ-панели: после поиска сайтов
    в журнале десятки тысяч адресов)."""
    if limit:
        rows = conn.execute("""(SELECT * FROM crawl_log ORDER BY day DESC, pos DESC, id DESC LIMIT %s)
                               UNION (SELECT * FROM crawl_log WHERE status IS DISTINCT FROM 'OK' ORDER BY day DESC, pos DESC, id DESC LIMIT %s)
                               ORDER BY day, pos, id""", (limit, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM crawl_log ORDER BY day, pos, id").fetchall()
    return [{"url": r["url"], "status": r["status"], "note": r["note"], "fetched_at": iso(r["fetched_at"])} for r in rows]


def crawl_summary(conn) -> dict:
    """Итоги обхода и поиска сайтов для админ-панели."""
    r = conn.execute("SELECT count(*) AS total, count(*) FILTER (WHERE status = 'OK') AS ok, min(day) AS first_day, max(day) AS last_day "
                     "FROM crawl_log").fetchone()
    s = conn.execute("SELECT count(*) FILTER (WHERE status = 'CONFIRMED') AS confirmed, count(*) FILTER (WHERE status = 'CANDIDATE') AS candidates "
                     "FROM site_discovery").fetchone()
    searched = conn.execute("SELECT count(*) AS n FROM site_search").fetchone()["n"]
    return {"total": r["total"], "ok": r["ok"], "failed": r["total"] - r["ok"], "first_day": iso(r["first_day"]), "last_day": iso(r["last_day"]),
            "searched": searched, "sites_confirmed": s["confirmed"], "sites_candidates": s["candidates"]}
