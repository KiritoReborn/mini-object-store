"""Bounded local-Docker connection and metadata controls, never container control."""
import asyncio
import json
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from . import config, database as db
from .models import StoreError
from .placement import heartbeat_is_fresh

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])


def same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
        parsed.port  # Reject malformed ports even when a forged Host matches.
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment
                and origin.lower() == f"{parsed.scheme}://{parsed.netloc}".lower()
                and not any(ord(c) <= 32 or ord(c) == 127 for c in origin)
                and (parsed.netloc.lower() == request.headers.get("host", "").lower()
                     or origin in config.ALLOWED_ORIGINS))
    except ValueError:
        return False


def require_admin(request: Request):
    if request.headers.get("x-artaud-admin") != "1" or not same_origin(request):
        raise StoreError(403, "ADMIN_REQUIRED", "Worker controls require a same-origin administrative request")


class WorkerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=64, strict=True)
    notes: str | None = Field(default=None, max_length=512, strict=True)

    @field_validator("display_name", "notes")
    @classmethod
    def safe_text(cls, value):
        if value is None or any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value):
            raise ValueError("Labels and notes must contain text without control characters")
        return value


class WorkerPatch(WorkerSettings):
    placement_enabled: StrictBool | None = None

    @field_validator("placement_enabled")
    @classmethod
    def nonnull_flag(cls, value):
        if value is None:
            raise ValueError("placement_enabled must be boolean")
        return value

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one setting")
        return self


class WorkerConnection(WorkerSettings):
    worker_id: str = Field(pattern=r"^worker(?:[1-9]|1[0-6])$", strict=True)
    base_url: str = Field(max_length=64, strict=True)

    @model_validator(mode="after")
    def local_origin(self):
        if self.base_url != f"http://{self.worker_id}:8001":
            raise ValueError("Origin must match the selected local-Docker worker")
        return self


def managed_profile(worker: dict) -> dict:
    timestamp = worker["last_heartbeat"]
    try:
        heartbeat = datetime.fromisoformat(timestamp)
        age = (datetime.now(timezone.utc) - heartbeat).total_seconds() if heartbeat.utcoffset() is not None else None
    except (ValueError, TypeError):
        age = None
    return {**worker, "heartbeat_age_seconds": age,
            "available": worker["status"] == "ALIVE" and heartbeat_is_fresh(timestamp)}


@router.get("")
def workers():
    managed = [managed_profile(worker) for worker in db.get_managed_workers()]
    return {"workers": managed,
            "placement_available_workers": sum(w["available"] and w["placement_enabled"] for w in managed)}


async def check_health(http: httpx.AsyncClient, body: WorkerConnection):
    try:
        # A total timeout also bounds a slow stream that never hits the per-read timeout.
        async with asyncio.timeout(config.HTTP_TIMEOUT):
            async with http.stream("GET", f"{body.base_url}/health", follow_redirects=False,
                                   headers={"Accept-Encoding": "identity"}) as response:
                if (response.status_code != 200
                        or response.headers.get("content-encoding", "identity").lower() != "identity"):
                    raise ValueError("Worker health failed")
                data = bytearray()
                async for part in response.aiter_bytes():
                    if len(data) + len(part) > 8192:
                        raise ValueError("Worker health response exceeded limit")
                    data.extend(part)
                health = json.loads(data)
                if (not isinstance(health, dict) or health.get("status") != "ok"
                        or health.get("worker_id") != body.worker_id):
                    raise ValueError("Worker identity did not match")
    except (httpx.HTTPError, ValueError, RecursionError, TimeoutError) as exc:
        raise StoreError(503, "WORKER_UNAVAILABLE", "Worker health or identity could not be verified") from exc


@router.post("/connect", dependencies=[Depends(require_admin)])
async def connect_worker(request: Request, body: WorkerConnection):
    await check_health(request.app.state.http, body)
    changes = body.model_dump(include={"display_name", "notes"}, exclude_unset=True)
    try:
        worker = await run_in_threadpool(db.connect_managed_worker, body.worker_id, body.base_url, changes)
    except ValueError as exc:
        raise StoreError(409, "WORKER_CONFLICT", "Worker is registered at a different origin") from exc
    return managed_profile(worker)


@router.patch("/{worker_id}", dependencies=[Depends(require_admin)])
def patch_worker(worker_id: str, body: WorkerPatch):
    worker = db.update_worker_settings(worker_id, body.model_dump(exclude_unset=True))
    if worker is None:
        raise StoreError(404, "WORKER_NOT_FOUND", "Worker does not exist")
    return managed_profile(worker)


@router.delete("/{worker_id}", status_code=204, dependencies=[Depends(require_admin)])
def forget_worker(worker_id: str):
    result = db.forget_worker(worker_id)
    if result == "missing":
        raise StoreError(404, "WORKER_NOT_FOUND", "Worker does not exist")
    if result == "protected":
        raise StoreError(409, "WORKER_IN_USE", "Only a stale or absent-heartbeat worker with no replica records can be forgotten")
    return Response(status_code=204)
