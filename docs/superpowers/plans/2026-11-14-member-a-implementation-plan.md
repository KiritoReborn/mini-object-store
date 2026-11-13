# Member A Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This document is a proposed execution plan; writing it does not authorize starting implementation or changing Member B's files.

**Goal:** Complete Member A's controller so arbitrary binary objects are stored with two replicas per chunk, retrieved with verified integrity, and managed through the six required public APIs.

**Architecture:** One FastAPI controller owns a persistent SQLite metadata database and communicates with four persistent workers over HTTP. Member A owns object lifecycle, authoritative hashes, placement, public endpoints and database helpers. Member B owns worker services, repair/rejoin/status, Docker and CLI; both integrate early through documented functions and payloads.

**Tech stack:** Team plan: Python 3.12, FastAPI, HTTPX, SQLite, pytest and Docker Compose. Retain the repository's existing pinned dependencies until the real worker implementation is available; review dependency changes jointly.

**Spec:** User-supplied assignment (3 pages), updated two-member plan v2.0 (15 pages), and teammate's pasted handoff. Source locations and evidence limits appear at the end.

**Worker handoff update:** Reviewed pushed commit `6a8d653` after this plan was first drafted. All 42 worker tests pass in the specified Linux Docker environment; live worker HTTP, corruption rejection/repair and restart persistence were also verified. Docker explicitly expects the proposed flat `controller/main.py` layout. Most settings in `.env.example` still need to be forwarded through Compose; native Windows worker tests fail at POSIX directory syncing. See [the handoff review](../../reviews/2026-11-14-worker-handoff-review.md) for evidence and the exact integration contract. The historical snapshot below records what was known before that push.

**A implementation update:** The user subsequently authorized implementation and Git synchronization. A-owned controller functionality and tests are now implemented; see [current handoff](../../HANDOFF.md) for verified evidence, rulings and remaining B dependencies. The original unchecked checklist below remains a planning reference, not an assertion that joint acceptance, B's reconciler or full release gates are complete. Shared contracts are implemented proposals awaiting B's review. Git feature branch is `feature/controller`.

## 1. What is known now

Reviewed on 14 November 2026, India time.

| Evidence | What it establishes | What it does not establish |
|---|---|---|
| Original assignment, pages 1-3 | Required topology, binary storage, metadata, six APIs, replication, failure/integrity demonstrations and Docker deployment | Specific language, DB schema, state names, heartbeat intervals or UI |
| Updated team plan, especially pages 3-5 and 11-14 | Agreed design direction, ownership and proposed wire/database contracts | That any module has been implemented or integrated |
| Teammate's handoff | He reports completed worker storage/API/heartbeat/config, four-worker Compose, and 42 passing worker tests; recovery/status/CLI and reliability tests remain | Independent code review, reproduced tests or an integrated system |
| Cloned repository at `95bc99b` (`Initialize project`), branch `master` | Only starter controller/worker health apps, package files and `requirements.txt` are present | The completed worker code, Compose files, contracts or tests |
| User clarification | Teammate has not pushed his implementation yet | Submission date, which remains unspecified |

No application tests were run during the initial planning task. The subsequent worker review above independently verified all 42 in Linux. The local checkout is `C:\Users\Raghu\Desktop\Cloud\mini-object-store`.

**Your immediate priority:** publish the database/helper contract and a working controller registration/heartbeat foundation. This unblocks B's recovery code. Then prove a real upload/download before completing secondary features.

## 2. Scope and ownership

| Owner | Files / responsibility |
|---|---|
| A | `controller/__init__.py`, `controller/main.py`, `controller/config.py`, `controller/models.py`, `controller/database.py`, `controller/objects.py`, `controller/placement.py` |
| A | `tests/test_api.py`, `tests/test_chunking.py`; proposed focused `tests/test_database.py` and `tests/test_placement.py` if useful for readable tests |
| B | `worker/*`, `controller/recovery.py`, `controller/status.py`, `client/*`, Dockerfiles, Compose, worker/demo utilities, worker/recovery/integrity tests |
| Joint | `contracts/*`, `README.md`, `requirements.txt`, `.env.example`, `scripts/demo.sh`, `tests/test_end_to_end.py` |

