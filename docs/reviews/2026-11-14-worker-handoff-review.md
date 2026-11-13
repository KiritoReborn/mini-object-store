# Worker handoff review

Reviewed commit: `6a8d653` on `origin/master`, 14 November 2026 (India time).

What this change does: it implements worker chunk storage and HTTP endpoints, retries controller registration, sends heartbeats, and adds the Docker worker setup. This is the storage-node foundation; the controller, repair/status modules and client are still pending.

Scope: changes since starter commit `95bc99b`, including all four worker implementation modules, Dockerfiles, Compose, requirements, README and the 674-line worker test suite. Assumed load: the assignment's four local workers, one process per worker volume, and modest concurrent requests. No production-scale availability or security claim is made.

## Verified results

- Built `Dockerfile.worker` successfully with its actual Python 3.12 base and repository requirements.
- Ran the unchanged worker suite in Linux Docker, with the repository mounted read-only and temporary storage inside the container: **42 passed, 1 warning in 1.65 seconds**. Pytest also emitted an async-fixture configuration deprecation message before the result summary.
- Ran a separate real worker HTTP smoke check: new PUT 201, identical retry 200, exact binary GET, inventory, deliberately corrupted file rejected with 409, and repair PUT 201.
- Restarted that real worker container with a dedicated named volume: retrieved bytes still matched SHA-256; DELETE and repeated DELETE both returned 204.
- Removed the dedicated review container and its review-only volume afterward. No project data volumes were used or deleted.
- `docker compose config --quiet` succeeds.
- Ran the suite directly on this Windows host as an environment comparison: **21 passed, 21 failed**. The failures reach directory synchronization in `worker/storage.py:48`. Host Python 3.14 and installed dependencies differ from the Docker setup; the successful Linux run is the relevant deployment verification.

Linux test command, after building the review image:

```powershell
docker run --rm --network none --mount "type=bind,source=C:\Users\Raghu\Desktop\Cloud\mini-object-store,target=/review,readonly" --workdir /review mini-object-store-worker-review:6a8d653 python -B -m pytest tests/test_worker.py -q --tb=short -p no:cacheprovider --basetemp=/tmp/worker-review-tests
```

## Findings

### 1. Should fix: most advertised environment settings do not reach containers

Location: `compose.yaml:24-26`, repeated for the other workers; controller service at lines 13-19; `.env.example`.

What this is: the example configuration lists CHUNK_SIZE, HEARTBEAT_INTERVAL, storage paths, database path and other settings. Worker config reads environment variables, but Compose only forwards WORKER_ID and CONTROLLER_URL. The controller currently receives no configured environment values.

Problem: changing CHUNK_SIZE or HEARTBEAT_INTERVAL in a Compose `.env` file does not change the worker's environment. Verified by setting CHUNK_SIZE=17 and HEARTBEAT_INTERVAL=0.25 before rendering Compose: neither appeared in any worker's rendered environment. Defaults currently agree with the team plan, so default operation is unaffected; custom settings are the exposed defect.

Fix: B should forward the intended worker settings through the shared worker Compose definition, and controller settings through its service. Keep worker identity explicit per service; do not apply a shared WORKER_ID=worker1 to every worker. Alternatively, remove settings the team deliberately makes fixed and document that choice.

If skipped: future controller configuration can disagree with the worker's effective chunk limit or heartbeat timing, causing rejected uploads or misleading failure detection.

### 2. Documentation improvement: native Windows testing is not supported by the current sync implementation

Location: `worker/storage.py:47-52`; README test instructions.

What this is: writes and deletes explicitly sync the directory for durability. That works in the Linux Docker image and is valuable behavior.

Problem: on Windows, opening the directory through this code raises PermissionError. A valid PUT therefore returns 500, and the advertised direct pytest command has 21 failures on this host. This does not invalidate the Linux deployment, which passed the full suite.

