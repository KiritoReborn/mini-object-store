"""Recovery policy with in-memory metadata, a fake clock and HTTPX workers.

These tests never connect to Docker/network services or wait for real timers.
The last tests additionally exercise the real SQLite/placement/lock boundary.
"""
import asyncio
import copy
import hashlib
import inspect
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from controller import recovery
from controller.objects import object_lock


@pytest_asyncio.fixture
async def cluster(monkeypatch):
    clock = SimpleNamespace(now=datetime.now(timezone.utc), tick=100.0)
    state = SimpleNamespace(workers={}, objects={}, replicas={}, data={}, corrupt=set(),
                            faults={}, history=[], transitions=[], bare=False, before=None)

    def workers():
        return [dict(w, chunk_count=sum(wid == w["worker_id"] and value == "HEALTHY"
                                       for (_, wid), value in state.replicas.items()))
                for w in state.workers.values()]

    def replicas(chunk_id):
        rows = []
        for (cid, wid), value in state.replicas.items():
            if cid == chunk_id:
                row = {"worker_id": wid, "state": value}
                if not state.bare:
                    row.update(base_url=state.workers[wid]["base_url"],
                               worker_status=state.workers[wid]["status"],
                               last_heartbeat=state.workers[wid]["last_heartbeat"])
                rows.append(row)
        return rows

    def manifest(oid):
        if oid not in state.objects:
            return None
        obj = copy.deepcopy(state.objects[oid])
        for chunk in obj["chunks"]:
            chunk["replicas"] = replicas(chunk["chunk_id"])
        return obj

    def chunks():
        return [copy.deepcopy(c) for o in state.objects.values() if o["status"] == "READY" for c in o["chunks"]]

    def known():
        return {c["chunk_id"] for o in state.objects.values() if o["status"] in {"UPLOADING", "READY"} for c in o["chunks"]}

    def transition(wid, expected, status):
        if state.workers[wid]["last_heartbeat"] != expected:
            return False
        state.transitions.append((wid, status))
        state.workers[wid]["status"] = status
        return True

    def upsert(cid, wid, status):
        assert any(cid == c["chunk_id"] for o in state.objects.values() for c in o["chunks"]), "missing parent"
        state.replicas[cid, wid] = status

    def set_replica(cid, wid, status):
        if (cid, wid) in state.replicas:
            state.replicas[cid, wid] = status

    for name, function in {
        "get_workers": workers, "get_replicas": replicas,
        "get_object_manifest": manifest, "get_chunks_for_repair": chunks,
        "known_chunk_ids": known, "transition_worker": transition,
        "upsert_replica": upsert, "set_replica_state": set_replica,
        "delete_replica_record": lambda cid, wid: state.replicas.pop((cid, wid), None),
    }.items():
        monkeypatch.setattr(recovery.db, name, function)

    def choose(candidates, excluded, count):
        selected = sorted((w for w in candidates if w["status"] == "ALIVE" and w["worker_id"] not in excluded),
                          key=lambda w: (w["chunk_count"], w["worker_id"]))[:count]
        if len(selected) < count:
            raise recovery.InsufficientWorkers("No target")
        return selected

    monkeypatch.setattr(recovery, "choose_workers", choose)

    def add_worker(wid, status="ALIVE", age=0):
        state.workers[wid] = {"worker_id": wid, "status": status, "base_url": f"http://{wid}:8001",
                              "last_heartbeat": (clock.now - timedelta(seconds=age)).isoformat() if age is not None else None}
        return state.workers[wid]

    def add_chunk(locations=("worker1",), data=b"database verified bytes\x00\xff", status="READY", oid=None):
        oid = oid or str(uuid4())
        obj = state.objects.setdefault(oid, {"object_id": oid, "status": status, "chunks": []})
        index = len(obj["chunks"])
        chunk = {"object_id": oid, "chunk_id": f"{oid}_{index}", "chunk_index": index,
                 "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        obj["chunks"].append(chunk)
        for wid in locations:
            state.replicas[chunk["chunk_id"], wid] = "HEALTHY"
            state.data[wid, chunk["chunk_id"]] = data
        return chunk

    def healthy(chunk):
        return {wid for (cid, wid), value in state.replicas.items() if cid == chunk["chunk_id"]
                and value == "HEALTHY" and state.workers[wid]["status"] == "ALIVE"}

    async def handler(request):
        wid = request.url.host.split("-")[0]
        cid = request.url.path.rsplit("/", 1)[-1]
        inventory = request.url.path.startswith("/internal/workers/")
        state.history.append((request.method, wid, cid))
        expected_timeout = 5 if inventory or request.method == "DELETE" else 10
        assert request.extensions["timeout"]["read"] == expected_timeout
        if state.before is not None:
            result = state.before(request)
            if inspect.isawaitable(result):
                await result
        fault = state.faults.get((request.method, wid, cid), state.faults.get((request.method, wid)))
        if fault is not None:
            if callable(fault):
                fault = fault(request)
                if inspect.isawaitable(fault):
                    fault = await fault
            if isinstance(fault, Exception):
                raise fault
            if fault is not None:
                return fault
        key = wid, cid
        if inventory:
            return httpx.Response(200, json={"worker_id": wid, "chunks": [
                {"chunk_id": chunk_id, "size": len(data), "sha256": None}
                for (worker_id, chunk_id), data in state.data.items() if worker_id == wid]})
        if request.method == "PUT":
            data = request.content
            assert request.headers["X-Chunk-SHA256"] == hashlib.sha256(data).hexdigest()
            assert request.headers["Content-Type"] == "application/octet-stream"
            if key in state.data and key not in state.corrupt and state.data[key] != data:
                return httpx.Response(409, json={"error": "CHUNK_CONFLICT"})
            existed = key in state.data
            state.data[key] = data
            state.corrupt.discard(key)
            return httpx.Response(200 if existed else 201, json={"chunk_id": cid, "size": len(data),
                                                               "sha256": hashlib.sha256(data).hexdigest()})
        if request.method == "DELETE":
            state.data.pop(key, None)
            state.corrupt.discard(key)
            return httpx.Response(204)
        if key not in state.data:
            return httpx.Response(404)
        if key in state.corrupt:
            return httpx.Response(409, json={"error": "CHUNK_CORRUPTED"})
        return httpx.Response(200, content=state.data[key], headers={"X-Chunk-SHA256": "0" * 64})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    runtime = recovery._Runtime(client=client, now=lambda: clock.now, monotonic=lambda: clock.tick,
                                started_at=clock.tick - 30, next_inventory=clock.tick + 60)
    monkeypatch.setattr(recovery, "_runtime", runtime)
    for index in range(1, 5):
        add_worker(f"worker{index}")
    yield SimpleNamespace(state=state, clock=clock, add_worker=add_worker, add_chunk=add_chunk,
                          healthy=healthy, runtime=runtime, client=client)
    await recovery.stop_reconciler()


pytestmark = pytest.mark.asyncio


async def test_case_1_stale_alive_and_joining_workers_die_without_deleting_rows(cluster, caplog):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cluster.add_worker("worker1", age=16)
    cluster.add_worker("worker2", "JOINING", age=16)
    await recovery.detect_dead_workers()
    assert {cluster.state.workers[w]["status"] for w in ("worker1", "worker2")} == {"DEAD"}
    assert len(cluster.state.replicas) == 2
    assert cluster.healthy(chunk) == set()
    assert "WORKER_DEAD worker_id=worker1" in caplog.text


async def test_case_2_dead_replica_is_replaced_on_another_distinct_worker(cluster, caplog):
    caplog.set_level("INFO", logger="recovery")
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cluster.add_worker("worker2", age=16)
    await recovery.run_once()
    assert cluster.state.workers["worker2"]["status"] == "DEAD"
    assert cluster.healthy(chunk) == {"worker1", "worker3"}
    assert cluster.state.data["worker3", chunk["chunk_id"]] == cluster.state.data["worker1", chunk["chunk_id"]]
    assert "REPLICA_REPAIRED" in caplog.text


async def test_case_3_zero_healthy_replicas_never_invents_data(cluster, caplog):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cluster.add_worker("worker1", "DEAD", age=30)
    cluster.add_worker("worker2", "DEAD", age=30)
    before = dict(cluster.state.replicas)
    await recovery.run_once()
    assert cluster.state.replicas == before
    assert not cluster.state.history
    assert "reason=no_verified_source" in caplog.text


async def test_case_4_only_one_alive_worker_has_no_target(cluster, caplog):
    chunk = cluster.add_chunk()
    for wid in ("worker2", "worker3", "worker4"):
        cluster.add_worker(wid, "DEAD", age=30)
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1"}
    assert not any(method == "PUT" for method, _, _ in cluster.state.history)
    assert "reason=no_eligible_target" in caplog.text


async def test_case_5_self_consistent_wrong_replica_is_deleted_before_repair(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cid = chunk["chunk_id"]
    cluster.state.data["worker2", cid] = b"self-consistent wrong file"
    cluster.state.replicas[cid, "worker2"] = "CORRUPT"
    await recovery.run_once()
    assert cluster.state.data["worker2", cid] == cluster.state.data["worker1", cid]
    writes = [method for method, wid, _ in cluster.state.history if wid == "worker2"]
    assert writes == ["DELETE", "PUT", "GET"]
    assert cluster.healthy(chunk) == {"worker1", "worker2"}


async def test_case_6_missing_replica_is_repaired_in_place(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cluster.state.data.pop(("worker2", chunk["chunk_id"]))
    cluster.state.replicas[chunk["chunk_id"], "worker2"] = "MISSING"
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker2"}
    assert ("PUT", "worker2", chunk["chunk_id"]) in cluster.state.history


async def test_case_7_empty_worker_is_promoted_only_after_successful_inventory(cluster, caplog):
    caplog.set_level("INFO", logger="recovery")
    cluster.add_worker("worker1", "JOINING")
    cluster.state.faults["GET", "worker1"] = httpx.ConnectError("offline")
    await recovery.run_once()
    assert cluster.state.workers["worker1"]["status"] == "JOINING"
    cluster.state.faults.clear()
    await recovery.run_once()
    assert cluster.state.workers["worker1"]["status"] == "ALIVE"
    assert "WORKER_ALIVE worker_id=worker1" in caplog.text


async def test_case_8_fresh_dead_worker_passes_through_joining(cluster):
    cluster.add_worker("worker1", "DEAD")
    await recovery.run_once()
    assert cluster.state.transitions == [("worker1", "JOINING"), ("worker1", "ALIVE")]


async def test_case_9_rejoin_handles_orphan_needed_copy_and_missing_record(cluster, caplog):
    caplog.set_level("INFO", logger="recovery")
    cluster.add_worker("worker2", "JOINING")
    needed = cluster.add_chunk(("worker1", "worker2"))
    missing = cluster.add_chunk(("worker1", "worker2"))
    cluster.state.data.pop(("worker2", missing["chunk_id"]))
    orphan = f"{uuid4()}_0"
    cluster.state.data["worker2", orphan] = b"deleted object"
    # Observe the reconciliation outcome before the subsequent repair phase.
    await recovery.reconcile_joining_workers()
    assert ("worker2", orphan) not in cluster.state.data
    assert cluster.healthy(needed) == {"worker1", "worker2"}
    assert cluster.state.replicas[missing["chunk_id"], "worker2"] == "MISSING"
    assert "ORPHAN_DELETED" in caplog.text
    assert "REPLICA_RESTORED" in caplog.text
    assert "REPLICA_MISSING" in caplog.text


async def test_case_10_surplus_is_trimmed_only_after_two_other_bytes_are_verified(cluster, caplog):
    caplog.set_level("INFO", logger="recovery")
    chunk = cluster.add_chunk(("worker1", "worker2", "worker3"))
    cluster.add_worker("worker3", "JOINING")
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker2"}
    assert ("worker3", chunk["chunk_id"]) not in cluster.state.data
    delete = cluster.state.history.index(("DELETE", "worker3", chunk["chunk_id"]))
    assert ("GET", "worker1", chunk["chunk_id"]) in cluster.state.history[:delete]
    assert ("GET", "worker2", chunk["chunk_id"]) in cluster.state.history[:delete]
    assert "SURPLUS_DELETED" in caplog.text


async def test_case_10_forged_other_copy_cannot_authorize_surplus_deletion(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2", "worker3"))
    cluster.add_worker("worker3", "JOINING")
    cluster.state.data["worker2", chunk["chunk_id"]] = b"wrong bytes"
    await recovery.reconcile_joining_workers()
    assert cluster.healthy(chunk) == {"worker1", "worker3"}
    assert ("worker3", chunk["chunk_id"]) in cluster.state.data
    assert cluster.state.replicas[chunk["chunk_id"], "worker2"] == "CORRUPT"


async def test_case_11_pending_delete_retries_unreachable_worker(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2", "worker3"))
    cid = chunk["chunk_id"]
    cluster.state.replicas[cid, "worker3"] = "PENDING_DELETE"
    cluster.state.faults["DELETE", "worker3"] = httpx.ReadTimeout("unreachable")
    await recovery.run_once()
    assert cluster.state.replicas[cid, "worker3"] == "PENDING_DELETE"
    cluster.state.faults.clear()
    await recovery.run_once()
    assert (cid, "worker3") not in cluster.state.replicas
    assert ("worker3", cid) not in cluster.state.data
    assert cluster.healthy(chunk) == {"worker1", "worker2"}


async def test_case_11_pending_copy_is_not_deleted_without_two_verified_others(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cluster.state.replicas[chunk["chunk_id"], "worker2"] = "PENDING_DELETE"
    for wid in ("worker3", "worker4"):
        cluster.add_worker(wid, "DEAD", age=30)
    await recovery.run_once()
    assert ("worker2", chunk["chunk_id"]) in cluster.state.data
    assert not any(method == "DELETE" for method, _, _ in cluster.state.history)


async def test_pending_absent_copies_release_targets_and_restore_two_replicas(cluster):
    chunk = cluster.add_chunk(("worker1", "worker4"))
    cid = chunk["chunk_id"]
    cluster.add_worker("worker4", "DEAD", age=30)
    for wid in ("worker2", "worker3"):
        cluster.state.replicas[cid, wid] = "PENDING_DELETE"

    await recovery.run_once()

    assert cluster.healthy(chunk) == {"worker1", "worker2"}
    assert (cid, "worker3") not in cluster.state.replicas
    assert cluster.state.data["worker2", cid] == cluster.state.data["worker1", cid]
    assert not any(method == "DELETE" for method, _, _ in cluster.state.history)
    assert sum(method == "PUT" for method, _, _ in cluster.state.history) == 1
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker2"}


async def test_pending_verified_copy_is_adopted_without_put_or_delete(cluster, caplog):
    caplog.set_level("INFO", logger="recovery")
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cid = chunk["chunk_id"]
    cluster.state.replicas[cid, "worker2"] = "PENDING_DELETE"

    await recovery.run_once()

    assert cluster.healthy(chunk) == {"worker1", "worker2"}
    assert cluster.state.data["worker2", cid] == cluster.state.data["worker1", cid]
    assert cluster.state.history == [("GET", "worker2", cid)]
    assert "REPLICA_RESTORED" in caplog.text


@pytest.mark.parametrize("bad_copy", ["409", "wrong_size", "wrong_hash"])
async def test_pending_corrupt_copy_is_deleted_before_record_removal(cluster, caplog, bad_copy):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cid = chunk["chunk_id"]
    cluster.state.replicas[cid, "worker2"] = "PENDING_DELETE"
    if bad_copy == "409":
        cluster.state.corrupt.add(("worker2", cid))
    else:
        cluster.state.data["worker2", cid] = b"!" * (chunk["size"] if bad_copy == "wrong_hash" else 1)
    # Leave no verified source so the cleared target is not immediately reused.
    cluster.state.faults["GET", "worker1"] = httpx.ReadTimeout("source unavailable")

    def record_exists_until_delete(request):
        if request.method == "DELETE" and request.url.host == "worker2":
            assert cluster.state.replicas[cid, "worker2"] == "PENDING_DELETE"

    cluster.state.before = record_exists_until_delete
    await recovery.run_once()

    assert ("DELETE", "worker2", cid) in cluster.state.history
    assert ("worker2", cid) not in cluster.state.data
    assert (cid, "worker2") not in cluster.state.replicas
    assert "CHUNK_CORRUPTED" in caplog.text
    assert not any(method == "PUT" for method, _, _ in cluster.state.history)


@pytest.mark.parametrize("failure", ["connection", "timeout", "5xx"])
async def test_pending_unreachable_copy_keeps_bytes_and_record(cluster, failure):
    chunk = cluster.add_chunk(("worker1", "worker2", "worker4"))
    cid = chunk["chunk_id"]
    cluster.state.replicas[cid, "worker2"] = "PENDING_DELETE"
    cluster.state.replicas[cid, "worker3"] = "PENDING_DELETE"
    cluster.add_worker("worker4", "DEAD", age=30)
    faults = {"connection": httpx.ConnectError("offline"), "timeout": httpx.ReadTimeout("slow"),
              "5xx": httpx.Response(503)}
    for wid in ("worker2", "worker3"):
        cluster.state.faults["GET", wid] = faults[failure]
    before_rows, before_data = dict(cluster.state.replicas), dict(cluster.state.data)

    await recovery.run_once()

    assert cluster.state.replicas == before_rows
    assert cluster.state.data == before_data
    assert ("GET", "worker2", cid) in cluster.state.history
    assert ("GET", "worker3", cid) in cluster.state.history
    assert not any(method in {"PUT", "DELETE"} for method, _, _ in cluster.state.history)


async def test_pending_corruption_delete_failure_keeps_record_for_retry(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cid = chunk["chunk_id"]
    cluster.state.replicas[cid, "worker2"] = "PENDING_DELETE"
    cluster.state.corrupt.add(("worker2", cid))
    cluster.state.faults["DELETE", "worker2"] = httpx.Response(503)
    cluster.state.faults["GET", "worker1"] = httpx.ReadTimeout("source unavailable")

    await recovery.run_once()

    assert ("DELETE", "worker2", cid) in cluster.state.history
    assert cluster.state.replicas[cid, "worker2"] == "PENDING_DELETE"
    assert ("worker2", cid) in cluster.state.data


async def test_case_12_ambiguous_put_is_retried_idempotently_without_duplicate_rows(cluster):
    chunk = cluster.add_chunk()
    cid = chunk["chunk_id"]
    for wid in ("worker3", "worker4"):
        cluster.add_worker(wid, "DEAD", age=30)

    def lose_reply(request):
        cluster.state.data["worker2", cid] = request.content
        raise httpx.ReadTimeout("write succeeded, response lost")

    cluster.state.faults["PUT", "worker2"] = lose_reply
    await recovery.run_once()
    assert (cid, "worker2") not in cluster.state.replicas
    cluster.state.faults.clear()
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker2"}
    assert len(cluster.state.replicas) == 2


async def test_case_13_failed_put_uses_next_candidate_and_never_records_health(cluster):
    chunk = cluster.add_chunk()
    cluster.state.faults["PUT", "worker2"] = httpx.ConnectError("offline")
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker3"}
    assert (chunk["chunk_id"], "worker2") not in cluster.state.replicas


@pytest.mark.parametrize("status", ["UPLOADING", "FAILED", "DELETING"])
async def test_case_14_repair_rechecks_ready_state_under_the_object_lock(cluster, monkeypatch, status):
    chunk = cluster.add_chunk()
    monkeypatch.setattr(recovery.db, "get_chunks_for_repair", lambda: [dict(chunk)])
    cluster.state.objects[chunk["object_id"]]["status"] = status
    await recovery.run_once()
    assert cluster.state.history == []
    assert cluster.healthy(chunk) == {"worker1"}


async def test_case_14_uploading_inventory_bytes_are_never_touched(cluster):
    cluster.add_worker("worker2", "JOINING")
    chunk = cluster.add_chunk(("worker2",), status="UPLOADING")
    await recovery.run_once()
    assert ("worker2", chunk["chunk_id"]) in cluster.state.data
    assert cluster.state.history == [("GET", "worker2", "chunks")]


async def test_case_15_never_heartbeated_worker_remains_joining(cluster):
    cluster.add_worker("worker2", "JOINING", age=None)
    await recovery.run_once()
    assert cluster.state.workers["worker2"]["status"] == "JOINING"


async def test_case_16_put_committed_before_controller_crash_is_adopted_by_retry(cluster):
    chunk = cluster.add_chunk()
    cluster.state.data["worker2", chunk["chunk_id"]] = cluster.state.data["worker1", chunk["chunk_id"]]
    await recovery.run_once()
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker2"}
    assert len(cluster.state.replicas) == 2
    assert sum(method == "PUT" for method, _, _ in cluster.state.history) == 1


async def test_case_17_controller_startup_grace_prevents_mass_dead(cluster):
    cluster.runtime.started_at = cluster.clock.tick
    for wid in cluster.state.workers:
        cluster.add_worker(wid, "JOINING", age=30)
    await recovery.run_once()
    assert {w["status"] for w in cluster.state.workers.values()} == {"JOINING"}
    cluster.clock.tick += 15
    await recovery.run_once()
    assert {w["status"] for w in cluster.state.workers.values()} == {"DEAD"}


async def test_case_18_two_dead_copies_remain_unavailable_until_verified_rejoin(cluster, caplog):
    caplog.set_level("INFO", logger="recovery")
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cluster.add_worker("worker1", "DEAD", age=30)
    cluster.add_worker("worker2", "DEAD", age=30)
    await recovery.run_once()
    assert cluster.healthy(chunk) == set()
    cluster.state.workers["worker1"]["last_heartbeat"] = cluster.clock.now.isoformat()
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker3"}
    assert "CHUNK_UNAVAILABLE" in caplog.text and "REPLICA_RESTORED" in caplog.text


async def test_case_19_external_deletion_during_put_removes_fresh_copy(cluster):
    chunk = cluster.add_chunk()
    cid = chunk["chunk_id"]

    def delete_object(request):
        cluster.state.data["worker2", cid] = request.content
        cluster.state.objects.pop(chunk["object_id"])
        cluster.state.replicas.clear()
        return httpx.Response(201)

    cluster.state.faults["PUT", "worker2"] = delete_object
    await recovery.run_once()
    assert ("worker2", cid) not in cluster.state.data
    assert cluster.state.replicas == {}
    assert ("DELETE", "worker2", cid) in cluster.state.history


async def test_case_20_transport_error_is_not_corruption_and_next_source_is_tried(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cluster.state.faults["GET", "worker1"] = httpx.ReadTimeout("paused source")
    data = await recovery._source(chunk)
    assert data == cluster.state.data["worker2", chunk["chunk_id"]]
    assert cluster.state.replicas[chunk["chunk_id"], "worker1"] == "HEALTHY"


async def test_case_20_only_source_unreachable_defers_repair_without_state_changes(cluster):
    chunk = cluster.add_chunk()
    cluster.state.faults["GET", "worker1"] = httpx.ConnectError("offline")
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1"}
    assert not any(method == "PUT" for method, _, _ in cluster.state.history)


async def test_case_21_disk_full_target_is_skipped(cluster):
    chunk = cluster.add_chunk()
    cluster.state.faults["PUT", "worker2"] = httpx.Response(507)
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker3"}
    assert (chunk["chunk_id"], "worker2") not in cluster.state.replicas


@pytest.mark.parametrize("wrong", [b"x", b"!" * len(b"database verified bytes\x00\xff")])
async def test_case_22_wrong_size_or_hash_is_rejected_even_with_matching_worker_hash(cluster, wrong):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cluster.state.faults["GET", "worker1"] = httpx.Response(
        200, content=wrong, headers={"X-Chunk-SHA256": hashlib.sha256(wrong).hexdigest()})
    assert await recovery._source(chunk) == cluster.state.data["worker2", chunk["chunk_id"]]
    assert cluster.state.replicas[chunk["chunk_id"], "worker1"] == "CORRUPT"


async def test_case_23_fast_restart_still_reconciles_as_joining(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2", "worker3"))
    cluster.add_worker("worker3", "JOINING", age=1)
    await recovery.run_once()
    assert cluster.state.workers["worker3"]["status"] == "ALIVE"
    assert cluster.healthy(chunk) == {"worker1", "worker2"}


async def test_case_24_flapping_worker_is_not_promoted_with_aged_heartbeat(cluster):
    cluster.add_worker("worker2", "JOINING")

    def age_during_inventory(request):
        if request.url.path.endswith("/chunks"):
            cluster.clock.now += timedelta(seconds=16)

    cluster.state.before = age_during_inventory
    await recovery.reconcile_joining_workers()
    assert cluster.state.workers["worker2"]["status"] == "JOINING"


async def test_case_25_each_request_resolves_the_current_database_origin(cluster):
    chunk = cluster.add_chunk()
    origins = []

    def move_after_put(request):
        origins.append(request.url.host)
        if request.method == "PUT":
            cluster.state.workers["worker2"]["base_url"] = "http://worker2-new:8001"

    cluster.state.before = move_after_put
    await recovery.run_once()
    assert "worker2" in origins and "worker2-new" in origins
    assert cluster.healthy(chunk) == {"worker1", "worker2"}


async def test_case_26_restart_rejoin_adopts_unrecorded_verified_copy(cluster):
    chunk = cluster.add_chunk()
    cluster.state.data["worker2", chunk["chunk_id"]] = cluster.state.data["worker1", chunk["chunk_id"]]
    cluster.add_worker("worker2", "JOINING")
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker2"}
    assert not any(method == "PUT" for method, _, _ in cluster.state.history)


async def test_case_27_overlapping_passes_and_many_chunks_remain_sequential(cluster):
    chunks = [cluster.add_chunk() for _ in range(8)]
    active = peak = 0

    async def observe(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1

    cluster.state.before = observe
    await asyncio.gather(recovery.run_once(), recovery.run_once())
    assert peak == 1
    assert all(len(cluster.healthy(c)) == 2 for c in chunks)
    assert sum(method == "PUT" for method, _, _ in cluster.state.history) == 8


async def test_case_28_unavailable_and_no_target_logs_are_throttled(cluster, caplog):
    unavailable = cluster.add_chunk(("worker2",))
    no_target = cluster.add_chunk()
    for wid in ("worker2", "worker3", "worker4"):
        cluster.add_worker(wid, "DEAD", age=30)
    await recovery.run_once()
    await recovery.run_once()
    assert sum(r.message.startswith("CHUNK_UNAVAILABLE") for r in caplog.records) == 2
    cluster.clock.tick += 60
    await recovery.run_once()
    assert sum(r.message.startswith("CHUNK_UNAVAILABLE") for r in caplog.records) == 4
    assert cluster.healthy(unavailable) == set() and cluster.healthy(no_target) == {"worker1"}


async def test_case_29_only_controller_stamped_heartbeat_decides_liveness(cluster):
    cluster.add_worker("worker2", "JOINING", age=30)
    cluster.state.faults["GET", "worker2"] = httpx.Response(200, json={
        "worker_id": "worker2", "last_heartbeat": "2999-01-01T00:00:00Z", "chunks": []})
    await recovery.run_once()
    assert cluster.state.workers["worker2"]["status"] == "DEAD"
    assert not cluster.state.history


async def test_case_30_large_inventory_completes_before_worker_promotion(cluster):
    cluster.add_worker("worker2", "JOINING")
    for _ in range(40):
        cluster.add_chunk(("worker1", "worker2"))

    def assert_joining(request):
        if request.url.host == "worker2":
            assert cluster.state.workers["worker2"]["status"] == "JOINING"

    cluster.state.before = assert_joining
    await recovery.reconcile_joining_workers()
    assert cluster.state.workers["worker2"]["status"] == "ALIVE"
    assert sum(method == "GET" and wid == "worker2" for method, wid, _ in cluster.state.history) == 41


async def test_bad_worker_and_chunk_exceptions_do_not_stop_the_pass(cluster, monkeypatch, caplog):
    cluster.add_worker("worker1", "JOINING")
    cluster.add_worker("worker2", "JOINING")
    broken = cluster.add_chunk(("worker3",))
    good = cluster.add_chunk(("worker3",))
    real_reconcile, real_repair = recovery._reconcile_worker, recovery.repair_chunk

    async def reconcile(worker, **kwargs):
        if worker["worker_id"] == "worker1":
            raise RuntimeError("bad worker")
        await real_reconcile(worker, **kwargs)

    async def repair(chunk):
        if chunk["chunk_id"] == broken["chunk_id"]:
            raise RuntimeError("bad chunk")
        await real_repair(chunk)

    monkeypatch.setattr(recovery, "_reconcile_worker", reconcile)
    monkeypatch.setattr(recovery, "repair_chunk", repair)
    await recovery.run_once()
    assert cluster.state.workers["worker2"]["status"] == "ALIVE"
    assert len(cluster.healthy(good)) == 2
    assert "WORKER_RECONCILE_FAILED" in caplog.text and "CHUNK_REPAIR_FAILED" in caplog.text


async def test_start_and_stop_create_one_task_and_drain_request_cancellation(cluster):
    entered, cancelled = asyncio.Event(), asyncio.Event()
    cluster.add_chunk()

    async def block(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    cluster.state.before = block
    assert recovery.start_reconciler() is None
    task = cluster.runtime.task
    recovery.start_reconciler()
    assert cluster.runtime.task is task
    await asyncio.wait_for(entered.wait(), 2)
    await recovery.stop_reconciler()
    assert task.cancelled() and cancelled.is_set()
    assert cluster.client.is_closed and cluster.runtime.task is None
    await recovery.stop_reconciler()


async def test_phase_exception_and_loop_exception_are_isolated(cluster, monkeypatch, caplog):
    repaired = asyncio.Event()

    async def fail():
        raise RuntimeError("phase failure")

    async def finish():
        repaired.set()

    monkeypatch.setattr(recovery, "detect_dead_workers", fail)
    monkeypatch.setattr(recovery, "repair_pass", finish)
    await recovery.run_once()
    assert repaired.is_set() and "RECONCILE_PHASE_FAILED" in caplog.text
    calls = []

    async def pass_then_cancel():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("pass failure")
        raise asyncio.CancelledError

    monkeypatch.setattr(recovery, "run_once", pass_then_cancel)
    monkeypatch.setattr(recovery, "RECONCILE_INTERVAL", 0)
    with pytest.raises(asyncio.CancelledError):
        await recovery._loop()
    assert len(calls) == 2 and "RECONCILE_PASS_FAILED" in caplog.text


async def test_bare_replica_adapter_and_empty_placement_result(cluster, monkeypatch):
    chunk = cluster.add_chunk()
    cluster.state.bare = True
    monkeypatch.setattr(recovery, "choose_workers", lambda *args: [])
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1"}
    assert not any(method == "PUT" for method, _, _ in cluster.state.history)


@pytest.mark.parametrize("timestamp", ["not-a-date", "2999-01-01T00:00:00+00:00"])
async def test_invalid_or_future_heartbeat_never_grants_eligibility(cluster, timestamp):
    worker = cluster.add_worker("worker2", "JOINING")
    worker["last_heartbeat"] = timestamp
    await recovery.run_once()
    assert worker["status"] == "JOINING"


async def test_naive_heartbeat_is_interpreted_as_utc(cluster):
    worker = cluster.add_worker("worker2", "JOINING")
    worker["last_heartbeat"] = cluster.clock.now.replace(tzinfo=None).isoformat()
    await recovery.run_once()
    assert worker["status"] == "ALIVE"


async def test_stale_state_compare_and_set_cannot_overwrite_fresh_heartbeat(cluster, monkeypatch):
    worker = cluster.add_worker("worker2", age=30)
    transition = recovery.db.transition_worker

    def race(wid, expected, status):
        worker["last_heartbeat"] = cluster.clock.now.isoformat()
        return transition(wid, expected, status)

    monkeypatch.setattr(recovery.db, "transition_worker", race)
    await recovery.detect_dead_workers()
    assert worker["status"] == "ALIVE"


@pytest.mark.parametrize("fault", [httpx.Response(500), RuntimeError("unexpected worker error")])
async def test_inventory_failure_keeps_worker_joining(cluster, fault):
    cluster.add_worker("worker2", "JOINING")
    cluster.state.faults["GET", "worker2"] = fault
    await recovery.run_once()
    assert cluster.state.workers["worker2"]["status"] == "JOINING"


@pytest.mark.parametrize("payload", [{"worker_id": "wrong", "chunks": []},
                                    {"worker_id": "worker2", "chunks": [{"chunk_id": "../unsafe"}]},
                                    {"worker_id": "worker2", "chunks": "bad"}])
async def test_malformed_inventory_never_promotes_or_deletes(cluster, payload):
    cluster.add_worker("worker2", "JOINING")
    cluster.state.faults["GET", "worker2"] = httpx.Response(200, json=payload)
    await recovery.run_once()
    assert cluster.state.workers["worker2"]["status"] == "JOINING"
    assert not any(method == "DELETE" for method, _, _ in cluster.state.history)


async def test_corrupt_worker_repair_failure_uses_spare_and_removes_bad_record(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cluster.state.replicas[chunk["chunk_id"], "worker2"] = "CORRUPT"
    cluster.state.faults["PUT", "worker2"] = httpx.Response(503)
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker3"}
    assert (chunk["chunk_id"], "worker2") not in cluster.state.replicas


async def test_successful_put_with_wrong_readback_is_not_recorded_healthy(cluster):
    chunk = cluster.add_chunk()
    cluster.state.faults["GET", "worker2"] = httpx.Response(200, content=b"wrong")
    await recovery.run_once()
    assert cluster.healthy(chunk) == {"worker1", "worker3"}
    assert (chunk["chunk_id"], "worker2") not in cluster.state.replicas


async def test_periodic_live_inventory_collects_late_orphan_and_surplus(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cid = chunk["chunk_id"]
    cluster.state.data["worker3", cid] = cluster.state.data["worker1", cid]
    orphan = f"{uuid4()}_0"
    cluster.state.data["worker3", orphan] = b"late write after rollback"
    cluster.runtime.next_inventory = cluster.clock.tick
    await recovery.run_once()
    assert ("worker3", orphan) not in cluster.state.data
    assert ("worker3", cid) not in cluster.state.data
    assert cluster.healthy(chunk) == {"worker1", "worker2"}
    assert ("GET", "worker1", cid) in cluster.state.history  # Verifies before trimming.


async def test_recovery_waits_for_upload_lock_and_rereads_before_orphan_deletion(cluster):
    cluster.add_worker("worker2", "JOINING")
    oid = str(uuid4())
    cid = f"{oid}_0"
    cluster.state.data["worker2", cid] = b"upload in progress"
    entered = asyncio.Event()

    async def reconcile():
        entered.set()
        await recovery.run_once()

    async with object_lock(oid):
        task = asyncio.create_task(reconcile())
        await entered.wait()
        await asyncio.sleep(0)
        assert not task.done()
        cluster.add_chunk(("worker2",), data=b"upload in progress", status="UPLOADING", oid=oid)
    await task
    assert ("worker2", cid) in cluster.state.data
    assert not any(method == "DELETE" for method, _, _ in cluster.state.history)


async def test_public_delete_waits_for_repair_and_observes_its_new_replica(cluster):
    chunk = cluster.add_chunk()
    entered, release = asyncio.Event(), asyncio.Event()

    async def block_put(request):
        if request.method == "PUT":
            entered.set()
            await release.wait()

    cluster.state.before = block_put
    task = asyncio.create_task(recovery.run_once())
    await asyncio.wait_for(entered.wait(), 2)
    seen = []

    async def delete():
        async with object_lock(chunk["object_id"]):
            seen.append(cluster.healthy(chunk))

    deleting = asyncio.create_task(delete())
    await asyncio.sleep(0)
    assert not deleting.done()
    release.set()
    await asyncio.gather(task, deleting)
    assert seen == [{"worker1", "worker2"}]


async def test_bad_surplus_record_is_removed_when_two_verified_copies_remain(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2", "worker3"))
    cid = chunk["chunk_id"]
    cluster.state.replicas[cid, "worker3"] = "CORRUPT"
    await recovery.run_once()
    assert (cid, "worker3") not in cluster.state.replicas
    assert ("worker3", cid) not in cluster.state.data
    assert cluster.healthy(chunk) == {"worker1", "worker2"}


async def test_live_inventory_does_not_protect_failed_object_healthy_rows(cluster):
    chunk = cluster.add_chunk(status="FAILED")
    cluster.runtime.next_inventory = cluster.clock.tick
    await recovery.run_once()
    assert ("worker1", chunk["chunk_id"]) not in cluster.state.data
    assert (chunk["chunk_id"], "worker1") not in cluster.state.replicas


async def test_missing_inventory_row_exception_does_not_skip_other_chunks(cluster, monkeypatch):
    cluster.add_worker("worker2", "JOINING")
    broken = cluster.add_chunk(("worker1", "worker2"))
    good = cluster.add_chunk(("worker1", "worker2"))
    for c in (broken, good):
        cluster.state.data.pop(("worker2", c["chunk_id"]))
    mark = recovery._mark_bad

    async def fail_one(chunk, *args, **kwargs):
        if chunk["chunk_id"] == broken["chunk_id"]:
            raise RuntimeError("one damaged metadata row")
        return await mark(chunk, *args, **kwargs)

    monkeypatch.setattr(recovery, "_mark_bad", fail_one)
    await recovery.reconcile_joining_workers()
    assert cluster.state.replicas[good["chunk_id"], "worker2"] == "MISSING"
    assert cluster.state.workers["worker2"]["status"] == "JOINING"


async def test_joining_worker_chunk_timeout_does_not_skip_the_remaining_inventory(cluster):
    cluster.add_worker("worker2", "JOINING")
    unavailable = cluster.add_chunk(("worker1", "worker2"))
    good = cluster.add_chunk(("worker1", "worker2"))
    cluster.state.faults["GET", "worker2", unavailable["chunk_id"]] = httpx.ReadTimeout("slow chunk")
    await recovery.reconcile_joining_workers()
    assert ("GET", "worker2", good["chunk_id"]) in cluster.state.history
    assert cluster.state.workers["worker2"]["status"] == "JOINING"


@pytest.mark.parametrize("status,state", [(404, "MISSING"), (409, "CORRUPT")])
async def test_joining_worker_missing_or_corrupt_bytes_are_deleted_and_classified(cluster, status, state):
    cluster.add_worker("worker2", "JOINING")
    chunk = cluster.add_chunk(("worker1", "worker2"))
    cid = chunk["chunk_id"]
    cluster.state.faults["GET", "worker2", cid] = httpx.Response(status)
    await recovery.reconcile_joining_workers()
    assert cluster.state.replicas[cid, "worker2"] == state
    assert ("worker2", cid) not in cluster.state.data


async def test_interrupted_source_stream_is_closed_and_not_mislabeled_corrupt(cluster):
    chunk = cluster.add_chunk(("worker1", "worker2"))
    closed = []

    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            raise httpx.ReadTimeout("connection interrupted during body")

        async def aclose(self):
            closed.append(True)

    cluster.state.faults["GET", "worker1"] = httpx.Response(200, stream=InterruptedStream())
    assert await recovery._source(chunk) == cluster.state.data["worker2", chunk["chunk_id"]]
    assert cluster.state.replicas[chunk["chunk_id"], "worker1"] == "HEALTHY"
    assert closed == [True]


async def test_cancellation_drains_metadata_mutation_before_releasing_object_lock(cluster, monkeypatch):
    chunk = cluster.add_chunk()
    entered, release, finished = Event(), Event(), Event()
    upsert = recovery.db.upsert_replica

    def paused_upsert(*args):
        entered.set()
        assert release.wait(3)
        upsert(*args)
        finished.set()

    monkeypatch.setattr(recovery.db, "upsert_replica", paused_upsert)
    task = asyncio.create_task(recovery.run_once())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()

        async def probe_lock():
            async with object_lock(chunk["object_id"]):
                assert finished.is_set()

        probe = asyncio.create_task(probe_lock())
        await asyncio.sleep(0)
        assert not probe.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await probe
        assert cluster.healthy(chunk) == {"worker1", "worker2"}
    finally:
        release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def test_deleted_chunks_do_not_leak_log_throttle_entries(cluster):
    chunk = cluster.add_chunk(("worker1",))
    cluster.add_worker("worker1", "DEAD", age=30)
    await recovery.run_once()
    assert chunk["chunk_id"] in cluster.runtime.notices
    cluster.state.objects.clear()
    await recovery.run_once()
    assert not cluster.runtime.notices


async def test_real_sqlite_controller_uses_production_recovery_for_admission_and_repair(tmp_path, monkeypatch):
    from controller import config, database as db, main

    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    data, offline, history = {}, set(), []

    def worker(request):
        wid, cid = request.url.host, request.url.path.rsplit("/", 1)[-1]
        key = wid, cid
        history.append((request.method, wid, cid))
        if wid in offline:
            raise httpx.ConnectError("worker stopped", request=request)
        if request.url.path.startswith("/internal/workers/"):
            return httpx.Response(200, json={"worker_id": wid, "chunks": [
                {"chunk_id": chunk_id, "size": len(value), "sha256": None}
                for (worker_id, chunk_id), value in data.items() if worker_id == wid]})
        if request.method == "DELETE":
            data.pop(key, None)
            return httpx.Response(204)
        if request.method == "PUT":
            if key in data and data[key] != request.content:
                return httpx.Response(409)
            existed = key in data
            data[key] = request.content
            return httpx.Response(200 if existed else 201, json={"chunk_id": cid, "size": len(request.content),
                                                               "sha256": hashlib.sha256(request.content).hexdigest()})
        if key not in data:
            return httpx.Response(404)
        return httpx.Response(200, content=data[key], headers={"X-Chunk-SHA256": hashlib.sha256(data[key]).hexdigest()})

    transport = httpx.MockTransport(worker)
    tick = [100.0]
    runtime = recovery._Runtime(client=httpx.AsyncClient(transport=transport), monotonic=lambda: tick[0])
    monkeypatch.setattr(recovery, "_runtime", runtime)
    app = main.create_app(worker_transport=transport)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://testserver") as client:
            for i in range(1, 5):
                wid = f"worker{i}"
                response = await client.post("/internal/workers/register", json={"worker_id": wid, "base_url": f"http://{wid}:8001"})
                assert response.status_code == 200
            await recovery.run_once()
            assert {w["status"] for w in db.get_workers()} == {"ALIVE"}
            assert (await client.get("/health")).json()["recovery_available"] is True
            original = (bytes(range(256)) * 19_532)[:5_000_001]
            uploaded = await client.post("/api/v1/objects", files={"file": ("recovery.bin", original)})
            assert uploaded.status_code == 201, uploaded.text
            oid = uploaded.json()["object_id"]
            assert uploaded.json()["num_chunks"] == 6
            assert db.get_object_manifest(oid)["chunks"][-1]["size"] == 1
            offline.add("worker2")
            with db.connection() as conn:
                conn.execute("UPDATE workers SET last_heartbeat=? WHERE worker_id='worker2'",
                             ((datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),))
            tick[0] += 20
            await recovery.run_once()
            assert next(w for w in db.get_workers() if w["worker_id"] == "worker2")["status"] == "DEAD"
            for chunk in db.get_object_manifest(oid)["chunks"]:
                assert len([r for r in chunk["replicas"] if r["state"] == "HEALTHY" and r["worker_status"] == "ALIVE"]) == 2
            assert (await client.get(f"/api/v1/objects/{oid}")).content == original
            offline.clear()
            await client.post("/internal/workers/register", json={"worker_id": "worker2", "base_url": "http://worker2:8001"})
            await recovery.run_once()
            for chunk in db.get_object_manifest(oid)["chunks"]:
                assert len([1 for (_, cid) in data if cid == chunk["chunk_id"]]) == 2
            # The worker claims a self-consistent hash for wrong bytes. A rejects
            # them against SQLite; B must DELETE before its verified rewrite.
            chunk = db.get_object_manifest(oid)["chunks"][0]
            wid = sorted(r["worker_id"] for r in chunk["replicas"] if r["state"] == "HEALTHY")[0]
            data[wid, chunk["chunk_id"]] = b"!" * chunk["size"]
            assert (await client.get(f"/api/v1/objects/{oid}")).content == original
            assert next(r for r in db.get_replicas(chunk["chunk_id"]) if r["worker_id"] == wid)["state"] == "CORRUPT"
            history.clear()
            await recovery.run_once()
            assert next(r for r in db.get_replicas(chunk["chunk_id"]) if r["worker_id"] == wid)["state"] == "HEALTHY"
            assert history.index(("DELETE", wid, chunk["chunk_id"])) < history.index(("PUT", wid, chunk["chunk_id"]))
            assert (await client.get(f"/api/v1/objects/{oid}")).content == original
    assert runtime.client is None and runtime.task is None
