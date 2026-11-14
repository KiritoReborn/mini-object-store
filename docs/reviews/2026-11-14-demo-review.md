# Worker demo and simple hosting review

Scope: changes after be6d75b for Member A's frontend/controller. User's final deployment requirement is Vercel static frontend and PC controller/four Docker workers, with one HTTPS ngrok address. Worker/recovery source is outside this change.

## Source and interface checks

Worker settings are additive; frozen recovery helper dictionaries/signatures remain unchanged. Placement pause filters only A's new upload selections. Forget checks every replica state and liveness atomically. Connect is restricted to matching local Docker worker origins and bounded identity/health checks; it neither creates a worker nor grants ALIVE.

Docker actions are explicit opt-in, owner-authenticated, serialized and limited to start/stop/restart on worker1..worker4. Inspection verifies Compose project/service/name before using the container ID. No shell, arbitrary container, container/volume removal or Docker TCP listener is exposed. The socket mount still grants privileged Docker access to the controller; use the optional overlay only on the trusted owner demo PC.

Remote APIs require the owner key and exact configured browser origin; keys remain in browser memory and the ignored local .env. File requests go directly to the HTTPS backend, without a Vercel upload proxy or extra application server. Default Compose binds the controller to loopback and omits Docker socket access.

The default activity view groups successful events while preserving failures and a technical view. Current availability, Docker running state, historical observations and self-reported demo checklist marks remain distinct. An author check corrected the prior fixed-four-node availability color/count assumption. No worker/recovery implementation was shipped to make JOINING disappear.

## Verification

- Linux Docker full suite: 218 passed; one existing Starlette/httpx deprecation warning. Source mount read-only, network disabled, temporary test data only.
- Frontend units: 19 passed. TypeScript/Vite local production build and Vercel dist build passed.
- Chromium: 25 passed, including keyboard/accessibility/narrow-screen checks, slow/stale/error observations, worker controls/confirmation, quiet summaries and remote connection/key non-persistence.
- Earlier real local API and browser checks stopped worker4 and restored it to running through the implemented controls, preserving volumes. Startup script also completed after the loopback/PowerShell fixes. Four workers were left running.
- Author inspected the actual desktop Cluster screenshot. Captures/test artifacts, credentials, frontend/dist and node_modules remain ignored.

An earlier full run had one intermittent concurrent-upload assertion. The isolated case, full object API group and two subsequent full suites passed. Added response diagnostics improve evidence if it recurs; its root cause remains unresolved. This review does not claim a fix.

The independent release reviewer completed only a partial pass before becoming unavailable; this is an author completion review, not a completed independent source or visual certification. Earlier review reports describe earlier commits and are not substitutes for this scope.

## Remaining integration

All four workers register and heartbeat but remain JOINING because Member B's production recovery module is absent. No normal-stack upload/recovery success is claimed. B must provide verified admission/rejoin/repair and run the joint failure/corruption demonstrations. Existing controlled A-only live evidence supplies test-only eligibility and does not prove production recovery.

Vercel is not connected/published and the local ngrok agent is not configured. No public URL or DNS change is claimed. DEMO.md contains the minimal remaining account/setup steps; PC/Docker/tunnel uptime and free-plan quotas bound availability.
