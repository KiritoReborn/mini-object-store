"""Observed controller activity must follow verified I/O and committed metadata."""
import asyncio
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_api import system, upload


@pytest.fixture(autouse=True)
def journal(monkeypatch):
    from controller import telemetry

    fresh = telemetry.ActivityJournal()
    monkeypatch.setattr(telemetry, "_journal", fresh)
    return telemetry


@pytest.fixture
def db(tmp_path, monkeypatch):
    from controller import config, database

    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    database.init_db()
    return database


def events(journal, kind=None):
    result = journal.get_activity()["events"]
    return result if kind is None else [event for event in result if event["kind"] == kind]


def test_activity_empty_stream_has_cursor_contract(tmp_path, monkeypatch):
    from controller import config, main

    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    with TestClient(main.create_app(worker_transport=httpx.MockTransport(
            lambda request: httpx.Response(204)))) as client:
        response = client.get("/api/v1/activity?after=0")
        assert response.status_code == 200
        result = response.json()
        assert result["stream_id"]
        assert {key: result[key] for key in (
            "oldest_id", "latest_id", "next_cursor", "truncated", "events"
        )} == {"oldest_id": 0, "latest_id": 0, "next_cursor": 0,
               "truncated": False, "events": []}
        assert client.get("/api/v1/activity?after=-1").status_code == 400
        assert client.get("/api/v1/activity?after=bad").status_code == 400


def test_journal_returns_all_retained_events_and_detects_cursor_gaps(journal):
    for index in range(600):
        journal.record_event("repair_started", chunk_id=str(index))
    snapshot = journal.get_activity(0)
    assert (snapshot["oldest_id"], snapshot["latest_id"], snapshot["next_cursor"]) == (89, 600, 600)
    assert snapshot["truncated"] is True
    assert [event["id"] for event in snapshot["events"]] == list(range(89, 601))
    assert len(journal.get_activity(88)["events"]) == 512
    assert journal.get_activity(88)["truncated"] is False
    tail = journal.get_activity(599)
    assert [event["id"] for event in tail["events"]] == [600]
    assert tail["next_cursor"] == 600
    assert tail["truncated"] is False
    assert journal.get_activity(600)["events"] == []
    assert journal.get_activity(600)["next_cursor"] == 600
    ahead = journal.get_activity(900)
    assert ahead["events"] == snapshot["events"]
    assert ahead["next_cursor"] == 600
    assert ahead["truncated"] is True


def test_new_process_stream_resets_identity_and_accepts_old_cursor(journal, monkeypatch):
    journal.record_event("repair_started")
    first = journal.get_activity()
    monkeypatch.setattr(journal, "_journal", journal.ActivityJournal())
    empty = journal.get_activity(first["next_cursor"])
    assert empty["stream_id"] != first["stream_id"]
    assert empty["events"] == []
    assert empty["next_cursor"] == 0
    assert empty["truncated"] is True
    journal.record_event("repair_completed")
    assert journal.get_activity()["latest_id"] == 1


def test_concurrent_publish_and_read_preserve_bounded_monotonic_snapshots(journal):
    def publish(worker):
        for index in range(100):
            journal.record_event("repair_started", worker_id=f"w{worker}")
            snapshot = journal.get_activity()
            ids = [event["id"] for event in snapshot["events"]]
            assert len(ids) <= 512
            assert ids == list(range(snapshot["oldest_id"], snapshot["latest_id"] + 1))
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(publish, range(8)))
    final = journal.get_activity()
    assert (len(final["events"]), final["oldest_id"], final["latest_id"]) == (512, 289, 800)


def test_event_payload_is_bounded_nullable_and_copied_without_private_fields(journal):
    journal.record_event("repair_started", worker_id="w" * 2000, detail="x" * 2000,
                         base_url="http://secret", metadata={"token": "secret"}, size=-1)
    event = events(journal)[0]
    assert set(event) == {"id", "timestamp", "kind", "object_id", "chunk_id", "worker_id",
                          "transfer_id", "direction", "size", "state", "previous_state", "name", "detail"}
    assert datetime.fromisoformat(event["timestamp"]).utcoffset().total_seconds() == 0
    assert 0 < len(event["worker_id"]) <= 512
    assert 0 < len(event["detail"]) <= 512
    assert event["size"] is None
    assert event["object_id"] is None
    assert "secret" not in json.dumps(event)
    event["kind"] = "tampered"
    assert events(journal)[0]["kind"] == "repair_started"


