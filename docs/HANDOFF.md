# Current controller/frontend handoff

Read this first in Codex, Claude or a new chat. Latest user instructions override the earlier planning history.

## Current scope and ownership

- User is Member A. Build frontend/controller and a simple demo. **Do not implement or modify worker code or recovery**; Member B is implementing those.
- Deployment choice: static frontend on Vercel; controller plus four Docker workers on the PC; one ngrok HTTPS address connects the browser directly to the backend. No nginx gateway, cloud database, VM or second application server. See DEMO.md.
- An interim recovery experiment was used while investigating endless JOINING, then removed when the user explicitly reserved recovery for B. controller/recovery.py and its tests are absent. No interim recovery implementation is committed or published. Do not re-add it or manually promote workers.
- Source branch: feature/controller. Earlier demo expansion 3ae2b93 and handoff 2f33556 were merged by the team in origin/master at **9b29954**. This checkout fast-forwarded to that merge, then published the connected-workspace expansion as **b50a86d** to origin/feature/controller. Post-push comparison was 0 ahead / 0 behind with a clean working tree. Later handoff-only commits may follow. No force push or new shared-master merge was performed here.

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

Connected workspace expansion:

- Scoped name/ID/custom-metadata search operates on READY list metadata only. Iterative key/scalar traversal preserves literal quotes, paths and nested values. CSV/JSON listing exports include metadata/capture time/snapshot status; CSV cells are quoted and formula-safe.
- Select this page touches visible rows only. Explicit selection can accumulate across pages with a visible note, and clears when search/type/scope changes. Confirmed bulk deletion serially reuses existing DELETE, reports removed/already absent/rejected/unknown/unattempted results, stops on uncertain or auth outcomes, and refreshes listings. No new bulk backend or recovery behavior.
- Connection settings can test a draft URL/key without saving them. Request diagnostics retain 60 redacted browser measurements, failure-first; include response/body failures even after 2xx headers. Clear/connection changes invalidate late old observations. No IDs/names/URLs/headers/bodies/metadata/keys enter this log/export. It is not a durable audit log or worker-latency metric.
- Sources and feature/ownership assessment: docs/research/2026-11-14-controller-frontend-features.md. Current code/review evidence: docs/reviews/2026-11-14-connected-workspace-review.md.

## Current runtime and credentials

- Normal local stack is running on http://127.0.0.1:8000/ with demo controls enabled. Four worker containers are running; worker4 was stopped and restored through both API and actual browser UI, preserving volumes.
- The controller binds only loopback. Internal routes are rejected for public hostnames. No worker ports or Docker TCP endpoint are published.
- Configure-Demo.ps1 generated a private owner key in ignored root .env. Never print/commit it. Open it privately and enter the value in frontend Connection settings; reload clears the frontend key. Start-Artaud.ps1 -DemoControls preserves it and the data volumes.
- All four workers register/heartbeat, but recovery_available=false and they remain JOINING. Root cause is absent B recovery, not broken Docker connectivity. Nonempty uploads require B's verified admission. The temporary experiment's runtime was replaced with this source-aligned controller.
- Existing user files/volumes were preserved. Only specifically identified browser QA objects were cleaned; do not delete unknown runtime files.
- **User deployed frontend:** https://frontend-nine-iota-19.vercel.app/ serves HTTP 200 and the earlier demo assets (index-BTn9gRMA.js). Requests to its own /api/v1/overview return 404: no backend URL is configured there yet. Do not claim the new connected-workspace build is deployed until its actual assets/requests are checked.
- The PC controller was rebuilt alone (worker containers/volumes left intact). Its authenticated overview returned 200 with Access-Control-Allow-Origin exactly https://frontend-nine-iota-19.vercel.app. Configure-Demo.ps1 stored this exact origin in the ignored root .env. Local smoke passed with two uniquely named empty QA objects, both removed; existing objects were preserved.
- **ngrok installed:** official Microsoft Store agent 3.39.11-msix-stable via WinGet, installation completed. No account config/authtoken is present in standard local paths or environment, and no public tunnel is running. The user must configure their private agent token locally; never request it in chat or retrieve/print it from the dashboard. Assigned domain was previously observed as tactile-chant-freely.ngrok-free.dev; verify the actual live endpoint before using it.
- **Vercel plugin is installed/enabled**, confirmed through Plugin Management. No Vercel account-management MCP tools are exposed in this chat. Official CLI 65.16.0 is available through npx, but whoami reported logged out. A device login was opened and its first code expired before approval; regenerate on continuation when the user is ready. Do not confuse plugin installation/browser login with CLI authorization. No Vercel setting/redeployment or DNS change has been made by this expansion.

