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

## Joint integration verified

The normal stack now has B's production recovery and four inventory-verified available workers. All six APIs and the actual browser operate with nonempty files. Registration remains JOINING until verification. Helper-based repair state transitions are observed; detailed transfer phases appear only if B emits those optional telemetry hooks.

B's recovery delivery and shared contract are integrated, including an atomic registration fence and consistent timestamp eligibility. The joint five-container check passed admission, two physical copies, failure/repair/rejoin, forged-sidecar corruption, restart persistence and a 50MB roundtrip. Read ACCEPTANCE.md for commands and HANDOFF.md for current evidence. Optional B status/standalone CLI work is separate; A's loader tolerates absence.

For a new Codex or Claude chat, read AGENTS.md then HANDOFF.md. Do not redo completed work, seed production data, or change B's functional files to disguise pending recovery.

Frontend hosting and actual worker Start/Stop/Restart are documented in [DEMO.md](DEMO.md). The live layout is Vercel frontend, PC controller/workers and one HTTPS connection. Configure-Demo.ps1 creates an ignored owner key; enter it in Connection settings before using the protected APIs. Prefer http://127.0.0.1:8000/ for the local dashboard. Both local and public browser workflows were verified against B's real recovery.