Do not implement B's pending recovery/status/CLI to make A appear complete. A wires them in and supplies the data and state transitions they need. Corrections to B-owned files go through B.

**Folder layout confirmed by the pushed code.** The starter controller remains at `controller/app/main.py`, but B's worker is now `worker/main.py` and Docker explicitly loads `controller.main:app`. Follow the flat layout already named in the handoff and blueprint: A moves the starter controller entry point to `controller/main.py`. Maintain one controller app, not two parallel implementations.

## 3. Global constraints

- Exactly 1 controller and 4 workers; local Docker deployment; persistent worker volumes; no Kubernetes for worker orchestration.
- `CHUNK_SIZE = 1_000_000` bytes and `REPLICATION_FACTOR = 2`, following the team plan's decimal-MB decision.
- Worker heartbeat every 5 seconds; `WORKER_DEAD_TIMEOUT = 15`; `RECONCILE_INTERVAL = 5`. These are team defaults, not assignment-mandated timings.
- UUID4 object IDs; chunk IDs `<object_id>_<zero-based-index>`; SQL ordering by `chunk_index`.
- Objects: `UPLOADING`, `READY`, `DELETING`, `FAILED`. Workers: `JOINING`, `ALIVE`, `DEAD`. Replicas: `HEALTHY`, `CORRUPT`, `MISSING`, `PENDING_DELETE`.
- Only READY objects appear through public list, metadata and download routes.
- READY is committed only after every chunk has two confirmed copies on distinct eligible workers. Empty objects have zero chunks and SHA-256 of empty bytes.
- SQLite is authoritative for expected chunk/object hash and size. Worker headers and sidecars are not proof of integrity.
- No network calls inside SQLite transactions. Keep transactions short; configure foreign keys on every connection, WAL mode and a 5000 ms busy timeout.
- Recommend one controller application process for this project, so the reconciler runs once and shared in-process locks coordinate correctly.
- Keep the agreed API/CLI scope. Spend polish time on correctness, diagnostics, evidence and documentation; additional product features come after all required gates pass.

## 4. Decisions to document with B before splitting work

These are proposed contract resolutions, not claims that B has accepted them. Put the accepted version in `contracts/db-helpers.md` and `contracts/api-contract.md`.

| Issue | Proposed resolution |
|---|---|
| Timestamps | UTC ISO8601 with explicit timezone, e.g. `2026-11-14T10:00:00+00:00`; use timezone-aware parsing |
| Worker fields | `worker_id`, `base_url`, `status`, `last_heartbeat`, `chunk_count` |
| Replica fields | `worker_id`, `state`, `base_url`, `worker_status`, `last_verified_at`; use `worker_status` to distinguish worker liveness from replica state |
| Placement load | `chunk_count` counts HEALTHY replica records for UPLOADING/READY objects on that worker; deterministic ties by worker ID; update local counts after successful writes |
| Registration | Upsert as JOINING, record a current timestamp; acknowledge with 200; retries must not create duplicates |
| Heartbeat | Known worker: timestamp update, 200; unknown worker: 404 so its existing retry code re-registers; heartbeat never directly promotes to ALIVE |
| DEAD worker returns | A records fresh heartbeat; B notices DEAD plus fresh timestamp, changes to JOINING, reconciles, then ALIVE |
| Orphan protection | `known_chunk_ids()` includes UPLOADING and READY chunks; excludes FAILED and DELETING. Record chunk metadata before its first worker PUT |
| Repair scope | `get_chunks_for_repair()` returns READY-object chunks only; repair must not publish or complete an UPLOADING object |
| Download states | A marks explicit absence MISSING and verified bad data CORRUPT; B polls those states and repairs. A timeout alone is not evidence of corruption |
| Ambiguous upload writes | A retains attempted locations whose PUT may have succeeded. If upload succeeds using other workers, record unselected uncertain locations as PENDING_DELETE, attempt cleanup, and have B retry pending deletions after confirming two good copies remain. Never silently abandon an extra copy on an ALIVE worker |
| Delete | A marks DELETING, cleans reachable copies and removes object/chunk/replica rows; B removes offline leftovers on rejoin |
| Reconciler hookup | Freeze whether start/stop are synchronous or awaitable. Start must schedule background work without waiting for workers to register; shutdown must stop and drain it before shared resources close |
| Lifecycle races | A and B share a per-object async lock for delete/repair and upload/orphan decisions; recheck current object state before repair finalization or destructive cleanup. Proposed lock accessor: `controller.objects.object_lock(object_id)`; objects must not import recovery |
| Worker transition races | B rechecks the latest heartbeat before marking DEAD or promoting a reconciled worker; do not overwrite a newer registration/heartbeat using an old snapshot |

