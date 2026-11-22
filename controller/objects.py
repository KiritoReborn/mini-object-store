"""Object lifecycle and bounded, database-verified worker transfers.

Recovery imports object_lock to serialize destructive changes to the same object.
HTTP and file I/O occur outside SQLite transactions. Worker failures never publish
an incomplete upload or start an unverified successful download response.
"""
import asyncio
import hashlib
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from uuid import uuid4

import anyio
import httpx
from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse, MalformedRangeHeader, RangeNotSatisfiable

from . import config, database as db, telemetry
from .models import ErrorResponse, MetadataPatch, StoreError, parse_metadata, safe_content_type, safe_filename
from .placement import InsufficientWorkers, choose_workers, heartbeat_is_fresh

router = APIRouter(prefix="/api/v1/objects", tags=["objects"])
log = logging.getLogger("controller")
_locks: dict[str, list] = {}


async def _run_sync(function, *args, on_cancel=None, **kwargs):
    """Finish an owned thread operation before cancellation releases its resources."""
    task = asyncio.create_task(run_in_threadpool(function, *args, **kwargs))
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
            try:
                result = task.result()
                if on_cancel is not None:
                    on_cancel(result)
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("CANCELLED_OPERATION_FAILED operation=%s", function.__name__)
        raise


def _discard_temp(result) -> None:
    fd, filename = result
    try:
        os.close(fd)
    finally:
        remove_download(Path(filename))


@asynccontextmanager
async def object_lock(object_id: str):
    """Reference-count waiters too, so cancellation cannot split a shared lock."""
    entry = _locks.setdefault(object_id, [asyncio.Lock(), 0])
    entry[1] += 1
    acquired = False
    try:
        await entry[0].acquire()
        acquired = True
        yield
    finally:
        if acquired:
            entry[0].release()
        entry[1] -= 1
        if entry[1] == 0:
            del _locks[object_id]


async def iter_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while data := await file.read(config.CHUNK_SIZE):
        yield data


def public_manifest(obj: dict) -> dict:
    result = {k: v for k, v in obj.items() if k != "chunks"}
    result["chunks"] = []
    for chunk in obj["chunks"]:
        healthy = [r for r in chunk["replicas"] if r["state"] == "HEALTHY"]
        result["chunks"].append({
            "chunk_id": chunk["chunk_id"], "index": chunk["chunk_index"],
            "size": chunk["size"], "sha256": chunk["sha256"],
            "workers": [r["worker_id"] for r in healthy],
            "available_workers": [r["worker_id"] for r in healthy
                                  if r["worker_status"] == "ALIVE" and heartbeat_is_fresh(r["last_heartbeat"])],
            "replicas": [{k: r[k] for k in ("worker_id", "state", "worker_status", "last_verified_at")}
                         for r in chunk["replicas"]],
        })
    return result


def ready_manifest(object_id: str) -> dict:
    obj = db.get_object_manifest(object_id)
    if obj is None or obj["status"] != "READY":
        raise StoreError(404, "OBJECT_NOT_FOUND", "Object does not exist")
    return obj


async def _delete_copy(http: httpx.AsyncClient, chunk_id: str, replica: dict) -> bool:
    try:
        response = await http.delete(f'{replica["base_url"]}/internal/chunks/{chunk_id}')
        if response.status_code == 204:
            return True
        log.warning("DELETE_DEFERRED chunk=%s worker=%s status=%s", chunk_id, replica["worker_id"], response.status_code)
    except httpx.HTTPError:
        log.warning("DELETE_DEFERRED chunk=%s worker=%s", chunk_id, replica["worker_id"])
    return False


async def discard_object(http: httpx.AsyncClient, object_id: str) -> None:
    """Caller holds object_lock; offline remnants become orphans on rejoin."""
    obj = await _run_sync(db.get_object_manifest, object_id)
    if obj is None:
        return
    for chunk in obj["chunks"]:
        for replica in chunk["replicas"]:
            await _delete_copy(http, chunk["chunk_id"], replica)
    await _run_sync(db.delete_object_record, object_id)
    if obj["status"] == "DELETING":
        log.info("OBJECT_DELETED object=%s", object_id)