def test_worker_events_follow_changes_not_heartbeats_or_failed_compare_and_set(db, journal):
    db.register_worker("w1", "http://private:8001")
    db.register_worker("w1", "http://private:8001")
    db.touch_heartbeat("w1")
    db.set_worker_state("absent", "ALIVE")
    db.set_worker_state("w1", "ALIVE")
    db.set_worker_state("w1", "ALIVE")
    old = db.get_workers()[0]["last_heartbeat"]
    db.touch_heartbeat("w1")
    assert db.transition_worker("w1", old, "DEAD") is False
    assert db.transition_worker("w1", db.get_workers()[0]["last_heartbeat"], "DEAD") is True
    db.register_worker("w1", "http://private:8001")
    assert [(event["previous_state"], event["state"]) for event in events(journal, "worker_state")] == [
        (None, "JOINING"), ("JOINING", "ALIVE"), ("ALIVE", "DEAD"), ("DEAD", "JOINING")]
    assert "private" not in json.dumps(events(journal))


def test_replica_events_follow_committed_changes_and_removal(db, journal):
    db.create_object("obj", "file.bin", "application/octet-stream", {})
    db.add_chunk("obj_0", "obj", 0, 1, "a" * 64)
    db.register_worker("w1", "http://private:8001")
    db.upsert_replica("obj_0", "w1", "PENDING_DELETE")
    db.upsert_replica("obj_0", "w1", "PENDING_DELETE")
    db.set_replica_state("missing", "w1", "CORRUPT")
    db.upsert_replica("obj_0", "w1", "HEALTHY")
    db.set_replica_state("obj_0", "w1", "CORRUPT")
    db.set_replica_state("obj_0", "w1", "CORRUPT")
    db.delete_replica_record("obj_0", "w1")
    db.delete_replica_record("obj_0", "w1")
    recorded = events(journal, "replica_state")
    assert [(event["previous_state"], event["state"]) for event in recorded] == [
        (None, "PENDING_DELETE"), ("PENDING_DELETE", "HEALTHY"), ("HEALTHY", "CORRUPT"), ("CORRUPT", None)]
    assert all(event["object_id"] == "obj" and event["chunk_id"] == "obj_0" for event in recorded)


def test_failed_commit_and_invalid_state_publish_no_events(db, journal, monkeypatch):
    db.register_worker("w1", "http://private:8001")
    baseline = events(journal)
    with pytest.raises(sqlite3.IntegrityError):
        db.set_worker_state("w1", "INVALID")
    original = db.connection

    @contextmanager
    def failed_commit():
        with original() as conn:
            yield conn
            raise sqlite3.OperationalError("commit refused")

    with monkeypatch.context() as patch:
        patch.setattr(db, "connection", failed_commit)
        with pytest.raises(sqlite3.OperationalError):
            db.set_worker_state("w1", "ALIVE")
    assert db.get_workers()[0]["status"] == "JOINING"
    assert events(journal) == baseline


def test_restart_only_reports_workers_actually_changed(db, journal):
    db.register_worker("alive", "http://alive:8001")
    db.set_worker_state("alive", "ALIVE")
    db.register_worker("joining", "http://joining:8001")
    cursor = journal.get_activity()["next_cursor"]
    db.prepare_restart()
    db.prepare_restart()
    changes = journal.get_activity(cursor)["events"]
    assert [(event["worker_id"], event["previous_state"], event["state"]) for event in changes] == [
        ("alive", "ALIVE", "JOINING")]


def test_concurrent_same_state_changes_emit_one_transition(db, journal):
    db.register_worker("w1", "http://w1:8001")
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: db.set_worker_state("w1", "ALIVE"), range(16)))
    assert [(event["previous_state"], event["state"]) for event in events(journal, "worker_state")] == [
        (None, "JOINING"), ("JOINING", "ALIVE")]


def test_verified_upload_download_and_object_lifecycle_are_observed(system, journal):
    client, _, db, _ = system
    response = upload(client, b"trusted", {"private": "secret"})
    assert response.status_code == 201
    oid = response.json()["object_id"]
    assert client.get(f"/api/v1/objects/{oid}").content == b"trusted"
    assert client.patch(f"/api/v1/objects/{oid}/metadata", json={"metadata": {"private": "new secret"}}).status_code == 200
    assert client.delete(f"/api/v1/objects/{oid}").status_code == 204
    recorded = client.get("/api/v1/activity").json()["events"]
    transfers = [event for event in recorded if event["transfer_id"]]
    starts = [event for event in transfers if event["kind"] == "transfer_started"]
    assert len(starts) == 3
    assert [event["direction"] for event in starts] == ["to_worker", "to_worker", "from_worker"]
    for event in starts:
        pair = [item for item in transfers if item["transfer_id"] == event["transfer_id"]]
        assert [item["kind"] for item in pair] == ["transfer_started", "transfer_completed"]
        assert all(item["size"] == 7 and item["object_id"] == oid for item in pair)
    lifecycle = [event["kind"] for event in recorded if event["kind"] in {
        "object_ready", "metadata_updated", "object_deleted"}]
    assert lifecycle == ["object_ready", "metadata_updated", "object_deleted"]
    assert "secret" not in json.dumps(recorded)
    assert db.get_object_manifest(oid) is None


