"""Worker controls use real SQLite; only the external HTTP boundary is replaced."""
import asyncio
import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

ADMIN = {"X-Artaud-Admin": "1"}


@pytest.fixture
def admin(tmp_path, monkeypatch, no_recovery_module):
    from controller import config, database, main, telemetry

    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    monkeypatch.setattr(telemetry, "_journal", telemetry.ActivityJournal())
    state = {"health": None, "requests": [], "data": {}}

    def worker(request):
        state["requests"].append((request.method, str(request.url)))
        if request.url.path == "/health":
            if state["health"] is not None:
                result = state["health"]
                if isinstance(result, Exception):
                    raise result
                return result
            return httpx.Response(200, json={"worker_id": request.url.host, "status": "ok"})
        key = (request.url.host, request.url.path)
        if request.method == "PUT":
            state["data"][key] = request.content
            return httpx.Response(201, json={"chunk_id": request.url.path.rsplit("/", 1)[-1],
                "size": len(request.content), "sha256": hashlib.sha256(request.content).hexdigest(), "status": "stored"})
        if request.method == "DELETE":
            state["data"].pop(key, None)
            return httpx.Response(204)
        return httpx.Response(200, content=state["data"][key])

    with TestClient(main.create_app(worker_transport=httpx.MockTransport(worker)), raise_server_exceptions=False) as client:
        yield client, database, state


def connect(client, worker_id="worker1", **fields):
    return client.post("/api/v1/workers/connect", json={"worker_id": worker_id,
        "base_url": f"http://{worker_id}:8001", **fields}, headers=ADMIN)


def add_worker(db, worker_id="worker1", heartbeat="fresh", status="ALIVE"):
    db.register_worker(worker_id, f"http://{worker_id}:8001")
    db.set_worker_state(worker_id, status)
    if heartbeat != "fresh":
        with db.connection() as conn:
            conn.execute("UPDATE workers SET last_heartbeat=? WHERE worker_id=?", (heartbeat, worker_id))


def test_managed_list_is_read_only_and_preserves_legacy_worker_shape(admin):
    client, db, state = admin
    add_worker(db)
    before = db.get_workers()
    response = client.get("/api/v1/workers")
    assert response.status_code == 200
    worker = response.json()["workers"][0]
    assert set(worker) == {"worker_id", "base_url", "status", "last_heartbeat", "chunk_count",
        "stored_bytes", "heartbeat_age_seconds", "available", "display_name", "notes",
        "placement_enabled", "replica_count", "can_forget"}
    assert worker["display_name"] == worker["notes"] == ""
    assert worker["placement_enabled"] is True
    assert worker["available"] is True
    assert worker["can_forget"] is False
    assert response.json()["placement_available_workers"] == 1
    assert state["requests"] == []
    assert db.get_workers() == before
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM worker_settings").fetchone()[0] == 0


def test_settings_pause_only_new_placement_and_persist_across_registration(admin):
    client, db, state = admin
    for index in range(1, 4):
        add_worker(db, f"worker{index}")
    before = db.get_workers()[0]
    result = client.patch("/api/v1/workers/worker1", headers=ADMIN,
        json={"display_name": "Archive α", "notes": "Existing disks", "placement_enabled": False})
    assert result.status_code == 200
    assert result.json()["display_name"] == "Archive α"
    assert result.json()["available"] is True
    assert result.json()["placement_enabled"] is False
    assert db.get_workers()[0] == before
    assert [w["worker_id"] for w in db.get_placement_workers()] == ["worker2", "worker3"]
    assert client.get("/api/v1/workers").json()["placement_available_workers"] == 2
    uploaded = client.post("/api/v1/objects", files={"file": ("x", b"abc")})
    assert uploaded.status_code == 201
    assert {host for host, _ in state["data"]} == {"worker2", "worker3"}
    assert client.get(f'/api/v1/objects/{uploaded.json()["object_id"]}').content == b"abc"
    db.register_worker("worker1", "http://worker1:8001")
    assert client.get("/api/v1/workers").json()["workers"][0]["placement_enabled"] is False
    assert client.patch("/api/v1/workers/worker1", headers=ADMIN,
        json={"placement_enabled": True}).status_code == 200
    assert len(db.get_placement_workers()) == 3


