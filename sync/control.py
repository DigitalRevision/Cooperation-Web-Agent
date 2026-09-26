"""Управление запусками сбора: защита от параллельных запусков, статус для админ-панели, запрос ручного запуска.

Всё хранится в базе sm01_ingest (раньше — файлы data/sync/run.lock, status.json, run-request.json):
  sync_lock    — идёт сбор; обновляется каждую минуту, запись старше LOCK_STALE_S считается брошенной;
  sync_state   — состояние для админ-панели: планировщик, этап, сколько компаний проверено, итог последнего запуска;
  sync_request — кнопка «Запустить сейчас» в админ-панели (пишет API), планировщик забирает запрос в течение 15 секунд.
"""
from __future__ import annotations
import os
import threading
from datetime import datetime

from pkdb import connect
from pkdb import ingest

LOCK_STALE_S = ingest.LOCK_STALE_S
HEARTBEAT_S = 60


def now_iso() -> str:
    # с часовым поясом: API может работать в другом поясе (контейнер в UTC) и должен правильно считать, давно ли отвечал планировщик
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _do(fn, *a):
    with connect("ingest") as c:
        r = fn(c, *a)
        c.commit()
        return r


def lock_active() -> bool:
    return _do(ingest.lock_active)


def acquire(info: dict) -> bool:
    """Занять запуск. False — уже идёт другой сбор (свежая блокировка)."""
    return _do(ingest.acquire, dict(info, pid=os.getpid(), at=now_iso()))


def release() -> None:
    _do(ingest.release)


def touch() -> None:
    _do(ingest.touch)


class Heartbeat:
    """Пока идёт сбор, раз в минуту обновляет блокировку: так видно, что процесс жив."""
    def __init__(self):
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self.stop.wait(HEARTBEAT_S):
            try:
                touch()
            except Exception:
                pass   # база недоступна минуту — не повод останавливать сбор; блокировка устареет сама

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()


def read_status() -> dict:
    return _do(ingest.read_status)


def update_status(**fields) -> dict:
    """Дополняет состояние; None удаляет поле."""
    return _do(ingest.update_status, fields, now_iso())


def request_run(by: str) -> dict:
    return _do(ingest.request_run, by)


def take_request() -> dict | None:
    """Забрать запрос ручного запуска."""
    return _do(ingest.take_request)
