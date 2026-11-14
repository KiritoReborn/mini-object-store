# Current combined project handoff

Read this first in Codex, Claude or a new chat. Latest user instructions override earlier planning history. Current integration is being prepared on feature/controller; use git log/status and the integration PR for the final merge SHA.

## Delivered scope and ownership

Member A owns controller/API/database/frontend; Member B delivered worker storage and production recovery in feature/workers at 2924a6db81c5635462d162c4f683889ad1584231 (c3821e1 code, 2924a6d handoff). That branch was combined locally with current A work before testing. No open worker PR existed when inspected, so the verified combined branch will be merged through an integration PR. Preserve B authorship and worker source. Optional status.py/standalone B CLI remain absent; main.py includes status.router only when that module actually exists. Existing synchronous-start/awaitable-stop hookup required no production change.

Recovery is installed and working; the old missing-reconciler/JOINING blocker is resolved. No manual ALIVE shortcut is installed. New/restarted workers remain JOINING until B verifies their inventory and DB-authoritative bytes.

Integration corrections:

- Explicit opt-in tests/conftest.py no_recovery_module fixture isolates A unit apps by simulating the optional module's absence. B recovery tests and lifecycle-hook tests retain their real/explicit hooks. The snapshot test calls overview without an application/background tasks.
- Same-origin registration during inventory previously could inherit old eligibility. Additive worker_registrations tokens now rotate transactionally on registration, remain stable across heartbeats, and are checked atomically at admission. Existing worker/helper dictionaries/signatures remain intact; legacy tokens are backfilled once. Read contracts/db-helpers.md before changing this boundary.
- Recovery rejects naive timestamps consistently with placement. A real-SQLite regression reproduces restart during inventory, fresh readmission/repair and normal-heartbeat liveness.
- Compose now forwards shared chunk size and timing configuration; replication remains fixed at two. Default chunk size is 1000000 bytes, heartbeat 5s, dead threshold 15s, reconcile interval 5s. B's operation-specific recovery HTTP limits remain 5s/10s.

## Runtime and deployment

Architecture: browser loads static frontend from Vercel and calls the PC controller directly through ngrok HTTPS; controller talks to four local Docker workers. No Vercel Docker backend, upload proxy, extra application server or cloud database.