@pytest.mark.parametrize("changes", [{}, {"status": "ALIVE"}, {"notes": None}, {"display_name": 1},
    {"display_name": "x" * 65}, {"notes": "x" * 513}, {"display_name": "new\nname"},
    {"notes": "\x7f"}, {"notes": "\u0085"}, {"notes": "\ud800"}, {"placement_enabled": "false"},
    {"placement_enabled": 0}, {"placement_enabled": None}])
def test_invalid_patch_is_400_and_does_not_change_worker(admin, changes):
    client, db, _ = admin
    add_worker(db)
    before = db.get_workers()
    response = client.patch("/api/v1/workers/worker1", headers={**ADMIN, "Content-Type": "application/json"},
        content=json.dumps(changes))
    assert response.status_code == 400
    assert db.get_workers() == before


@pytest.mark.parametrize("method,path,body", [("post", "/api/v1/workers/connect", {"worker_id": "worker1", "base_url": "http://worker1:8001"}),
    ("patch", "/api/v1/workers/worker1", {"notes": "changed"}), ("delete", "/api/v1/workers/worker1", None)])
@pytest.mark.parametrize("headers", [{}, {"X-Artaud-Admin": "true"}, {**ADMIN, "Origin": "https://evil.example"},
    {**ADMIN, "Origin": "null"}, {**ADMIN, "Origin": "http://testserver@evil.example"},
    {**ADMIN, "Origin": "http://testserver:80"}])
def test_admin_mutations_require_header_and_same_origin_authority(admin, method, path, body, headers):
    client, db, state = admin
    add_worker(db, heartbeat=None)
    response = client.request(method, path, json=body, headers=headers)
    assert response.status_code == 403
    assert len(db.get_workers()) == 1
    assert state["requests"] == []


def test_matching_origin_authority_is_allowed_and_missing_workers_are_404(admin):
    client, _, _ = admin
    headers = {**ADMIN, "Origin": "http://testserver"}
    assert client.patch("/api/v1/workers/missing", headers=headers, json={"notes": "x"}).status_code == 404
    assert client.delete("/api/v1/workers/missing", headers=headers).status_code == 404
    assert client.post("/api/v1/workers/connect", headers=headers,
        json={"worker_id": "worker16", "base_url": "http://worker16:8001"}).status_code == 200


def test_connect_is_idempotent_without_resetting_alive_or_existing_settings(admin):
    client, db, state = admin
    result = connect(client, display_name="Hot tier", notes="Rack 1")
    assert result.status_code == 200
    assert result.json()["status"] == "JOINING"
    assert result.json()["display_name"] == "Hot tier"
    db.set_worker_state("worker1", "ALIVE")
    before = db.get_workers()[0]
    again = connect(client, notes="Rack 2")
    assert again.status_code == 200
    assert again.json()["display_name"] == "Hot tier"
    assert again.json()["notes"] == "Rack 2"
    assert db.get_workers()[0] == before
    assert state["requests"] == [("GET", "http://worker1:8001/health")] * 2


def test_conflicting_registration_is_409_without_overwriting_worker(admin):
    client, db, _ = admin
    db.register_worker("worker1", "http://legacy:8001")
    before = db.get_workers()
    assert connect(client).status_code == 409
    assert db.get_workers() == before


def test_concurrent_connect_preserves_single_registration_and_alive_state(admin):
    client, db, _ = admin
    add_worker(db)
    before = db.get_workers()
    with ThreadPoolExecutor(4) as pool:
        responses = list(pool.map(lambda _: connect(client), range(8)))
    assert all(response.status_code == 200 for response in responses)
    assert db.get_workers() == before


def test_concurrent_new_connections_create_one_joining_record(admin):
    client, db, _ = admin
    with ThreadPoolExecutor(4) as pool:
        responses = list(pool.map(lambda _: connect(client), range(8)))
    assert all(response.status_code == 200 for response in responses)
    assert [(w["worker_id"], w["status"]) for w in db.get_workers()] == [("worker1", "JOINING")]