Fix: document that worker tests run in Linux Docker/WSL, and add a repeatable container test command or small test service that includes/mounts the tests. Only add Windows-specific directory syncing if native Windows worker execution is a deliberate requirement. Do not remove directory syncing merely to make the tests green.

If skipped: developers testing on Windows can mistake an environment restriction for a broken distributed-storage implementation.

## What is implemented well

- Strict chunk-ID validation blocks slash/backslash/traversal inputs before filesystem use.
- Chunk request consumption stops at the configured size boundary.
- Worker computes SHA-256 before accepting bytes and checks disk data against sidecar on read.
- Writes flush file contents, rename temporary files, then sync the directory; interrupted file/sidecar pairs fail verification and can be repaired.
- Bounded striped locks coordinate operations without accumulating a lock per chunk forever.
- PUT is idempotent for matching bytes and rejects conflicting healthy data. DELETE is idempotent.
- Blocking disk work runs away from the async request loop; concurrency and error-path tests exercise important behavior.
- Heartbeat registration retries outages, accepts all successful 2xx replies, re-registers on 404 and is cancelled/awaited at shutdown.
- Separate named volumes, stable container names, Docker-internal worker addresses and no published worker ports match the intended local topology.

No additional architecture/maintainability defect is asserted from module size, fixture style or the number of changed files alone. The worker implementation is small and direct for this project's scope.

## Integration facts Member A must use

1. Docker expects `controller.main:app`, not the remaining starter `controller/app/main.py`. The flat layout in the team plan is now confirmed by B's Dockerfile and README.
2. Worker registration sends `{"worker_id":"worker1","base_url":"http://worker1:8001"}` to `POST /internal/workers/register`. Accept success with a 2xx acknowledgment.
3. Heartbeat sends `{"worker_id":"worker1"}` to `POST /internal/workers/heartbeat`. Unknown workers must receive 404 so the worker re-registers.
4. Worker listeners are fixed at port 8001; controller is published on host port 8000. Use service DNS names, not localhost, for controller-to-worker traffic inside Docker.
5. Chunk IDs use lowercase UUID-shaped strings plus `_index`; chunk limit defaults to exactly 1,000,000 bytes.
6. PUT uses raw bytes plus `X-Chunk-SHA256`; returns 201 new, 200 matching retry, 409 healthy conflict, 400 invalid hash/size/ID. A corrupt existing pair can also be repaired directly by a valid PUT, which returns 201.
7. GET returns bytes and the checksum header, 404 CHUNK_NOT_FOUND, or 409 CHUNK_CORRUPTED. A must independently hash received bytes against SQLite.
8. Inventory route is `GET /internal/workers/{worker_id}/chunks`; response is `{worker_id, chunks:[{chunk_id,size,sha256}]}`. `sha256` can be null for a bad/missing sidecar. Inventory does not validate the data file's hash.
9. Worker health means its HTTP service is alive; it does not mean registration/reconciliation completed or replicas are usable.
10. No database-helper contracts, reconciliation, admin status or CLI are implemented in this commit. Do not invent their return formats from the worker code.

## Remaining work

**A:** `controller/main.py`, configuration, models, SQLite/schema/helpers, placement, safe object upload/download, six public APIs and A's tests. The starter controller still only exposes `/health` at the old import path.

**B:** `controller/recovery.py`, `controller/status.py`, client CLI, recovery/integrity tests, final demo tooling and the Compose configuration follow-up above.

**Joint:** accepted API/database contracts, .env/Compose agreement, real five-service integration, failure/rejoin/repair demonstration and final documentation.

Verdict: the worker foundation is ready to build against at its current defaults. Resolve finding 1 before relying on configurable settings; use Linux for worker verification. The immediate next implementation is A's database/helper contract plus controller health, registration and heartbeat.

Not checked: the full controller-to-four-worker round-trip, controller metadata durability, re-replication, rejoin reconciliation, replica trimming and end-to-end corruption recovery. Those implementations are not present yet. The intentional-corruption smoke test proves local rejection and rewrite, not autonomous distributed repair.