## Verification

Connected-workspace final verification: **28 frontend unit cases and 29 Chromium cases passed**; TypeScript/local production and Vercel dist builds passed. Author inspected desktop/320px fixture captures and corrected the initially cramped mobile search. Independent source review identified literal metadata escaping and hidden post-header request failures; failing regressions reproduced both, fixes passed and reviewer confirmed resolution with no new material issue.

Actual local controller smoke: frontend/e2e/live-file-tools.mjs tested owner-key connection probe, quoted literal metadata search, CSV export and confirmed two-file deletion against real APIs. It creates/removes two uniquely named empty QA objects only; this does not prove nonempty upload/admission or recovery. No new Python behavior changed in this expansion; the full backend result below is the prior verified checkpoint.

Final backend suite: **218 passed**, one existing Starlette/httpx deprecation warning, in a disposable Linux Docker container with the source mounted read-only and no network. Two new security cases cover wrong-project Docker protection and remote CORS preflight. An earlier full run hit one intermittent pre-existing concurrent-upload assertion (217 passed, 1 failed); isolated concurrent upload, the whole 26-case object API group, and two subsequent full 218-case runs passed. Response diagnostics were added; the intermittent failure's root cause has not been identified, so no fix to it is claimed.

Prior demo verification: 19 unit cases and 25 Chromium cases passed. See docs/reviews/2026-11-14-demo-review.md for that earlier scope and limits.

Actual local checks: Docker control API reported four running containers; worker4 stop returned running=false and immediate start restored running=true. Real Chromium entered the private key via Connection settings and verified Stop/Start confirmations and displayed state. All four were left running. Startup script initially exposed a localhost/IPv6 health-check mismatch after loopback binding; explicit 127.0.0.1 and a PowerShell single-line-array fix now make startup finish successfully.

## Remaining work and safe continuation

1. Connected-workspace source/research/review publication is complete on feature/controller (b50a86d), with matching remote hash. Worker source/recovery/status and frozen helper contracts remain unchanged. Actual Vercel deployment of this build awaits account access; do not confuse Git push with verified production publishing.
2. B implements controller/recovery.py start_reconciler/stop_reconciler and status.py router, plus CLI/reliability integration. Shared API/helper/lock contracts are in contracts/*.md. No heartbeat promotion shortcut.
3. User configures the private ngrok agent token locally (agent installation is done) and approves a fresh Vercel CLI device login. Start ngrok forwarding http://127.0.0.1:8000, verify public liveness/internal-route denial/auth/exact CORS, then set VITE_API_BASE_URL and redeploy only the existing frontend project after verifying team/project/environment. Never put the owner key in Vercel variables. Exact frontend CORS is already applied on the PC. Verify the actual deployed browser flows before claiming the connection complete.
4. Run the final joint stop/fallback/repair/rejoin/corruption demonstration using B's actual reconciler. Existing tests/live_controller_check.py remains explicitly controlled A-only evidence with test-only eligibility; it does not prove B's production recovery.
5. Run source changes through npm run build to update committed controller/static. Keep test captures, node_modules, dist, .vercel and credentials out of Git.