Why the orphan rule matters: a worker PUT can be physically present before its upload is READY. If cleanup only recognizes READY objects, it can delete a valid in-progress upload. A stale inventory snapshot can cause the same problem: B must recheck the current DB under the shared coordination rule immediately before destructive cleanup.

## 5. Shared interfaces A must provide

Preserve the blueprint's names and synchronous database signatures unless both members agree to a change:

```python
get_workers() -> list[dict]
set_worker_state(worker_id: str, state: str) -> None
register_worker(worker_id: str, base_url: str) -> None
touch_heartbeat(worker_id: str) -> bool
get_chunks_for_repair() -> list[dict]
get_replicas(chunk_id: str) -> list[dict]
upsert_replica(chunk_id: str, worker_id: str, state: str) -> None
set_replica_state(chunk_id: str, worker_id: str, state: str) -> None
delete_replica_record(chunk_id: str, worker_id: str) -> None
known_chunk_ids() -> set[str]
get_object_manifest(object_id: str) -> dict | None
choose_workers(workers: list[dict], excluded: set[str], count: int) -> list[dict]
```

`get_workers`, chunks and replica dictionaries use the exact field names above and in the blueprint: chunks contain `chunk_id`, `object_id`, `chunk_index`, `size`, `sha256`. `get_object_manifest` returns the object fields, decoded `metadata`, and `chunks` ordered by index, each including `replicas`; unknown ID returns None. This is an internal helper: public routes separately enforce READY visibility.

Define in the contract: valid/invalid state behavior; whether updates to missing replica records are no-ops; unknown worker behavior; and failure when placement has too few candidates. Proposed placement failure is a small `InsufficientWorkers` exception mapped by A's API to 503. Do not silently return fewer than `count` workers.

Worker contract already reported by B: PUT raw bytes plus `X-Chunk-SHA256` -> 201 new / 200 identical retry / 409 conflicting healthy content / 400 bad hash or oversized data; GET -> 200 bytes or 404 missing / 409 `CHUNK_CORRUPTED`; DELETE -> 204 even if absent. Verify the real payloads after his push.

## 6. Review focus

Five easily missed conditions must have explicit tests in the owning tasks:

1. PUT succeeds remotely but its reply times out: retry must remain idempotent and upload failure must not expose a partial object (Task 5).
2. Worker returns corrupted bytes with a matching forged header/sidecar: DB-backed verification still rejects them (Task 6).
3. Repair or orphan cleanup overlaps upload/delete: no live upload chunk is removed and no deleted object gains a new replica (Tasks 5, 9).
4. Controller restarts with UPLOADING/DELETING rows and formerly ALIVE workers: resume cleanup and reconcile before using stale state (Task 10).
5. Temp-file creation, writing or response transfer fails: no partial success before verification and no abandoned temp files during normal cleanup (Task 6).

## 7. Ordered implementation tasks

