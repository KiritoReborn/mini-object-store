"""Owner demo authorization and recovery with SQLite and one real worker volume."""
import hashlib
import logging
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from controller import config, database as db, recovery, telemetry

KEY = "placeholder-owner-key-for-tests-only"
HEADERS = {"X-Artaud-Key": KEY, "X-Artaud-Admin": "1"}
DATA = b"verify these bytes\x00\xff"
WORKER_ORIGIN = "http://replica-one:8011"


@pytest.fixture
def fault_demo(tmp_path, monkeypatch, no_recovery_module):
    monkeypatch.setenv("WORKER_ID", "worker1")
    from worker import config as worker_config, main as worker_main, storage

    monkeypatch.setattr(worker_config, "WORKER_ID", "worker1")
    monkeypatch.setattr(worker_config, "ENABLE_FAULT_INJECTION", True)
    root = tmp_path / "worker"
    root.mkdir()
    monkeypatch.setattr(storage, "ROOT", root)
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    monkeypatch.setattr(config, "API_KEY", KEY)
    monkeypatch.setattr(config, "DEMO_CONTROLS", False)
    monkeypatch.setattr(config, "DEMO_FAULT_INJECTION", True)
    monkeypatch.setattr(telemetry, "_journal", telemetry.ActivityJournal())

    primary = httpx.ASGITransport(app=worker_main.app)
    state = SimpleNamespace(calls=[], worker_error=None, secondary={})

    async def worker(request):
        state.calls.append((request.method, str(request.url)))
        assert "x-artaud-key" not in request.headers and "x-artaud-admin" not in request.headers
        if request.url.host == "replica-one":
            if request.url.path.startswith("/internal/demo/"):
                assert request.extensions["timeout"]["read"] == 3
                if state.worker_error == "timeout":
                    raise httpx.ReadTimeout("simulated worker timeout", request=request)
                if state.worker_error:
                    return httpx.Response(state.worker_error, json={"message": "Untrusted worker response"})
            return await primary.handle_async_request(request)
        assert request.url.host == "worker2"
        chunk_id = request.url.path.rsplit("/", 1)[-1]
        if request.method == "POST":
            assert request.url.path.startswith("/internal/demo/corrupt/")
            assert request.headers["X-Artaud-Worker-ID"] == "worker2"
            data = state.secondary[chunk_id]
            state.secondary[chunk_id] = bytes([data[0] ^ 1]) + data[1:]
            return httpx.Response(200, json={
                "chunk_id": chunk_id, "worker_id": "worker2", "offset": 0,
                "size": len(data), "action": "corrupted",
            })
        if request.method == "PUT":
            state.secondary[chunk_id] = request.content
            return httpx.Response(201, json={
                "chunk_id": chunk_id, "size": len(request.content),
                "sha256": hashlib.sha256(request.content).hexdigest(),
            })
        if request.method == "GET" and chunk_id in state.secondary:
            return httpx.Response(200, content=state.secondary[chunk_id])
        return httpx.Response(404)

    transport = httpx.MockTransport(worker)
    with TestClient(no_recovery_module.create_app(worker_transport=transport)) as client:
        for worker_id, origin in (("worker1", WORKER_ORIGIN), ("worker2", "http://worker2:8001")):
            db.register_worker(worker_id, origin)
            db.set_worker_state(worker_id, "ALIVE")
        response = client.post("/api/v1/objects", headers=HEADERS, files={"file": ("demo.bin", DATA)})
        assert response.status_code == 201, response.text
        obj = response.json()
        state.client = client
        state.chunk_id = obj["chunks"][0]["chunk_id"]
        state.path = f'/api/v1/objects/{obj["object_id"]}'
        state.action = f"/api/v1/demo/workers/worker1/chunks/{state.chunk_id}/corrupt"
        state.transport = transport
        state.disk = storage.chunk_path(state.chunk_id)
        state.calls.clear()
        yield state


