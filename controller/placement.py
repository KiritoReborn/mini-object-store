"""Deterministic placement shared by upload and B's repair loop."""
from datetime import datetime, timezone

from . import config


class InsufficientWorkers(Exception):
    """There are fewer eligible distinct workers than requested."""


def heartbeat_is_fresh(timestamp: str | None) -> bool:
    if timestamp is None:
        return False
    try:
        heartbeat = datetime.fromisoformat(timestamp)
        if heartbeat.utcoffset() is None:
            return False
        age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
        return 0 <= age < config.WORKER_DEAD_TIMEOUT
    except (ValueError, TypeError):
        return False


def choose_workers(workers: list[dict], excluded: set[str], count: int) -> list[dict]:
    if count < 0:
        raise ValueError("count must be nonnegative")
    candidates = {w["worker_id"]: w for w in workers
                  if w["status"] == "ALIVE" and w["worker_id"] not in excluded
                  and ("last_heartbeat" not in w or heartbeat_is_fresh(w["last_heartbeat"]))}
    selected = sorted(candidates.values(), key=lambda w: (w["chunk_count"], w["worker_id"]))[:count]
    if len(selected) != count:
        raise InsufficientWorkers(f"Need {count} eligible workers, found {len(selected)}")
    return selected
