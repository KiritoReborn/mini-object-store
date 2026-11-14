"""Short, synchronous SQLite transactions; never perform HTTP calls here.

Public functions are also the direct import contract for recovery.py/status.py.
Each call owns and closes its connection, so request threads share no connection.
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config, telemetry
from .placement import heartbeat_is_fresh


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@contextmanager
def connection():
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))


def prepare_restart() -> None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute("SELECT worker_id, status FROM workers WHERE status!='JOINING'").fetchall()
        conn.execute("UPDATE workers SET status='JOINING'")
        conn.execute("UPDATE objects SET status='FAILED' WHERE status='UPLOADING'")
    for worker in changed:
        telemetry.record_event("worker_state", worker_id=worker["worker_id"],
                               previous_state=worker["status"], state="JOINING")


def register_worker(worker_id: str, base_url: str) -> None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = conn.execute("SELECT status FROM workers WHERE worker_id=?", (worker_id,)).fetchone()
        conn.execute("""INSERT INTO workers VALUES (?, ?, ?, 'JOINING')
            ON CONFLICT(worker_id) DO UPDATE SET base_url=excluded.base_url,
            last_heartbeat=excluded.last_heartbeat, status='JOINING'""",
            (worker_id, base_url, utc_now()))
    previous = before[0] if before else None
    if previous != "JOINING":
        telemetry.record_event("worker_state", worker_id=worker_id, previous_state=previous, state="JOINING")


def touch_heartbeat(worker_id: str) -> bool:
    with connection() as conn:
        return conn.execute("UPDATE workers SET last_heartbeat=? WHERE worker_id=?",
                            (utc_now(), worker_id)).rowcount == 1


def set_worker_state(worker_id: str, state: str) -> None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = conn.execute("SELECT status FROM workers WHERE worker_id=?", (worker_id,)).fetchone()
        conn.execute("UPDATE workers SET status=? WHERE worker_id=?", (state, worker_id))
    if before and before[0] != state:
        telemetry.record_event("worker_state", worker_id=worker_id, previous_state=before[0], state=state)


def transition_worker(worker_id: str, expected_heartbeat: str, state: str) -> bool:
    """Compare-and-set prevents a stale liveness scan overwriting a new heartbeat."""
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = conn.execute("SELECT status FROM workers WHERE worker_id=?", (worker_id,)).fetchone()
        updated = conn.execute("UPDATE workers SET status=? WHERE worker_id=? AND last_heartbeat=?",
                               (state, worker_id, expected_heartbeat)).rowcount == 1
    if updated and before[0] != state:
        telemetry.record_event("worker_state", worker_id=worker_id, previous_state=before[0], state=state)
    return updated


def get_workers() -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute("""SELECT w.*,
            (SELECT count(*) FROM replicas r JOIN chunks c USING(chunk_id)
             JOIN objects o USING(object_id) WHERE r.worker_id=w.worker_id
             AND r.state='HEALTHY' AND o.status IN ('UPLOADING','READY')) AS chunk_count
            FROM workers w ORDER BY worker_id""")]


def get_placement_workers() -> list[dict]:
    """A-side upload selection only; recovery's get_workers contract is unchanged."""
    with connection() as conn:
        return [dict(row) for row in conn.execute("""SELECT w.*,
            (SELECT count(*) FROM replicas r JOIN chunks c USING(chunk_id)
             JOIN objects o USING(object_id) WHERE r.worker_id=w.worker_id
             AND r.state='HEALTHY' AND o.status IN ('UPLOADING','READY')) AS chunk_count
            FROM workers w LEFT JOIN worker_settings s USING(worker_id)
            WHERE coalesce(s.placement_enabled, 1)=1 ORDER BY worker_id""")]


def heartbeat_is_stale_or_absent(timestamp: str | None) -> bool:
    if timestamp is None:
        return True
    try:
        heartbeat = datetime.fromisoformat(timestamp)
        return (heartbeat.utcoffset() is not None
                and (datetime.now(timezone.utc) - heartbeat).total_seconds() >= config.WORKER_DEAD_TIMEOUT)
    except (ValueError, TypeError):
        return False