def test_fault_controls_are_off_without_both_controller_prerequisites(fault_demo, monkeypatch):
    client = fault_demo.client
    overview = "/api/v1/overview"
    assert client.get(overview, headers=HEADERS).json()["fault_injection_enabled"] is True
    monkeypatch.setattr(config, "DEMO_FAULT_INJECTION", False)
    assert "fault_injection_enabled" not in client.get(overview, headers=HEADERS).json()
    disabled = client.post(fault_demo.action, headers=HEADERS)
    assert disabled.status_code == 404 and disabled.json()["error"] == "NOT_FOUND"
    monkeypatch.setattr(config, "DEMO_FAULT_INJECTION", True)
    monkeypatch.setattr(config, "API_KEY", "")
    assert "fault_injection_enabled" not in client.get(overview).json()
    assert client.post(fault_demo.action, headers=HEADERS).status_code == 401
    assert fault_demo.calls == [] and fault_demo.disk.read_bytes() == DATA


@pytest.mark.parametrize("headers,status", [
    ({"X-Artaud-Admin": "1"}, 401),
    ({**HEADERS, "X-Artaud-Key": "wrong-placeholder"}, 401),
    ({"X-Artaud-Key": KEY}, 403),
    ({**HEADERS, "X-Artaud-Admin": "0"}, 403),
    ({**HEADERS, "Origin": "https://other.example"}, 403),
])
def test_fault_control_requires_owner_and_admin(fault_demo, headers, status):
    response = fault_demo.client.post(fault_demo.action, headers=headers)
    assert response.status_code == status and response.json()["message"]
    assert KEY not in response.text and not fault_demo.calls


def test_fault_control_checks_worker_chunk_and_replica_in_sqlite(fault_demo):
    client, action, chunk_id = fault_demo.client, fault_demo.action, fault_demo.chunk_id
    for path, status, code in (
        (action.replace("/worker1/", "/unknown/"), 404, "WORKER_NOT_FOUND"),
        (action.replace(chunk_id, chunk_id[:-1] + "99"), 404, "CHUNK_NOT_FOUND"),
        (action.replace(chunk_id, chunk_id + "0"), 400, "INVALID_CHUNK_ID"),
    ):
        response = client.post(path, headers=HEADERS)
        assert response.status_code == status and response.json()["error"] == code

    for replica_state in ("CORRUPT", "MISSING", "PENDING_DELETE"):
        db.set_replica_state(chunk_id, "worker1", replica_state)
        response = client.post(action, headers=HEADERS)
        assert response.status_code == 409 and response.json()["error"] == "REPLICA_NOT_HEALTHY"
    db.delete_replica_record(chunk_id, "worker1")
    assert client.post(action, headers=HEADERS).status_code == 409
    assert fault_demo.calls == [] and fault_demo.disk.read_bytes() == DATA


@pytest.mark.parametrize("worker_status,status", [(404, 404), (409, 409), (500, 503), ("timeout", 503)])
def test_fault_control_reports_worker_failure(fault_demo, worker_status, status):
    fault_demo.worker_error = worker_status
    response = fault_demo.client.post(fault_demo.action, headers=HEADERS)
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"] and response.json()["message"]
    assert "Untrusted worker response" not in response.text
    assert fault_demo.disk.read_bytes() == DATA
    assert all(r["state"] == "HEALTHY" for r in db.get_replicas(fault_demo.chunk_id))


