import asyncio
import hashlib
import json
import logging
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from threading import Barrier, Event

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure WORKER_ID is set before importing worker config
os.environ["WORKER_ID"] = "worker_test"

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from worker import config, heartbeat, storage
import worker.main as worker_main
from worker.main import app


@pytest.fixture(autouse=True)
def setup_storage(tmp_path: Path, monkeypatch):
    """Isolate storage per test using pytest tmp_path."""
    monkeypatch.setattr(config, "STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def client():
    # Use TestClient without triggering background heartbeat task
    test_client = TestClient(app, raise_server_exceptions=False)
    try:
        yield test_client
    finally:
        test_client.close()


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


VALID_CHUNK_ID = "550e8400-e29b-41d4-a716-446655440000_0"


def test_demo_fault_disabled_returns_json_404(client, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_FAULT_INJECTION", False, raising=False)
    response = client.post(f"/internal/demo/corrupt/{VALID_CHUNK_ID}")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"error": "NOT_FOUND", "message": "Not Found"}


@pytest.fixture
def demo_fault(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_FAULT_INJECTION", True, raising=False)
    return f"/internal/demo/corrupt/{VALID_CHUNK_ID}"


def test_demo_fault_changes_one_byte_and_put_repairs_it(client, demo_fault, caplog):
    data = b"demo payload"
    sha = compute_sha256(data)
    chunk_url = f"/internal/chunks/{VALID_CHUNK_ID}"
    assert client.put(chunk_url, headers={"X-Chunk-SHA256": sha}, content=data).status_code == 201
    sidecar = storage.sha_path(VALID_CHUNK_ID)
    original_sidecar = sidecar.read_bytes(), sidecar.stat().st_mtime_ns
    wrong_worker = client.post(demo_fault, headers={"X-Artaud-Worker-ID": "other-worker"})
    assert wrong_worker.status_code == 404 and wrong_worker.json()["error"] == "WRONG_WORKER"
    assert storage.chunk_path(VALID_CHUNK_ID).read_bytes() == data
    response = client.post(demo_fault)
    assert response.status_code == 200
    assert response.json() == {
        "chunk_id": VALID_CHUNK_ID, "worker_id": config.WORKER_ID, "offset": 0,
        "size": len(data), "action": "corrupted",
    }
    assert storage.chunk_path(VALID_CHUNK_ID).read_bytes() == bytes([data[0] ^ 1]) + data[1:]
    assert (sidecar.read_bytes(), sidecar.stat().st_mtime_ns) == original_sidecar
    assert "FAULT_INJECTED" in caplog.text and VALID_CHUNK_ID in caplog.text
    response = client.get(chunk_url)
    assert response.status_code == 409 and response.json()["error"] == "CHUNK_CORRUPTED"
    response = client.post(demo_fault)
    assert response.status_code == 409 and response.json()["error"] == "CHUNK_CORRUPTED"
    assert client.put(chunk_url, headers={"X-Chunk-SHA256": sha}, content=data).status_code == 201
    assert client.get(chunk_url).content == data


def test_demo_fault_rejects_missing_empty_and_invalid_paths(client, demo_fault):
    response = client.post(demo_fault)
    assert response.status_code == 404 and response.json()["error"] == "CHUNK_NOT_FOUND"
    storage.put(VALID_CHUNK_ID, b"", compute_sha256(b""))
    response = client.post(demo_fault)
    assert response.status_code == 409 and response.json()["error"] == "CHUNK_EMPTY"
    for bad_id in ("bad", VALID_CHUNK_ID + "0", "%2e%2e%2foutside", f"{VALID_CHUNK_ID}%2foutside"):
        response = client.post(f"/internal/demo/corrupt/{bad_id}")
        assert response.status_code == 400 and response.json()["error"] == "INVALID_CHUNK_ID"
    assert storage.chunk_path(VALID_CHUNK_ID).read_bytes() == b""


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_demo_fault_never_writes_through_a_link(client, demo_fault, tmp_path, link):
    original = tmp_path / "outside-chunk-id"
    original.write_bytes(b"untouched")
    path = storage.chunk_path(VALID_CHUNK_ID)
    if link == "symlink":
        path.symlink_to(original)
    else:
        path.hardlink_to(original)
    storage.sha_path(VALID_CHUNK_ID).write_text(compute_sha256(b"untouched"))
    response = client.post(demo_fault)
    assert response.status_code == 409
    assert original.read_bytes() == b"untouched"


@pytest.mark.parametrize("method,expected", [("GET", 409), ("PUT", 201), ("DELETE", 204)])
def test_demo_fault_holds_chunk_lock_through_fsync(client, demo_fault, monkeypatch, method, expected):
    data = b"demo bytes"
    sha = compute_sha256(data)
    storage.put(VALID_CHUNK_ID, data, sha)
    writing, resume, competing = Event(), Event(), Event()
    real_fsync = os.fsync

    def paused_fsync(fd):
        if not writing.is_set():
            writing.set()
            if not resume.wait(3):
                raise RuntimeError("fault injection was not released")
        return real_fsync(fd)

    def compete():
        competing.set()
        kwargs = {"content": data, "headers": {"X-Chunk-SHA256": sha}} if method == "PUT" else {}
        return client.request(method, f"/internal/chunks/{VALID_CHUNK_ID}", **kwargs)

    monkeypatch.setattr(os, "fsync", paused_fsync)
    with ThreadPoolExecutor(2) as pool:
        injection = pool.submit(client.post, demo_fault)
        try:
            assert writing.wait(3)
            contender = pool.submit(compete)
            assert competing.wait(3)
            with pytest.raises(FutureTimeout):
                contender.result(timeout=0.05)
        finally:
            resume.set()
        assert injection.result(timeout=3).status_code == 200
        assert contender.result(timeout=3).status_code == expected
    assert storage.check(VALID_CHUNK_ID)[0] == {"GET": "corrupt", "PUT": "ok", "DELETE": "missing"}[method]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"worker_id": "worker_test", "status": "ok"}


def test_put_and_idempotent_put(client):
    data = b"x" * 1024
    sha = compute_sha256(data)
    url = f"/internal/chunks/{VALID_CHUNK_ID}"

    # First PUT -> 201 Created
    r1 = client.put(url, headers={"X-Chunk-SHA256": sha}, content=data)
    assert r1.status_code == 201
    assert r1.json()["status"] == "stored"
    assert r1.json()["size"] == 1024
    assert r1.json()["sha256"] == sha

    # Second PUT with identical data -> 200 OK
    r2 = client.put(url, headers={"X-Chunk-SHA256": sha}, content=data)
    assert r2.status_code == 200
    assert r2.json()["status"] == "stored"


def test_get_chunk(client):
    data = b"hello distributed world"
    sha = compute_sha256(data)
    url = f"/internal/chunks/{VALID_CHUNK_ID}"

    client.put(url, headers={"X-Chunk-SHA256": sha}, content=data)

    r = client.get(url)
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["X-Chunk-SHA256"] == sha


def test_get_chunk_not_found(client):
    url = f"/internal/chunks/{VALID_CHUNK_ID}"
    r = client.get(url)
    assert r.status_code == 404
    assert r.json()["error"] == "CHUNK_NOT_FOUND"


def test_list_chunks(client):
    data = b"inventory chunk test"
    sha = compute_sha256(data)
    client.put(f"/internal/chunks/{VALID_CHUNK_ID}", headers={"X-Chunk-SHA256": sha}, content=data)

    # Correct worker
    r = client.get("/internal/workers/worker_test/chunks")
    assert r.status_code == 200
    res = r.json()
    assert res["worker_id"] == "worker_test"
    assert len(res["chunks"]) == 1
    assert res["chunks"][0]["chunk_id"] == VALID_CHUNK_ID
    assert res["chunks"][0]["size"] == len(data)
    assert res["chunks"][0]["sha256"] == sha

    # Wrong worker
    r_wrong = client.get("/internal/workers/wrong_worker/chunks")
    assert r_wrong.status_code == 404
    assert r_wrong.json()["error"] == "WRONG_WORKER"


@pytest.mark.parametrize("index", ["0", "1", "10"])
def test_delete_and_delete_twice(client, index):
    data = b"delete test data"
    sha = compute_sha256(data)
    chunk_id = VALID_CHUNK_ID.rsplit("_", 1)[0] + "_" + index
    url = f"/internal/chunks/{chunk_id}"

    assert client.put(url, headers={"X-Chunk-SHA256": sha}, content=data).status_code == 201
    before_delete = client.get(url)
    assert before_delete.status_code == 200
    assert before_delete.content == data

    # First delete -> 204
    r1 = client.delete(url)
    assert r1.status_code == 204

    # Second delete (already deleted) -> still 204
    r2 = client.delete(url)
    assert r2.status_code == 204

    # Verify chunk is gone
    assert client.get(url).status_code == 404
    assert not storage.chunk_path(chunk_id).exists()
    assert not storage.sha_path(chunk_id).exists()


def test_bad_puts(client):
    url = f"/internal/chunks/{VALID_CHUNK_ID}"

    # Missing X-Chunk-SHA256 header -> 400
    r_no_header = client.put(url, content=b"some data")
    assert r_no_header.status_code == 400
    assert r_no_header.json()["error"] == "MISSING_CHECKSUM"

    # Mismatched SHA256 -> 400
    wrong_sha = "0" * 64
    r_mismatch = client.put(url, headers={"X-Chunk-SHA256": wrong_sha}, content=b"some data")
    assert r_mismatch.status_code == 400
    assert r_mismatch.json()["error"] == "CHECKSUM_MISMATCH"

    # Body over CHUNK_SIZE (1,000,000 bytes) -> 400
    too_large = b"a" * 1000001
    sha_large = compute_sha256(too_large)
    r_large = client.put(url, headers={"X-Chunk-SHA256": sha_large}, content=too_large)
    assert r_large.status_code == 400
    assert r_large.json()["error"] == "CHUNK_TOO_LARGE"


def test_put_conflict(client):
    data1 = b"original data"
    sha1 = compute_sha256(data1)
    url = f"/internal/chunks/{VALID_CHUNK_ID}"

    r1 = client.put(url, headers={"X-Chunk-SHA256": sha1}, content=data1)
    assert r1.status_code == 201

    data2 = b"different data"
    sha2 = compute_sha256(data2)
    r2 = client.put(url, headers={"X-Chunk-SHA256": sha2}, content=data2)
    assert r2.status_code == 409
    assert r2.json()["error"] == "CHUNK_CONFLICT"


def test_corrupt_chunk_and_repair(client):
    data = b"valid data for corruption check"
    sha = compute_sha256(data)
    url = f"/internal/chunks/{VALID_CHUNK_ID}"

    # 1. Put valid chunk
    r = client.put(url, headers={"X-Chunk-SHA256": sha}, content=data)
    assert r.status_code == 201

    # 2. Corrupt the file directly on disk
    chunk_file = storage.chunk_path(VALID_CHUNK_ID)
    with open(chunk_file, "ab") as f:
        f.write(b"x")

    # 3. GET should return 409 CHUNK_CORRUPTED
    r_corrupt = client.get(url)
    assert r_corrupt.status_code == 409
    assert r_corrupt.json()["error"] == "CHUNK_CORRUPTED"

    # 4. PUT original bytes again over corrupt chunk -> returns 201 (repair)
    r_repair = client.put(url, headers={"X-Chunk-SHA256": sha}, content=data)
    assert r_repair.status_code == 201

    # 5. GET should now return 200 with original data
    r_ok = client.get(url)
    assert r_ok.status_code == 200
    assert r_ok.content == data


def test_invalid_chunk_ids_and_path_traversal(client):
    invalid_ids = [
        "..%2Fetc",
        "%2E%2E%2Fetc",
        "bad%5Cpath",
        VALID_CHUNK_ID + "%2Fchild",
        "%252e%252e%252fetc",
        "invalid_id",
        "123",
        "550e8400-e29b-41d4-a716-446655440000",  # missing _index
        "550e8400-e29b-41d4-a716-44665544000z_0",  # invalid hex
        VALID_CHUNK_ID + "0",  # non-canonical _00 index
    ]
    for cid in invalid_ids:
        # GET
        r_get = client.get(f"/internal/chunks/{cid}")
        assert r_get.status_code == 400
        assert r_get.json()["error"] == "INVALID_CHUNK_ID"

        # DELETE
        r_del = client.delete(f"/internal/chunks/{cid}")
        assert r_del.status_code == 400
        assert r_del.json()["error"] == "INVALID_CHUNK_ID"

        # PUT
        r_put = client.put(
            f"/internal/chunks/{cid}",
            headers={"X-Chunk-SHA256": "0" * 64},
            content=b"test",
        )
        assert r_put.status_code == 400
        assert r_put.json()["error"] == "INVALID_CHUNK_ID"


@pytest.mark.parametrize("sidecar", [None, b"\xff", b"not a checksum", b"g" * 64])
def test_missing_or_bad_sidecar_is_repairable(client, sidecar):
    data = b"repairable bytes"
    sha = compute_sha256(data)
    url = f"/internal/chunks/{VALID_CHUNK_ID}"
    assert client.put(url, headers={"X-Chunk-SHA256": sha}, content=data).status_code == 201
    if sidecar is None:
        storage.sha_path(VALID_CHUNK_ID).unlink()
    else:
        storage.sha_path(VALID_CHUNK_ID).write_bytes(sidecar)

    response = client.get(url)
    assert response.status_code == 409
    assert response.json()["error"] == "CHUNK_CORRUPTED"
    assert storage.inventory()[0]["sha256"] is None
    assert client.put(url, headers={"X-Chunk-SHA256": sha}, content=data).status_code == 201
    assert client.get(url).content == data
    assert storage.check(VALID_CHUNK_ID) == ("ok", data, sha)


def test_exact_chunk_size_is_accepted(client):
    data = b"x" * config.CHUNK_SIZE
    url = f"/internal/chunks/{VALID_CHUNK_ID}"
    response = client.put(url, headers={"X-Chunk-SHA256": compute_sha256(data)}, content=data)
    assert response.status_code == 201
    assert client.get(url).content == data


def test_oversized_stored_chunk_is_not_read_and_can_be_repaired(client, monkeypatch):
    chunk_file = storage.chunk_path(VALID_CHUNK_ID)
    sidecar = storage.sha_path(VALID_CHUNK_ID)
    oversized = b"x" * (config.CHUNK_SIZE + 1)
    chunk_file.write_bytes(oversized)
    sidecar.write_text(compute_sha256(oversized), encoding="ascii")
    real_read = Path.read_bytes

    def bounded_read(path):
        if path == chunk_file:
            assert path.stat().st_size <= config.CHUNK_SIZE, "oversized chunk was read"
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", bounded_read)
    url = f"/internal/chunks/{VALID_CHUNK_ID}"
    response = client.get(url)
    assert response.status_code == 409
    assert response.json()["error"] == "CHUNK_CORRUPTED"

    data = b"repaired chunk"
    sha = compute_sha256(data)
    assert client.put(url, headers={"X-Chunk-SHA256": sha}, content=data).status_code == 201
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["X-Chunk-SHA256"] == sha

    chunk_file.write_bytes(oversized)
    sidecar.write_text(compute_sha256(oversized), encoding="ascii")
    assert client.delete(url).status_code == 204
    assert not chunk_file.exists()
    assert not sidecar.exists()


@pytest.mark.parametrize("sidecar_size", [128, 129, 4096])
def test_sidecar_read_limit_and_repair(client, monkeypatch, sidecar_size):
    data = b"sidecar limit"
    sha = compute_sha256(data)
    url = f"/internal/chunks/{VALID_CHUNK_ID}"
    assert client.put(url, headers={"X-Chunk-SHA256": sha}, content=data).status_code == 201
    sidecar = storage.sha_path(VALID_CHUNK_ID)
    padded_sha = sha.encode("ascii") + b" " * (sidecar_size - 64)
    sidecar.write_bytes(padded_sha)
    real_open = Path.open

    def bounded_open(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        if path == sidecar:
            real_read = stream.read

            def bounded_read(size=-1):
                assert 0 <= size <= 128, "sidecar read exceeded its hard cap"
                return real_read(size)

            stream.read = bounded_read
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", bounded_open)
        response = client.get(url)
        inventory = storage.inventory()
    if sidecar_size == 128:
        assert response.status_code == 200
        assert response.content == data
        assert inventory == [{"chunk_id": VALID_CHUNK_ID, "size": len(data), "sha256": sha}]
    else:
        assert response.status_code == 409
        assert response.json()["error"] == "CHUNK_CORRUPTED"
        assert inventory == [{"chunk_id": VALID_CHUNK_ID, "size": len(data), "sha256": None}]
        assert client.put(url, headers={"X-Chunk-SHA256": sha}, content=data).status_code == 201
        response = client.get(url)
        assert response.status_code == 200
        assert response.content == data
        assert response.headers["X-Chunk-SHA256"] == sha

        sidecar.write_bytes(padded_sha)
        assert client.delete(url).status_code == 204
        assert not storage.chunk_path(VALID_CHUNK_ID).exists()
        assert not sidecar.exists()


def test_oversized_stream_stops_consuming_before_end(monkeypatch):
    monkeypatch.setattr(config, "CHUNK_SIZE", 4)
    received = []
    messages = iter([
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"5", "more_body": True},
        {"type": "http.request", "body": b"must not be read", "more_body": False},
    ])

    async def receive():
        message = next(messages)
        received.append(message["body"])
        return message

    request = Request({"type": "http", "headers": [(b"x-chunk-sha256", b"0" * 64)]}, receive)
    response = asyncio.run(worker_main.put_chunk(VALID_CHUNK_ID, request))
    assert response.status_code == 400
    assert json.loads(response.body)["error"] == "CHUNK_TOO_LARGE"
    assert received == [b"1234", b"5"]
    assert not list(storage.ROOT.iterdir())


def test_concurrent_identical_puts_create_only_once():
    data = b"same bytes"
    sha = compute_sha256(data)
    ready = Barrier(8)

    def put(_):
        ready.wait(timeout=3)
        return storage.put(VALID_CHUNK_ID, data, sha)

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(put, range(8)))
    assert results.count("created") == 1
    assert results.count("exists") == 7
    assert storage.check(VALID_CHUNK_ID) == ("ok", data, sha)