@pytest.mark.parametrize("worker_id,url", [("worker0", "http://worker0:8001"), ("worker17", "http://worker17:8001"),
    ("worker01", "http://worker01:8001"), ("worker1", "http://worker2:8001"),
    ("worker1", "http://127.0.0.1:8001"), ("worker1", "http://169.254.169.254"),
    ("worker1", "https://worker1:8001"), ("worker1", "http://worker1:8001/"),
    ("worker1", "http://worker1:8001/health"), ("worker1", "http://worker1:8001?x=1"),
    ("worker1", "http://worker1:8001#x"), ("worker1", "http://user@worker1:8001"),
    ("worker1", "http://worker1.:8001"), ("worker1", "HTTP://worker1:8001"),
    ("worker1", "http://worker1:8001\n")])
def test_connector_rejects_nonexact_docker_origins_without_network(admin, worker_id, url):
    client, db, state = admin
    response = client.post("/api/v1/workers/connect", headers=ADMIN, json={"worker_id": worker_id, "base_url": url})
    assert response.status_code == 400
    assert db.get_workers() == []
    assert state["requests"] == []


@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "http://169.254.169.254"}),
    httpx.Response(500), httpx.Response(200, content=b"not json"),
    httpx.Response(200, json={"status": "ok", "worker_id": "worker2"}),
    httpx.Response(200, json={"status": "wrong", "worker_id": "worker1"}),
    httpx.Response(200, json=[]), httpx.Response(200, content=b"x" * 8193),
    httpx.ConnectError("private upstream problem")])
def test_health_failures_are_503_without_registration_or_redirect(admin, response):
    client, db, state = admin
    state["health"] = response
    result = connect(client)
    assert result.status_code == 503
    assert "private" not in result.text
    assert db.get_workers() == []
    assert state["requests"] == [("GET", "http://worker1:8001/health")]


def test_health_stream_is_closed_at_the_bound_instead_of_reading_whole_response(admin):
    class HealthStream(httpx.SyncByteStream):
        consumed = 0
        closed = False

        def __iter__(self):
            for _ in range(100):
                self.consumed += 1024
                yield b"x" * 1024

        def close(self):
            self.closed = True

    client, db, state = admin
    stream = HealthStream()
    # MockTransport adapts a synchronous byte stream for its async response path.
    class AsyncHealthStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for part in stream:
                yield part

        async def aclose(self):
            stream.close()

    state["health"] = httpx.Response(200, stream=AsyncHealthStream())
    assert connect(client).status_code == 503
    assert stream.closed
    assert stream.consumed <= 8193 + 1024
    assert db.get_workers() == []


def test_compressed_health_is_rejected_without_decoding_an_unbounded_body(admin):
    client, db, state = admin
    state["health"] = httpx.Response(200, content=gzip.compress(b'{"status":"ok","worker_id":"worker1"}'),
        headers={"Content-Encoding": "gzip"})
    assert connect(client).status_code == 503
    assert db.get_workers() == []


def test_slow_health_stream_has_a_total_timeout_and_is_closed(admin, monkeypatch):
    from controller import config

    class SlowHealthStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.01)
                yield b" "

        async def aclose(self):
            self.closed = True

    client, db, state = admin
    monkeypatch.setattr(config, "HTTP_TIMEOUT", 0.03)
    stream = SlowHealthStream()
    state["health"] = httpx.Response(200, stream=stream)
    assert connect(client).status_code == 503
    assert stream.closed
    assert db.get_workers() == []


def test_exact_health_byte_limit_accepts_a_valid_identity(admin):
    client, _, state = admin
    body = b'{"status":"ok","worker_id":"worker1"}'
    state["health"] = httpx.Response(200, content=body + b" " * (8192 - len(body)))
    assert connect(client).status_code == 200


@pytest.mark.parametrize("heartbeat,can_forget", [(None, True), ("2000-01-01T00:00:00+00:00", True),
    ("fresh", False), ("invalid", False), ("2000-01-01T00:00:00", False),
    ((datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), False)])
def test_forget_requires_stale_or_absent_heartbeat_even_for_dead_workers(admin, heartbeat, can_forget):
    client, db, _ = admin
    add_worker(db, heartbeat=heartbeat, status="DEAD")
    assert client.get("/api/v1/workers").json()["workers"][0]["can_forget"] is can_forget
    result = client.delete("/api/v1/workers/worker1", headers=ADMIN)
    assert result.status_code == (204 if can_forget else 409)
    assert len(db.get_workers()) == (0 if can_forget else 1)


