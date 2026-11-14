"""Real controller and SQLite with only the external worker HTTP boundary replaced."""
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def system(tmp_path, monkeypatch):
    from controller import config, database
    from controller.main import create_app
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    state = {"data": {}, "fail_put": set(), "fail_get": set(), "fail_delete": set(),
             "forged": set(), "missing": set(), "lost_reply": set(), "bad_ack": set(), "history": []}

    def worker(request):
        worker_id = request.url.host
        chunk_id = request.url.path.rsplit("/", 1)[-1]
        key = (worker_id, chunk_id)
        state["history"].append((request.method, worker_id, chunk_id))
        if request.method == "PUT":
            if worker_id in state["fail_put"]:
                raise httpx.ConnectError("worker offline", request=request)
            data = request.content
            assert request.headers["X-Chunk-SHA256"] == hashlib.sha256(data).hexdigest()
            existed = key in state["data"]
            state["data"][key] = data
            if worker_id in state["lost_reply"]:
                raise httpx.ReadTimeout("written, but reply lost", request=request)
            if worker_id in state["bad_ack"]:
                return httpx.Response(201, json={"chunk_id": "wrong"})
            return httpx.Response(200 if existed else 201, json={
                "chunk_id": chunk_id, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "status": "stored"})
        if request.method == "DELETE":
            if worker_id in state["fail_delete"]:
                raise httpx.ConnectError("worker offline", request=request)
            state["data"].pop(key, None)
            return httpx.Response(204)
        if worker_id in state["fail_get"]:
            raise httpx.ReadTimeout("read timeout", request=request)
        if key not in state["data"] or worker_id in state["missing"]:
            return httpx.Response(404, json={"error": "CHUNK_NOT_FOUND", "message": "missing"})
        data = state["data"][key]
        if worker_id in state["forged"]:
            data = b"!" * len(data)
        return httpx.Response(200, content=data, headers={"X-Chunk-SHA256": hashlib.sha256(data).hexdigest()})

    with TestClient(create_app(worker_transport=httpx.MockTransport(worker)), raise_server_exceptions=False) as client:
        for index in range(1, 5):
            wid = f"worker{index}"
            database.register_worker(wid, f"http://{wid}:8001")
            # This unit fixture isolates transfer behavior; test_recovery covers admission.
            database.set_worker_state(wid, "ALIVE")
        yield client, state, database, tmp_path


def upload(client, data=b"hello\x00binary\xff", metadata=None, name="sample.bin"):
    fields = {} if metadata is None else {"metadata": json.dumps(metadata)}
    return client.post("/api/v1/objects", files={"file": (name, data, "application/octet-stream")}, data=fields)


def test_registration_heartbeat_and_degraded_health_are_honest(system):
    client, _, db, _ = system
    assert client.post("/internal/workers/heartbeat", json={"worker_id": "new"}).status_code == 404
    assert client.post("/internal/workers/register", json={"worker_id": "new", "base_url": "http://new:8001"}).status_code == 200
    assert client.post("/internal/workers/heartbeat", json={"worker_id": "new"}).status_code == 200
    assert next(w for w in db.get_workers() if w["worker_id"] == "new")["status"] == "JOINING"
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["recovery_available"] is False


def test_binary_upload_download_and_two_distinct_replicas(system):
    client, _, db, tmp = system
    data = bytes(range(256)) * 3907
    response = upload(client, data, {"course": "CC"})
    assert response.status_code == 201, response.text
    obj = response.json()
    assert obj["sha256"] == hashlib.sha256(data).hexdigest()
    assert obj["num_chunks"] == 2
    manifest = db.get_object_manifest(obj["object_id"])
    for chunk in manifest["chunks"]:
        assert len({r["worker_id"] for r in chunk["replicas"] if r["state"] == "HEALTHY"}) == 2
    downloaded = client.get(f'/api/v1/objects/{obj["object_id"]}')
    assert downloaded.status_code == 200
    assert downloaded.content == data
    assert downloaded.headers["content-type"] == "application/octet-stream"
    assert not list((tmp / "downloads").iterdir())


