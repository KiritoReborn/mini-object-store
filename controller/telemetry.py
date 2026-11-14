"""Bounded, process-local observations, never part of a storage transaction.

B may call record_event("repair_started" | "repair_completed" | "repair_failed",
object_id=..., chunk_id=..., worker_id=..., detail=...). Fields are optional;
use fixed explanations, never URLs, exception text, secrets or custom metadata.
This journal is recent operational context, not a durable audit log.
"""
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

_KINDS = {
    "transfer_started", "transfer_completed", "transfer_failed", "object_ready",
    "object_deleted", "metadata_updated", "worker_state", "replica_state",
    "repair_started", "repair_completed", "repair_failed",
    "worker_settings", "worker_action", "worker_connected", "worker_forgotten",
}
_TEXT_FIELDS = ("object_id", "chunk_id", "worker_id", "transfer_id", "direction",
                "state", "previous_state", "name", "detail")


class ActivityJournal:
    def __init__(self):
        self._stream_id = str(uuid4())
        self._events = deque(maxlen=512)
        self._latest_id = 0
        self._lock = Lock()

    def record(self, kind: str, fields: dict) -> None:
        if kind not in _KINDS:
            return
        event = {key: value[:512] if isinstance(value := fields.get(key), str) else None
                 for key in _TEXT_FIELDS}
        size = fields.get("size")
        event["size"] = size if type(size) is int and 0 <= size <= 2**63 - 1 else None
        with self._lock:
            self._latest_id += 1
            self._events.append({"id": self._latest_id,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                "kind": kind, **event})

    def snapshot(self, after: int = 0) -> dict:
        with self._lock:
            oldest = self._events[0]["id"] if self._events else 0
            ahead = after > self._latest_id
            events = [dict(event) for event in self._events if ahead or event["id"] > after]
            return {"stream_id": self._stream_id, "oldest_id": oldest,
                "latest_id": self._latest_id,
                "next_cursor": events[-1]["id"] if events else (0 if ahead else after),
                "truncated": ahead or after < oldest - 1, "events": events}


_journal = ActivityJournal()


def record_event(kind: str, **fields) -> None:
    """Best effort, bounded publication; observation must never fail storage work."""
    try:
        _journal.record(kind, fields)
    except Exception:
        pass


def get_activity(after: int = 0) -> dict:
    return _journal.snapshot(after)
