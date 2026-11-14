# Project continuation

Read `docs/HANDOFF.md` before continuing an existing task. It records the current implementation, verification, decisions and remaining work. `docs/CONTROLLER.md` is the controller guide; `contracts/api-contract.md` and `contracts/db-helpers.md` define the integration boundary.

For frontend work also read PRODUCT.md, DESIGN.md and docs/FRONTEND.md. Edit frontend/src, then regenerate controller/static with npm run build. Keep QA fixtures out of the runtime bundle. The web UI uses the real same-origin APIs and must preserve stale/unknown availability instead of manufacturing health.

## Ownership

Member A owns controller main/config/models/database/schema/placement/objects and their tests. Member B owns worker code, controller/recovery.py, controller/status.py, Dockerfiles/Compose, CLI and reliability tests. Contracts, README and end-to-end checks are shared. Coordinate changes across that boundary explicitly.

## Correctness boundaries

- Use one controller process. SQLite transactions remain short; perform no network calls inside them.
- Preserve helper signatures and dict fields documented in contracts. B's recovery code imports these directly.
- Only READY objects are public. Chunks of UPLOADING objects remain protected from orphan cleanup.
- Registration/heartbeat never promote workers to ALIVE. B verifies inventory and bytes before promotion.
- The controller DB is authoritative for hash and size. Verify every download chunk and whole object before binary success starts.
- Recovery/destructive cleanup must share `controller.objects.object_lock(object_id)` and reread current state before mutation.
- Run the full test suite in Linux Docker because worker directory syncing is Linux-specific. Use focused failing tests before behavioral fixes.
- Record verified results and unfinished integration in the handoff. A controlled test harness supplying eligibility does not prove B's production reconciler.
