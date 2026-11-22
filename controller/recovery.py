"""Sequential, DB-verified recovery for the single controller process.

Object locks span worker mutations, never SQLite transactions. A successful
write is read back before it becomes HEALTHY; inventory hashes are only hints.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import anyio
import httpx
from fastapi.concurrency import run_in_threadpool

from . import database as db
from .objects import object_lock
from .placement import InsufficientWorkers, choose_workers

try:
    from .config import CHUNK_SIZE, RECONCILE_INTERVAL, REPLICATION_FACTOR, WORKER_DEAD_TIMEOUT
except ImportError:
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000000"))
    REPLICATION_FACTOR = int(os.getenv("REPLICATION_FACTOR", "2"))
    WORKER_DEAD_TIMEOUT = float(os.getenv("WORKER_DEAD_TIMEOUT", "15"))
    RECONCILE_INTERVAL = float(os.getenv("RECONCILE_INTERVAL", "5"))

log = logging.getLogger("recovery")
_CHUNK_ID = re.compile(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})_(0|[1-9][0-9]*)\Z")
_INVENTORY_INTERVAL = 60.0


@dataclass
class _Runtime:
    """One loop/client, with replaceable clocks and transport for deterministic tests."""

    client: httpx.AsyncClient | None = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    monotonic: Callable[[], float] = time.monotonic
    started_at: float | None = None
    next_inventory: float | None = None
    task: asyncio.Task | None = None
    pass_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    notices: dict[str, tuple[str, float]] = field(default_factory=dict)


_runtime = _Runtime()


async def _db(function: Callable[..., Any], *args: Any) -> Any:
    """Drain an in-flight DB call before cancellation releases the object lock."""
    task = asyncio.create_task(run_in_threadpool(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled() and task.exception() is not None:
                log.error("DB_DRAIN_FAILED operation=%s", function.__name__, exc_info=task.exception())
        raise


def _parse_ts(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return None if parsed.utcoffset() is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _fresh(worker: dict) -> bool:
    timestamp = _parse_ts(worker.get("last_heartbeat"))
    return timestamp is not None and 0 <= (_runtime.now() - timestamp).total_seconds() < WORKER_DEAD_TIMEOUT


async def _worker(worker_id: str) -> dict | None:
    return next((w for w in await _db(db.get_workers) if w["worker_id"] == worker_id), None)


async def _replicas_with_workers(chunk_id: str) -> list[dict]:
    """Normalize legacy bare replicas and A's worker_status join using current workers."""
    workers = {w["worker_id"]: w for w in await _db(db.get_workers)}
    rows = await _db(db.get_replicas, chunk_id)
    return [{**row, "base_url": workers[row["worker_id"]]["base_url"],
             "worker_status": workers[row["worker_id"]]["status"],
             "last_heartbeat": workers[row["worker_id"]].get("last_heartbeat")}
            for row in rows if row["worker_id"] in workers]


async def _healthy(chunk: dict, excluded: set[str] | None = None) -> list[dict]:
    rows = await _replicas_with_workers(chunk["chunk_id"])
    distinct = {r["worker_id"]: r for r in rows if r["state"] == "HEALTHY"
                and r["worker_status"] == "ALIVE" and _fresh(r)
                and r["worker_id"] not in (excluded or set())}
    return list(distinct.values())


async def _ready_chunk(object_id: str, chunk_id: str) -> dict | None:
    manifest = await _db(db.get_object_manifest, object_id)
    if manifest is None or manifest["status"] != "READY":
        return None
    return next((c for c in manifest["chunks"] if c["chunk_id"] == chunk_id), None)


async def _transition(worker: dict, state: str) -> bool:
    # Frozen CAS helper: a newer registration/heartbeat invalidates stale decisions.
    return await _db(db.transition_worker, worker["worker_id"], worker["last_heartbeat"], state)


