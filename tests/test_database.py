"""Metadata invariants required by the public API and B's reconciler."""
import importlib.util
import sqlite3
from datetime import datetime

import pytest


def test_controller_has_the_docker_import_target():
    assert importlib.util.find_spec("controller.main") is not None


@pytest.fixture
def db(tmp_path, monkeypatch):
    from controller import config, database
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    database.init_db()
    return database


def make_object(db, object_id="obj", status="UPLOADING"):
    db.create_object(object_id, "test.bin", "application/octet-stream", {"course": "CC"})
    if status != "UPLOADING":
        db.set_object_state(object_id, status)
    return object_id


def test_registration_is_joining_and_heartbeat_does_not_promote(db):
    assert db.touch_heartbeat("unknown") is False
    db.register_worker("w1", "http://worker1:8001")
    worker = db.get_workers()[0]
    assert worker["status"] == "JOINING"
    assert datetime.fromisoformat(worker["last_heartbeat"]).utcoffset().total_seconds() == 0
    assert db.touch_heartbeat("w1") is True
    assert db.get_workers()[0]["status"] == "JOINING"
    db.set_worker_state("w1", "DEAD")
    db.touch_heartbeat("w1")
    assert db.get_workers()[0]["status"] == "DEAD"
    db.register_worker("w1", "http://worker1:8001")
    assert len(db.get_workers()) == 1
    assert db.get_workers()[0]["status"] == "JOINING"


def test_registration_token_changes_only_on_registration_and_preserves_worker_shape(db):
    db.register_worker("w1", "http://worker1:8001")
    token = db.get_worker_registration("w1")
    assert token and len(token) == 32
    assert set(db.get_workers()[0]) == {"worker_id", "base_url", "status", "last_heartbeat", "chunk_count"}
    db.touch_heartbeat("w1")
    assert db.get_worker_registration("w1") == token
    db.register_worker("w1", "http://worker1:8001")
    assert db.get_worker_registration("w1") != token


def test_registration_token_migration_preserves_existing_worker(db):
    db.register_worker("w1", "http://worker1:8001")
    before = db.get_workers()
    with db.connection() as conn:
        conn.execute("DELETE FROM worker_registrations")
    db.init_db()
    token = db.get_worker_registration("w1")
    assert token and db.get_workers() == before
    db.init_db()
    assert db.get_worker_registration("w1") == token


def test_known_chunks_protect_uploads_but_exclude_abandoned_objects(db):
    for state in ("UPLOADING", "READY", "FAILED", "DELETING"):
        make_object(db, state, state)
        db.add_chunk(state + "_0", state, 0, 1, "a" * 64)
    assert db.known_chunk_ids() == {"UPLOADING_0", "READY_0"}
    assert [c["chunk_id"] for c in db.get_chunks_for_repair()] == ["READY_0"]


def test_manifest_order_replica_join_load_and_cascade(db):
    make_object(db)
    db.register_worker("w1", "http://worker1:8001")
    db.set_worker_state("w1", "ALIVE")
    for index in (2, 0, 1):
        db.add_chunk(f"obj_{index}", "obj", index, 1, "a" * 64)
        db.upsert_replica(f"obj_{index}", "w1", "HEALTHY")
        db.upsert_replica(f"obj_{index}", "w1", "HEALTHY")
    manifest = db.get_object_manifest("obj")
    assert [c["chunk_index"] for c in manifest["chunks"]] == [0, 1, 2]
    replicas = db.get_replicas("obj_0")
    assert len(replicas) == 1
    assert replicas[0]["base_url"] == "http://worker1:8001"
    assert replicas[0]["worker_status"] == "ALIVE"
    assert replicas[0]["last_verified_at"] is not None
    assert db.get_workers()[0]["chunk_count"] == 3
    db.delete_object_record("obj")
    assert db.get_replicas("obj_0") == []
    assert db.get_object_manifest("obj") is None


def test_constraints_reject_duplicate_indices_and_invalid_states(db):
    make_object(db)
    db.add_chunk("obj_0", "obj", 0, 1, "a" * 64)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_chunk("different", "obj", 0, 1, "a" * 64)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_chunk("missing_0", "missing", 0, 1, "a" * 64)
    with pytest.raises(sqlite3.IntegrityError):
        db.set_object_state("obj", "INVALID")


def test_ready_commit_requires_two_alive_copies(db):
    make_object(db)
    db.add_chunk("obj_0", "obj", 0, 1, "a" * 64)
    db.register_worker("w1", "http://worker1:8001")
    db.set_worker_state("w1", "ALIVE")
    db.upsert_replica("obj_0", "w1", "HEALTHY")
    assert db.finalize_object("obj", 1, 1, "b" * 64) is False
    assert db.get_object_manifest("obj")["status"] == "UPLOADING"
    db.register_worker("w2", "http://worker2:8001")
    db.upsert_replica("obj_0", "w2", "HEALTHY")
    assert db.finalize_object("obj", 1, 1, "b" * 64) is False
    db.set_worker_state("w2", "ALIVE")
    assert db.finalize_object("obj", 1, 1, "b" * 64) is True
    assert db.get_object_manifest("obj")["status"] == "READY"


def test_restart_retains_ready_but_abandons_uploads_and_worker_liveness(db):
    make_object(db, "ready", "READY")
    make_object(db, "partial")
    db.register_worker("w1", "http://worker1:8001")
    db.set_worker_state("w1", "ALIVE")
    db.init_db()
    db.prepare_restart()
    assert db.get_object_manifest("ready")["status"] == "READY"
    assert db.get_object_manifest("partial")["status"] == "FAILED"
    assert db.get_workers()[0]["status"] == "JOINING"


def test_metadata_merge_preserves_existing_keys_and_object_bytes(db):
    make_object(db, status="READY")
    before = db.get_object_manifest("obj")
    assert db.patch_metadata("obj", {"reviewed": True})
    after = db.get_object_manifest("obj")
    assert after["metadata"] == {"course": "CC", "reviewed": True}
    for field in ("created_at", "sha256", "size", "num_chunks"):
        assert after[field] == before[field]


def test_worker_state_compare_and_set_does_not_overwrite_new_heartbeat(db):
    db.register_worker("w1", "http://worker1:8001")
    old = db.get_workers()[0]["last_heartbeat"]
    db.touch_heartbeat("w1")
    assert db.transition_worker("w1", old, "DEAD") is False
    assert db.get_workers()[0]["status"] == "JOINING"


def test_ready_commit_does_not_count_stale_heartbeat_as_available(db):
    make_object(db)
    db.add_chunk("obj_0", "obj", 0, 1, "a" * 64)
    for wid in ("w1", "w2"):
        db.register_worker(wid, f"http://{wid}:8001")
        db.set_worker_state(wid, "ALIVE")
        db.upsert_replica("obj_0", wid, "HEALTHY")
    with db.connection() as conn:
        conn.execute("UPDATE workers SET last_heartbeat='2000-01-01T00:00:00+00:00' WHERE worker_id='w1'")
    assert db.finalize_object("obj", 1, 1, "b" * 64) is False