- Public frontend: https://frontend-nine-iota-19.vercel.app/ . Current promoted candidate dpl_HPE3VgKWoUCwFCwcjcpLZsa1QRo7, source frontend asset index-DtlTObPE.js. It includes metadata/ID search, exports, bulk actions, connection testing and request diagnostics.
- Current backend: https://d55b-119-161-98-68.ngrok-free.app → http://127.0.0.1:8000. Ngrok runs hidden with request inspection disabled. Its PID/logs are in ignored frontend/test-results/connection; no token was copied into the repo. PC/Docker/agent must stay running. Verify the actual endpoint after restart; a changed URL needs a Vercel variable update/redeploy or tab-local Connection settings override.
- Vercel CLI65.16.0 is signed in as kiritoreborn; project frontend, ID prj_vXMKpATbbwTAdk2AXw3UqpYz9aBb, scope raghus-projects-d1fa7fd7, root frontend, framework Vite/output dist. Production VITE_API_BASE_URL is the public backend URL only. Root .vercel/project.json and .env.local are private/ignored. Never print or commit account credentials.
- Deployment upload whitelist includes only frontend source and excludes env files, node_modules, dist, captures and all backend/data files. The verified staged deployment had 51 frontend source files and zero unexpected source categories. Use documented /* + !frontend patterns; trailing-slash directory negation previously selected zero files. The staging automation bypass created by vercel curl was revoked afterward; other protection settings were preserved.
- PC controller binds loopback, keeps owner-key API authentication and exact CORS for the frontend URL. Public internal worker routes return404; forged internal Host requests were rejected by ngrok with421 while normal TLS validation remained enabled. No host rewrite is configured.
- Owner key remains in ignored root .env. Enter it in frontend Connection settings; it stays in page memory and clears on reload. It is absent from bundles, Vercel variables, diagnostics exports and browser storage. Do not request/paste it in chat.
- Current PC state verified: recovery_available=true, 4 registered/4 available, 2 existing objects, zero under-replicated chunks and zero corrupt replicas. Four worker containers/volumes preserved. Before upgrading only the controller, all five volumes were backed up under ignored data/backups/pre-recovery-20261114-185439.

## Frontend/API behavior

All six REST APIs work independently of the UI. Upload uses spooled multipart and chunk-sized reads; READY requires two acknowledged eligible locations per chunk. Download verifies complete object/chunk bytes before binary success. JSON errors, metadata merge restrictions, object locks, cancellation cleanup and original worker contracts remain intact.

UI provides file lifecycle/metadata/chunks, real topology/placement, bounded activity/replay, quiet summaries, diagnostics and confirmed worker controls. Docker controls are optional owner-demo conveniences with privileged socket access; start/stop/restart only for fixed project workers, no arbitrary exec/delete/volume removal. Standard assignment commands docker stop worker2 / docker start worker2 still work. Placement pause affects subsequent A uploads, not B recovery policy.

Literal name/ID/custom-metadata search never downloads file bytes. CSV/JSON listing exports include metadata/capture time/snapshot status; CSV is formula-safe. Explicit page selection may accumulate with a visible note; changing filters clears it. Serial bulk deletion reports per-file known/unknown/unattempted outcomes and stops on uncertain/auth failures. Request diagnostics retain60 redacted browser observations, not a persistent audit log or worker latency metric. Recovery UI displays actual DB state transitions; detailed transfer phases appear only if B emits the documented optional telemetry hooks.

## Verified evidence

- Full Linux suite: 299 passed, 1 skipped (explicit opt-in live Docker test), 1 existing Starlette/httpx warning. Baseline combined source had290 passed/2 failures; the reported third snapshot race was intermittent. Both admission/timestamp defects were reproduced by failing regressions before fixes. Independent standards/spec reviews and a follow-up admission review found the material issues resolved.
- Frontend prior/current code: 28 unit and29 Chromium cases passed, including keyboard/accessibility/narrow screens. Local and Vercel builds passed. Current public build was checked for correct HTTPS origin/current features and absence of owner key.
- tests/test_end_to_end.py --large --browser passed with five isolated real containers and B's actual reconciler:4 ALIVE, browser workflow, 5000001-byte six-chunk/two-physical-copy roundtrip across4 workers, Unicode filename/PATCH, actual worker2 stop/read fallback/DEAD repair/rejoin/surplus trim, corruption with forged sidecar and DB-hash repair, controller restart persistence, 50000000-byte streamed/hash-matching transfer with50 chunks, all six endpoints and physical delete cleanup. All labelled QA resources removed. The first restart check exposed Docker changing its random host port; the harness now refreshes the mapping and the complete rerun passed.
- Public Vercel→HTTPS→PC browser test passed with baked-in origin (no manual URL override), owner key,4 available recovered workers, real1000001-byte upload/metadata/chunks/hash-matching download/delete and worker controls. Only its uniquely named temporary object was removed; existing2 objects preserved.
- scripts/demo.sh Linux shell syntax and Compose configuration validated. Historical tests/live_controller_check.py is pre-recovery A-only evidence and intentionally expects absent recovery; use the new joint harness for current acceptance.

## Final publication / continuation

Finish the committed clean-checkout verification, create/merge the integration PR into master after green, then sync/verify the exact remote merge. Record its SHA/link here. No force pushes. Keep worker source unchanged and preserve B ownership.

For local startup use scripts/Start-Artaud.ps1 (optional -DemoControls); no Node server is required. See README.md, docs/ACCEPTANCE.md, docs/DEMO.md and contracts/*.md for explanation and repeatable checks. Optional B CLI/status and deeper repair telemetry are separate coordination items, not missing core upload/admission/recovery behavior. Future features/backlog are in docs/research/2026-11-14-controller-frontend-features.md; avoid reimplementing B recovery or adding deployment infrastructure.
