"""Opt-in, owner-authenticated demo actions."""
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool

from . import config, database as db, telemetry
from .models import StoreError
from .objects import _run_sync, object_lock, ready_manifest
from .worker_admin import require_admin

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
WORKERS = ("worker1", "worker2", "worker3", "worker4")
# Matches the canonical IDs used by worker storage and recovery.
_CHUNK_ID = re.compile(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})_(?:0|[1-9][0-9]*)")


@asynccontextmanager
async def engine(request):
    if not config.DEMO_CONTROLS or not config.API_KEY:
        raise StoreError(503, "DEMO_DISABLED", "Start the controller with demo controls enabled to use container actions")
    transport = request.app.state.docker_transport or httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
    try:
        async with httpx.AsyncClient(base_url="http://docker", transport=transport, timeout=12, trust_env=False) as http:
            yield http
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise StoreError(503, "DOCKER_UNAVAILABLE", "Docker control is unavailable. Check Docker Desktop and the demo-control setup") from exc


async def inspect_worker(http, wid):
    result = await http.get(f"/containers/{wid}/json")
    if result.status_code == 404:
        return {"worker_id": wid, "container_state": "not_created", "running": False}, None
    if result.status_code != 200:
        raise StoreError(503, "DOCKER_UNAVAILABLE", "Docker could not inspect the worker")
    body = result.json()
    labels = body.get("Config", {}).get("Labels") or {}
    if (labels.get("com.docker.compose.project") != config.DOCKER_PROJECT
            or labels.get("com.docker.compose.service") != wid or body.get("Name") != "/" + wid):
        raise StoreError(409, "CONTAINER_MISMATCH", "This container does not belong to the configured project worker")
    return {"worker_id": wid, "container_state": body["State"]["Status"],
            "running": body["State"]["Running"] is True}, body["Id"]


@router.get("/workers")
async def containers(request: Request):
    if not config.DEMO_CONTROLS:
        return {"enabled": False, "workers": []}
    async with engine(request) as http:
        return {"enabled": True, "workers": [(await inspect_worker(http, wid))[0] for wid in WORKERS]}


@router.post("/workers/{worker_id}/{action}", dependencies=[Depends(require_admin)])
async def control_worker(request: Request, worker_id: str, action: str):
    if worker_id not in WORKERS or action not in {"start", "stop", "restart"}:
        raise StoreError(400, "INVALID_DEMO_ACTION", "Only start, stop and restart on worker1 through worker4 are supported")
    # One action at a time prevents double-clicks and overlapping lifecycle commands.
    async with request.app.state.demo_lock:
        async with engine(request) as http:
            _, cid = await inspect_worker(http, worker_id)
            if cid is None:
                raise StoreError(404, "CONTAINER_MISSING", "Start the original Docker Compose stack first")
            result = await http.post(f"/containers/{cid}/{action}", params={"t": "3"} if action != "start" else None)
            if result.status_code not in {204, 304}:
                raise StoreError(503, "DEMO_ACTION_FAILED", "Docker did not complete the requested action")
            telemetry.record_event("worker_action", worker_id=worker_id, state=action, detail="Container action completed; recovery state is separate")
            current, _ = await inspect_worker(http, worker_id)
            return {"action": action, **current}


@router.post("/workers/{worker_id}/chunks/{chunk_id}/corrupt")
async def corrupt_replica(request: Request, worker_id: str, chunk_id: str):
    if not config.DEMO_FAULT_INJECTION:
        raise StoreError(404, "NOT_FOUND", "Route not found")
    if not config.API_KEY:
        raise StoreError(401, "AUTH_REQUIRED", "Configure owner access to enable demo fault injection")
    require_admin(request)
    match = _CHUNK_ID.fullmatch(chunk_id)
    if match is None:
        raise StoreError(400, "INVALID_CHUNK_ID", "Chunk ID must be <uuid>_<index>")
    object_id = match[1]
    async with request.app.state.demo_lock, object_lock(object_id):
        workers = await run_in_threadpool(db.get_workers)
        if not any(worker["worker_id"] == worker_id for worker in workers):
            raise StoreError(404, "WORKER_NOT_FOUND", "Worker has not registered")
        obj = await run_in_threadpool(ready_manifest, object_id)
        chunk = next((item for item in obj["chunks"] if item["chunk_id"] == chunk_id), None)
        if chunk is None:
            raise StoreError(404, "CHUNK_NOT_FOUND", "Object does not contain this chunk")
        replica = next((item for item in chunk["replicas"] if item["worker_id"] == worker_id), None)
        if replica is None or replica["state"] != "HEALTHY":
            raise StoreError(409, "REPLICA_NOT_HEALTHY", "Worker must hold a healthy replica of this chunk")

        try:
            response = await request.app.state.http.post(
                f'{replica["base_url"]}/internal/demo/corrupt/{chunk_id}',
                headers={"X-Artaud-Worker-ID": worker_id}, timeout=3,
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise StoreError(503, "FAULT_INJECTION_FAILED", "Worker did not confirm the demo fault") from exc
        try:
            acknowledgment = response.json() if response.status_code in {200, 404, 409} else None
        except ValueError:
            acknowledgment = None
        worker_error = acknowledgment.get("error") if isinstance(acknowledgment, dict) else None
        if response.status_code == 404:
            if worker_error == "CHUNK_NOT_FOUND":
                await _run_sync(db.set_replica_state, chunk_id, worker_id, "MISSING")
                raise StoreError(404, "CHUNK_NOT_FOUND", "The worker reports this replica is missing")
            raise StoreError(404, "FAULT_TARGET_UNAVAILABLE", "Worker fault injection is unavailable for this replica")
        if response.status_code == 409:
            if worker_error == "CHUNK_CORRUPTED":
                await _run_sync(db.set_replica_state, chunk_id, worker_id, "CORRUPT")
                raise StoreError(409, "REPLICA_ALREADY_CORRUPT", "This replica is already corrupt and has been marked for recovery")
            raise StoreError(409, "FAULT_INJECTION_REJECTED", "Worker could not verify a healthy nonempty copy")
        result = {"chunk_id": chunk_id, "worker_id": worker_id, "offset": 0,
                  "size": chunk["size"], "action": "corrupted"}
        if (response.status_code != 200 or not isinstance(acknowledgment, dict)
                or any(acknowledgment.get(k) != v for k, v in result.items())):
            raise StoreError(503, "FAULT_INJECTION_FAILED", "Worker did not confirm the demo fault")
        telemetry.record_event("fault_injected", object_id=object_id, worker_id=worker_id,
                               chunk_id=chunk_id, size=chunk["size"], detail="One stored byte was changed for the demo")
        return result