@pytest.mark.parametrize("failure,attempts", [("lost_reply", 2), ("bad_ack", 1), ("fail_put", 2)])
def test_write_retries_have_distinct_ids_and_unverified_writes_never_complete(system, journal, failure, attempts):
    client, state, _, _ = system
    state[failure] = {"worker1"}
    assert upload(client).status_code == 201
    recorded = [event for event in events(journal) if event["worker_id"] == "worker1" and event["transfer_id"]]
    assert [event["kind"] for event in recorded] == ["transfer_started", "transfer_failed"] * attempts
    starts = recorded[::2]
    assert len({event["transfer_id"] for event in starts}) == attempts
    assert all(a["transfer_id"] == b["transfer_id"] for a, b in zip(recorded[::2], recorded[1::2]))


def test_corrupt_download_attempt_fails_then_verified_fallback_completes(system, journal):
    client, state, db, _ = system
    oid = upload(client, b"trusted").json()["object_id"]
    cursor = journal.get_activity()["next_cursor"]
    state["forged"] = {"worker1"}
    response = client.get(f"/api/v1/objects/{oid}")
    assert response.content == b"trusted"
    recorded = journal.get_activity(cursor)["events"]
    transfers = [event for event in recorded if event["transfer_id"]]
    assert [(event["worker_id"], event["kind"]) for event in transfers] == [
        ("worker1", "transfer_started"), ("worker1", "transfer_failed"),
        ("worker2", "transfer_started"), ("worker2", "transfer_completed")]
    assert [(event["previous_state"], event["state"]) for event in recorded if event["kind"] == "replica_state"] == [("HEALTHY", "CORRUPT")]
    assert db.get_replicas(oid + "_0")[0]["state"] == "CORRUPT"


@pytest.mark.parametrize("operation", ["put", "get", "get-stream"])
def test_cancelled_transfer_has_failed_terminal_and_preserves_cancellation(db, journal, operation):
    from controller import objects

    data = b"trusted"
    chunk = {"chunk_id": "obj_0", "object_id": "obj", "size": 7,
             "sha256": hashlib.sha256(data).hexdigest()}
    db.create_object("obj", "file.bin", "application/octet-stream", {})
    db.add_chunk("obj_0", "obj", 0, 7, chunk["sha256"])
    db.register_worker("w1", "http://w1:8001")
    db.set_worker_state("w1", "ALIVE")
    db.upsert_replica("obj_0", "w1", "HEALTHY")

    async def scenario():
        entered = asyncio.Event()

        async def blocked(request):
            if operation == "get-stream":
                class InterruptedBytes(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        yield b"tru"
                        entered.set()
                        await asyncio.Future()

                return httpx.Response(200, stream=InterruptedBytes())
            entered.set()
            await asyncio.Future()

        async with httpx.AsyncClient(transport=httpx.MockTransport(blocked)) as http:
            if operation == "put":
                work = objects._put_copy(http, chunk, db.get_workers()[0], data)
            else:
                chunk["replicas"] = db.get_replicas("obj_0")
                work = objects.read_verified_chunk(http, chunk)
            task = asyncio.create_task(work)
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    transfers = [event for event in events(journal) if event["transfer_id"]]
    assert [event["kind"] for event in transfers] == ["transfer_started", "transfer_failed"]
    assert transfers[0]["transfer_id"] == transfers[1]["transfer_id"]
    assert transfers[1]["detail"] == "cancelled"


def test_telemetry_failure_cannot_fail_storage_operations(system, journal, monkeypatch):
    client, _, _, _ = system

    def unavailable(*args, **kwargs):
        raise RuntimeError("journal unavailable")

    monkeypatch.setattr(journal._journal, "record", unavailable)
    response = upload(client, b"trusted")
    assert response.status_code == 201
    oid = response.json()["object_id"]
    assert client.get(f"/api/v1/objects/{oid}").content == b"trusted"
    assert client.delete(f"/api/v1/objects/{oid}").status_code == 204