For behavioral tasks: add focused tests, run to observe failure, implement the smallest change, rerun the affected suite, then commit that coherent deliverable. Commands below are future checks, not results already obtained.

### Task 1 - Align the checkout and freeze contracts (C0)

**Files:** joint `contracts/api-contract.md`, `contracts/db-schema.sql`, `contracts/db-helpers.md`, `.env.example`; A controller layout only.

- [x] Fetch B's pushed branch/commit when available. Read his worker config, request payloads, tests and Docker commands; reproduce his reported worker tests. Verified at `6a8d653`: 42 passed in Linux Docker, plus live worker persistence/corruption checks.
- [ ] Create A's `feature/controller` branch from the agreed shared baseline. The repository currently defaults to `master`; do not assume a `main` branch exists.
- [ ] Confirm the single app layout, ports, worker DNS names and ownership table.
- [ ] Copy Appendix B's four-table schema and constraints into the shared schema contract. Record the resolutions in Sections 4-5, plus upload/PATCH/error examples.
- [ ] Agree how both members will run commands on Windows versus inside Linux containers. Host binary uploads should use `curl.exe` or a Python client, not ambiguous PowerShell aliases.

**Pass:** B can implement recovery without guessing dict keys, timestamps, load values or lifecycle ownership. Any proposed changes have been acknowledged by both members. Commit contracts separately from product code.

### Task 2 - Build durable database helpers and controller foundation (C1 contribution)

**Files:** `controller/{__init__,config,models,database,main}.py`; tests in `test_database.py` and `test_api.py`.

**Consumes:** frozen schema/helper contract. **Produces:** all Section 5 database helpers, config constants, `/health`, register and heartbeat endpoints.

- [ ] Add tests for table creation, FK cascades, duplicate replica prevention, valid state constraints, timezone timestamps, unknown heartbeat false, registration JOINING and heartbeat never promoting workers.
- [ ] Initialize `DATABASE_PATH=/data/metadata.db` in deployment; use an isolated temporary DB in tests. Verify reopening retains rows and every connection enforces foreign keys.
- [ ] Implement the frozen helpers, including ordered manifests, exact joined replica fields, READY-only repair selection and UPLOADING-aware known IDs.
- [ ] Add request models and consistent `{"error":"CODE","message":"..."}` responses. Translate relevant invalid-client request validation to 400.
- [ ] Implement controller `/health`, `POST /internal/workers/register` and `POST /internal/workers/heartbeat` with the agreed 200/404 behavior.
- [ ] Use application lifespan for DB setup and one shared HTTPX AsyncClient; set finite worker-request timeouts. Keep health distinct from having enough workers to upload.
- [ ] Push this foundation early so B can develop recovery against real helpers. Stubs may briefly unblock import work, but do not report helper behavior as complete until its tests pass.

**Check:** `python -m pytest tests/test_database.py tests/test_api.py -q` (only committed tests). **Pass:** persistence and helper/API tests pass; workers can register and heartbeat against A's real controller. Full C1 additionally needs B's Compose and startup reconciliation.

### Task 3 - Wire minimum reconciliation and run all five services (C1)

**Files:** A `controller/main.py`; B supplies `controller/recovery.py`, Docker/Compose and worker code.

- [ ] B supplies the minimal JOINING inventory check and promotion path. Empty workers can become ALIVE only after successful inventory review.
- [ ] A includes B's `status.router` when delivered and starts/stops his reconciler through lifespan using the frozen async/sync convention.
- [ ] Startup makes previously persisted workers JOINING; it must not trust old ALIVE states after a controller restart.
- [ ] Run `docker compose up --build -d` and `docker compose ps`; verify controller plus worker1-worker4, distinct volumes, current heartbeats and eventual ALIVE status.

**Pass:** five real services run; all workers register, heartbeat and reconcile. No manual database update or heartbeat shortcut is used to force ALIVE. If B's minimum reconciliation is delayed, A can continue unit tests, but live upload integration remains incomplete.