def test_concurrent_different_puts_conflict():
    ready = Barrier(8)
    payloads = [bytes([value]) for value in range(8)]

    def put(data):
        ready.wait(timeout=3)
        return storage.put(VALID_CHUNK_ID, data, compute_sha256(data))

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(put, payloads))
    assert results.count("created") == 1
    assert results.count("conflict") == 7
    winner = payloads[results.index("created")]
    assert storage.check(VALID_CHUNK_ID) == ("ok", winner, compute_sha256(winner))


def test_get_and_delete_do_not_split_the_verified_read(monkeypatch):
    data = b"read before deletion"
    sha = compute_sha256(data)
    storage.put(VALID_CHUNK_ID, data, sha)
    reading, resume, deleting = Event(), Event(), Event()
    real_read = Path.read_bytes

    def paused_read(path):
        if path == storage.chunk_path(VALID_CHUNK_ID):
            reading.set()
            if not resume.wait(3):
                raise RuntimeError("read was not released")
        return real_read(path)

    def delete():
        deleting.set()
        storage.delete(VALID_CHUNK_ID)

    monkeypatch.setattr(Path, "read_bytes", paused_read)
    with ThreadPoolExecutor(2) as pool:
        get_future = pool.submit(storage.check, VALID_CHUNK_ID)
        try:
            assert reading.wait(3)
            delete_future = pool.submit(delete)
            assert deleting.wait(3)
            with pytest.raises(FutureTimeout):
                delete_future.result(timeout=0.05)
        finally:
            resume.set()
        assert get_future.result(timeout=3) == ("ok", data, sha)
        delete_future.result(timeout=3)
    assert storage.check(VALID_CHUNK_ID)[0] == "missing"


