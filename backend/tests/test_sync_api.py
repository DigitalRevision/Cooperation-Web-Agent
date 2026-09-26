"""Состояние сбора из реестров и кнопка «Запустить сбор» в админ-панели (состояние — в базе sm01_ingest)."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import staff_id
from pkdb import connect, ingest

c = TestClient(main.app)
H = {"Authorization": "Bearer dev-user"}
A = {"Authorization": "Bearer dev-admin"}


@pytest.fixture(autouse=True)
def sync_dir(monkeypatch):
    with connect("ingest") as g:
        g.execute("TRUNCATE sync_lock, sync_request")
        g.execute("UPDATE sync_state SET status = '{}'")
        g.commit()
    spawned = []
    monkeypatch.setattr(main, "spawn_sync", lambda: spawned.append(True))
    return None, spawned


def ingest_do(fn, *a):
    with connect("ingest") as g:
        r = fn(g, *a)
        g.commit()
        return r


def daemon_alive(d):
    ingest_do(ingest.update_status, {"daemon_at": datetime.now().astimezone().isoformat(timespec="seconds"), "schedule": "00:01",
                                     "next_run": "2026-09-26T00:01"}, "")


def test_only_admin_can_start_and_moderator_sees_status(sync_dir):
    assert c.post("/api/v1/admin/sync/run", headers=H).status_code == 403
    assert c.get("/api/v1/admin/sync", headers=H).status_code == 403
    st = c.get("/api/v1/admin/sync", headers=A).json()
    assert st["running"] is False and st["daemon_alive"] is False and st["last_run"] is None


def test_button_queues_run_for_the_scheduler(sync_dir):
    d, spawned = sync_dir
    daemon_alive(d)
    r = c.post("/api/v1/admin/sync/run", headers=A)
    assert r.status_code == 202 and r.json()["mode"] == "daemon" and r.json()["request_pending"] is True
    assert ingest_do(ingest.take_request)["requested_by"] == staff_id("dev-admin") and not spawned
    assert c.get("/api/v1/admin/sync", headers=A).json()["schedule"] == "00:01"


def test_without_scheduler_the_api_starts_sync_itself(sync_dir):
    d, spawned = sync_dir
    r = c.post("/api/v1/admin/sync/run", headers=A)
    assert r.status_code == 202 and r.json()["mode"] == "spawned" and spawned == [True] and not r.json()["request_pending"]


def test_second_run_is_refused_while_sync_is_running(sync_dir):
    d, spawned = sync_dir
    assert ingest_do(ingest.acquire, {"trigger": "тест"})
    ingest_do(ingest.update_status, {"stage": "проверка компаний", "done": 500, "total": 4558}, "")
    st = c.get("/api/v1/admin/sync", headers=A).json()
    assert st["running"] and st["done"] == 500 and st["total"] == 4558
    assert c.post("/api/v1/admin/sync/run", headers=A).status_code == 409 and not spawned
    # брошенная блокировка (процесс упал) не мешает новому запуску
    with connect("ingest") as g:
        g.execute("UPDATE sync_lock SET heartbeat_at = now() - interval '1 hour'")
        g.commit()
    assert c.post("/api/v1/admin/sync/run", headers=A).status_code == 202