### Task 4 - Implement ordered chunking and placement

**Files:** A `controller/objects.py`, `controller/placement.py`; `tests/test_chunking.py`, optional `tests/test_placement.py`.

**Interfaces:** proposed `iter_chunks(file: UploadFile) -> AsyncIterator[bytes]`; frozen `choose_workers(...)`; shared `object_lock(object_id)` for lifecycle coordination.

- [ ] Test lengths 0, 1, 999999, 1000000, 1000001, 2000000 and 5000001; concatenating chunks must recover exact original bytes and ordering.
- [ ] Implement bounded reads, incremental SHA-256 and `<uuid>_<index>` chunk IDs. A zero-byte object produces no chunks.
- [ ] Test placement excludes JOINING/DEAD workers and caller-excluded IDs, chooses distinct least-loaded workers, breaks ties deterministically and fails if fewer than `count` eligible candidates exist.
- [ ] Update local placement load after successful writes; refresh candidates when a request fails. Avoid hard-coding worker pairs.

**Check:** `python -m pytest tests/test_chunking.py tests/test_placement.py -q` if separate placement tests are created. **Pass:** 5000001 bytes gives six ordered chunks, last size 1; selection follows frozen eligibility and load rules.

### Task 5 - Implement safe upload with rollback

**Files:** A `controller/objects.py`, `database.py`, `models.py`; `tests/test_api.py`.

**Endpoint:** `POST /api/v1/objects`, multipart required `file`, optional JSON-string `metadata`; success 201 containing Object ID and READY metadata.

- [ ] Test valid binary upload, malformed metadata/missing file -> 400, insufficient workers -> 503, and hidden UPLOADING/FAILED objects.
- [ ] Create UPLOADING object; for each chunk persist its expected size/hash/order before network PUT, so rejoin cleanup recognizes it.
- [ ] Choose two distinct ALIVE workers; send raw bytes and expected SHA header. Check acknowledgment shape, size/hash against the request contract; record HEALTHY only after confirmed success.
- [ ] Retry an uncertain PUT idempotently with the same chunk ID and bytes; on worker failure try another eligible worker. Track every attempted location, including writes whose replies timed out, for rollback cleanup.
- [ ] If failover succeeds elsewhere, clean uncertain surplus locations without risking the two confirmed copies. Persist remaining ambiguous locations as PENDING_DELETE and coordinate B's retry path; test eventual removal even when that worker never restarts.
- [ ] Test mid-upload failure both with a spare worker (can succeed) and without sufficient workers (503, never READY); test a timeout after remote success creates no duplicate replica record.
- [ ] Commit final size, count and object checksum with READY only when every chunk meets the replication rule. Liveness can change immediately afterward; recovery handles later failures.
- [ ] On failure/cancellation, mark FAILED and perform bounded best-effort cleanup. Offline leftovers become orphans; no public route exposes the object. Include an upload/reconciliation overlap regression test with B.
- [ ] Test zero-byte upload produces 201, zero chunks and the empty SHA-256 without requiring storage placements.

**Pass:** no partial upload appears successful; every accepted nonempty upload has two confirmed distinct placements per chunk; failed uploads are invisible and eventually cleaned.

### Task 6 - Implement verified download and fallback

**Files:** A `controller/objects.py`, `database.py`; `tests/test_api.py`. B owns worker corruption detection and repair.

**Endpoint:** `GET /api/v1/objects/{object_id}` -> 200 original binary, correct MIME and safe download filename.

