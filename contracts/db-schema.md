# Persistent metadata schema

The authoritative DDL is [controller/schema.sql](../controller/schema.sql). One controller process owns SQLite; foreign keys, WAL and bounded busy timeouts are configured by database.py. Shared functions/record shapes are in [db-helpers.md](db-helpers.md).

| Table | Identity and relationship | Invariant |
|---|---|---|
| objects | object_id primary key | Only READY objects are public; UPLOADING/FAILED/DELETING remain internal. System size/hash and ordered chunk count are authoritative. |
| chunks | chunk_id primary key; object_id cascades; unique object_id/index | Nonnegative size/index, DB SHA-256 authoritative. UPLOADING chunks are protected from orphan cleanup. |
| workers | worker_id primary key | JOINING/ALIVE/DEAD; base_url is internal origin; timezone-aware heartbeat. Registration/heartbeat alone never admit a worker. |
| replicas | primary key chunk_id/worker_id; chunk cascades | HEALTHY/CORRUPT/MISSING/PENDING_DELETE; HEALTHY timestamp follows verified I/O. Worker removal requires zero replica records. |
| worker_settings | worker_id cascading foreign key | Optional UI label/notes and next-upload placement flag; does not change B's recovery policy. |
| worker_registrations | worker_id cascading foreign key | Non-secret admission token rotates on registration, not heartbeat; prevents stale inventory promotion. |

Schema initialization is additive and repeatable. Existing worker registrations receive a token once; repeated initialization preserves it. Controller restart changes known workers to JOINING and interrupted uploads to FAILED before recovery starts. No file contents are stored in SQLite. Physical chunks and sidecars remain in each worker's persistent volume.