def _managed_workers(conn, worker_id: str | None = None) -> list[dict]:
    workers = [dict(row) for row in conn.execute("""SELECT w.*,
        coalesce(s.display_name, '') AS display_name, coalesce(s.notes, '') AS notes,
        coalesce(s.placement_enabled, 1) AS placement_enabled,
        (SELECT count(*) FROM replicas r WHERE r.worker_id=w.worker_id) AS replica_count,
        coalesce(load.chunk_count, 0) AS chunk_count, coalesce(load.stored_bytes, 0) AS stored_bytes
        FROM workers w LEFT JOIN worker_settings s USING(worker_id)
        LEFT JOIN (
            SELECT r.worker_id, count(*) AS chunk_count, sum(c.size) AS stored_bytes
            FROM replicas r JOIN chunks c USING(chunk_id) JOIN objects o USING(object_id)
            WHERE r.state='HEALTHY' AND o.status IN ('UPLOADING','READY') GROUP BY r.worker_id
        ) AS load USING(worker_id)
        WHERE (? IS NULL OR w.worker_id=?) ORDER BY w.worker_id""", (worker_id, worker_id))]
    for worker in workers:
        worker["placement_enabled"] = bool(worker["placement_enabled"])
        worker["can_forget"] = worker["replica_count"] == 0 and heartbeat_is_stale_or_absent(worker["last_heartbeat"])
    return workers


def get_managed_workers() -> list[dict]:
    with connection() as conn:
        return _managed_workers(conn)


def _write_worker_settings(conn, worker_id: str, changes: dict) -> bool:
    if not changes:
        return False
    before = conn.execute("SELECT * FROM worker_settings WHERE worker_id=?", (worker_id,)).fetchone()
    current = dict(before) if before else {"display_name": "", "notes": "", "placement_enabled": True}
    fields = [key for key in ("display_name", "notes", "placement_enabled") if key in changes]
    if not any(current[key] != changes[key] for key in fields):
        return False
    conn.execute("INSERT OR IGNORE INTO worker_settings(worker_id) VALUES (?)", (worker_id,))
    conn.execute(f"UPDATE worker_settings SET {', '.join(key + '=?' for key in fields)} WHERE worker_id=?",
                 (*[changes[key] for key in fields], worker_id))
    return True


def connect_managed_worker(worker_id: str, base_url: str, changes: dict) -> dict:
    """Health was checked outside this atomic insert; an existing state is preserved."""
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = conn.execute("SELECT base_url FROM workers WHERE worker_id=?", (worker_id,)).fetchone()
        if before and before[0] != base_url:
            raise ValueError("Worker is already registered at a different origin")
        if before is None:
            conn.execute("INSERT INTO workers VALUES (?, ?, ?, 'JOINING')", (worker_id, base_url, utc_now()))
        changed = _write_worker_settings(conn, worker_id, changes)
        worker = _managed_workers(conn, worker_id)[0]
    if before is None:
        telemetry.record_event("worker_connected", worker_id=worker_id, state="JOINING")
    if changed:
        telemetry.record_event("worker_settings", worker_id=worker_id)
    return worker


def update_worker_settings(worker_id: str, changes: dict) -> dict | None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM workers WHERE worker_id=?", (worker_id,)).fetchone():
            return None
        changed = _write_worker_settings(conn, worker_id, changes)
        worker = _managed_workers(conn, worker_id)[0]
    if changed:
        telemetry.record_event("worker_settings", worker_id=worker_id)
    return worker


def forget_worker(worker_id: str) -> str:
    """Recheck liveness and every replica under the same write lock as deletion."""
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        workers = _managed_workers(conn, worker_id)
        if not workers:
            return "missing"
        if not workers[0]["can_forget"]:
            return "protected"
        conn.execute("DELETE FROM workers WHERE worker_id=?", (worker_id,))
    telemetry.record_event("worker_forgotten", worker_id=worker_id)
    return "forgotten"


