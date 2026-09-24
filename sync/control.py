"""Управление запусками сбора: защита от параллельных запусков, статус для админ-панели, запрос ручного запуска.

Файлы в data/sync/:
  run.lock          — идёт сбор; обновляется каждую минуту, запись старше LOCK_STALE_S считается брошенной;
  status.json       — состояние для админ-панели: планировщик, этап, сколько компаний проверено, итог последнего запуска;
  run-request.json  — кнопка «Запустить сейчас» в админ-панели (пишет API), планировщик забирает его в течение 15 секунд.
"""
from __future__ import annotations
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

LOCK, STATUS, REQUEST = "run.lock", "status.json", "run-request.json"
LOCK_STALE_S = 600          # без обновления 10 минут — процесс сбора завершился аварийно
HEARTBEAT_S = 60


def now_iso() -> str:
    # с часовым поясом: API может работать в другом поясе (контейнер в UTC) и должен правильно считать, давно ли отвечал планировщик
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def lock_active(sync_dir: Path) -> bool:
    p = Path(sync_dir) / LOCK
    try:
        return time.time() - p.stat().st_mtime < LOCK_STALE_S
    except OSError:
        return False


def acquire(sync_dir: Path, info: dict) -> bool:
    """Занять запуск. False — уже идёт другой сбор (свежая блокировка)."""
    p = Path(sync_dir) / LOCK
    p.parent.mkdir(parents=True, exist_ok=True)
    if lock_active(sync_dir):
        return False
    p.unlink(missing_ok=True)   # брошенная блокировка после аварийного завершения
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False            # другой процесс успел первым
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dict(info, pid=os.getpid(), at=now_iso()), f, ensure_ascii=False)
    return True


def release(sync_dir: Path) -> None:
    (Path(sync_dir) / LOCK).unlink(missing_ok=True)


def touch(sync_dir: Path) -> None:
    p = Path(sync_dir) / LOCK
    if p.exists():
        os.utime(p, None)


class Heartbeat:
    """Пока идёт сбор, раз в минуту обновляет блокировку: так видно, что процесс жив."""
    def __init__(self, sync_dir: Path):
        self.sync_dir, self.stop = Path(sync_dir), threading.Event()
        self.t = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self.stop.wait(HEARTBEAT_S):
            touch(self.sync_dir)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()


def update_status(sync_dir: Path, **fields) -> dict:
    """Дополняет status.json; None удаляет поле."""
    p = Path(sync_dir) / STATUS
    st = read_json(p) or {}
    for k, v in fields.items():
        if v is None:
            st.pop(k, None)
        else:
            st[k] = v
    st["updated_at"] = now_iso()
    _write_json(p, st)
    return st


def request_run(sync_dir: Path, by: str) -> dict:
    req = {"requested_by": by, "at": now_iso()}
    _write_json(Path(sync_dir) / REQUEST, req)
    return req


def take_request(sync_dir: Path) -> dict | None:
    """Забрать запрос ручного запуска (файл удаляется)."""
    p = Path(sync_dir) / REQUEST
    req = read_json(p)
    if req is None:
        return None
    p.unlink(missing_ok=True)
    return req