def test_delete_and_put_do_not_split_the_file_pair(monkeypatch):
    storage.put(VALID_CHUNK_ID, b"old", compute_sha256(b"old"))
    deleted_data, resume, putting = Event(), Event(), Event()
    real_unlink = Path.unlink

    def paused_unlink(path, *args, **kwargs):
        result = real_unlink(path, *args, **kwargs)
        if path == storage.chunk_path(VALID_CHUNK_ID):
            deleted_data.set()
            if not resume.wait(3):
                raise RuntimeError("delete was not released")
        return result

    def put():
        putting.set()
        return storage.put(VALID_CHUNK_ID, b"new", compute_sha256(b"new"))

    monkeypatch.setattr(Path, "unlink", paused_unlink)
    with ThreadPoolExecutor(2) as pool:
        delete_future = pool.submit(storage.delete, VALID_CHUNK_ID)
        try:
            assert deleted_data.wait(3)
            put_future = pool.submit(put)
            assert putting.wait(3)
            with pytest.raises(FutureTimeout):
                put_future.result(timeout=0.05)
        finally:
            resume.set()
        delete_future.result(timeout=3)
        assert put_future.result(timeout=3) == "created"
    assert storage.check(VALID_CHUNK_ID) == ("ok", b"new", compute_sha256(b"new"))