def get_overview_snapshot() -> dict:
    """Read totals, recorded worker load and READY replicas in one snapshot."""
    with connection() as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        totals = dict(conn.execute("""SELECT count(*) AS object_count,
            coalesce(sum(size), 0) AS logical_bytes FROM objects WHERE status='READY'""").fetchone())
        totals["workers"] = [dict(row) for row in conn.execute("""SELECT
            w.worker_id, w.status, w.last_heartbeat,
            coalesce(load.chunk_count, 0) AS chunk_count,
            coalesce(load.stored_bytes, 0) AS stored_bytes
            FROM workers w LEFT JOIN (
                SELECT r.worker_id, count(*) AS chunk_count, sum(c.size) AS stored_bytes
                FROM replicas r JOIN chunks c USING(chunk_id) JOIN objects o USING(object_id)
                WHERE r.state='HEALTHY' AND o.status IN ('UPLOADING','READY')
                GROUP BY r.worker_id
            ) AS load USING(worker_id) ORDER BY w.worker_id""")]
        totals["replicas"] = [dict(row) for row in conn.execute("""SELECT
            c.chunk_id, r.worker_id, r.state FROM chunks c JOIN objects o USING(object_id)
            LEFT JOIN replicas r USING(chunk_id) WHERE o.status='READY'""")]
        return totals


def get_chunks_for_repair() -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute("""SELECT c.* FROM chunks c
            JOIN objects o USING(object_id) WHERE o.status='READY'
            ORDER BY c.object_id, c.chunk_index""")]


def _replicas(conn, chunk_id: str) -> list[dict]:
    return [dict(row) for row in conn.execute("""SELECT r.worker_id, r.state,
        r.last_verified_at, w.base_url, w.status AS worker_status, w.last_heartbeat
        FROM replicas r JOIN workers w USING(worker_id) WHERE r.chunk_id=?
        ORDER BY r.worker_id""", (chunk_id,))]


def get_replicas(chunk_id: str) -> list[dict]:
    with connection() as conn:
        return _replicas(conn, chunk_id)


def _replica_before(conn, chunk_id: str, worker_id: str):
    return conn.execute("""SELECT c.object_id, c.size, r.state FROM chunks c
        LEFT JOIN replicas r ON r.chunk_id=c.chunk_id AND r.worker_id=?
        WHERE c.chunk_id=?""", (worker_id, chunk_id)).fetchone()


def _replica_changed(before, chunk_id: str, worker_id: str, state: str | None) -> None:
    if before and before["state"] != state:
        telemetry.record_event("replica_state", chunk_id=chunk_id, worker_id=worker_id,
            object_id=before["object_id"], size=before["size"], previous_state=before["state"], state=state)


def upsert_replica(chunk_id: str, worker_id: str, state: str) -> None:
    verified = utc_now() if state == "HEALTHY" else None
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = _replica_before(conn, chunk_id, worker_id)
        conn.execute("""INSERT INTO replicas VALUES (?, ?, ?, ?)
            ON CONFLICT(chunk_id, worker_id) DO UPDATE SET
            state=excluded.state, last_verified_at=excluded.last_verified_at""",
            (chunk_id, worker_id, state, verified))
    _replica_changed(before, chunk_id, worker_id, state)


def set_replica_state(chunk_id: str, worker_id: str, state: str) -> None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = _replica_before(conn, chunk_id, worker_id)
        conn.execute("""UPDATE replicas SET state=?, last_verified_at=?
            WHERE chunk_id=? AND worker_id=?""",
            (state, utc_now() if state == "HEALTHY" else None, chunk_id, worker_id))
    if before and before["state"] is not None:
        _replica_changed(before, chunk_id, worker_id, state)


def delete_replica_record(chunk_id: str, worker_id: str) -> None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = _replica_before(conn, chunk_id, worker_id)
        conn.execute("DELETE FROM replicas WHERE chunk_id=? AND worker_id=?", (chunk_id, worker_id))
    _replica_changed(before, chunk_id, worker_id, None)


def known_chunk_ids() -> set[str]:
    with connection() as conn:
        return {row[0] for row in conn.execute("""SELECT chunk_id FROM chunks
            JOIN objects USING(object_id) WHERE status IN ('UPLOADING','READY')""")}


def _object(row) -> dict:
    result = dict(row)
    result["metadata"] = json.loads(result.pop("custom_metadata_json"))
    return result


