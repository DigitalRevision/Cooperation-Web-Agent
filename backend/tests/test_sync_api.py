"""Состояние сбора из реестров и кнопка «Запустить сбор» в админ-панели."""
import json
import os
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import main

c = TestClient(main.app)
H = {"Authorization": "Bearer dev-user"}
A = {"Authorization": "Bearer dev-admin"}


@pytest.fixture(autouse=True)
def sync_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "SYNC_DIR", tmp_path)
    spawned = []
    monkeypatch.setattr(main, "spawn_sync", lambda: spawned.append(True))
    return tmp_path, spawned


def daemon_alive(d):
    (d / "status.json").write_text(json.dumps({"daemon_at": datetime.now().isoformat(timespec="seconds"), "schedule": "00:01",
                                               "next_run": "2026-09-26T00:01"}), encoding="utf-8")


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
    assert json.loads((d / "run-request.json").read_text(encoding="utf-8"))["requested_by"] == "dev-admin" and not spawned
    assert c.get("/api/v1/admin/sync", headers=A).json()["schedule"] == "00:01"


def test_without_scheduler_the_api_starts_sync_itself(sync_dir):
    d, spawned = sync_dir
    r = c.post("/api/v1/admin/sync/run", headers=A)
    assert r.status_code == 202 and r.json()["mode"] == "spawned" and spawned == [True] and not (d / "run-request.json").exists()


def test_second_run_is_refused_while_sync_is_running(sync_dir):
    d, spawned = sync_dir
    (d / "run.lock").write_text("{}", encoding="utf-8")
    (d / "status.json").write_text(json.dumps({"stage": "проверка компаний", "done": 500, "total": 4558}), encoding="utf-8")
    st = c.get("/api/v1/admin/sync", headers=A).json()
    assert st["running"] and st["done"] == 500 and st["total"] == 4558
    assert c.post("/api/v1/admin/sync/run", headers=A).status_code == 409 and not spawned
    # брошенная блокировка (процесс упал) не мешает новому запуску
    os.utime(d / "run.lock", (time.time() - 3600, time.time() - 3600))
    assert c.post("/api/v1/admin/sync/run", headers=A).status_code == 202