def _notice(chunk: dict, reason: str) -> None:
    key, now = chunk["chunk_id"], _runtime.monotonic()
    previous = _runtime.notices.get(key)
    if previous is None or previous[0] != reason or now - previous[1] >= 60:
        log.warning("CHUNK_UNAVAILABLE object_id=%s chunk_id=%s reason=%s", chunk["object_id"], key, reason)
        _runtime.notices[key] = (reason, now)


async def _request(method: str, worker_id: str, path: str, *, timeout: float, **kwargs: Any) -> httpx.Response | None:
    try:
        worker = await _worker(worker_id)  # Never retain an origin across requests.
        if worker is None:
            return None
        assert _runtime.client is not None
        return await _runtime.client.request(method, worker["base_url"].rstrip("/") + path,
                                             timeout=timeout, **kwargs)
    except httpx.HTTPError:
        log.warning("WORKER_REQUEST_FAILED worker_id=%s method=%s path=%s", worker_id, method, path)
    except Exception:
        log.exception("WORKER_REQUEST_FAILED worker_id=%s method=%s path=%s", worker_id, method, path)
    return None


async def _delete_chunk(worker_id: str, chunk_id: str) -> bool:
    response = await _request("DELETE", worker_id, f"/internal/chunks/{chunk_id}", timeout=5)
    return response is not None and response.status_code == 204


async def _get_inventory(worker_id: str) -> set[str] | None:
    response = await _request("GET", worker_id, f"/internal/workers/{worker_id}/chunks", timeout=5)
    if response is None or response.status_code != 200:
        return None
    try:
        payload = response.json()
        if payload["worker_id"] != worker_id or not isinstance(payload["chunks"], list):
            raise ValueError("Invalid inventory envelope")
        chunks = [entry["chunk_id"] for entry in payload["chunks"]]
        if any(not isinstance(cid, str) or _CHUNK_ID.fullmatch(cid) is None for cid in chunks):
            raise ValueError("Invalid inventory chunk ID")
        return set(chunks)
    except Exception:
        log.exception("INVENTORY_INVALID worker_id=%s", worker_id)
        return None


@dataclass(frozen=True)
class _Read:
    data: bytes | None = None
    state: str | None = None  # None with no data means transport/service failure.


async def _fetch_verified(worker_id: str, chunk: dict) -> _Read:
    try:
        worker = await _worker(worker_id)
        if worker is None:
            return _Read()
        assert _runtime.client is not None
        async with _runtime.client.stream("GET", f'{worker["base_url"].rstrip("/")}/internal/chunks/{chunk["chunk_id"]}',
                                          timeout=10) as response:
            if response.status_code in {404, 409}:
                return _Read(state="MISSING" if response.status_code == 404 else "CORRUPT")
            if response.status_code != 200:
                return _Read()
            # Bound memory even if a broken worker streams an oversized body.
            if not 0 <= chunk["size"] <= CHUNK_SIZE:
                raise ValueError("Invalid authoritative chunk size")
            data = bytearray()
            async for part in response.aiter_bytes(chunk_size=65_536):
                data.extend(part[:max(0, chunk["size"] + 1 - len(data))])
                if len(data) > chunk["size"]:
                    return _Read(state="CORRUPT")
            if len(data) != chunk["size"] or hashlib.sha256(data).hexdigest() != chunk["sha256"]:
                return _Read(state="CORRUPT")
            return _Read(data=bytes(data))
    except httpx.HTTPError:
        log.warning("READ_UNAVAILABLE object_id=%s chunk_id=%s worker_id=%s",
                    chunk["object_id"], chunk["chunk_id"], worker_id)
    except Exception:
        log.exception("READ_FAILED object_id=%s chunk_id=%s worker_id=%s",
                      chunk["object_id"], chunk["chunk_id"], worker_id)
    return _Read()


async def _mark_bad(chunk: dict, worker_id: str, state: str, *, insert: bool = False) -> None:
    rows = await _db(db.get_replicas, chunk["chunk_id"])
    previous = next((r["state"] for r in rows if r["worker_id"] == worker_id), None)
    if previous == state:
        return
    await _db(db.upsert_replica if insert else db.set_replica_state, chunk["chunk_id"], worker_id, state)
    log.warning("%s object_id=%s chunk_id=%s worker_id=%s",
                "CHUNK_CORRUPTED" if state == "CORRUPT" else "REPLICA_MISSING",
                chunk["object_id"], chunk["chunk_id"], worker_id)


