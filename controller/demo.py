"""Opt-in, owner-authenticated demo actions for four existing Compose workers."""
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, Request

from . import config, telemetry
from .models import StoreError
from .worker_admin import require_admin

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
WORKERS = ("worker1", "worker2", "worker3", "worker4")


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