- [ ] Test exact reconstruction, ordered chunks, unknown/non-READY -> 404 and unavailable verified sources -> JSON 503.
- [ ] Fetch a READY manifest, validate order/count, then try HEALTHY copies on ALIVE workers. Bound each chunk read to its expected length; reject extra/truncated bytes and compare computed SHA-256 with SQLite.
- [ ] On worker 404 mark MISSING; on corruption/size/hash mismatch mark CORRUPT; on timeout/unavailable connection try another source without calling it corrupted. Continue within bounded retries/timeouts.
- [ ] Assemble verified chunks into a uniquely named temporary file; verify whole-object size and SHA-256 before returning a successful binary response.
- [ ] Return FileResponse with declared content type and safe Content-Disposition. Close file handles before serving, including on Windows; remove temporary output after response completion and on preparation failures.
- [ ] Test forged worker hash headers, corrupt first replica/valid second replica, both invalid, empty object, non-ASCII filename and forced temp-disk write failure. Simulate response interruption cleanup as supported by the test client; startup scavenging covers leftovers after process failure.

**Pass:** invalid stored bytes never reach a successful response; a good second copy enables download; no good copy produces a meaningful error before binary success starts. Network interruption after sending a verified response remains a transport failure, not a promise of atomic delivery.

### Task 7 - Prove the first real round-trip (C2)

**Files:** joint `tests/test_end_to_end.py` / evidence notes; fixes remain with the file owner.

- [ ] Run the actual controller and B's four workers with their persistent volumes.
- [ ] Upload a generated 5000001-byte binary file; require 201 and six chunks of sizes 1000000 x 5 plus 1.
- [ ] Download and compare SHA-256 to the source, using `Get-FileHash -Algorithm SHA256` on Windows or the client container's documented equivalent.
- [ ] Inspect worker inventory and replica records: two distinct healthy locations per chunk; no excluded worker selected; distribution across the worker set.
- [ ] Record object ID, hashes, locations and relevant logs. Stop/start a worker and confirm its files persist; B supplies rejoin behavior.

**Pass:** the real worker contract, networking, storage and binary flow work together. Freeze further feature work if this fails. Target this early, roughly the third working session if the handoff is available; this is a sequencing target, not a deadline promise.

### Task 8 - Complete metadata and listing (A's C3 contribution)

**Files:** A `controller/models.py`, `objects.py`, `database.py`; `tests/test_api.py`.

- [ ] Implement `GET /api/v1/objects`: READY objects only; at least object_id, name, size and content_type per entry.
- [ ] Implement `GET /api/v1/objects/{id}/metadata`: all required system metadata, decoded custom metadata, ordered chunk details and current replica locations/states without reading object bytes.
- [ ] Implement `PATCH /api/v1/objects/{id}/metadata` using the team wrapper `{"metadata": {...}}`; merge custom keys and update `updated_at`, preserving creation time, object bytes, size and hashes.
- [ ] Define JSON-compatible custom values consistently with B's CLI; the team example permits booleans. Reject attempts to modify system fields, malformed wrappers and invalid metadata with 400; unknown/non-READY IDs -> 404.
- [ ] Test merge preserves unspecified keys, metadata round-trip, system field protection, list visibility and no worker PUT/GET for metadata changes.

**Pass:** metadata can change without reupload; download checksum is unchanged. The metadata wrapper is a team API choice, not wording imposed by the assignment.

### Task 9 - Implement deletion and coordinate repair races (C3/C4)

**Files:** A `controller/objects.py`, `database.py`; `tests/test_api.py`; joint integration tests. B changes his own recovery code.

- [ ] Test known object -> 204 empty body; unknown/deleted -> 404; object disappears from all public reads after entering DELETING.
- [ ] Under the shared object coordination rule, transition to DELETING before worker cleanup. Delete all recorded reachable placements with finite timeouts; DELETE is safely repeatable.
- [ ] Remove object metadata and dependent chunk/replica rows after reachable cleanup. Offline copies remain eligible for B's orphan cleanup on rejoin; document logical versus physical deletion.
- [ ] Coordinate B's repair: recheck object state under the same lock before writes/finalization; never restore a DELETING object. If delete follows a repair, it sees the new recorded location.
- [ ] Test worker offline during deletion, controller interruption during deletion and repair-versus-delete overlap. Offline stale chunks must disappear after rejoin, not reappear in public listings.