async def _source(chunk: dict, excluded: set[str] | None = None) -> bytes | None:
    for replica in await _healthy(chunk, excluded):
        result = await _fetch_verified(replica["worker_id"], chunk)
        if result.data is not None:
            return result.data
        if result.state:
            await _mark_bad(chunk, replica["worker_id"], result.state)
    return None


async def _two_verified_others(chunk: dict, worker_id: str) -> bool:
    """Do not delete surplus on the strength of DB state or sidecar hints alone."""
    verified = set()
    for replica in await _healthy(chunk, {worker_id}):
        result = await _fetch_verified(replica["worker_id"], chunk)
        if result.data is not None:
            verified.add(replica["worker_id"])
        elif result.state:
            await _mark_bad(chunk, replica["worker_id"], result.state)
        if len(verified) == REPLICATION_FACTOR:
            current = {r["worker_id"] for r in await _healthy(chunk, {worker_id})}
            return verified <= current
    return False


async def detect_dead_workers() -> None:
    for worker in await _db(db.get_workers):
        try:
            if worker["status"] == "DEAD" and _fresh(worker):
                if await _transition(worker, "JOINING"):
                    log.info("WORKER_JOINING worker_id=%s", worker["worker_id"])
            elif worker["status"] in {"ALIVE", "JOINING"}:
                timestamp = _parse_ts(worker.get("last_heartbeat"))
                age = (_runtime.now() - timestamp).total_seconds() if timestamp else None
                grace = _runtime.started_at is None or _runtime.monotonic() - _runtime.started_at < WORKER_DEAD_TIMEOUT
                if not grace and age is not None and age >= WORKER_DEAD_TIMEOUT:
                    if await _transition(worker, "DEAD"):
                        log.warning("WORKER_DEAD worker_id=%s", worker["worker_id"])
        except Exception:
            log.exception("WORKER_SCAN_FAILED worker_id=%s", worker["worker_id"])


async def _inventory_chunk(worker_id: str, chunk_id: str) -> bool:
    object_id = _CHUNK_ID.fullmatch(chunk_id).group(1)
    async with object_lock(object_id):
        # Both observations are fresh under the same lock used by upload/delete.
        known = await _db(db.known_chunk_ids)
        manifest = await _db(db.get_object_manifest, object_id)
        if manifest is not None and manifest["status"] == "UPLOADING":
            return True
        if chunk_id not in known:
            if not await _delete_chunk(worker_id, chunk_id):
                return False
            await _db(db.delete_replica_record, chunk_id, worker_id)
            log.info("ORPHAN_DELETED object_id=%s chunk_id=%s worker_id=%s", object_id, chunk_id, worker_id)
            return True
        if manifest is None or manifest["status"] != "READY":
            return False  # Inconsistent snapshots must never authorize deletion.
        chunk = next((c for c in manifest["chunks"] if c["chunk_id"] == chunk_id), None)
        if chunk is None:
            return False
        result = await _fetch_verified(worker_id, chunk)
        if result.state:
            await _mark_bad(chunk, worker_id, result.state, insert=True)
            return await _delete_chunk(worker_id, chunk_id)
        if result.data is None:
            return False
        if await _two_verified_others(chunk, worker_id):
            if not await _delete_chunk(worker_id, chunk_id):
                return False
            await _db(db.delete_replica_record, chunk_id, worker_id)
            log.info("SURPLUS_DELETED object_id=%s chunk_id=%s worker_id=%s", object_id, chunk_id, worker_id)
        else:
            await _db(db.upsert_replica, chunk_id, worker_id, "HEALTHY")
            log.info("REPLICA_RESTORED object_id=%s chunk_id=%s worker_id=%s", object_id, chunk_id, worker_id)
        return True


