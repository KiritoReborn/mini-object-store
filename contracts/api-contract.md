# Object store HTTP contract

One local controller at port 8000; four worker listeners at port 8001. Internal calls use Docker service DNS, not localhost. Errors have `{"error":"CODE","message":"human-readable message"}`. Invalid request bodies/metadata return 400; unknown objects 404; unavailable required storage 503; unexpected controller faults 500. Worker healthy-content conflicts use 409.

## Public endpoints (Member A)

| Method | Route | Body / response | Success |
|---|---|---|---|
| POST | `/api/v1/objects` | multipart: required `file`, optional `metadata` JSON string; returns READY object metadata including ID/hash/count/locations | 201 |
| GET | `/api/v1/objects/{id}` | Verified original bytes, Content-Type, safe Content-Disposition, X-Object-SHA256 and checksum ETag | 200 |
| GET | `/api/v1/objects/{id}/metadata` | System/custom metadata, ordered chunk index/size/hash, workers and replica states | 200 |
| PATCH | `/api/v1/objects/{id}/metadata` | `{"metadata":{"course":"CC","reviewed":true}}`; merge custom keys; returns updated metadata | 200 |
| DELETE | `/api/v1/objects/{id}` | Logical removal and reachable physical cleanup; no response body | 204 |
| GET | `/api/v1/objects` | JSON array of READY objects with system/custom fields; no chunks downloaded | 200 |

Custom metadata must be a JSON object with finite JSON values, encoded size at most 32768 bytes after merge. System fields such as size/hash/name/status/timestamps/chunks cannot be modified through custom metadata. PATCH preserves unspecified custom keys; null is a JSON value, not a key-deletion instruction. Filenames retain safe Unicode names and have path components removed. Invalid/empty/control-character names return 400. Content type defaults to application/octet-stream if missing or invalid.

Object IDs are UUID4; chunk IDs are `<uuid>_<zero-based-index>`; default chunk size is 1000000 bytes and replication factor is 2 on distinct workers. Empty objects have zero chunks and the SHA-256 of empty bytes. Object states UPLOADING/FAILED/DELETING are hidden from all public reads.

An upload returns 201 only after every chunk has two acknowledged hash-valid writes to eligible workers and the final metadata commit succeeds. Worker availability can change afterward. A download verifies every chunk and the entire object into controller-owned temporary storage before returning binary success; unavailable good copies return JSON 503. A connection interruption during file transmission is still a transport error.

DELETE of unknown/already-deleted object returns 404. Offline bytes are removed by B's eventual reconciliation; a 204 does not claim an offline disk has already been erased. No public upload-idempotency key, authentication or range-upload protocol is implemented.

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

Defaults: heartbeat interval 5 seconds, dead threshold 15 seconds, reconciliation interval 5 seconds, controller worker-request timeout 5 seconds. Timings are configurable team choices. Compose currently forwards only worker identity and controller URL; B still needs to wire the other environment settings into containers before non-default settings are relied on.
