# Object store HTTP contract

One local controller at port 8000; four worker listeners at port 8001. Internal calls use Docker service DNS, not localhost. Errors have `{"error":"CODE","message":"human-readable message"}`. Invalid request bodies/metadata return 400; unknown objects 404; unavailable required storage 503; unexpected controller faults 500. Worker healthy-content conflicts use 409.

## Public endpoints (Member A)

| Method | Route                           | Body / response                                                                                                              | Success                       |
| ------ | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| POST   | `/api/v1/objects`               | multipart: required `file`, optional `metadata` JSON string; returns READY object metadata including ID/hash/count/locations | 201                           |
| GET    | `/api/v1/objects/{id}`          | Verified original bytes, Content-Type, safe Content-Disposition, X-Object-SHA256 and checksum ETag                           | 200 or 206 for a served range |
| GET    | `/api/v1/objects/{id}/metadata` | System/custom metadata, ordered chunk index/size/hash, workers and replica states                                            | 200                           |
| PATCH  | `/api/v1/objects/{id}/metadata` | `{"metadata":{"course":"CC","reviewed":true}}`; merge custom keys; returns updated metadata                                  | 200                           |
| DELETE | `/api/v1/objects/{id}`          | Logical removal and reachable physical cleanup; no response body                                                             | 204                           |
| GET    | `/api/v1/objects`               | JSON array of READY objects with system/custom fields; no chunks downloaded                                                  | 200                           |

Custom metadata must be a JSON object with finite JSON values, encoded size at most 32768 bytes after merge. System fields such as size/hash/name/status/timestamps/chunks cannot be modified through custom metadata. PATCH preserves unspecified custom keys; null is a JSON value, not a key-deletion instruction. Filenames retain safe Unicode names and have path components removed. Invalid/empty/control-character names return 400. Content type defaults to application/octet-stream if missing or invalid.

Object IDs are UUID4; chunk IDs are `<uuid>_<zero-based-index>`; default chunk size is 1000000 bytes and replication factor is 2 on distinct workers. Empty objects have zero chunks and the SHA-256 of empty bytes. Object states UPLOADING/FAILED/DELETING are hidden from all public reads.

An upload returns 201 only after every chunk has two acknowledged hash-valid writes to eligible workers and the final metadata commit succeeds. Worker availability can change afterward. A download verifies every chunk and the entire object into controller-owned temporary storage before returning binary success; unavailable good copies return JSON 503. A connection interruption during file transmission is still a transport error.

Downloads check object existence first. Without `If-Range`, the controller validates `Range` against the stored size before preparing the download. With `If-Range`, Starlette compares the validator to the response's strong ETag or `Last-Modified`. A mismatch returns the full verified body. Applicable malformed and unsatisfiable ranges return JSON `400 INVALID_RANGE` and `416 RANGE_NOT_SATISFIABLE`, respectively, with `Content-Range: bytes */<size>` on `416`.

DELETE of unknown/already-deleted object returns 404. Offline bytes are removed by B's eventual reconciliation; a 204 does not claim an offline disk has already been erased. No public upload-idempotency key or range-upload protocol is implemented.

## Optional owner demo access (Member A)

When ARTAUD_API_KEY is configured, every `/api/v1/*` request requires the matching `X-Artaud-Key` header; missing/wrong keys return 401. This is a shared owner key, not multi-user authentication. The browser keeps it only in page memory. Remote browser access requires an exact origin in ARTAUD_ALLOWED_ORIGINS; unsafe API requests reject other origins. Administrative mutations additionally require `X-Artaud-Admin: 1`. Public-host requests to `/internal/*` return 404; worker registration/heartbeats remain on the trusted Docker network. `/health` remains public liveness information.

The optional Vercel frontend calls the PC's HTTPS API directly. File bodies do not pass through Vercel. Local-only use needs neither Vercel nor a tunnel. See [the simple demo setup](../docs/DEMO.md).

## Worker administration and demo controls (Member A)

| Method | Route                                                 | Behavior                                                                                                                                                                                                   | Success |
| ------ | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| GET    | `/api/v1/workers`                                     | `{workers, placement_available_workers}`; worker profiles include base_url/status/heartbeat, availability, labels/notes, placement_enabled, replica_count, chunk_count/stored_bytes and can_forget         | 200     |
| POST   | `/api/v1/workers/connect`                             | Required worker_id/base_url; optional display_name/notes. Only worker1..worker16 with exact `http://<worker_id>:8001`; bounded health/identity verification. New records JOINING; existing state preserved | 200     |
| PATCH  | `/api/v1/workers/{id}`                                | Nonempty subset of display_name (max 64), notes (max 512), placement_enabled (boolean); returns updated profile                                                                                            | 200     |
| DELETE | `/api/v1/workers/{id}`                                | Atomic metadata-only forget; requires stale/absent heartbeat and zero replica records of every state. In-use 409; missing 404                                                                              | 204     |
| GET    | `/api/v1/demo/workers`                                | `{enabled, workers:[{worker_id, container_state, running}]}`; disabled returns false/empty list                                                                                                            | 200     |
| POST   | `/api/v1/demo/workers/{id}/{action}`                  | Opt-in, authenticated start/stop/restart for existing worker1..worker4 only. Returns action and actual container state; missing container 404, identity mismatch 409, disabled/engine failure 503          | 200     |
| POST   | `/api/v1/demo/workers/{id}/chunks/{chunk_id}/corrupt` | Requires `ARTAUD_DEMO_FAULT_INJECTION=1`, an owner key and the admin header. Targets a registered worker's HEALTHY replica. Disabled or absent target 404, unhealthy copy 409, worker failure 503.         | 200     |