async def cleanup_abandoned(http: httpx.AsyncClient) -> None:
    """Retry persistent cleanup while the controller is running."""
    while True:
        try:
            for oid in await _run_sync(db.get_abandoned_object_ids):
                async with object_lock(oid):
                    await discard_object(http, oid)
        except Exception:
            log.exception("ABANDONED_OBJECT_CLEANUP_FAILED")
        await asyncio.sleep(config.RECONCILE_INTERVAL)


@contextmanager
def _transfer(chunk: dict, worker_id: str, direction: str):
    fields = {"object_id": chunk["object_id"], "chunk_id": chunk["chunk_id"],
              "worker_id": worker_id, "direction": direction, "size": chunk["size"],
              "transfer_id": str(uuid4())}
    telemetry.record_event("transfer_started", **fields)
    completed = False
    detail = "unverified response"

    def verified():
        nonlocal completed
        completed = True
        telemetry.record_event("transfer_completed", **fields)

    try:
        yield verified
    except BaseException as exc:
        detail = "cancelled" if isinstance(exc, asyncio.CancelledError) else "transfer failed"
        raise
    finally:
        if not completed:
            telemetry.record_event("transfer_failed", **fields, detail=detail)


async def _put_copy(http: httpx.AsyncClient, chunk: dict, worker: dict, data: bytes) -> bool:
    # Persist uncertainty BEFORE the request: a lost response may still mean a stored copy.
    await _run_sync(db.upsert_replica, chunk["chunk_id"], worker["worker_id"], "PENDING_DELETE")
    for _ in range(2):
        try:
            with _transfer(chunk, worker["worker_id"], "to_worker") as verified:
                response = await http.put(f'{worker["base_url"]}/internal/chunks/{chunk["chunk_id"]}',
                    content=data, headers={"X-Chunk-SHA256": chunk["sha256"], "Content-Type": "application/octet-stream"})
                if response.status_code not in {200, 201}:
                    break
                ack = response.json()
                if not isinstance(ack, dict) or any(ack.get(k) != chunk[k] for k in ("chunk_id", "size", "sha256")):
                    break
                verified()
            await _run_sync(db.upsert_replica, chunk["chunk_id"], worker["worker_id"], "HEALTHY")
            return True
        except (httpx.HTTPError, ValueError):
            log.warning("PUT_RETRY object=%s chunk=%s worker=%s", chunk["object_id"], chunk["chunk_id"], worker["worker_id"])
    return False


async def _store_chunk(http: httpx.AsyncClient, chunk: dict, data: bytes) -> None:
    tried: set[str] = set()
    stored = 0
    while stored < config.REPLICATION_FACTOR:
        workers = await _run_sync(db.get_placement_workers)
        try:
            worker = choose_workers(workers, tried, 1)[0]
        except InsufficientWorkers as exc:
            raise StoreError(503, "STORAGE_UNAVAILABLE", "Cannot obtain two confirmed replicas for a chunk") from exc
        tried.add(worker["worker_id"])
        if await _put_copy(http, chunk, worker, data):
            stored += 1
    for replica in await _run_sync(db.get_replicas, chunk["chunk_id"]):
        if replica["state"] == "PENDING_DELETE" and await _delete_copy(http, chunk["chunk_id"], replica):
            await _run_sync(db.delete_replica_record, chunk["chunk_id"], replica["worker_id"])