async def _verify_expected_replicas(worker_id: str, inventory: set[str], *, joining: bool) -> bool:
    complete = True
    if joining:
        snapshots = await _db(db.get_chunks_for_repair)
    else:
        snapshots = await _db(db.get_healthy_chunks_for_worker, worker_id)
    for snapshot in snapshots:
        if joining and snapshot["chunk_id"] in inventory:
            continue
        try:
            async with object_lock(snapshot["object_id"]):
                chunk = await _ready_chunk(snapshot["object_id"], snapshot["chunk_id"])
                if chunk is None:
                    continue
                replica = next((r for r in chunk["replicas"] if r["worker_id"] == worker_id), None)
                if replica is None:
                    continue
                if joining:
                    await _mark_bad(chunk, worker_id, "MISSING")
                elif replica["state"] == "HEALTHY":
                    # Check actual bytes even when the worker lists the expected chunk.
                    result = await _fetch_verified(worker_id, chunk)
                    if result.state:
                        await _mark_bad(chunk, worker_id, result.state)
        except Exception:
            complete = False
            log.exception("INVENTORY_REPLICA_CHECK_FAILED chunk_id=%s worker_id=%s", snapshot["chunk_id"], worker_id)
    return complete


async def _reconcile_worker(worker: dict, *, joining: bool) -> None:
    worker_id = worker["worker_id"]
    registration = await _db(db.get_worker_registration, worker_id) if joining else None
    inventory = await _get_inventory(worker_id)
    if inventory is None:
        return
    complete = True
    for chunk_id in sorted(inventory):
        try:
            if not joining:
                # Recorded healthy copies are verified together below.
                rows = await _db(db.get_replicas, chunk_id)
                known = await _db(db.known_chunk_ids)
                if chunk_id in known and any(r["worker_id"] == worker_id and r["state"] == "HEALTHY" for r in rows):
                    continue
            if not await _inventory_chunk(worker_id, chunk_id):
                complete = False
        except Exception:
            complete = False
            log.exception("INVENTORY_CHUNK_FAILED chunk_id=%s worker_id=%s", chunk_id, worker_id)
    if not joining:
        await _verify_expected_replicas(worker_id, inventory, joining=False)
    elif complete:
        current = await _worker(worker_id)
        if current is None or current["base_url"] != worker["base_url"] or current["status"] != "JOINING":
            return
        if not await _verify_expected_replicas(worker_id, inventory, joining=True):
            return
        # Heartbeats may age or registrations may change during a large inventory.
        current = await _worker(worker_id)
        if (current is not None and current["status"] == "JOINING"
                and current["base_url"] == worker["base_url"] and _fresh(current)
                and await _db(db.complete_worker_admission, worker_id, current["last_heartbeat"], registration)):
            log.info("WORKER_ALIVE worker_id=%s", worker_id)


async def reconcile_joining_workers() -> None:
    for worker in await _db(db.get_workers):
        if worker["status"] == "JOINING":
            try:
                await _reconcile_worker(worker, joining=True)
            except Exception:
                log.exception("WORKER_RECONCILE_FAILED worker_id=%s", worker["worker_id"])
    if _runtime.next_inventory is not None and _runtime.monotonic() >= _runtime.next_inventory:
        _runtime.next_inventory = _runtime.monotonic() + _INVENTORY_INTERVAL
        for worker in await _db(db.get_workers):
            if worker["status"] == "ALIVE" and _fresh(worker):
                try:
                    await _reconcile_worker(worker, joining=False)
                except Exception:
                    log.exception("LIVE_INVENTORY_FAILED worker_id=%s", worker["worker_id"])


async def _cleanup_surplus(chunk: dict) -> None:
    for replica in await _replicas_with_workers(chunk["chunk_id"]):
        wid = replica["worker_id"]
        if replica["worker_status"] != "ALIVE" or not _fresh(replica):
            continue
        if len(await _healthy(chunk, {wid})) < REPLICATION_FACTOR:
            continue
        if await _two_verified_others(chunk, wid) and await _delete_chunk(wid, chunk["chunk_id"]):
            await _db(db.delete_replica_record, chunk["chunk_id"], wid)
            log.info("SURPLUS_DELETED object_id=%s chunk_id=%s worker_id=%s",
                     chunk["object_id"], chunk["chunk_id"], wid)


