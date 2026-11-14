# Member A: ready to run and hand off

Your controller, object lifecycle/APIs, database helpers, tests and integrated web interface are implemented. The dashboard includes normal file operations and the live topology, chunk placement, transfer timeline, storage distribution, recovery observations and diagnostic/manifest exports. See HANDOFF.md for current evidence and publication status; LIVE_SYSTEM.md explains the visual system and event integration.

## Start everything already provided

Start Docker Desktop's Linux engine, then from the repository folder run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Artaud.ps1
```

The execution-policy flag applies only to that process. This script builds/starts the existing controller and four workers, keeps existing data volumes, checks the dashboard/health/overview/activity endpoints and prints actual availability. The committed frontend build runs without Node. Open http://localhost:8000/ and choose Cluster for the live view.

If you have edited frontend source, first rebuild it with your existing Node/npm installation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Artaud.ps1 -RebuildFrontend
```

This installs the locked frontend dependencies and regenerates the production build before starting Docker. No credentials, cloud account, new hosting service, or configuration overwrite is required for the existing local stack. Stop normally with `docker compose down` to retain stored data.

## Shared completion still requires Member B

The normal stack currently registers four workers, but its missing production recovery service leaves them JOINING. Nonempty file storage requires two inventory-verified available workers. A's code deliberately preserves this correctness rule. Detailed repair phases will appear when B's recovery loop emits them; helper-based state changes are already observed.

B must deliver recovery.py/status.py, CLI/reliability tests and the remaining Compose settings, accept the helper contract and run the joint failure/rejoin/corruption demonstrations. Member A's controlled live harness exercises real bytes/workers with **test-only** eligibility; it is not the production reconciler. The project is not fully release-complete until those shared gates pass.

For a new Codex or Claude chat, read AGENTS.md then HANDOFF.md. Do not redo completed work, seed production data, or change B's functional files to disguise pending recovery.