def test_empty_file_needs_no_workers_and_has_empty_checksum(system):
    client, _, db, _ = system
    for w in db.get_workers():
        db.set_worker_state(w["worker_id"], "DEAD")
    response = upload(client, b"")
    assert response.status_code == 201
    obj = response.json()
    assert obj["num_chunks"] == 0
    assert obj["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert client.get(f'/api/v1/objects/{obj["object_id"]}').content == b""


@pytest.mark.parametrize("body", ["{bad", "[]", '{"size":4}', '{"x":NaN}', '"text"'])
def test_invalid_upload_metadata_is_400_without_writes(system, body):
    client, state, db, _ = system
    response = client.post("/api/v1/objects", files={"file": ("x", b"x")}, data={"metadata": body})
    assert response.status_code == 400
    assert "error" in response.json()
    assert state["data"] == {}
    assert db.list_objects() == []


def test_missing_file_and_invalid_worker_requests_are_400(system):
    client, _, _, _ = system
    assert client.post("/api/v1/objects").status_code == 400
    for body in [{}, {"worker_id": "../bad", "base_url": "http://w:8001"},
                 {"worker_id": "w", "base_url": "file:///etc/passwd"},
                 {"worker_id": "w", "base_url": "http://user:password@w:8001"}]:
        assert client.post("/internal/workers/register", json=body).status_code == 400


def test_failed_upload_rolls_back_reachable_copies_and_stays_invisible(system):
    client, state, db, _ = system
    state["fail_put"] = {"worker2", "worker3", "worker4"}
    response = upload(client)
    assert response.status_code == 503
    assert db.list_objects() == []
    assert state["data"] == {}
    assert db.known_chunk_ids() == set()


@pytest.mark.parametrize("failure", ["fail_put", "lost_reply", "bad_ack"])
def test_spare_worker_handles_failed_or_ambiguous_write(system, failure):
    client, state, db, _ = system
    state[failure] = {"worker1"}
    response = upload(client)
    assert response.status_code == 201, response.text
    chunk = db.get_object_manifest(response.json()["object_id"])["chunks"][0]
    assert len([r for r in chunk["replicas"] if r["state"] == "HEALTHY"]) == 2
    assert len(state["data"]) == 2
    assert all(wid != "worker1" for wid, _ in state["data"])


def test_uncertain_surplus_is_tracked_until_delete_can_be_retried(system):
    client, state, db, _ = system
    state["lost_reply"] = {"worker1"}
    state["fail_delete"] = {"worker1"}
    response = upload(client)
    assert response.status_code == 201
    chunk = db.get_object_manifest(response.json()["object_id"])["chunks"][0]
    assert {r["worker_id"] for r in chunk["replicas"] if r["state"] == "PENDING_DELETE"} == {"worker1"}
    assert len([r for r in chunk["replicas"] if r["state"] == "HEALTHY"]) == 2


@pytest.mark.parametrize("failure,expected", [("forged", "CORRUPT"), ("missing", "MISSING"), ("fail_get", "HEALTHY")])
def test_download_falls_back_and_classifies_failure_accurately(system, failure, expected):
    client, state, db, _ = system
    data = b"trusted bytes"
    oid = upload(client, data).json()["object_id"]
    state[failure] = {"worker1"}
    response = client.get(f"/api/v1/objects/{oid}")
    assert response.status_code == 200
    assert response.content == data
    replica = next(r for r in db.get_replicas(oid + "_0") if r["worker_id"] == "worker1")
    assert replica["state"] == expected


def test_no_good_copy_returns_json_503_without_temp_leaks(system):
    client, state, _, tmp = system
    oid = upload(client).json()["object_id"]
    state["forged"] = {"worker1", "worker2"}
    response = client.get(f"/api/v1/objects/{oid}")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json"
    assert not list((tmp / "downloads").iterdir())


def test_whole_object_hash_is_verified_before_a_successful_response(system):
    client, _, db, _ = system
    oid = upload(client).json()["object_id"]
    with db.connection() as conn:
        conn.execute("UPDATE objects SET sha256=? WHERE object_id=?", ("0" * 64, oid))
    assert client.get(f"/api/v1/objects/{oid}").status_code == 503


def test_metadata_patch_and_list_never_transfer_object_bytes(system):
    client, state, _, _ = system
    oid = upload(client, metadata={"course": "CC"}).json()["object_id"]
    before = client.get(f"/api/v1/objects/{oid}/metadata").json()
    state["history"].clear()
    response = client.patch(f"/api/v1/objects/{oid}/metadata", json={"metadata": {"reviewed": True}})
    assert response.status_code == 200
    after = response.json()
    assert after["metadata"] == {"course": "CC", "reviewed": True}
    assert after["sha256"] == before["sha256"]
    assert after["updated_at"] >= before["updated_at"]
    assert len(client.get("/api/v1/objects").json()) == 1
    assert state["history"] == []
    assert client.patch(f"/api/v1/objects/{oid}/metadata", json={"metadata": {"sha256": "fake"}}).status_code == 400


def test_delete_hides_object_even_if_a_worker_is_offline(system):
    client, state, db, _ = system
    oid = upload(client).json()["object_id"]
    state["fail_delete"] = {"worker1"}
    response = client.delete(f"/api/v1/objects/{oid}")
    assert response.status_code == 204
    assert response.content == b""
    assert db.get_object_manifest(oid) is None
    assert db.known_chunk_ids() == set()
    assert len(state["data"]) == 1  # Offline bytes await B's rejoin cleanup.
    assert client.get(f"/api/v1/objects/{oid}").status_code == 404
    assert client.get(f"/api/v1/objects/{oid}/metadata").status_code == 404
    assert client.delete(f"/api/v1/objects/{oid}").status_code == 404
    assert client.get("/api/v1/objects").json() == []


def test_non_ready_objects_are_hidden_and_filename_is_safe(system):
    client, _, db, _ = system
    response = upload(client, name="../résumé.bin")
    assert response.status_code == 201
    oid = response.json()["object_id"]
    assert response.json()["name"] == "résumé.bin"
    assert "filename*=utf-8" in client.get(f"/api/v1/objects/{oid}").headers["content-disposition"].lower()
    db.set_object_state(oid, "UPLOADING")
    assert client.get(f"/api/v1/objects/{oid}").status_code == 404
    assert client.patch(f"/api/v1/objects/{oid}/metadata", json={"metadata": {}}).status_code == 404
    assert client.get("/api/v1/objects").json() == []


def test_tempfile_failure_returns_json_and_exposes_no_internal_path(system, monkeypatch):
    client, _, _, _ = system
    from controller import objects
    oid = upload(client).json()["object_id"]

    def no_disk(*args, **kwargs):
        raise OSError("private/path: disk full")

    monkeypatch.setattr(objects.tempfile, "mkstemp", no_disk)
    response = client.get(f"/api/v1/objects/{oid}")
    assert response.status_code == 503
    assert "private/path" not in response.text


def test_upload_read_failure_rolls_back_and_returns_service_error(system, monkeypatch):
    from controller import objects
    client, state, db, _ = system

    async def broken_read(file):
        yield b"first chunk"
        raise OSError("input temporary disk failed")

    monkeypatch.setattr(objects, "iter_chunks", broken_read)
    response = upload(client)
    assert response.status_code == 503
    assert db.list_objects() == []
    assert state["data"] == {}


def test_parallel_uploads_keep_distinct_objects_and_replica_pairs(system):
    from concurrent.futures import ThreadPoolExecutor
    client, _, db, _ = system
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda n: upload(client, bytes([n]) * 1000001), range(4)))
    assert all(r.status_code == 201 for r in results), [(r.status_code, r.text) for r in results]
    ids = {r.json()["object_id"] for r in results}
    assert len(ids) == 4
    for oid in ids:
        assert len(db.get_object_manifest(oid)["chunks"]) == 2


def test_merged_metadata_limit_is_checked_without_losing_previous_values(system):
    from controller import config
    client, _, _, _ = system
    oid = upload(client, metadata={"a": "a" * (config.MAX_METADATA_BYTES // 2)}).json()["object_id"]
    patch = {"metadata": {"b": "b" * (config.MAX_METADATA_BYTES // 2)}}
    assert client.patch(f"/api/v1/objects/{oid}/metadata", json=patch).status_code == 400
    assert list(client.get(f"/api/v1/objects/{oid}/metadata").json()["metadata"]) == ["a"]
