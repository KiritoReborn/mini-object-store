# Controller database and lifecycle contract

Implemented by A at `controller/database.py`; consumed directly by B's recovery/status modules. Synchronous helpers perform short, parameterized SQLite transactions. Async callers use `fastapi.concurrency.run_in_threadpool`; never hold a database connection across HTTP. One controller process owns the DB and in-process object locks.

Authoritative schema: [`controller/schema.sql`](../controller/schema.sql). Connection settings: foreign_keys ON on every connection, busy_timeout 5000 ms, WAL initialized once. Times use timezone-aware UTC ISO8601 with microseconds. No separate repository/adapter framework is needed.

## Frozen helper shapes

| Function | Return / behavior |
|---|---|
| `get_workers() -> list[dict]` | All workers, ordered by worker_id; fields below |
| `register_worker(worker_id, base_url) -> None` | Upsert as JOINING with current heartbeat timestamp; never automatically ALIVE |
| `touch_heartbeat(worker_id) -> bool` | Update timestamp only; false for unknown ID; do not change worker state |
| `set_worker_state(worker_id, state) -> None` | State update; unknown ID is a no-op |
| `transition_worker(worker_id, expected_heartbeat, state) -> bool` | Compare-and-set state only when heartbeat still matches the observed value; use for stale-state decisions |
| `get_chunks_for_repair() -> list[dict]` | All chunks of READY objects, ordered by object_id/index; authoritative size/hash |
| `get_replicas(chunk_id) -> list[dict]` | Replica records joined to worker URL/state/timestamp; absent chunk -> empty list |
| `upsert_replica(chunk_id, worker_id, state) -> None` | Idempotent insert/update; HEALTHY sets last_verified_at; other states clear it; unknown parent IDs fail FK validation |
| `set_replica_state(chunk_id, worker_id, state) -> None` | Update existing row, same timestamp rule; unknown pair is a no-op |
| `delete_replica_record(chunk_id, worker_id) -> None` | Idempotent row deletion |
| `known_chunk_ids() -> set[str]` | Includes UPLOADING and READY; excludes FAILED/DELETING |
| `get_object_manifest(object_id) -> dict \| None` | Consistent snapshot of object plus ordered chunks and joined replicas; internal helper includes non-READY objects |
| `choose_workers(workers, excluded, count) -> list[dict]` | In placement.py; distinct ALIVE workers, fresh heartbeat when provided, least chunk_count then worker_id; raises InsufficientWorkers rather than return too few |

Invalid persisted enum values fail SQLite CHECK constraints. These helpers intentionally do not infer arbitrary state transitions; callers own lifecycle decisions. B must never mark a replica HEALTHY without verifying bytes against chunk size and DB SHA-256.

**Worker dictionary:** `worker_id`, `base_url`, `status`, `last_heartbeat`, `chunk_count`. Load counts HEALTHY replicas for UPLOADING/READY objects. Heartbeat can be null in legacy data; treat absent/invalid timestamps as unavailable. Worker state: JOINING/ALIVE/DEAD.

**Chunk dictionary:** `chunk_id`, `object_id`, `chunk_index`, `size`, `sha256`.

**Replica dictionary:** `worker_id`, `state`, `last_verified_at`, `base_url`, `worker_status`, `last_heartbeat`. Replica state: HEALTHY/CORRUPT/MISSING/PENDING_DELETE. The key is `worker_status`, not `status`.

**Manifest:** object_id, name, size, content_type, created_at, updated_at, sha256, num_chunks, decoded `metadata`, status, and `chunks`. Each chunk contains the chunk fields plus `replicas` as above. Public routes alone enforce READY visibility.

## Recovery coordination required from B

1. `register_worker` always writes JOINING. A heartbeat from DEAD only updates time. B recognizes the fresh heartbeat as rejoin, changes to JOINING, inventories/verifies, then promotes to ALIVE. Use compare-and-set when old heartbeat observations could overwrite newer ones.
2. Before destructive work, use `async with controller.objects.object_lock(object_id)`, then reread current state. A holds the same lock for upload, verified-download preparation, PATCH and DELETE. Do not import main.py from recovery.py; objects.py does not import recovery.py.
3. An inventory snapshot or `known_chunk_ids()` snapshot can become stale. Parse object_id from the validated chunk ID, acquire its lock and reread current state before orphan deletion. UPLOADING chunk rows exist before PUT; never delete those chunks.
4. A marks successful replica PUTs HEALTHY, missing download copies MISSING, and corrupt/size/hash-mismatching copies CORRUPT. A transport timeout alone does not imply corruption.
5. A records attempted upload locations before PUT as PENDING_DELETE. Confirmed success becomes HEALTHY. Uncertain surplus copies are deleted where reachable; remaining PENDING_DELETE records on READY objects need B's retry path, including workers that never restart. Confirm two verified good distinct copies remain before deleting a surplus copy.
6. On failed upload or public delete, reachable copies are deleted, then metadata is removed. Offline remnants are unknown chunks on rejoin. An ambiguous timed-out write can finish late; periodic inventory reconciliation of live workers is also needed to collect such remnants, not just rejoin-time inventory.
7. Controller restart sets formerly known workers JOINING and interrupted UPLOADING objects FAILED. A schedules failed/deleting cleanup; B inventories workers and restores eligibility. No automatic ALIVE promotion is provided in A's implementation.
8. Repair selects READY chunks only. Never repair FAILED/DELETING objects or publish UPLOADING objects. Shared lock must span network mutation and final state recheck, while SQLite transactions stay short.

## Main application hookup

B provides `controller/recovery.py` exporting `start_reconciler()` and `stop_reconciler()`. A supports synchronous or awaitable hooks. Start must schedule the background loop and return None promptly; do not return the long-running Task itself, because A awaits awaitable hook results. Stop must stop and await that loop. If using an async loop, expose `async def stop_reconciler()` so shutdown drains it before the HTTP client closes.

B provides `controller/status.py` exporting `router: APIRouter`. A includes it in create_app. Existing modules with broken dependencies fail visibly; genuinely missing B modules leave `/health` reporting `recovery_available: false`, and workers stay JOINING. A's `/health` checks DB access and HTTP liveness; it is not proof of two-copy storage readiness.

Other A-owned helpers are visible in database.py for object lifecycle. B should prefer the frozen names above; coordinate any additional shared dependency through this document.

## A-only worker settings extension

The additive worker_settings table stores display_name/notes and placement_enabled with a cascading foreign key to workers. Missing settings use empty labels/notes and placement enabled. Existing workers/replicas columns and frozen helper return shapes are unchanged.

A uploads call get_placement_workers(), which returns the same shape as get_workers() while excluding placement-disabled nodes. B continues using get_workers(); a presentation pause does not silently change B's repair policy. get_managed_workers/connect_managed_worker/update_worker_settings/forget_worker serve the UI routes, not the frozen recovery boundary. Forget checks heartbeat and all replica states under a single immediate transaction; invalid, naive or future heartbeats remain protected. Settings events publish only after commit.