def test_inventory_ignores_sidecars_tmp_and_directories():
    data = b"inventory"
    sha = compute_sha256(data)
    storage.put(VALID_CHUNK_ID, data, sha)
    (storage.ROOT / "orphan.tmp").write_bytes(b"junk")
    (storage.ROOT / VALID_CHUNK_ID.replace("_0", "_1")).mkdir()
    legacy_id = VALID_CHUNK_ID + "0"
    (storage.ROOT / legacy_id).write_bytes(data)
    (storage.ROOT / (legacy_id + ".sha256")).write_text(sha, encoding="ascii")
    assert storage.inventory() == [{"chunk_id": VALID_CHUNK_ID, "size": len(data), "sha256": sha}]


def test_inventory_tolerates_disappearing_chunk(monkeypatch):
    storage.put(VALID_CHUNK_ID, b"gone", compute_sha256(b"gone"))
    real_iterdir = Path.iterdir

    def stale_entries(path):
        entries = list(real_iterdir(path))
        storage.delete(VALID_CHUNK_ID)
        return iter(entries)

    monkeypatch.setattr(Path, "iterdir", stale_entries)
    assert storage.inventory() == []


@pytest.mark.parametrize("failed_rename, expected_state", [(1, "missing"), (2, "corrupt")])
def test_interrupted_write_fails_closed_and_can_be_repaired(monkeypatch, failed_rename, expected_state):
    data = b"atomic bytes"
    sha = compute_sha256(data)
    real_replace = os.replace
    calls = 0

    def interrupted_replace(src, dst):
        nonlocal calls
        calls += 1
        if calls == failed_rename:
            raise OSError("injected rename failure")
        real_replace(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "replace", interrupted_replace)
        with pytest.raises(OSError, match="injected"):
            storage.put(VALID_CHUNK_ID, data, sha)
    assert storage.check(VALID_CHUNK_ID)[0] == expected_state
    assert not list(storage.ROOT.glob("*.tmp"))
    assert storage.put(VALID_CHUNK_ID, data, sha) == "created"
    assert storage.check(VALID_CHUNK_ID) == ("ok", data, sha)


