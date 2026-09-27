"""Краулер как постоянный процесс: обход после каждого сбора из реестров и задания повторного обхода из админ-панели.

  python daemon.py        (из каталога crawler/; docker compose — сервис crawler; локально — отдельное окно start-local.cmd)

Раз в минуту смотрит в sm01_ingest:
  • закончился сбор из реестров (sync: ежедневно в PK_SYNC_AT, по умолчанию 00:01, и по кнопке в админ-панели) — ночной запуск:
    поиск сайтов у предприятий без сайта и обход всех известных сайтов;
  • в очереди есть задания повторного обхода из админ-панели (crawl_job) — обход этих адресов, без поиска.
Каждый запуск записывается в crawl_run. Как только он закончен, планировщик сбора переносит найденные сайты и позиции
в карточки (sync/run.py) — следующей ночи ждать не нужно.
PK_CRAWL_AFTER_SYNC=0 — без ночного запуска, только задания из админ-панели. Разовый запуск: scrapy crawl company_sites.
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if not (HERE / "pkdb").is_dir() and (HERE.parent / "pkdb").is_dir():   # локально pkdb лежит в корне проекта, в образе — рядом
    sys.path.insert(0, str(HERE.parent))

from pkdb import connect, ingest  # noqa: E402

POLL_S = 60


def log(*a):
    print(datetime.now().strftime("%d.%m.%Y %H:%M:%S"), *a, flush=True)


def nightly_due(status: dict, sync_running: bool, last_nightly_started: datetime | None) -> bool:
    """Ночной запуск — после каждого законченного сбора из реестров: сбор сейчас не идёт, а последний начался позже прошлого
    ночного обхода. Пока ни одного сбора не было, краулер ждёт первого."""
    started = status.get("last_started_at")
    if sync_running or status.get("state") == "running" or not started:
        return False
    return last_nightly_started is None or datetime.fromisoformat(started).astimezone() > last_nightly_started


def crawl(kind: str, args: list[str], jobs: list[str] | None = None) -> bool:
    """Один запуск Scrapy отдельным процессом (реактор Twisted второй раз в одном процессе не запускается)."""
    with connect("ingest") as g:
        run = ingest.crawl_run_start(g, kind)
        g.commit()
    log(f"запуск {run['id']}: " + ("после сбора из реестров — поиск и обход сайтов" if kind == "nightly" else f"задания из админ-панели ({len(jobs)})"))
    cmd = [sys.executable, "-m", "scrapy", "crawl", "company_sites", "-s", "LOG_LEVEL=" + os.environ.get("PK_CRAWL_LOG_LEVEL", "INFO"), *args]
    try:
        code = subprocess.call(cmd, cwd=HERE)
        error = None if code == 0 else f"Scrapy завершился с кодом {code}"
    except OSError as e:
        code, error = -1, f"Scrapy не запустился: {e}"
    with connect("ingest") as g:
        stats = ingest.crawl_run_stats(g, run["started_at"])
        if jobs:
            stats["jobs"] = len(jobs)
            ingest.crawl_jobs_finish(g, jobs, code == 0, error)
        ingest.crawl_run_finish(g, run["id"], code == 0, stats, error)
        g.commit()
    log(f"запуск {run['id']} " + ("закончен" if code == 0 else f"не удался: {error}") + f"; {stats}")
    return code == 0


def main():
    after_sync = os.environ.get("PK_CRAWL_AFTER_SYNC", "1") not in ("0", "false", "no")
    log("краулер: " + ("обход после каждого сбора из реестров и " if after_sync else "") + "задания повторного обхода из админ-панели")
    unfinished = True   # при старте и после сбоя посреди запуска: незаконченный запуск — прерван, его задания — снова в очередь
    while True:
        try:
            with connect("ingest") as g:
                if unfinished and ingest.crawl_runs_abandon(g):
                    log("незаконченный запуск отмечен как прерванный, его задания возвращены в очередь")
                unfinished = False
                jobs = ingest.crawl_jobs_take(g)
                status, running = ingest.read_status(g), ingest.lock_active(g)
                last = ingest.crawl_run_last(g, "nightly")
                g.commit()
        except Exception as e:
            log(f"нет связи с базой: {type(e).__name__}: {e}")
            time.sleep(15)
            continue
        try:
            if jobs:
                crawl("jobs", ["-a", "jobs=" + ",".join(j["id"] for j in jobs)], [j["id"] for j in jobs])
            elif after_sync and nightly_due(status, running, last["started_at"] if last else None):
                crawl("nightly", [])
            else:
                time.sleep(POLL_S)
        except Exception as e:   # связь с базой пропала посреди запуска
            log(f"ошибка запуска: {type(e).__name__}: {e}")
            unfinished = True
            time.sleep(15)


if __name__ == "__main__":
    main()