async def _reconcile_pending(chunk: dict) -> None:
    """Caller holds object_lock; recover uncertain copies before placing new ones."""
    for replica in await _replicas_with_workers(chunk["chunk_id"]):
        if len(await _healthy(chunk)) >= REPLICATION_FACTOR:
            break
        if replica["state"] != "PENDING_DELETE" or replica["worker_status"] != "ALIVE" or not _fresh(replica):
            continue
        wid = replica["worker_id"]
        result = await _fetch_verified(wid, chunk)
        current = await _worker(wid)
        if (current is None or current["status"] != "ALIVE" or not _fresh(current)
                or current["base_url"] != replica["base_url"]):
            continue
        if await _ready_chunk(chunk["object_id"], chunk["chunk_id"]) is None:
            return
        if result.data is not None:
            await _db(db.upsert_replica, chunk["chunk_id"], wid, "HEALTHY")
            log.info("REPLICA_RESTORED object_id=%s chunk_id=%s worker_id=%s",
                     chunk["object_id"], chunk["chunk_id"], wid)
        elif result.state == "MISSING":
            await _db(db.delete_replica_record, chunk["chunk_id"], wid)
            log.warning("REPLICA_MISSING object_id=%s chunk_id=%s worker_id=%s",
                        chunk["object_id"], chunk["chunk_id"], wid)
        elif result.state == "CORRUPT":
            log.warning("CHUNK_CORRUPTED object_id=%s chunk_id=%s worker_id=%s",
                        chunk["object_id"], chunk["chunk_id"], wid)
            if await _delete_chunk(wid, chunk["chunk_id"]):
                await _db(db.delete_replica_record, chunk["chunk_id"], wid)


async def _put_verified(worker_id: str, chunk: dict, data: bytes) -> bool:
    current = await _worker(worker_id)
    if (current is None or current["status"] != "ALIVE" or not _fresh(current)
            or await _ready_chunk(chunk["object_id"], chunk["chunk_id"]) is None
            or len(await _healthy(chunk)) >= REPLICATION_FACTOR):
        return False
    response = await _request("PUT", worker_id, f'/internal/chunks/{chunk["chunk_id"]}', timeout=10,
                              content=data, headers={"Content-Type": "application/octet-stream",
                                                     "X-Chunk-SHA256": chunk["sha256"]})
    if response is None or not response.is_success:
        return False
    # Defensive against external DB changes even though cooperating deletes lock.
    if await _ready_chunk(chunk["object_id"], chunk["chunk_id"]) is None:
        await _delete_chunk(worker_id, chunk["chunk_id"])
        return False
    result = await _fetch_verified(worker_id, chunk)
    if result.data is None:
        if result.state:
            await _mark_bad(chunk, worker_id, result.state)
        return False
    if await _ready_chunk(chunk["object_id"], chunk["chunk_id"]) is None:
        await _delete_chunk(worker_id, chunk["chunk_id"])
        return False
    current = await _worker(worker_id)
    if current is None or current["status"] != "ALIVE" or not _fresh(current):
        return False
    await _db(db.upsert_replica, chunk["chunk_id"], worker_id, "HEALTHY")
    log.info("REPLICA_REPAIRED object_id=%s chunk_id=%s worker_id=%s",
             chunk["object_id"], chunk["chunk_id"], worker_id)
    return True


async def _select_target(chunk: dict, tried: set[str]) -> str | None:
    rows = await _db(db.get_replicas, chunk["chunk_id"])
    excluded = tried | {r["worker_id"] for r in rows}
    workers = [w for w in await _db(db.get_workers) if w["status"] == "ALIVE" and _fresh(w)]
    try:
        choices = choose_workers(workers, excluded, 1)
    except InsufficientWorkers:
        return None
    allowed = {w["worker_id"] for w in workers} - excluded
    return next((w["worker_id"] for w in choices if w["worker_id"] in allowed), None)