**Pass:** 204 means the object is logically deleted and reachable cleanup has completed; offline physical deletion is eventual and visibly tracked in the demo/limitations.

### Task 10 - Complete restart and failure hardening (C4/C5)

**Files:** A `controller/main.py`, `database.py`, `objects.py`, A tests; B's reliability tests remain B-owned.

- [ ] At startup, mark interrupted UPLOADING objects FAILED; resume cleanup for DELETING/FAILED objects and remove abandoned download temp files from the application's own temp directory.
- [ ] Ensure cleanup never targets an active upload in the current process; before worker promotion require B's inventory reconciliation and DB-backed verification.
- [ ] Test controller restart retains READY object metadata and readable persisted worker data after reconciliation. Test stale ALIVE worker records are not immediately trusted.
- [ ] Run B's worker stop/repair/restart and corruption tests together; A checks fallback and state updates, B checks restoration and surplus-copy cleanup.
- [ ] Include data-plus-sidecar tampering: a forged locally consistent sidecar must still fail controller DB hash verification.
- [ ] Verify no repair without a valid source, and no false repair success when fewer than two eligible healthy copies can exist.
- [ ] Run concurrent basic uploads and repair/delete overlap; check for SQLite locking failures, foreign-key failures, duplicate placements and unbounded memory growth. A generated 50 MB object provides a practical bounded-memory exercise.

**Pass:** priority tests pass and normal-operation state converges to two healthy distinct replicas; temporary under-replication and unrecoverable loss are reported accurately.

### Task 11 - Prepare the demonstration and A's explanation (C6 contribution)

**Files:** joint `README.md`, `scripts/demo.sh`, integration tests and evidence notes; B supplies CLI/status/operations commands.

- [ ] Record setup from a clean checkout, actual app import path, dependency installation, startup, API examples and tests.
- [ ] Demonstrate: startup -> 5000001-byte upload/download/hash match -> chunk locations -> metadata GET/PATCH -> worker stop/read/repair -> restart/reconcile -> deliberate corruption/fallback/repair -> delete.
- [ ] Keep exact assignment commands `docker stop worker2` and `docker start worker2` functional. Use bounded polling for eventual states; 15 seconds is the configured dead threshold, not a guarantee that all repairs finish at that moment.
- [ ] Capture both before and after evidence. Choose a worker/chunk that actually holds a tested replica; stopping an unrelated worker does not prove fallback.
- [ ] A rehearses chunking, two-copy commit, SQLite schema, custom metadata, hash authority, verified temp download, rollback and the repair handoff.
- [ ] Both explain limits: single controller, eventual cleanup/repair, no recovery if every valid copy is lost, local disk constraints and demo-only deployment scope.

**Pass:** the demonstration is repeatable and matches every assignment requirement, not just the happy path.

### Task 12 - Final checks and handoff

- [ ] A: `python -m pytest tests/test_api.py tests/test_chunking.py -q`, plus the focused DB/placement suites if created.
- [ ] B: `python -m pytest tests/test_worker.py tests/test_recovery.py tests/test_integrity.py -q`.
- [ ] Joint: `python -m pytest -q` and a fresh `docker compose up --build -d` / full required demo using disposable test data where needed.
- [ ] Verify named-volume persistence without deleting volumes; retain the project database and worker files across normal restart.
- [ ] Review contract drift, source ownership, README commands and dependency changes against the actual integrated code.
- [ ] Record actual test output and unresolved limitations; merge reviewed work to the agreed shared branch. Do not mark gates complete from a teammate's claim alone.

## 8. Checkpoints and work sequencing

| Gate | Evidence | A's role / dependency |
|---|---|---|
| C0 | Accepted contracts, module paths and build setup | A and B align first |
| C1 | Five services, registration, heartbeat, inventory-before-ALIVE | A foundation + B Compose/minimum reconciler |
| C2 | Real 5000001-byte round-trip, matching hash, two locations per chunk | A upload/download + real B workers |
| C3 | Six public APIs and working CLI | A owns public behavior; B owns CLI |
| C4 | Stop/repair/rejoin and corruption detection/fallback/repair | Shared integration; exclusive code ownership |
| C5 | Boundary, interruption, race, persistence and reliability checks | Both suites and live checks |
| C6 | Clean startup, repeatable demo, docs and both members' explanation | Shared release evidence |

