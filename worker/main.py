import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from . import config, storage
from .heartbeat import run_heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def heartbeat_done(task):
    if task.cancelled():
        return
    exc = task.exception()
    log.error(
        "HEARTBEAT_STOPPED worker=%s", config.WORKER_ID,
        exc_info=(type(exc), exc, exc.__traceback__) if exc else None,
    )


@asynccontextmanager
async def lifespan(app):
    storage.ROOT.mkdir(parents=True, exist_ok=True)
    storage.cleanup_tmp()
    task = asyncio.create_task(run_heartbeat(), name=f"heartbeat-{config.WORKER_ID}")
    task.add_done_callback(heartbeat_done)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            # heartbeat_done observes and logs unexpected task failures.
            pass


app = FastAPI(lifespan=lifespan)


def err(status, code, msg, chunk_id=None, headers=None):
    log.warning("ERROR worker=%s chunk=%s code=%s msg=%s",
                config.WORKER_ID, chunk_id, code, msg)
    return JSONResponse(status_code=status, content={"error": code, "message": msg}, headers=headers)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return err(exc.status_code, code, str(exc.detail), request.path_params.get("chunk_id"), exc.headers)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.error(
        "UNHANDLED worker=%s chunk=%s path=%s", config.WORKER_ID,
        request.path_params.get("chunk_id"), request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(status_code=500, content={
        "error": "INTERNAL_ERROR", "message": "worker failed to process request",
    })


@app.get("/health")
def health():
    return {"worker_id": config.WORKER_ID, "status": "ok"}


@app.put("/internal/chunks/{chunk_id:path}")
async def put_chunk(chunk_id: str, request: Request):
    if not storage.valid_id(chunk_id):
        return err(400, "INVALID_CHUNK_ID", "chunk id must be <uuid>_<index>", chunk_id)
    sha = request.headers.get("X-Chunk-SHA256", "").lower()
    if not sha:
        return err(400, "MISSING_CHECKSUM", "X-Chunk-SHA256 header required", chunk_id)
    if not storage.HEX64_RE.fullmatch(sha):
        return err(400, "CHECKSUM_MISMATCH", "checksum must contain 64 hex characters", chunk_id)

    buf = bytearray()
    async for part in request.stream():
        if len(buf) + len(part) > config.CHUNK_SIZE:
            return err(400, "CHUNK_TOO_LARGE", f"max {config.CHUNK_SIZE} bytes", chunk_id)
        buf.extend(part)
    data = bytes(buf)

    result = await run_in_threadpool(_store, chunk_id, data, sha)
    if result == "bad_hash":
        return err(400, "CHECKSUM_MISMATCH", "body hash does not match header", chunk_id)
    if result == "conflict":
        return err(409, "CHUNK_CONFLICT", "healthy chunk with different data exists", chunk_id)
    log.info("PUT worker=%s chunk=%s result=%s", config.WORKER_ID, chunk_id, result)
    return JSONResponse(
        status_code=201 if result == "created" else 200,
        content={"chunk_id": chunk_id, "size": len(data), "sha256": sha, "status": "stored"},
    )


def _store(chunk_id, data, sha):
    if storage.sha256_hex(data) != sha:
        return "bad_hash"
    return storage.put(chunk_id, data, sha)


@app.get("/internal/chunks/{chunk_id:path}")
def get_chunk(chunk_id: str):
    if not storage.valid_id(chunk_id):
        return err(400, "INVALID_CHUNK_ID", "chunk id must be <uuid>_<index>", chunk_id)
    state, data, sha = storage.check(chunk_id)
    if state == "missing":
        return err(404, "CHUNK_NOT_FOUND", "no such chunk on this worker", chunk_id)
    if state == "corrupt":
        return err(409, "CHUNK_CORRUPTED", "stored chunk failed checksum", chunk_id)
    return Response(content=data, media_type="application/octet-stream",
                    headers={"X-Chunk-SHA256": sha})


@app.delete("/internal/chunks/{chunk_id:path}")
def delete_chunk(chunk_id: str):
    if not storage.valid_id(chunk_id):
        return err(400, "INVALID_CHUNK_ID", "chunk id must be <uuid>_<index>", chunk_id)
    storage.delete(chunk_id)
    log.info("DELETE worker=%s chunk=%s", config.WORKER_ID, chunk_id)
    return Response(status_code=204)


@app.get("/internal/workers/{worker_id}/chunks")
def list_chunks(worker_id: str):
    if worker_id != config.WORKER_ID:
        return err(404, "WRONG_WORKER", "this is " + config.WORKER_ID)
    return {"worker_id": config.WORKER_ID, "chunks": storage.inventory()}