def test_retry_finishes_failed_directory_sync(monkeypatch):
    real_sync = storage._fsync_dir
    calls = 0

    def fail_first_sync():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("directory sync failed")
        real_sync()

    monkeypatch.setattr(storage, "_fsync_dir", fail_first_sync)
    data = b"retry commit"
    with pytest.raises(OSError, match="directory sync failed"):
        storage.put(VALID_CHUNK_ID, data, compute_sha256(data))
    assert storage.put(VALID_CHUNK_ID, data, compute_sha256(data)) == "exists"
    assert calls == 2


def test_put_syncs_files_before_directory(monkeypatch):
    synced_directories = []
    real_fsync = os.fsync

    def record_sync(fd):
        synced_directories.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_fsync(fd)

    monkeypatch.setattr(storage.os, "fsync", record_sync)
    storage.put(VALID_CHUNK_ID, b"durable", compute_sha256(b"durable"))
    assert synced_directories == [False, False, True]


@pytest.mark.parametrize("operation", ["put", "check", "delete", "inventory"])
def test_storage_failures_return_json_and_log_context(client, monkeypatch, caplog, operation):
    def fail(*args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(storage, operation, fail)
    url = f"/internal/chunks/{VALID_CHUNK_ID}"
    with caplog.at_level(logging.ERROR, logger="worker"):
        if operation == "put":
            response = client.put(url, headers={"X-Chunk-SHA256": compute_sha256(b"x")}, content=b"x")
        elif operation == "check":
            response = client.get(url)
        elif operation == "delete":
            response = client.delete(url)
        else:
            response = client.get("/internal/workers/worker_test/chunks")
    assert response.status_code == 500
    assert response.json() == {"error": "INTERNAL_ERROR", "message": "worker failed to process request"}
    assert "worker=worker_test" in caplog.text
    if operation != "inventory":
        assert f"chunk={VALID_CHUNK_ID}" in caplog.text


def test_framework_errors_use_json_envelope(client):
    missing = client.get("/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"] == "NOT_FOUND"
    method = client.post(f"/internal/chunks/{VALID_CHUNK_ID}")
    assert method.status_code == 405
    assert method.json()["error"] == "METHOD_NOT_ALLOWED"
    assert "allow" in method.headers


def test_put_does_not_block_health_requests(monkeypatch):
    started, resume = Event(), Event()
    real_put = storage.put

    def slow_put(*args):
        started.set()
        if not resume.wait(3):
            raise RuntimeError("write was not released")
        return real_put(*args)

    monkeypatch.setattr(storage, "put", slow_put)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://worker") as client:
            put_task = asyncio.create_task(client.put(
                f"/internal/chunks/{VALID_CHUNK_ID}", content=b"x",
                headers={"X-Chunk-SHA256": compute_sha256(b"x")},
            ))
            try:
                assert await asyncio.to_thread(started.wait, 3)
                assert not put_task.done()
                response = await asyncio.wait_for(client.get("/health"), timeout=1)
                assert response.status_code == 200
            finally:
                resume.set()
                response = await put_task
            assert response.status_code == 201

    asyncio.run(scenario())


def test_startup_cleans_orphans_and_shutdown_awaits_heartbeat(monkeypatch):
    started, stopped = Event(), Event()
    orphan = storage.ROOT / "abandoned.tmp"
    orphan.write_bytes(b"interrupted write")
    data = b"keep this chunk"
    sha = compute_sha256(data)
    storage.put(VALID_CHUNK_ID, data, sha)

    async def fake_heartbeat():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            stopped.set()

    monkeypatch.setattr(worker_main, "run_heartbeat", fake_heartbeat)
    with TestClient(app) as client:
        assert started.wait(3)
        assert not orphan.exists()
        assert client.get(f"/internal/chunks/{VALID_CHUNK_ID}").content == data
    assert stopped.is_set()
    assert storage.check(VALID_CHUNK_ID) == ("ok", data, sha)


def test_unexpected_heartbeat_exit_is_logged(monkeypatch, caplog):
    async def broken_heartbeat():
        raise RuntimeError("unexpected heartbeat failure")

    monkeypatch.setattr(worker_main, "run_heartbeat", broken_heartbeat)

    async def scenario():
        async with worker_main.lifespan(app):
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR, logger="worker"):
        asyncio.run(scenario())
    assert "HEARTBEAT_STOPPED worker=worker_test" in caplog.text
    assert "unexpected heartbeat failure" in caplog.text