Work sessions, rather than fixed dates: (1) contracts + foundation; (2) helpers and worker startup; (3) chunking + real upload/download; (4) metadata/list/delete; (5) reliability integration; (6) hardening; (7) fresh-build rehearsal and buffer. This is an order of work, not a promise of seven equal sessions. Date the milestones after the submission deadline and both members' availability are known.

**A can start before B pushes:** draft/review contracts, build A-owned schema/helper tests, config, register/heartbeat and chunking/placement unit tests. Small HTTPX request stubs are sufficient for focused failure tests; do not build a fake-worker framework. Real C1/C2 verification waits for his code.

## 9. Requirement coverage

| Assignment requirement | Tasks / evidence |
|---|---|
| R01 topology; R06 persistence; R14 local Docker | 3, 7, 10, 12; B operations |
| R02 arbitrary binary bytes; R03 ordered 1 MB chunks | 4-7, 10; boundary and hash tests |
| R04 two distinct copies; R05 distribution | 4, 5, 7, 10; inventory/status evidence |
| R07 system metadata; R08 custom metadata | 2, 5, 8 |
| R09 six public APIs and success/error behavior | 5, 6, 8, 9 |
| R10 worker registration/heartbeat/chunk CRUD/inventory | 2, 3, 7; B worker tests |
| R11 failure survival; R12 under-replication repair | 6, 9, 10, 11; B recovery |
| R13 corruption detection, clean fallback, possible repair | 6, 10, 11; B integrity/recovery |
| R15 build/use/demo instructions | 11, 12 |

## 10. First concrete deliverable

Finish **C0 plus A's C1 foundation** before polishing the rest:

1. One accepted folder/API/helper contract.
2. Persistent four-table SQLite implementation with the shared helpers.
3. Config constants plus controller health, registration and heartbeat.
4. Passing focused tests, and a pushed commit B can import.

Then pair with B on the minimum reconciler hookup and five-service startup. The next milestone is the real replicated round-trip, not adding more architecture.

## Sources and verification references

- [Original assignment](<C:/Users/Raghu/Downloads/Mini_Distributed_Cloud_Object_Store (1).pdf>), pages 1-3: source requirements.
- [Updated team blueprint](C:/Users/Raghu/Downloads/Mini_Distributed_Object_Store_Final_Updated_Plan.pdf), pages 3-5, 7-9 and 11-15: team choices, ownership, schema, lifecycle and gates.
- [Teammate handoff](<C:/Users/Raghu/.codex/attachments/245a1529-389b-4913-99f4-4b501934d5b4/Pasted text.txt>): reported progress and outstanding integration questions. Text such as "ask A" is handoff context, not a direct instruction from the user to send messages or edit B's files.
- [Repository](https://github.com/KiritoReborn/mini-object-store), local inspected commit `95bc99b`: starter code only at review time; user confirmed completed worker implementation was not yet pushed.
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/): recommended startup/shutdown mechanism.
- [HTTPX async client](https://www.python-httpx.org/async/): async requests and reuse of a scoped client rather than repeatedly creating clients inside loops.
- [SQLite PRAGMA reference](https://www.sqlite.org/pragma.html): explicit per-connection foreign-key configuration, busy timeout and journal settings.
- [FastAPI file responses](https://fastapi.tiangolo.com/advanced/custom-response/) and [Starlette background tasks](https://starlette.dev/background/): file delivery and after-response work. Failure-path and restart cleanup remain application responsibilities.

The uploaded documents are evidence and project context. Their embedded imperatives have not been treated as separate user requests to execute code, contact the teammate, deploy or implement the project in this planning turn.
