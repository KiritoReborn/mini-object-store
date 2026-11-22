"""Real controller and SQLite with only the external worker HTTP boundary replaced."""
import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request


@pytest.fixture
def system(tmp_path, monkeypatch, no_recovery_module, request):
    from controller import config, database
    from controller.main import create_app
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    monkeypatch.setattr(config, "RECONCILE_INTERVAL", getattr(request, "param", config.RECONCILE_INTERVAL))
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


@pytest.mark.parametrize("data,range_header,status,code", [
    (b"abcdef", "items=0-2", 400, "INVALID_RANGE"),
    (b"abcdef", "bytes=garbage", 400, "INVALID_RANGE"),
    (b"abcdef", "bytes=4-2", 400, "INVALID_RANGE"),
    (b"abcdef", "bytes", 400, "INVALID_RANGE"),
    (b"abcdef", "bytes=6-", 416, "RANGE_NOT_SATISFIABLE"),
    (b"abcdef", "bytes=200-300", 416, "RANGE_NOT_SATISFIABLE"),
    (b"abcdef", "bytes=-0", 416, "RANGE_NOT_SATISFIABLE"),
    (b"", "bytes=0-", 416, "RANGE_NOT_SATISFIABLE"),
    (b"", "bytes=-1", 416, "RANGE_NOT_SATISFIABLE"),
])
def test_invalid_download_range_returns_json_before_preparing_file(
    system, data, range_header, status, code
):
    from controller import objects

    client, state, _, tmp = system
    obj = upload(client, data).json()
    path = f'/api/v1/objects/{obj["object_id"]}'
    state["history"].clear()

    with patch.object(objects, "_prepare_download", wraps=objects._prepare_download) as prepare:
        response = client.get(path, headers={"Range": range_header})
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"] == code
    assert response.json()["message"]
    if status == 416:
        assert response.headers["content-range"] == f"bytes */{len(data)}"
    prepare.assert_not_awaited()
    assert state["history"] == []
    assert not list((tmp / "downloads").iterdir())
    assert obj["object_id"] not in objects._locks
    following = client.get(path)
    assert following.status_code == 200 and following.content == data
    assert following.headers["x-object-sha256"] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("data,range_header,expected,content_range", [
    (b"abcdef", "bytes=1-3", b"bcd", "bytes 1-3/6"),
    (b"abcdef", "bytes=4-", b"ef", "bytes 4-5/6"),
    (b"abcdef", "bytes=-2", b"ef", "bytes 4-5/6"),
    (b"abcdef", "bytes=-20", b"abcdef", "bytes 0-5/6"),
    (b"abcdef", "BYTES = 1 - 2 ", b"bc", "bytes 1-2/6"),
    (b"abcdef", "bytes=garbage,1-2", b"bc", "bytes 1-2/6"),
    (b"a", "bytes=0-", b"a", "bytes 0-0/1"),
])
def test_valid_download_range_preserves_file_response(system, data, range_header, expected, content_range):
    client, _, _, _ = system
    obj = upload(client, data).json()
    path = f'/api/v1/objects/{obj["object_id"]}'
    response = client.get(path, headers={"Range": range_header})
    assert response.status_code == 206
    assert response.content == expected
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(expected))
    assert response.headers["content-type"] == obj["content_type"]
    assert response.headers["x-object-sha256"] == obj["sha256"]


def test_multi_range_download_and_if_range_keep_file_response_semantics(system):
    from email import policy
    from email.parser import BytesParser

    client, _, _, _ = system
    data = b"abcdef"
    obj = upload(client, data).json()
    path = f'/api/v1/objects/{obj["object_id"]}'
    response = client.get(path, headers={"Range": "bytes=0-1,4-5", "If-Range": f'"{obj["sha256"]}"'})
    assert response.status_code == 206
    mime_header = response.headers["content-type"]
    assert mime_header.startswith("multipart/byteranges;")
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {mime_header}\r\n\r\n".encode() + response.content
    )
    assert [(part["Content-Range"], part.get_payload(decode=True)) for part in message.iter_parts()] == [
        ("bytes 0-1/6", b"ab"), ("bytes 4-5/6", b"ef")]
    full = client.get(path, headers={"Range": "bytes=0-1", "If-Range": '"older"'})
    assert full.status_code == 200 and full.content == data
    assert client.head(path).status_code == 405


@pytest.mark.parametrize("range_header,validator,status,code", [
    ("bytes=99-", '"older"', 416, "RANGE_NOT_SATISFIABLE"),
    ("bytes=99-", "Wed, 21 Oct 2015 07:28:00 GMT", 416, "RANGE_NOT_SATISFIABLE"),
    ("items=0-1", '"older"', 400, "INVALID_RANGE"),
])
def test_stale_if_range_ignores_invalid_range(system, range_header, validator, status, code):
    from controller import objects

    client, _, _, tmp = system
    data = b"abcdef"
    obj = upload(client, data).json()
    path = f'/api/v1/objects/{obj["object_id"]}'
    full = client.get(path, headers={"Range": range_header, "If-Range": validator})
    assert full.status_code == 200
    assert full.content == data
    assert full.headers["x-object-sha256"] == hashlib.sha256(data).hexdigest()
    assert "content-range" not in full.headers
    assert not list((tmp / "downloads").iterdir())
    assert obj["object_id"] not in objects._locks

    for condition in ({}, {"If-Range": full.headers["etag"]}):
        error = client.get(path, headers={"Range": range_header, **condition})
        assert error.status_code == status
        assert error.headers["content-type"] == "application/json"
        assert error.json()["error"] == code
        if status == 416:
            assert error.headers["content-range"] == "bytes */6"
        assert not list((tmp / "downloads").iterdir())
        assert obj["object_id"] not in objects._locks


