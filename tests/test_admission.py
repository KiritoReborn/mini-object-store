"""Real SQLite and production recovery: registration must fence inventory admission."""
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def admission(tmp_path, monkeypatch):
    from controller import config, database as db, recovery

    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    db.init_db()
    for wid in ("worker1", "worker2"):
        db.register_worker(wid, f"http://{wid}:8001")
    db.set_worker_state("worker1", "ALIVE")
    oid = str(uuid4())
    db.create_object(oid, "admission.bin", "application/octet-stream", {})
    chunks = []
    data = {}
    for index in range(2):
        cid, body = f"{oid}_{index}", f"chunk-{index}".encode()
        db.add_chunk(cid, oid, index, len(body), hashlib.sha256(body).hexdigest())
        chunks.append(cid)
        for wid in ("worker1", "worker2"):
            data[wid, cid] = body
            db.upsert_replica(cid, wid, "HEALTHY")
    db.set_object_state(oid, "READY")
    hook = [None]

    def worker(request):
        wid, cid = request.url.host, request.url.path.rsplit("/", 1)[-1]
        if request.url.path.startswith("/internal/workers/"):
            return httpx.Response(200, json={"worker_id": wid, "chunks": [
                {"chunk_id": chunk_id} for worker_id, chunk_id in data if worker_id == wid]})
        if hook[0] is not None:
            hook[0](request)
        if request.method == "DELETE":
            data.pop((wid, cid), None)
            return httpx.Response(204)
        if request.method == "PUT":
            data[wid, cid] = request.content
            return httpx.Response(201)
        return httpx.Response(200, content=data[wid, cid]) if (wid, cid) in data else httpx.Response(404)

    runtime = recovery._Runtime(client=httpx.AsyncClient(transport=httpx.MockTransport(worker)))
    monkeypatch.setattr(recovery, "_runtime", runtime)
    try:
        yield SimpleNamespace(db=db, recovery=recovery, chunks=chunks, data=data, hook=hook)
    finally:
        await recovery.stop_reconciler()


@pytest.mark.asyncio
async def test_restart_during_inventory_cannot_promote_an_old_inventory(admission):
    state = admission
    restarted = False

    def restart(request):
        nonlocal restarted
        if not restarted and request.url.host == "worker2" and request.url.path.endswith(state.chunks[1]):
            restarted = True
            state.db.register_worker("worker2", "http://worker2:8001")
            state.data.pop(("worker2", state.chunks[0]))

    state.hook[0] = restart
    worker = next(w for w in state.db.get_workers() if w["worker_id"] == "worker2")
    await state.recovery._reconcile_worker(worker, joining=True)
    assert restarted
    assert next(w for w in state.db.get_workers() if w["worker_id"] == "worker2")["status"] == "JOINING"
    current = next(w for w in state.db.get_workers() if w["worker_id"] == "worker2")
    await state.recovery._reconcile_worker(current, joining=True)
    assert next(w for w in state.db.get_workers() if w["worker_id"] == "worker2")["status"] == "ALIVE"
    await state.recovery.repair_pass()
    assert state.data["worker2", state.chunks[0]] == state.data["worker1", state.chunks[0]]


@pytest.mark.asyncio
async def test_heartbeats_during_inventory_do_not_prevent_admission(admission):
    state = admission
    state.hook[0] = lambda request: state.db.touch_heartbeat("worker2")
    worker = next(w for w in state.db.get_workers() if w["worker_id"] == "worker2")
    await state.recovery._reconcile_worker(worker, joining=True)
    assert next(w for w in state.db.get_workers() if w["worker_id"] == "worker2")["status"] == "ALIVE"


@pytest.mark.asyncio
async def test_admission_commit_atomically_checks_the_registration(admission):
    db = admission.db
    token = db.get_worker_registration("worker2")
    db.register_worker("worker2", "http://worker2:8001")
    latest = next(w for w in db.get_workers() if w["worker_id"] == "worker2")
    assert db.get_worker_registration("worker2") != token
    assert db.complete_worker_admission("worker2", latest["last_heartbeat"], token) is False
    assert next(w for w in db.get_workers() if w["worker_id"] == "worker2")["status"] == "JOINING"
