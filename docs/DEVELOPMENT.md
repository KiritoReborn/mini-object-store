# Development and testing

[Setup](../README.md#run-locally) · [Architecture](ARCHITECTURE.md) · [API contract](../contracts/api-contract.md)

## Code map

| Area                                                   | Main files                                                              |
| ------------------------------------------------------ | ----------------------------------------------------------------------- |
| App lifecycle, validation and configuration            | `controller/main.py`, `models.py`, `config.py`                          |
| SQLite metadata and stable integration helpers         | `controller/database.py`, `schema.sql`, `contracts/`                    |
| Placement and object lifecycle                         | `controller/placement.py`, `objects.py`                                 |
| Inventory, admission and automatic repair              | `controller/recovery.py`                                                |
| Worker disk storage, HTTP API and heartbeat            | `worker/storage.py`, `main.py`, `heartbeat.py`                          |
| Dashboard, worker administration and demo control APIs | `controller/dashboard.py`, `worker_admin.py`, `demo.py`, `telemetry.py` |
| React interface and browser verification               | `frontend/src/`, `frontend/e2e/`                                        |
| Docker/Compose and end-to-end acceptance               | Dockerfiles, Compose files, `tests/test_end_to_end.py`                  |

Run one controller process. Per-object locks and background work are process-local; multiple Uvicorn workers are unsupported. SQLite transactions remain short and contain no network calls. Controller download preparation uses temporary disk storage, then verifies complete bytes before returning a binary response.

Before changing shared helpers, read [db-helpers.md](../contracts/db-helpers.md). Preserve record shapes, registration fencing, object locks and post-commit observation. The controller database is authoritative for chunk size/hash; worker sidecars alone cannot establish integrity. Only READY objects are public.

## Controller development

Docker uses Python 3.12 and the shared `requirements.txt`. For direct host development, install those requirements, set `DATABASE_PATH` and `DOWNLOAD_TEMP_DIR` to writable local paths, then run:

```sh
python -m uvicorn controller.main:app --host 127.0.0.1 --port 8000
```

The default Docker paths are `/data/metadata.db` and `/data/downloads`. Worker storage defaults to `/data/chunks`. Internal requests use Docker service DNS, not localhost. A variable written in `.env` is not automatically injected into a container unless Compose references it.

### Compose configuration

| Setting                  | Default                  | Scope                                                           |
| ------------------------ | ------------------------ |
| `CHUNK_SIZE`             | 1,000,000 bytes          | Controller and workers                                          |
| `HEARTBEAT_INTERVAL`     | 5 seconds                | Worker heartbeat                                                |
| `WORKER_DEAD_TIMEOUT`    | 15 seconds               | Controller eligibility/death detection                          |
| `RECONCILE_INTERVAL`     | 5 seconds                | Recovery passes                                                 |
| `HTTP_TIMEOUT`           | 5 seconds                | A's worker requests; recovery has separate per-operation limits |
| `CONTROLLER_URL`         | `http://controller:8000` | Worker registration/heartbeat                                   |
| `ARTAUD_API_KEY`         | Empty                    | Optional local owner key; required for public/demo operation    |
| `ARTAUD_ALLOWED_ORIGINS` | Empty                    | Exact allowed remote frontend origins                           |

Replication is fixed at two. Ports are fixed by Compose/Dockerfiles: controller `8000`, workers `8001`. Recreate affected services after configuration changes. The controls overlay derives its container-project allowlist from the active Compose project, including `-p`; preserve the original project/volumes.

`ARTAUD_DEMO_CONTROLS=true` and `ARTAUD_DEMO_FAULT_INJECTION=1` are set by the controls overlay, which also sets `WORKER_ENABLE_FAULT_INJECTION=1` on all workers. Starting only the controller with that overlay cannot enable the worker corruption endpoint on an existing base-only worker image/configuration. See [demo setup](DEMO.md).

## Frontend development

Use Node.js 22.12 or newer. From the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Vite serves http://127.0.0.1:5173 and proxies API/health/docs requests to the local controller on port `8000`. Existing owner authentication still applies. Edit `frontend/src`, then run `npm run build` to typecheck and regenerate the committed `controller/static` assets. Rebuild/recreate the controller to serve them. Vercel builds write `frontend/dist` instead.

The UI uses React/TypeScript, plain CSS, Lucide icons and self-hosted Geist. [DESIGN.md](../DESIGN.md) defines its tokens and interactions. Keep empty/loading/error/stale states, keyboard navigation, focus management, reduced motion and small-screen layouts usable.

### Frontend behavior to preserve

- Upload progress describes bytes sent. Only controller `201` means Stored. Cancellation and ambiguous outcomes must remain explicit.
- Downloads use the writable-file picker where available. The Blob fallback buffers the full response before triggering save. Picker cancellation is not download success.
- Metadata PATCH sends changed/new top-level keys; unspecified keys survive and same-key changes remain last-writer-wins. Key deletion is not implemented.
- Literal metadata/ID/name search reads listings, not file bytes. CSV exports neutralize formula prefixes and preserve snapshot labels. Bulk deletion confirms selected names and stops after uncertain/auth failures.
- The owner key stays in memory and clears on reload. Session-only backend preferences are separate from credentials. Keys never enter build variables, browser storage, captures or exports.
- Worker counts/bytes describe recorded replicas, not disk capacity. Storage eligibility, container running state and upload-placement pause are distinct.
- Request diagnostics retain at most 60 redacted observations in memory. They describe browser elapsed time, not worker latency or a durable audit trail.

### Local file checksum verification

In **Files → Details → Verify integrity**, select one original/downloaded file and choose **Verify file**. The tool compares its SHA-256 with stored object metadata. It accepts files up to 128 MiB (134,217,728 bytes), including empty files, over HTTPS or localhost with Web Crypto support.

Files are read in 256 KiB slices with progress and accumulated into a complete buffer for Web Crypto. The selected bytes stay in the browser; no additional API call uploads them. MATCH/MISMATCH refers to that selected file at verification time. A JSON report includes filename, size, expected/computed hashes and capture time. Replacing the file, closing the inspector or cancelling discards pending results; an already running digest may finish internally.

## Automated checks

### Linux backend suite

Build from the repository root:

```sh
docker build -f Dockerfile.controller -t mini-object-store-controller:integration .
docker build -f Dockerfile.worker -t mini-object-store-worker:integration .
```

PowerShell:

```powershell
docker run --rm --network none --mount "type=bind,source=$($PWD.Path),target=/review,readonly" --workdir /review mini-object-store-controller:integration python -B -m pytest tests -q -p no:cacheprovider --basetemp=/tmp/object-store-tests
```

POSIX shell:

```sh
docker run --rm --network none --mount "type=bind,source=$PWD,target=/review,readonly" --workdir /review mini-object-store-controller:integration python -B -m pytest tests -q -p no:cacheprovider --basetemp=/tmp/object-store-tests
```

The read-only mount supplies the checkout/tests. Temporary data remains in the disposable container; existing Compose volumes are not attached. Linux is required for worker directory-sync tests. Normal pytest skips the explicitly invoked live Docker test.

### Frontend checks

```sh
cd frontend
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Vitest exercises request, metadata, integrity, formatting, connection and export boundaries. Normal Playwright tests use explicit HTTP fixtures, including failures and accessibility checks. These fixtures never ship in the runtime bundle and do not prove production recovery.

### Real five-container acceptance

With the integration images above, Docker and host Python 3.12+, run from the repository root:

```sh
python tests/test_end_to_end.py --large
```

After installing frontend dependencies and Chromium, include the real browser workflow:

```sh
python tests/test_end_to_end.py --large --browser
```

The standard-library harness creates a UUID-labelled private network, controller, four workers and five new volumes, with a random loopback controller port. Only its own resources are removed afterward. The controller performs normal verified admission and recovery in this test. It checks exact chunk boundaries, two physical copies/hash validation, Unicode metadata, stop/fallback/death/repair/rejoin, forged-sidecar corruption, restart persistence, physical deletion and optional 50,000,000-byte streaming.

`sh scripts/demo.sh --large` is a POSIX wrapper for the same runner. Use `--help` for timeouts/image options; defaults are the integration tags above. The older `tests/live_controller_check.py` remains historical pre-recovery A-only tooling; use `test_end_to_end.py` for current integrated evidence.

Scripts under `frontend/e2e/live-*.mjs` are explicitly invoked checks against actual configured endpoints. Some create/delete a QA object or stop/restart a real worker. Read their operations first and notify anyone demonstrating the shared stack; prefer the isolated harness. Never use a private existing object for a public-route performance test.

### Dated verification

On 23 November 2026, a clean snapshot at `20357e2` passed 369 backend tests, 42 frontend unit tests and 43 Chromium cases. Pytest skipped the opt-in live test, which passed separately with the full five-container, 50 MB and real-browser workflow. The backend suite emitted one Starlette test-client deprecation warning. [Verification report](report/artaud-report.pdf)

A separate fresh clone at `8ea6280` also passed 369 backend tests, 42 frontend unit tests and 43 Chromium cases. The isolated Docker Desktop loopback run uploaded one 50,000,000-byte object in 3.53 s and downloaded it in 0.88 s with matching SHA-256. After the stop command, worker2 was first observed `DEAD` at 17.21 s, and the replica deficit reached zero at 19.09 s. Verified rejoin took 6.07 s from the start command. [Report and evidence](report/artaud-report.pdf)

## Activity contract

`GET /api/v1/activity?after=0` returns a bounded process-local journal:

```json
{
  "stream_id": "process-session-uuid",
  "oldest_id": 0,
  "latest_id": 0,
  "next_cursor": 0,
  "truncated": false,
  "events": []
}
```

The journal retains up to 512 events and resets on controller restart. IDs increase within a session. After a changed stream ID, the browser replaces old history and refetches from 0. Eviction or a cursor reset can mark `truncated`. An ahead-of-stream cursor returns retained history; `next_cursor` is the last returned ID, or the unchanged valid cursor when no events exist.

Each event contains `id`, UTC `timestamp`, `kind` and nullable `object_id`, `chunk_id`, `worker_id`, `transfer_id`, `direction`, `size`, `state`, `previous_state`, `name`, `detail`. Text is bounded at 512 characters; size is a nonnegative signed 64-bit integer. Directions are `to_worker`/`from_worker`. File bytes, custom metadata, URLs, secrets and exception text are excluded.

Kinds include transfer started/completed/failed; object ready/deleted; metadata updated; worker/replica state; repair started/completed/failed; worker settings/action/connected/forgotten; and fault injected. Actual identifiers are defined in `controller/telemetry.py`.

Mutation observations publish after successful DB commits and may interleave relative to commit order. Unchanged heartbeats/states do not flood the journal. A removed replica can have null state. Object cascade deletion does not imply every offline disk was already erased. Telemetry is best effort and cannot decide storage success. Current overview/manifests remain authoritative; this is not a permanent audit log.

Each worker transfer attempt has its own ID. Completion means acknowledged write or verified read, not a browser save or final object publication. Corruption injection emits `fault_injected` after the worker acknowledgement. A later download or inventory pass records CORRUPT when it detects the damaged copy. Detailed repair phases appear only when actual recovery emits them.

Recovery can use the optional hook:

```python
from controller.telemetry import record_event

record_event("repair_started", object_id=object_id, chunk_id=chunk_id,
             worker_id=target_worker_id, detail="Copying from a verified replica")
# Only after the actual write/read-back verification succeeds:
record_event("repair_completed", object_id=object_id, chunk_id=chunk_id,
             worker_id=target_worker_id, detail="Replacement copy verified")
```

Use fixed nonsensitive descriptions and real transfer directions only. This hook does not bypass object locks, checksum checks or verified admission. The topology does not claim worker-to-worker forwarding or packet-rate measurement.

The UI keeps up to 512 observed events and labels stream gaps/restarts. Pause freezes the explorer's snapshots/manifests/activity, not the surrounding workspace. Live requests are serialized and bounded; reduced motion removes packet travel. Replay is labelled historical observation and does not change health. Exports retain stale/pause/error/capture labels rather than implying one atomic snapshot across endpoints.
