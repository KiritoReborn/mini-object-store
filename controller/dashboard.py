"""Read-only dashboard summaries; recorded replicas do not measure disk capacity."""
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request

from . import config, database as db, telemetry
from .placement import heartbeat_is_fresh

router = APIRouter()


@router.get("/api/v1/activity", tags=["dashboard"])
def activity(after: int = Query(0, ge=0)):
    return telemetry.get_activity(after)


@router.get("/api/v1/overview", tags=["dashboard"])
def overview(request: Request):
    snapshot = db.get_overview_snapshot()
    now = datetime.now(timezone.utc)
    workers = snapshot["workers"]
    available = set()
    for worker in workers:
        timestamp = worker["last_heartbeat"]
        try:
            heartbeat = datetime.fromisoformat(timestamp)
            age = (now - heartbeat).total_seconds() if heartbeat.utcoffset() is not None else None
        except (ValueError, TypeError):
            age = None
        worker["heartbeat_age_seconds"] = age
        worker["available"] = worker["status"] == "ALIVE" and heartbeat_is_fresh(timestamp)
        if worker["available"]:
            available.add(worker["worker_id"])

    eligible_replicas = {}
    corrupt_replicas = 0
    for replica in snapshot.pop("replicas"):
        chunk_workers = eligible_replicas.setdefault(replica["chunk_id"], set())
        if replica["state"] == "HEALTHY" and replica["worker_id"] in available:
            chunk_workers.add(replica["worker_id"])
        elif replica["state"] == "CORRUPT":
            corrupt_replicas += 1

    return {
        **snapshot,
        "chunk_count": len(eligible_replicas),
        "healthy_replica_count": sum(len(copies) for copies in eligible_replicas.values()),
        "under_replicated_chunks": sum(len(copies) < config.REPLICATION_FACTOR
                                       for copies in eligible_replicas.values()),
        "corrupt_replicas": corrupt_replicas,
        "worker_count": len(workers),
        "available_workers": len(available),
        "replication_factor": config.REPLICATION_FACTOR,
        "chunk_size": config.CHUNK_SIZE,
        "recovery_available": request.app.state.recovery_available,
        **({"fault_injection_enabled": True} if config.DEMO_FAULT_INJECTION and config.API_KEY else {}),
    }
