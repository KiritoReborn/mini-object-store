"""One controller process owns SQLite, HTTP pooling and recovery lifecycle."""
import asyncio
import inspect
import logging
import sqlite3
import secrets
from contextlib import asynccontextmanager, suppress
from importlib import import_module
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException

from . import config, dashboard, database as db, demo, objects, worker_admin
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


def create_app(*, worker_transport=None, docker_transport=None) -> FastAPI:
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
            app.state.docker_transport = docker_transport
            app.state.demo_lock = asyncio.Lock()
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
    app.include_router(worker_admin.router)
    app.include_router(demo.router)

    @app.middleware("http")
    async def protect_api_origin(request: Request, call_next):
        if request.url.path.startswith("/internal/") and request.url.hostname not in {"controller", "localhost", "127.0.0.1", "::1", "testserver"}:
            return JSONResponse(status_code=404, content={"error": "NOT_FOUND", "message": "Route not found"})
        if (request.method in {"POST", "PUT", "PATCH", "DELETE"}
                and request.url.path.startswith("/api/v1/") and not worker_admin.same_origin(request)):
            return JSONResponse(status_code=403, content={"error": "ORIGIN_FORBIDDEN",
                "message": "API changes require a same-origin request"})
        if request.url.path.startswith("/api/v1/") and config.API_KEY and not secrets.compare_digest(request.headers.get("X-Artaud-Key", "").encode(), config.API_KEY.encode()):
            return JSONResponse(status_code=401, content={"error": "AUTH_REQUIRED", "message": "Enter the owner access key in Connection settings"})
        return await call_next(request)

    if config.ALLOWED_ORIGINS:
        app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS,
                           allow_methods=["GET", "POST", "PATCH", "DELETE"],
                           allow_headers=["Content-Type", "X-Artaud-Key", "X-Artaud-Admin", "ngrok-skip-browser-warning"],
                           expose_headers=["X-Object-SHA256", "ETag", "Content-Disposition"])

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

    default_openapi = app.openapi

    def openapi():
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = default_openapi()
        for path in schema["paths"].values():
            for operation in path.values():
                responses = operation.get("responses", {})
                validation = responses.get("422", {}).get("content", {}).get("application/json", {}).get("schema", {})
                if validation.get("$ref") == "#/components/schemas/HTTPValidationError":
                    del responses["422"]
                    responses.setdefault("400", {
                        "description": "Invalid request fields or JSON",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                    })
        return schema

    app.openapi = openapi
    return app


app = create_app()