async def repair_chunk(snapshot: dict) -> None:
    async with object_lock(snapshot["object_id"]):
        chunk = await _ready_chunk(snapshot["object_id"], snapshot["chunk_id"])
        if chunk is None:
            return
        await _reconcile_pending(chunk)
        await _cleanup_surplus(chunk)
        healthy = await _healthy(chunk)
        if len(healthy) >= REPLICATION_FACTOR:
            _runtime.notices.pop(chunk["chunk_id"], None)
            return
        data = await _source(chunk)
        if data is None:
            _notice(chunk, "no_verified_source")
            return
        tried: set[str] = set()
        failed_bad: set[str] = set()
        # Prefer replacing a known bad copy before consuming another worker.
        for replica in await _replicas_with_workers(chunk["chunk_id"]):
            if len(await _healthy(chunk)) >= REPLICATION_FACTOR:
                break
            wid = replica["worker_id"]
            if replica["state"] not in {"CORRUPT", "MISSING"} or replica["worker_status"] != "ALIVE" or not _fresh(replica):
                continue
            tried.add(wid)
            if not await _delete_chunk(wid, chunk["chunk_id"]) or not await _put_verified(wid, chunk, data):
                failed_bad.add(wid)
        while len(await _healthy(chunk)) < REPLICATION_FACTOR:
            if await _ready_chunk(chunk["object_id"], chunk["chunk_id"]) is None:
                return
            target = await _select_target(chunk, tried)
            if target is None:
                _notice(chunk, "no_eligible_target")
                return
            tried.add(target)
            await _put_verified(target, chunk, data)
        for worker_id in failed_bad:
            await _db(db.delete_replica_record, chunk["chunk_id"], worker_id)
        await _cleanup_surplus(chunk)
        _runtime.notices.pop(chunk["chunk_id"], None)


async def repair_pass() -> None:
    chunks = await _db(db.get_chunks_for_repair)
    current = {c["chunk_id"] for c in chunks}
    # Keep throttle entries only for currently retained READY chunks.
    for chunk_id in set(_runtime.notices) - current:
        del _runtime.notices[chunk_id]
    for chunk in chunks:
        try:
            await repair_chunk(chunk)
        except Exception:
            log.exception("CHUNK_REPAIR_FAILED object_id=%s chunk_id=%s", chunk["object_id"], chunk["chunk_id"])


async def run_once() -> None:
    """Run one serialized pass; tests may replace _runtime's client and clocks."""
    async with _runtime.pass_lock:
        if _runtime.started_at is None:
            _runtime.started_at = _runtime.monotonic()
        if _runtime.next_inventory is None:
            _runtime.next_inventory = _runtime.monotonic() + _INVENTORY_INTERVAL
        if _runtime.client is None:
            _runtime.client = httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False)
        for phase in (detect_dead_workers, reconcile_joining_workers, repair_pass):
            try:
                await phase()
            except Exception:
                log.exception("RECONCILE_PHASE_FAILED phase=%s", phase.__name__)


async def _loop() -> None:
    while True:
        try:
            await run_once()
        except Exception:
            log.exception("RECONCILE_PASS_FAILED")
        await asyncio.sleep(RECONCILE_INTERVAL)


def start_reconciler() -> None:
    if _runtime.task is not None and not _runtime.task.done():
        return
    _runtime.started_at = _runtime.monotonic()
    _runtime.next_inventory = _runtime.monotonic() + _INVENTORY_INTERVAL
    _runtime.notices.clear()
    if _runtime.client is None or _runtime.client.is_closed:
        _runtime.client = httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False)
    _runtime.task = asyncio.create_task(_loop(), name="object-store-reconciler")


async def stop_reconciler() -> None:
    """Awaited by A's lifespan so no recovery request outlives the shared client."""
    task = _runtime.task
    try:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        if _runtime.client is not None:
            await _runtime.client.aclose()
        _runtime.task = None
        _runtime.client = None
        _runtime.started_at = None