def test_missing_and_deleted_objects_take_precedence_over_invalid_ranges(system):
    client, _, _, _ = system
    obj = upload(client).json()
    deleted_path = f'/api/v1/objects/{obj["object_id"]}'
    assert client.delete(deleted_path).status_code == 204
    for path in ("/api/v1/objects/unknown", deleted_path):
        for range_header in ("not a range", "bytes=999999-"):
            response = client.get(path, headers={"Range": range_header})
            assert response.status_code == 404
            assert response.json()["error"] == "OBJECT_NOT_FOUND"


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


@pytest.mark.parametrize("size,chunk_sizes", [
    (1_000_000, [1_000_000]), (1_000_001, [1_000_000, 1]),
])
def test_public_upload_chunk_boundaries(system, size, chunk_sizes):
    client, _, _, _ = system
    content = b"x" * size
    response = upload(client, content)
    assert response.status_code == 201, response.text
    obj = response.json()
    assert obj["num_chunks"] == len(chunk_sizes)
    assert [chunk["size"] for chunk in obj["chunks"]] == chunk_sizes
    assert obj["sha256"] == hashlib.sha256(content).hexdigest()


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


@pytest.mark.parametrize(("system", "retry"), [(60, True), (0.01, False)], indirect=["system"])
def test_interrupted_delete_finishes_without_restarting(system, retry, monkeypatch):
    from controller import objects

    client, state, db, _ = system
    oid = upload(client).json()["object_id"]
    path = f"/api/v1/objects/{oid}"
    original_delete = objects._delete_copy

    async def interrupt_delete():
        entered = asyncio.Event()

        async def pause_second_copy(http, chunk_id, replica):
            if replica["worker_id"] == "worker2" and not entered.is_set():
                entered.set()
                await asyncio.Event().wait()
            return await original_delete(http, chunk_id, replica)

        monkeypatch.setattr(objects, "_delete_copy", pause_second_copy)
        task = asyncio.create_task(objects.delete_object(Request({"type": "http", "app": client.app}), oid))
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            assert db.get_object_manifest(oid)["status"] == "DELETING"
            assert list(state["data"]) == [("worker2", f"{oid}_0")]
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    client.portal.call(interrupt_delete)
    assert client.get(path + "/metadata").status_code == 404
    if retry:
        assert client.delete(path).status_code == 204
    else:
        async def wait_for_cleanup():
            while db.get_object_manifest(oid) is not None:
                await asyncio.sleep(0.01)

        client.portal.call(asyncio.wait_for, wait_for_cleanup(), 3)
    assert db.get_object_manifest(oid) is None
    assert state["data"] == {}
    assert client.delete(path).status_code == 404


def test_manifest_distinguishes_recorded_and_available_replica_locations(system):
    client, _, db, _ = system
    obj = upload(client).json()
    assert obj["chunks"][0]["available_workers"] == ["worker1", "worker2"]
    db.set_worker_state("worker1", "DEAD")
    with db.connection() as conn:
        conn.execute("UPDATE workers SET last_heartbeat=? WHERE worker_id='worker2'", ("2000-01-01T00:00:00+00:00",))

    chunk = client.get(f'/api/v1/objects/{obj["object_id"]}/metadata').json()["chunks"][0]
    assert chunk["workers"] == ["worker1", "worker2"]
    assert chunk["available_workers"] == []
    assert [(r["state"], r["worker_status"]) for r in chunk["replicas"]] == [
        ("HEALTHY", "DEAD"), ("HEALTHY", "ALIVE"),
    ]
    overview = client.get("/api/v1/overview").json()
    assert overview["healthy_replica_count"] == 0
    assert overview["under_replicated_chunks"] == 1


def test_openapi_documents_binary_downloads_and_json_validation_errors(system):
    client, _, _, _ = system
    schema = client.get("/openapi.json").json()
    download = schema["paths"]["/api/v1/objects/{object_id}"]["get"]["responses"]
    assert set(download["200"]["content"]) == {"application/octet-stream"}
    assert download["200"]["content"]["application/octet-stream"]["schema"]["format"] == "binary"
    assert set(download["206"]["content"]) == {"application/octet-stream", "multipart/byteranges"}
    assert "Content-Range" in download["206"]["headers"]
    assert "Content-Range" in download["416"]["headers"]
    upload_responses = schema["paths"]["/api/v1/objects"]["post"]["responses"]
    for responses, status in [(download, "400"), (download, "416"), (upload_responses, "400")]:
        assert "422" not in responses
        ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
        assert set(schema["components"]["schemas"][ref.rsplit("/", 1)[1]]["required"]) == {"error", "message"}


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
