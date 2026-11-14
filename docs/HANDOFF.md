# Current controller/frontend handoff

Read this first in Codex, Claude or a new chat. Latest user instructions override the earlier planning history.

## Member B recovery delivery - 14 November 2026

The latest task explicitly authorizes B's production `controller/recovery.py` and
`tests/test_recovery.py`. Those files are now implemented. Earlier statements
below that recovery is absent describe the previous checkout/runtime, not this
new source. No A-owned source, existing tests, workers, deployment controls,
frontend, requirements or contracts were changed in this delivery.

Implemented behavior:

- A synchronous `start_reconciler()` returns None promptly; an **async**
  `stop_reconciler()` cancels/awaits the task and closes its HTTP client. This
  follows the current hookup in contracts/db-helpers.md and main.py; a synchronous
  stop cannot drain async work before returning to that running event loop.
- Serialized passes detect stale workers with startup grace and heartbeat CAS,
  reconcile JOINING inventories, then repair READY chunks. Fresh DEAD workers
  must pass JOINING again. Absent/invalid/future heartbeats do not grant admission.
- Every retained/read-back copy is verified against SQLite size/SHA-256.
  CORRUPT/MISSING copies are deleted before rewrite; failed targets do not become
  HEALTHY. Surplus deletion requires two independently verified other copies.
- All object mutations share objects.object_lock, reread current manifests, and
  protect UPLOADING objects. Threaded DB calls drain before cancellation releases
  the lock. HTTP origins are resolved from the DB for each request.
- Live-worker inventories run once per minute to collect late ambiguous writes
  and orphan/surplus copies. This does not periodically scrub HEALTHY file bytes.
  Unavailable/no-target logs are throttled per chunk; deleted chunks' throttle
  entries are pruned. Required demo log event names are present.
- Tests replace `_runtime.client`, `.now` and `.monotonic`; `run_once()` is the
  deterministic one-pass entry point. SQLite helpers remain direct imports and
  keep their frozen signatures. No new dependency was added.

Verification on this checkout:

- `.venv/bin/python -m pytest tests/test_recovery.py -v --tb=short`: **65 passed**.
  Includes at least one test for every numbered case 1-30, partial-stream and
  cancellation cases, inventory errors, lock races and per-call HTTP timeouts.
- The integration case uses the actual FastAPI lifespan/routes, SQLite helpers,
  placement and B reconciler, with only worker HTTP replaced by MockTransport.
  It verifies real admission, 5,000,001 bytes -> 6 chunks / 1-byte final chunk,
  two-copy repair, rejoin trimming, DB-authoritative corruption fallback/repair,
  and successful downloads. It does not manually supply worker eligibility.
- Full suite in disposable Python 3.12 Linux Docker, read-only source mount,
  network disabled: **281 passed, 2 failed**, one existing Starlette/httpx warning.
  Both failures are A-owned expectations of `recovery_available: false` now that
  recovery is installed: `tests/test_api.py:74` and `tests/test_dashboard.py:48`.
  A should explicitly suppress the optional recovery module in those fixtures
  when testing the absent-module scenario, or update the installed-module
  expectations and isolate their external worker HTTP. They were left untouched
  as required by the exclusive file scope. No all-green full-suite claim is made.

Linux command used (no project volumes or published ports):

```sh
docker run --rm --network none \
  --mount type=bind,source="$PWD",target=/review,readonly \
  --workdir /review cloud_project-controller:latest \
  python -B -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/recovery-review --tb=short
```

Remaining integration: A's two absent-module fixture expectations need updating;
B's status router, CLI and other previously pending work remain outside this
task. No project service was rebuilt/restarted or volume changed. Run the joint
five-container stop/start/corruption demo after deployment before claiming the
live recovery gate. The mock-boundary integration test is not that live demo.

## Current scope and ownership

- User is Member A. Build frontend/controller and a simple demo. **Do not implement or modify worker code or recovery**; Member B is implementing those.
- Deployment choice: static frontend on Vercel; controller plus four Docker workers on the PC; one ngrok HTTPS address connects the browser directly to the backend. No nginx gateway, cloud database, VM or second application server. See DEMO.md.
- An interim recovery experiment was used while investigating endless JOINING, then removed when the user explicitly reserved recovery for B. controller/recovery.py and its tests are absent. No interim recovery implementation is committed or published. Do not re-add it or manually promote workers.
- Source branch: feature/controller. Synchronized with origin/master at be6d75b, then committed this expansion as **3ae2b93** and pushed it to origin/feature/controller. Post-push comparison showed 0 ahead / 0 behind and a clean working tree. Later documentation-only commits may follow. No force push or new shared-master merge was performed.

## What is implemented now

Original A object lifecycle, verified chunk/object downloads, two-copy upload commit, metadata/list/delete, persistence and shared contracts remain intact. The React dashboard is committed as source and generated controller/static assets; normal local use needs no Node server. Earlier evidence/review reports are under docs/reviews.

New local worker administration:

- GET /api/v1/workers adds labels/notes, actual availability, all-replica counts, placement_enabled and can_forget. Existing B helper dictionaries/signatures remain unchanged.
- Connect validates only matching local-Docker worker1..worker16 origins and verifies a bounded health/identity response. It connects an already running service, never creates a container or grants ALIVE.
- PATCH edits name/notes or pauses A's next upload selection. Reads/in-flight writes/recovery state are separate.
- Forget is atomic and allowed only for stale/absent-heartbeat nodes with zero replica records of any state. It does not delete containers/disks.