Placement pause affects subsequent A upload selections; reads, in-flight writes and B recovery policy remain separate. Connect does not create a container. Forget never deletes disks. Container actions require the optional Docker socket overlay and matching Compose project/service/name; no arbitrary target, shell, creation/deletion or volume removal is exposed. Actual container running state and controller storage eligibility are different facts. No action bypasses inventory verification or promotes a worker to ALIVE.

## Dashboard extension (Member A)

`GET /` serves the built dashboard with no-cache HTML; `/assets/*` serves only built assets. Missing API routes remain 404 and do not become SPA HTML. A missing build returns JSON 503.

`GET /api/v1/overview` is read-only and separate from B's `/admin/status`. It returns object_count/logical_bytes/chunk_count for READY objects; healthy_replica_count/under_replicated_chunks/corrupt_replicas; worker_count/available_workers; replication_factor/chunk_size/recovery_available; and workers with worker_id/status/last_heartbeat/heartbeat_age_seconds/available/chunk_count/stored_bytes. Healthy availability requires ALIVE and a fresh timezone-aware heartbeat. Recorded worker copies/bytes include active uploads and READY data; they are not physical disk capacity. An aware future heartbeat is unavailable and has negative age; invalid/absent times have null age. The UI treats clock mismatch and stale snapshots explicitly.

Overview includes `fault_injection_enabled: true` when controller fault injection and owner authentication are configured. The demo overlay enables the controller and worker flags together. Under the normal object lock, the controller sends the fault request to the selected worker over HTTP and records the copy as CORRUPT after acknowledgement. The demo can target the last readable copy. A worker-confirmed corrupt or missing replica also updates the manifest. Recovery continues on its normal schedule.

Dashboard activity: `GET /api/v1/activity?after=0` returns stream_id/oldest_id/latest_id/next_cursor/truncated/events. The cursor is nonnegative; at most 512 process-local events are retained. Events describe acknowledged/verified transfer attempts and committed helper changes; restarts reset the stream. Concurrent post-commit observations may interleave, so current manifests/overview remain authoritative. See [the complete event contract](../docs/DEVELOPMENT.md#activity-contract), including optional B repair events. No helper signature or recovery policy changes are required.

## Worker -> controller

- `POST /internal/workers/register`: `{"worker_id":"worker1","base_url":"http://worker1:8001"}` -> 200 `{worker_id,status:"registered"}`. Upsert JOINING, never auto-promote.
- `POST /internal/workers/heartbeat`: `{"worker_id":"worker1"}` -> 200 `{worker_id,status:"accepted"}`; unknown ID -> 404 WORKER_NOT_FOUND. No promotion on heartbeat.
- `GET /health`: controller liveness/DB check and boolean recovery_available. Missing reconciler is explicit.

Worker IDs: 1-64 characters, first alphanumeric, remainder alphanumeric/underscore/hyphen. Base URL must be an HTTP(S) origin without credentials, query, fragment or path. Internal endpoints are intended for the trusted local Docker network; no authentication/authorization is claimed.

## Controller -> worker (Member B's implemented behavior)

- `PUT /internal/chunks/{chunk_id}`: raw bytes, `X-Chunk-SHA256` and application/octet-stream. 201 new/repaired, 200 identical retry, 409 conflicting healthy content, 400 invalid ID/hash/size.
- `GET /internal/chunks/{chunk_id}`: 200 bytes with checksum header; 404 CHUNK_NOT_FOUND; 409 CHUNK_CORRUPTED. Controller verifies against SQLite regardless of the header.
- `DELETE /internal/chunks/{chunk_id}`: 204, even if absent.
- `GET /internal/workers/{worker_id}/chunks`: `{worker_id,chunks:[{chunk_id,size,sha256}]}`. Inventory checksum can be null and is informational only; recovery must verify actual bytes.
- `POST /internal/demo/corrupt/{chunk_id}`: Disabled by default (404). With `WORKER_ENABLE_FAULT_INJECTION=1`, flips byte zero of an existing, healthy, nonempty chunk under its normal lock and preserves the checksum sidecar. An optional `X-Artaud-Worker-ID` must match the receiving worker. Returns 200 `{chunk_id,worker_id,offset,size,action:"corrupted"}`.

Defaults: heartbeat interval 5 seconds, dead threshold 15 seconds, reconciliation interval 5 seconds, controller worker-request timeout 5 seconds. Base Compose now forwards CHUNK_SIZE consistently to controller/workers, HEARTBEAT_INTERVAL to workers and WORKER_DEAD_TIMEOUT/RECONCILE_INTERVAL/HTTP_TIMEOUT to the controller. Restart/recreate services after changing these environment settings; existing containers do not change in place. Replication remains fixed at two distinct workers by assignment policy. Use the 1,000,000-byte default for grading/demo chunk-boundary cases; changing it is not a migration of existing data. B's recovery uses its documented fixed per-operation request limits (inventory/delete 5 seconds, chunk read/write 10 seconds), separate from A's HTTP_TIMEOUT.