def test_fault_control_records_corruption_reported_by_the_worker(fault_demo):
    fault_demo.disk.write_bytes(b"?" + DATA[1:])
    response = fault_demo.client.post(fault_demo.action, headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["error"] == "REPLICA_ALREADY_CORRUPT"
    assert db.get_replicas(fault_demo.chunk_id)[0]["state"] == "CORRUPT"


def test_fault_control_records_a_missing_replica_reported_by_the_worker(fault_demo):
    fault_demo.disk.unlink()
    response = fault_demo.client.post(fault_demo.action, headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["error"] == "CHUNK_NOT_FOUND"
    assert db.get_replicas(fault_demo.chunk_id)[0]["state"] == "MISSING"


@pytest.mark.parametrize("peer_state", ["CORRUPT", "MISSING"])
def test_fault_control_can_corrupt_the_last_available_copy(fault_demo, peer_state):
    chunk_id = fault_demo.chunk_id
    if peer_state == "CORRUPT":
        fault_demo.secondary[chunk_id] = b"?" + DATA[1:]
    else:
        del fault_demo.secondary[chunk_id]
    db.set_replica_state(chunk_id, "worker2", peer_state)

    response = fault_demo.client.post(fault_demo.action, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert fault_demo.calls == [("POST", f"{WORKER_ORIGIN}/internal/demo/corrupt/{chunk_id}")]
    assert fault_demo.disk.read_bytes() == bytes([DATA[0] ^ 1]) + DATA[1:]
    assert [r["state"] for r in db.get_replicas(chunk_id)] == ["CORRUPT", peer_state]
    assert fault_demo.client.get(fault_demo.path, headers=HEADERS).status_code == 503


def test_fault_control_can_corrupt_both_copies_before_repair(fault_demo):
    client, chunk_id = fault_demo.client, fault_demo.chunk_id
    assert client.post(fault_demo.action, headers=HEADERS).status_code == 200
    second = client.post(fault_demo.action.replace("/worker1/", "/worker2/"), headers=HEADERS)
    assert second.status_code == 200, second.text
    assert second.json()["worker_id"] == "worker2"

    corrupted = bytes([DATA[0] ^ 1]) + DATA[1:]
    assert fault_demo.disk.read_bytes() == fault_demo.secondary[chunk_id] == corrupted
    assert {r["state"] for r in db.get_replicas(chunk_id)} == {"CORRUPT"}
    download = client.get(fault_demo.path, headers=HEADERS)
    assert download.status_code == 503
    assert download.headers["content-type"] == "application/json"
    assert download.json()["error"] == "OBJECT_UNAVAILABLE"


def test_download_refuses_both_bad_copies_even_when_manifest_said_healthy(fault_demo):
    bad = b"?" + DATA[1:]
    fault_demo.disk.write_bytes(bad)
    fault_demo.secondary[fault_demo.chunk_id] = bad
    assert all(r["state"] == "HEALTHY" for r in db.get_replicas(fault_demo.chunk_id))
    download = fault_demo.client.get(fault_demo.path, headers=HEADERS)
    assert download.status_code == 503
    assert download.headers["content-type"] == "application/json"
    assert download.json()["error"] == "OBJECT_UNAVAILABLE"
    assert {r["state"] for r in db.get_replicas(fault_demo.chunk_id)} == {"CORRUPT"}


def test_fault_control_falls_back_and_recovery_repairs(fault_demo, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    client, chunk_id = fault_demo.client, fault_demo.chunk_id
    response = client.post(fault_demo.action, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "chunk_id": chunk_id, "worker_id": "worker1", "offset": 0, "size": len(DATA), "action": "corrupted",
    }
    assert fault_demo.calls == [("POST", f"{WORKER_ORIGIN}/internal/demo/corrupt/{chunk_id}")]
    assert KEY not in response.text and KEY not in caplog.text
    assert fault_demo.disk.read_bytes() == bytes([DATA[0] ^ 1]) + DATA[1:]
    activity = client.get("/api/v1/activity", headers=HEADERS).json()["events"]
    event, = [event for event in activity if event["kind"] == "fault_injected"]
    assert (event["worker_id"], event["chunk_id"], event["size"]) == ("worker1", chunk_id, len(DATA))
    manifest = client.get(fault_demo.path + "/metadata", headers=HEADERS).json()
    assert {r["worker_id"]: r["state"] for r in manifest["chunks"][0]["replicas"]} == {
        "worker1": "CORRUPT", "worker2": "HEALTHY",
    }
    overview = client.get("/api/v1/overview", headers=HEADERS).json()
    assert overview["corrupt_replicas"] == overview["under_replicated_chunks"] == 1
    assert any(row["kind"] == "replica_state" and row["state"] == "CORRUPT" for row in activity)
    fault_demo.calls.clear()
    download = client.get(fault_demo.path, headers=HEADERS)
    assert download.status_code == 200 and download.content == DATA
    assert download.headers["x-object-sha256"] == hashlib.sha256(DATA).hexdigest()
    assert fault_demo.calls == [("GET", f"http://worker2:8001/internal/chunks/{chunk_id}")]
    assert db.get_replicas(chunk_id)[0]["state"] == "CORRUPT"

    runtime = recovery._Runtime(client=httpx.AsyncClient(transport=fault_demo.transport))
    monkeypatch.setattr(recovery, "_runtime", runtime)
    try:
        client.portal.call(recovery.run_once)
        assert {r["worker_id"] for r in db.get_replicas(chunk_id) if r["state"] == "HEALTHY"} == {"worker1", "worker2"}
        assert fault_demo.disk.read_bytes() == DATA
    finally:
        client.portal.call(recovery.stop_reconciler)