@pytest.mark.parametrize("replica_state", ["HEALTHY", "CORRUPT", "MISSING", "PENDING_DELETE"])
def test_forget_counts_every_replica_record_including_failed_objects(admin, replica_state):
    client, db, _ = admin
    add_worker(db, heartbeat=None)
    db.create_object("obj", "x", "application/octet-stream", {})
    db.add_chunk("obj_0", "obj", 0, 3, "a" * 64)
    db.set_object_state("obj", "FAILED")
    db.upsert_replica("obj_0", "worker1", replica_state)
    worker = client.get("/api/v1/workers").json()["workers"][0]
    assert worker["replica_count"] == 1
    assert worker["can_forget"] is False
    assert client.delete("/api/v1/workers/worker1", headers=ADMIN).status_code == 409
    assert len(db.get_replicas("obj_0")) == 1


def test_forget_rereads_guard_and_cascades_settings_without_contacting_worker(admin):
    client, db, state = admin
    add_worker(db, heartbeat=None)
    assert client.patch("/api/v1/workers/worker1", headers=ADMIN, json={"notes": "Old disk"}).status_code == 200
    assert client.get("/api/v1/workers").json()["workers"][0]["can_forget"] is True
    db.touch_heartbeat("worker1")
    assert client.delete("/api/v1/workers/worker1", headers=ADMIN).status_code == 409
    with db.connection() as conn:
        conn.execute("UPDATE workers SET last_heartbeat=NULL")
    assert client.delete("/api/v1/workers/worker1", headers=ADMIN).status_code == 204
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM worker_settings").fetchone()[0] == 0
    assert state["requests"] == []


def test_admin_observations_are_bounded_and_exclude_labels_and_notes(admin):
    client, _, _ = admin
    assert connect(client, display_name="private label", notes="private note").status_code == 200
    assert client.patch("/api/v1/workers/worker1", headers=ADMIN,
        json={"placement_enabled": False}).status_code == 200
    _, db, _ = admin
    with db.connection() as conn:
        conn.execute("UPDATE workers SET last_heartbeat=NULL")
    assert client.delete("/api/v1/workers/worker1", headers=ADMIN).status_code == 204
    activity = client.get("/api/v1/activity").json()
    assert {"worker_connected", "worker_settings", "worker_forgotten"} <= {e["kind"] for e in activity["events"]}
    assert "private" not in json.dumps(activity)


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://testserver/path", "not an origin",
    "http://testserver?", "http://testserver#"])
def test_cross_origin_object_upload_is_rejected_before_metadata_or_worker_requests(admin, origin):
    client, db, state = admin
    response = client.post("/api/v1/objects", headers={"Origin": origin}, files={"file": ("x", b"abc")})
    assert response.status_code == 403
    assert db.get_abandoned_object_ids() == []
    assert state["requests"] == []


def test_same_origin_object_upload_is_allowed(admin):
    client, db, _ = admin
    for index in range(1, 3):
        add_worker(db, f"worker{index}")
    assert client.post("/api/v1/objects", headers={"Origin": "http://testserver"},
        files={"file": ("x", b"abc")}).status_code == 201


def test_pausing_an_inflight_copy_does_not_reject_commit_or_existing_download(admin, monkeypatch):
    from controller import objects
    client, db, _ = admin
    for index in range(1, 3):
        add_worker(db, f"worker{index}")
    original_put = objects._put_copy

    async def pause_after_ack(http, chunk, worker, data):
        stored = await original_put(http, chunk, worker, data)
        db.update_worker_settings(worker["worker_id"], {"placement_enabled": False})
        return stored

    monkeypatch.setattr(objects, "_put_copy", pause_after_ack)
    response = client.post("/api/v1/objects", files={"file": ("x", b"abc")})
    assert response.status_code == 201
    assert client.get("/api/v1/workers").json()["placement_available_workers"] == 0
    assert client.get(f'/api/v1/objects/{response.json()["object_id"]}').content == b"abc"
    assert client.post("/api/v1/objects", files={"file": ("x", b"def")}).status_code == 503
    assert len(db.list_objects()) == 1