@pytest.mark.parametrize("success_status", [200, 201, 204])
def test_registration_retries_failures_and_accepts_2xx(monkeypatch, caplog, success_status):
    responses = iter([
        httpx.ConnectError("controller offline"), httpx.ReadTimeout("controller slow"),
        RuntimeError("unexpected client error"), httpx.Response(503), httpx.Response(success_status),
    ])
    requests, sleeps = [], []

    def handler(request):
        requests.append(request)
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(heartbeat.asyncio, "sleep", sleep)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await heartbeat.register(client)

    with caplog.at_level(logging.WARNING, logger="worker"):
        asyncio.run(scenario())
    assert len(requests) == 5
    assert sleeps == [2, 2, 2, 2]
    assert all(request.url.path == "/internal/workers/register" for request in requests)
    assert json.loads(requests[-1].content) == {"worker_id": config.WORKER_ID, "base_url": config.BASE_URL}
    assert all("worker=worker_test" in record.message for record in caplog.records if record.name == "worker")


def test_heartbeat_reregisters_and_survives_outages(monkeypatch):
    responses = [
        httpx.Response(201), httpx.Response(404), httpx.Response(503), httpx.Response(204),
        httpx.ReadTimeout("controller slow"), httpx.Response(503), httpx.Response(204),
    ]
    requests, sleeps, clients = [], [], []
    real_client = httpx.AsyncClient

    def handler(request):
        requests.append(request)
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def client_factory(**kwargs):
        client = real_client(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    async def sleep(seconds):
        sleeps.append(seconds)
        if not responses:
            raise asyncio.CancelledError

    monkeypatch.setattr(heartbeat.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(heartbeat.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(heartbeat.run_heartbeat())
    assert [request.url.path.rsplit("/", 1)[1] for request in requests] == [
        "register", "heartbeat", "register", "register", "heartbeat", "heartbeat", "heartbeat",
    ]
    assert sleeps == [config.HEARTBEAT_INTERVAL, 2] + [config.HEARTBEAT_INTERVAL] * 4
    assert all(json.loads(request.content)["worker_id"] == config.WORKER_ID for request in requests)
    assert all(set(request.extensions["timeout"].values()) == {5} for request in requests)
    assert clients[0].is_closed


def test_registration_cancellation_while_controller_is_down(monkeypatch):
    async def cancel_sleep(_):
        raise asyncio.CancelledError

    def handler(request):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(heartbeat.asyncio, "sleep", cancel_sleep)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await heartbeat.register(client)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scenario())


@pytest.mark.parametrize("worker_id", [None, "", "   "])
def test_missing_worker_id_fails_clearly(worker_id):
    env = dict(os.environ)
    env.pop("WORKER_ID", None)
    if worker_id is not None:
        env["WORKER_ID"] = worker_id
    result = subprocess.run(
        [sys.executable, "-B", "-c", "import worker.config"],
        cwd=Path(__file__).resolve().parent.parent, env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "WORKER_ID must be set to a non-empty worker identifier" in result.stderr