@router.post("", status_code=201)
async def upload_object(request: Request, file: UploadFile = File(...), metadata: str | None = Form(None)):
    custom = parse_metadata(metadata)
    name = safe_filename(file.filename)
    oid = str(uuid4())
    http = request.app.state.http
    async with object_lock(oid):
        try:
            await _run_sync(db.create_object, oid, name, safe_content_type(file.content_type), custom)
            whole_hash, size, count = hashlib.sha256(), 0, 0
            async for data in iter_chunks(file):
                chunk = {"chunk_id": f"{oid}_{count}", "object_id": oid,
                         "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                await _run_sync(db.add_chunk, chunk["chunk_id"], oid, count, len(data), chunk["sha256"])
                await _store_chunk(http, chunk, data)
                whole_hash.update(data)
                size += len(data)
                count += 1
            committed = await _run_sync(db.finalize_object, oid, size, count, whole_hash.hexdigest())
            if not committed:
                raise StoreError(503, "STORAGE_UNAVAILABLE", "Replica availability changed before upload commit")
        except BaseException as exc:
            # Cancellation also abandons the upload. Shield cleanup from request cancellation.
            with anyio.CancelScope(shield=True):
                await _run_sync(db.set_object_state, oid, "FAILED")
                await discard_object(http, oid)
            if isinstance(exc, OSError):
                raise StoreError(503, "UPLOAD_STORAGE_UNAVAILABLE", "Upload temporary storage is unavailable") from exc
            raise
    log.info("OBJECT_READY object=%s size=%s chunks=%s", oid, size, count)
    return public_manifest(await _run_sync(ready_manifest, oid))


async def read_verified_chunk(http: httpx.AsyncClient, chunk: dict) -> bytes:
    for replica in chunk["replicas"]:
        if replica["state"] != "HEALTHY" or replica["worker_status"] != "ALIVE":
            continue
        state = None
        try:
            with _transfer(chunk, replica["worker_id"], "from_worker") as verified:
                async with http.stream("GET", f'{replica["base_url"]}/internal/chunks/{chunk["chunk_id"]}') as response:
                    if response.status_code == 404:
                        state = "MISSING"
                    elif response.status_code == 409:
                        state = "CORRUPT"
                    elif response.status_code == 200:
                        data = bytearray()
                        async for part in response.aiter_bytes(chunk_size=65_536):
                            data.extend(part)
                            if len(data) > chunk["size"]:
                                break
                        if len(data) == chunk["size"] and hashlib.sha256(data).hexdigest() == chunk["sha256"]:
                            verified()
                            return bytes(data)
                        state = "CORRUPT"
        except httpx.HTTPError:
            log.warning("READ_UNAVAILABLE chunk=%s worker=%s", chunk["chunk_id"], replica["worker_id"])
        if state:
            await _run_sync(db.set_replica_state, chunk["chunk_id"], replica["worker_id"], state)
            log.warning("REPLICA_%s chunk=%s worker=%s", state, chunk["chunk_id"], replica["worker_id"])
    raise StoreError(503, "OBJECT_UNAVAILABLE", "No verified readable copy of a required chunk")


def remove_download(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.exception("TEMP_CLEANUP_FAILED file=%s", path.name)


class DownloadRangeError(Exception):
    def __init__(self, response: JSONResponse):
        self.response = response


class VerifiedFileResponse(FileResponse):
    """Release verified temp data even if sending the response is interrupted."""
    @classmethod
    def _parse_range_header(cls, http_range: str, file_size: int) -> list[tuple[int, int]]:
        try:
            return super()._parse_range_header(http_range, file_size)
        except MalformedRangeHeader as exc:
            raise DownloadRangeError(JSONResponse(
                {"error": "INVALID_RANGE", "message": exc.content}, status_code=400,
            )) from exc
        except RangeNotSatisfiable as exc:
            raise DownloadRangeError(JSONResponse(
                {"error": "RANGE_NOT_SATISFIABLE", "message": "Requested range is outside the object"},
                status_code=416, headers={"Content-Range": f"bytes */{exc.max_size}"},
            )) from exc

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        except DownloadRangeError as exc:
            await exc.response(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await _run_sync(remove_download, Path(self.path))


async def _prepare_download(http: httpx.AsyncClient, obj: dict) -> Path:
    path = None
    try:
        fd, filename = await _run_sync(tempfile.mkstemp, prefix="download-", suffix=".tmp",
                                      dir=config.DOWNLOAD_TEMP_DIR, on_cancel=_discard_temp)
        path = Path(filename)
        whole_hash, size = hashlib.sha256(), 0
        try:
            output = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with output:
            if len(obj["chunks"]) != obj["num_chunks"]:
                raise StoreError(503, "OBJECT_UNAVAILABLE", "Object manifest is incomplete")
            for index, chunk in enumerate(obj["chunks"]):
                if chunk["chunk_index"] != index:
                    raise StoreError(503, "OBJECT_UNAVAILABLE", "Object manifest is out of order")
                data = await read_verified_chunk(http, chunk)
                await _run_sync(output.write, data)
                whole_hash.update(data)
                size += len(data)
        if size != obj["size"] or whole_hash.hexdigest() != obj["sha256"]:
            raise StoreError(503, "OBJECT_UNAVAILABLE", "Object failed complete integrity verification")
        return path
    except BaseException:
        if path is not None:
            remove_download(path)
        raise


@router.get("")
def list_objects():
    return db.list_objects()


@router.get("/{object_id}/metadata")
def get_metadata(object_id: str):
    return public_manifest(ready_manifest(object_id))


@router.patch("/{object_id}/metadata")
async def patch_metadata(object_id: str, body: MetadataPatch):
    async with object_lock(object_id):
        try:
            found = await _run_sync(db.patch_metadata, object_id, body.metadata)
        except ValueError as exc:
            raise StoreError(400, "INVALID_METADATA", "Merged metadata exceeds the size limit") from exc
        if not found:
            raise StoreError(404, "OBJECT_NOT_FOUND", "Object does not exist")
        return public_manifest(await _run_sync(ready_manifest, object_id))


_FILE_BODY = {"schema": {"type": "string", "format": "binary"}}
_RANGE_HEADER = {"schema": {"type": "string"}}
_ATTACHMENT_HEADERS = {
    name: {"schema": {"type": "string"}}
    for name in ("Content-Disposition", "X-Object-SHA256", "ETag")
}


@router.get("/{object_id}", response_class=Response, responses={
    200: {"description": "Verified object bytes with the stored media type",
          "content": {"application/octet-stream": _FILE_BODY}, "headers": _ATTACHMENT_HEADERS},
    206: {"description": "One or more byte ranges from the verified object; a single range uses the stored media type",
          "content": {"application/octet-stream": _FILE_BODY, "multipart/byteranges": _FILE_BODY},
          "headers": {**_ATTACHMENT_HEADERS, "Content-Range": _RANGE_HEADER}},
    400: {"description": "INVALID_RANGE: malformed Range header", "model": ErrorResponse},
    404: {"description": "Object does not exist or is no longer public", "model": ErrorResponse},
    416: {"description": "RANGE_NOT_SATISFIABLE: no bytes at the requested offset",
          "model": ErrorResponse,
          "headers": {"Content-Range": {"schema": {"type": "string"}, "example": "bytes */100"}}},
    503: {"description": "Object or temporary download storage is unavailable", "model": ErrorResponse},
})
async def download_object(request: Request, object_id: str):
    async with object_lock(object_id):
        obj = await _run_sync(ready_manifest, object_id)
        range_header = request.headers.get("range")
        # FileResponse evaluates If-Range against the actual response validators
        # before parsing. Its Last-Modified comes from the prepared file's stat.
        if range_header is not None and "if-range" not in request.headers:
            try:
                VerifiedFileResponse._parse_range_header(range_header, obj["size"])
            except DownloadRangeError as exc:
                return exc.response
        try:
            path = await _prepare_download(request.app.state.http, obj)
        except OSError as exc:
            log.exception("DOWNLOAD_STORAGE_FAILED object=%s", object_id)
            raise StoreError(503, "TEMP_STORAGE_UNAVAILABLE", "Download temporary storage is unavailable") from exc
    return VerifiedFileResponse(path, filename=obj["name"], media_type=obj["content_type"],
        headers={"X-Object-SHA256": obj["sha256"], "ETag": f'"{obj["sha256"]}"'})


@router.delete("/{object_id}", status_code=204)
async def delete_object(request: Request, object_id: str):
    async with object_lock(object_id):
        obj = await _run_sync(db.get_object_manifest, object_id)
        if obj is None or obj["status"] not in {"READY", "DELETING"}:
            raise StoreError(404, "OBJECT_NOT_FOUND", "Object does not exist")
        if obj["status"] == "READY":
            await _run_sync(db.set_object_state, object_id, "DELETING")
        await discard_object(request.app.state.http, object_id)
    return Response(status_code=204)