New demo controls in controller/demo.py:

- Opt-in GET /api/v1/demo/workers and POST /api/v1/demo/workers/{worker}/{start|stop|restart} use Docker's local socket.
- Exact worker1..worker4 allowlist, expected Compose-project/service/name checks, owner key plus admin header, serial actions and frontend confirmation. No shell, exec, arbitrary container, create/delete, volume deletion or Docker TCP port.
- compose.controls.yaml is an optional overlay. It mounts Docker's privileged socket; this remains powerful access and belongs only on the trusted owner demo PC. Default Compose omits the socket.
- Actual container state is displayed separately from controller ALIVE/JOINING. Starting a container does not complete B's reconciliation.

Frontend changes:

- Operation summary is the activity default: group similar successful chunk events by file/direction/minute, omit started/ordinary healthy bookkeeping, retain failures. Technical events remain available via the filter. Bounded history/replay/error/gap/restart truth stays intact.
- Backend Connection settings support the direct remote HTTPS address and an in-memory owner key; no key enters storage, exports, Vercel build variables or the bundle.
- Guided demo checklist and self-reported note export; no checkmark claims automatic test/recovery success.
- Worker labels/notes/pause/connect/forget plus confirmed actual start/stop/restart and separate container-state display.
- frontend/vercel.json + VERCEL-aware build output dist. Local builds still regenerate controller/static. VITE_API_BASE_URL is public URL only. Exact-origin CORS and owner-key API authentication live in the controller.

## Current runtime and credentials

- Normal local stack is running on http://127.0.0.1:8000/ with demo controls enabled. Four worker containers are running; worker4 was stopped and restored through both API and actual browser UI, preserving volumes.
- The controller binds only loopback. Internal routes are rejected for public hostnames. No worker ports or Docker TCP endpoint are published.
- Configure-Demo.ps1 generated a private owner key in ignored root .env. Never print/commit it. Open it privately and enter the value in frontend Connection settings; reload clears the frontend key. Start-Artaud.ps1 -DemoControls preserves it and the data volumes.
- All four workers register/heartbeat, but recovery_available=false and they remain JOINING. Root cause is absent B recovery, not broken Docker connectivity. Nonempty uploads require B's verified admission. The temporary experiment's runtime was replaced with this source-aligned controller.
- Existing user files/volumes were preserved. Only specifically identified browser QA objects were cleaned; do not delete unknown runtime files.
- No public tunnel is running. ngrok browser sign-in was confirmed earlier, but the local agent token/config is absent. Its assigned domain was observed as tactile-chant-freely.ngrok-free.dev. Do not claim it is active.
- Vercel integration was suggested but latest confirmed state is not installed/connected. No frontend has been published to Vercel, no DNS/domain changes made, and no account token saved to the repo. Complete publishing after the user connects Vercel and configures their local ngrok agent. See DEMO.md for the minimal steps.

## Verification

Frontend unit tests: 19 passed. TypeScript/local build and Vercel dist build passed. Chromium suite: 25 passed, including accessibility/mobile, exact remote API connection/key non-persistence, operation-summary grouping and confirmed worker stop/start.

Final backend suite: **218 passed**, one existing Starlette/httpx deprecation warning, in a disposable Linux Docker container with the source mounted read-only and no network. Two new security cases cover wrong-project Docker protection and remote CORS preflight. An earlier full run hit one intermittent pre-existing concurrent-upload assertion (217 passed, 1 failed); isolated concurrent upload, the whole 26-case object API group, and two subsequent full 218-case runs passed. Response diagnostics were added; the intermittent failure's root cause has not been identified, so no fix to it is claimed.

Final frontend verification: 19 unit cases and 25 Chromium cases passed again; local and Vercel-mode TypeScript/Vite builds passed. An initial browser-run attempt could not start its local server under restricted execution and was stopped; the permitted rerun completed all cases. Author inspected the real desktop Cluster capture. See docs/reviews/2026-11-14-demo-review.md for scope and limits.

Actual local checks: Docker control API reported four running containers; worker4 stop returned running=false and immediate start restored running=true. Real Chromium entered the private key via Connection settings and verified Stop/Start confirmations and displayed state. All four were left running. Startup script initially exposed a localhost/IPv6 health-check mismatch after loopback binding; explicit 127.0.0.1 and a PowerShell single-line-array fix now make startup finish successfully.

## Remaining work and safe continuation

1. Final tests/docs review and feature-branch publication are complete (3ae2b93). Worker source and recovery hooks remain unchanged. Review or merge through the team's normal GitHub workflow when ready.
2. B implements controller/recovery.py start_reconciler/stop_reconciler and status.py router, plus CLI/reliability integration. Shared API/helper/lock contracts are in contracts/*.md. No heartbeat promotion shortcut.
3. Connect Vercel, publish only frontend with VITE_API_BASE_URL, configure exact ARTAUD_ALLOWED_ORIGINS using Configure-Demo.ps1, start the local ngrok agent and verify the actual URLs. No Vercel upload proxy or extra gateway.
4. Run the final joint stop/fallback/repair/rejoin/corruption demonstration using B's actual reconciler. Existing tests/live_controller_check.py remains explicitly controlled A-only evidence with test-only eligibility; it does not prove B's production recovery.
5. Run source changes through npm run build to update committed controller/static. Keep test captures, node_modules, dist, .vercel and credentials out of Git.