def get_object_manifest(object_id: str) -> dict | None:
    with connection() as conn:
        conn.execute("BEGIN")  # One consistent snapshot for object, chunks and replicas.
        row = conn.execute("SELECT * FROM objects WHERE object_id=?", (object_id,)).fetchone()
        if row is None:
            return None
        obj = _object(row)
        obj["chunks"] = []
        for row in conn.execute("SELECT * FROM chunks WHERE object_id=? ORDER BY chunk_index", (object_id,)):
            chunk = dict(row)
            chunk["replicas"] = _replicas(conn, chunk["chunk_id"])
            obj["chunks"].append(chunk)
        return obj


def create_object(object_id: str, name: str, content_type: str, metadata: dict) -> None:
    now = utc_now()
    with connection() as conn:
        conn.execute("""INSERT INTO objects VALUES (?, ?, 0, ?, ?, ?, ?, 0, ?, 'UPLOADING')""",
            (object_id, name, content_type, now, now, hashlib.sha256(b"").hexdigest(),
             json.dumps(metadata, ensure_ascii=False, allow_nan=False)))


def add_chunk(chunk_id: str, object_id: str, index: int, size: int, sha256: str) -> None:
    with connection() as conn:
        conn.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)", (chunk_id, object_id, index, size, sha256))


def set_object_state(object_id: str, state: str) -> None:
    with connection() as conn:
        conn.execute("UPDATE objects SET status=? WHERE object_id=?", (state, object_id))


def finalize_object(object_id: str, size: int, num_chunks: int, sha256: str) -> bool:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        chunks = conn.execute("SELECT * FROM chunks WHERE object_id=? ORDER BY chunk_index", (object_id,)).fetchall()
        if len(chunks) != num_chunks or sum(c["size"] for c in chunks) != size:
            return False
        for index, chunk in enumerate(chunks):
            eligible = {r["worker_id"] for r in _replicas(conn, chunk["chunk_id"])
                        if r["state"] == "HEALTHY" and r["worker_status"] == "ALIVE"
                        and heartbeat_is_fresh(r["last_heartbeat"])}
            if chunk["chunk_index"] != index or len(eligible) < config.REPLICATION_FACTOR:
                return False
        committed = conn.execute("""UPDATE objects SET size=?, num_chunks=?, sha256=?, status='READY'
            WHERE object_id=? AND status='UPLOADING'""", (size, num_chunks, sha256, object_id)).rowcount == 1
        row = conn.execute("SELECT name FROM objects WHERE object_id=?", (object_id,)).fetchone() if committed else None
    if committed:
        telemetry.record_event("object_ready", object_id=object_id, size=size, name=row[0],
                               previous_state="UPLOADING", state="READY")
    return committed


def list_objects() -> list[dict]:
    with connection() as conn:
        return [_object(row) for row in conn.execute("SELECT * FROM objects WHERE status='READY' ORDER BY created_at, object_id")]


def patch_metadata(object_id: str, changes: dict) -> bool:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT custom_metadata_json, name FROM objects WHERE object_id=? AND status='READY'", (object_id,)).fetchone()
        if row is None:
            return False
        metadata = json.loads(row[0])
        metadata.update(changes)
        encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > config.MAX_METADATA_BYTES:
            raise ValueError("Merged metadata exceeds the size limit")
        conn.execute("UPDATE objects SET custom_metadata_json=?, updated_at=? WHERE object_id=?", (encoded, utc_now(), object_id))
    if encoded != row[0]:
        telemetry.record_event("metadata_updated", object_id=object_id, name=row[1])
    return True


def delete_object_record(object_id: str) -> None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = conn.execute("SELECT name, size, status FROM objects WHERE object_id=?", (object_id,)).fetchone()
        conn.execute("DELETE FROM objects WHERE object_id=?", (object_id,))
    if before and before["status"] in {"READY", "DELETING"}:
        telemetry.record_event("object_deleted", object_id=object_id, name=before["name"],
                               size=before["size"], previous_state=before["status"])


def get_abandoned_object_ids() -> list[str]:
    with connection() as conn:
        return [row[0] for row in conn.execute("SELECT object_id FROM objects WHERE status IN ('FAILED','DELETING')")]
