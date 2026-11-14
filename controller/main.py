"""One controller process owns SQLite, HTTP pooling and recovery lifecycle."""
import asyncio
import inspect
import logging
import sqlite3
from contextlib import asynccontextmanager, suppress
from importlib import import_module
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from . import config, dashboard, database as db, objects
from .models import Heartbeat, Registration, StoreError

log = logging.getLogger("controller")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
STATIC_DIR = Path(__file__).with_name("static")


def _optional_module(name: str):
    try:
        return import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise  # Missing dependencies inside an existing module must fail visibly.
        return None


def _cleanup_downloads():
    config.DOWNLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    for path in config.DOWNLOAD_TEMP_DIR.glob("download-*.tmp"):
        objects.remove_download(path)


def create_app(*, worker_transport=None) -> FastAPI:
    recovery = _optional_module("controller.recovery")
    status = _optional_module("controller.status")

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(db.init_db)
        await run_in_threadpool(db.prepare_restart)
        await run_in_threadpool(_cleanup_downloads)
        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, transport=worker_transport,
                                     trust_env=False, follow_redirects=False) as http:
            app.state.http = http
            app.state.recovery_available = recovery is not None
            if recovery is not None:
                started = recovery.start_reconciler()
                if inspect.isawaitable(started):
                    await started
            else:
                log.warning("RECOVERY_NOT_INSTALLED: workers stay JOINING until Member B's reconciler verifies them")
            cleanup = asyncio.create_task(objects.cleanup_abandoned(http), name="abandoned-object-cleanup")
            try:
                yield
            finally:
                if recovery is not None:
                    stopped = recovery.stop_reconciler()
                    if inspect.isawaitable(stopped):
                        await stopped
                cleanup.cancel()
                with suppress(asyncio.CancelledError):
                    await cleanup

    app = FastAPI(title="Mini Distributed Object Store - Controller", version="0.2.0", lifespan=lifespan)
    app.include_router(objects.router)
    app.include_router(dashboard.router)
    if status is not None:
        app.include_router(status.router)
    if (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="dashboard-assets")

    @app.exception_handler(StoreError)
    async def store_error(request: Request, exc: StoreError):
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"error": "INVALID_REQUEST", "message": "Request fields or JSON are invalid"})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": "HTTP_ERROR", "message": str(exc.detail)}, headers=exc.headers)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request: Request, exc: sqlite3.Error):
        log.exception("DATABASE_UNAVAILABLE path=%s", request.url.path)
        return JSONResponse(status_code=503, content={"error": "DATABASE_UNAVAILABLE", "message": "Metadata storage is unavailable"})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log.exception("REQUEST_FAILED path=%s", request.url.path)
        return JSONResponse(status_code=500, content={"error": "INTERNAL_ERROR", "message": "Controller failed to process request"})

    @app.get("/", include_in_schema=False)
    def dashboard_index():
        index = STATIC_DIR / "index.html"
        if not index.is_file():
            raise StoreError(503, "DASHBOARD_UNAVAILABLE", "The dashboard build is unavailable")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    @app.get("/health", tags=["internal"])
    def health():
        db.get_workers()  # Check metadata access without declaring JOINING workers ready.
        return {"status": "ok", "service": "controller", "recovery_available": app.state.recovery_available}

    @app.post("/internal/workers/register", tags=["internal"])
    def register(body: Registration):
        db.register_worker(body.worker_id, body.base_url)
        log.info("WORKER_JOINING worker=%s", body.worker_id)
        return {"worker_id": body.worker_id, "status": "registered"}

    @app.post("/internal/workers/heartbeat", tags=["internal"])
    def heartbeat(body: Heartbeat):
        if not db.touch_heartbeat(body.worker_id):
            raise StoreError(404, "WORKER_NOT_FOUND", "Worker must register first")
        return {"worker_id": body.worker_id, "status": "accepted"}

    return app


app = create_app()
