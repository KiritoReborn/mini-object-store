"""Dashboard summaries describe authoritative metadata without probing workers."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def dashboard(tmp_path, monkeypatch, no_recovery_module):
    from controller import config, database, main

    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    monkeypatch.setattr(main, "STATIC_DIR", static, raising=False)

    def unexpected_http(request):
        raise AssertionError(f"Overview must not contact a worker: {request.url}")

    with TestClient(main.create_app(worker_transport=httpx.MockTransport(unexpected_http))) as client:
        yield client, database, static


def add_object(db, object_id, status, sizes):
    db.create_object(object_id, object_id + ".bin", "application/octet-stream", {})
    for index, size in enumerate(sizes):
        db.add_chunk(f"{object_id}_{index}", object_id, index, size, "a" * 64)
    with db.connection() as conn:
        conn.execute("UPDATE objects SET status=?, size=?, num_chunks=? WHERE object_id=?",
                     (status, sum(sizes), len(sizes), object_id))


def add_worker(db, worker_id, status="ALIVE", heartbeat=None):
    db.register_worker(worker_id, f"http://{worker_id}:8001")
    db.set_worker_state(worker_id, status)
    if heartbeat is not None:
        with db.connection() as conn:
            conn.execute("UPDATE workers SET last_heartbeat=? WHERE worker_id=?", (heartbeat, worker_id))


def test_overview_empty_store_has_real_zero_totals(dashboard):
    client, _, _ = dashboard
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    assert response.json() == {
        "object_count": 0, "logical_bytes": 0, "chunk_count": 0,
        "healthy_replica_count": 0, "under_replicated_chunks": 0, "corrupt_replicas": 0,
        "worker_count": 0, "available_workers": 0, "replication_factor": 2,
        "chunk_size": 1_000_000, "recovery_available": False, "workers": [],
    }


def test_overview_ready_totals_exclude_uploads_and_report_stale_or_corrupt_copies(dashboard):
    client, db, _ = dashboard
    add_object(db, "ready", "READY", [4, 6, 2])
    add_object(db, "upload", "UPLOADING", [9])
    add_worker(db, "alive")
    add_worker(db, "fresh")
    add_worker(db, "stale", heartbeat="2000-01-01T00:00:00+00:00")
    add_worker(db, "joining", "JOINING")
    db.upsert_replica("ready_0", "alive", "HEALTHY")
    db.upsert_replica("ready_0", "fresh", "HEALTHY")
    db.upsert_replica("ready_1", "alive", "HEALTHY")
    db.upsert_replica("ready_1", "stale", "HEALTHY")
    db.upsert_replica("ready_1", "joining", "HEALTHY")
    db.upsert_replica("ready_1", "fresh", "CORRUPT")
    db.upsert_replica("ready_2", "fresh", "MISSING")
    db.upsert_replica("ready_2", "alive", "PENDING_DELETE")
    db.upsert_replica("upload_0", "alive", "HEALTHY")
    db.upsert_replica("upload_0", "fresh", "CORRUPT")

    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    result = response.json()
    assert {key: result[key] for key in (
        "object_count", "logical_bytes", "chunk_count", "healthy_replica_count",
        "under_replicated_chunks", "corrupt_replicas", "worker_count", "available_workers"
    )} == {
        "object_count": 1, "logical_bytes": 12, "chunk_count": 3,
        "healthy_replica_count": 3, "under_replicated_chunks": 2, "corrupt_replicas": 1,
        "worker_count": 4, "available_workers": 2,
    }
    workers = {worker["worker_id"]: worker for worker in result["workers"]}
    assert workers["alive"]["chunk_count"] == 3
    assert workers["alive"]["stored_bytes"] == 19
    assert workers["fresh"]["stored_bytes"] == 4
    assert workers["stale"]["status"] == "ALIVE"
    assert workers["stale"]["available"] is False
    assert workers["stale"]["stored_bytes"] == 6
    assert workers["joining"]["available"] is False


@pytest.mark.parametrize("status,heartbeat,available,invalid", [
    ("ALIVE", "fresh", True, False),
    ("JOINING", "fresh", False, False),
    ("DEAD", "fresh", False, False),
    ("ALIVE", "2000-01-01T00:00:00+00:00", False, False),
    ("ALIVE", "not-a-time", False, True),
    ("ALIVE", "2026-01-01T00:00:00", False, True),
    ("ALIVE", "future", False, False),
    ("ALIVE", "null", False, True),
])
def test_overview_worker_availability_requires_fresh_aware_heartbeat(
        dashboard, status, heartbeat, available, invalid):
    client, db, _ = dashboard
    if heartbeat == "fresh":
        heartbeat = datetime.now(timezone.utc).isoformat()
    elif heartbeat == "future":
        heartbeat = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    add_worker(db, "worker", status, heartbeat)
    if heartbeat == "null":
        with db.connection() as conn:
            conn.execute("UPDATE workers SET last_heartbeat=NULL")
        heartbeat = None
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    worker = response.json()["workers"][0]
    assert set(worker) == {"worker_id", "status", "last_heartbeat", "heartbeat_age_seconds",
                           "available", "chunk_count", "stored_bytes"}
    assert worker["status"] == status
    assert worker["last_heartbeat"] == heartbeat
    assert worker["available"] is available
    assert response.json()["available_workers"] == int(available)
    if invalid:
        assert worker["heartbeat_age_seconds"] is None
    elif heartbeat and datetime.fromisoformat(heartbeat) > datetime.now(timezone.utc):
        assert worker["heartbeat_age_seconds"] < 0
    else:
        assert worker["heartbeat_age_seconds"] >= 0


def test_overview_does_not_mutate_or_contact_workers_and_reports_recovery(dashboard):
    client, db, _ = dashboard
    add_worker(db, "worker")
    add_object(db, "ready", "READY", [5])
    db.upsert_replica("ready_0", "worker", "HEALTHY")

    def records():
        with db.connection() as conn:
            return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]
                    for table in ("objects", "chunks", "workers", "replicas")}

    before = records()
    client.app.state.recovery_available = True
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    assert response.json()["recovery_available"] is True
    assert records() == before


def test_overview_reads_one_snapshot_while_ready_object_changes(tmp_path, monkeypatch):
    from controller import config, database as db
    from controller.dashboard import overview
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    db.init_db()  # Test the transaction directly, with no application background tasks.
    add_worker(db, "worker")
    add_object(db, "ready", "READY", [5])
    db.upsert_replica("ready_0", "worker", "HEALTHY")
    original_connection = db.connection

    @contextmanager
    def concurrent_connection():
        with original_connection() as conn:
            reads = 0

            def trace(statement):
                nonlocal reads
                if statement.lstrip().upper().startswith("SELECT"):
                    reads += 1
                    if reads == 2:
                        with original_connection() as writer:
                            writer.execute("UPDATE objects SET status='FAILED' WHERE object_id='ready'")

            conn.set_trace_callback(trace)
            yield conn

    monkeypatch.setattr(db, "connection", concurrent_connection)
    result = overview(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(recovery_available=False))))
    assert result["object_count"] == 1
    assert result["logical_bytes"] == 5
    assert result["chunk_count"] == 1
    assert result["healthy_replica_count"] == 1
    assert result["under_replicated_chunks"] == 1
    assert result["workers"][0]["stored_bytes"] == 5
    with original_connection() as conn:
        assert conn.execute("SELECT status FROM objects WHERE object_id='ready'").fetchone()[0] == "FAILED"


def test_missing_dashboard_build_returns_meaningful_503_without_api_fallback(dashboard):
    client, _, _ = dashboard
    response = client.get("/")
    assert response.status_code == 503
    assert "dashboard" in response.json()["message"].lower()
    assert client.get("/api/v1/does-not-exist").status_code == 404
    assert client.get("/unmatched-page").status_code == 404


def test_dashboard_serves_index_without_cache_and_only_assets_directory(dashboard):
    client, _, static = dashboard
    (static / "index.html").write_text("<!doctype html><title>Object store</title>", encoding="utf-8")
    (static / "assets" / "app-123.js").write_text("console.log('dashboard')", encoding="utf-8")
    (static / "private.txt").write_text("not public", encoding="utf-8")
    response = client.get("/")
    assert response.status_code == 200
    assert "Object store" in response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "no-cache" in response.headers["cache-control"]
    assert client.get("/assets/app-123.js").status_code == 200
    assert client.get("/private.txt").status_code == 404
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/v1/does-not-exist").status_code == 404
