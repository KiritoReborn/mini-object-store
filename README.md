# Mini Distributed Cloud Object Store

Member A's controller and Member B's worker foundation are implemented. The
controller provides all six object APIs, persistent SQLite metadata, placement,
replicated upload, verified download, and registration/heartbeat endpoints.
See [the controller guide](docs/CONTROLLER.md), [current handoff](docs/HANDOFF.md),
and [shared contracts](contracts/db-helpers.md) before continuing development.

**Web workspace:** the Artaud dashboard is served at `http://localhost:8000/` by
the controller. It includes file search/filter/sort, a multi-file upload queue,
downloads, metadata editing, chunk locations, delete confirmation and live node
summaries. Its built assets ship with the controller; no Node server is needed
in Docker. See [frontend development and verification](docs/FRONTEND.md) and
[the design system](DESIGN.md).

**Live system explorer:** choose Cluster for controller/worker wiring, recent
transfer animation and replay, per-file chunk placement, storage distribution,
recovery observations and JSON diagnostic exports. See [the visual system guide](docs/LIVE_SYSTEM.md).
Windows startup is available through `scripts/Start-Artaud.ps1`; [Member A readiness](docs/MEMBER_A_READY.md)
records the one-command setup and the remaining shared integration boundary.

**Integration pending:** B's recovery/status/CLI are not delivered yet. Registered
workers safely stay JOINING, so nonempty uploads return 503 until inventory
reconciliation promotes them to ALIVE. `/health` reports `recovery_available`.
Neither registration nor heartbeat is a promotion shortcut.

The workers store chunks under `/data/chunks`, using one named Docker volume per
worker. The controller's SQLite hash remains the source of truth for integrity;
the worker sidecar is a local self-check.

## Run locally

The controller entry point is `controller/main.py`, matching the existing
Dockerfile. Start the five-service stack:

```sh
docker compose up --build -d
docker compose ps
```

To run only the worker services:

```sh
docker compose up --build -d worker1 worker2 worker3 worker4
docker compose ps
```

Workers retry registration while the controller is offline,
accept any 2xx registration response, and re-register after a heartbeat 404.
Heartbeats use a five-second interval by default and finite HTTP timeouts.

The worker listener and default advertised port are fixed at 8001. `WORKER_ID`
must be non-empty. The base Compose file publishes only controller port 8000.
Optional worker port mappings belong in the git-ignored `compose.override.yaml`.
The `/health` check measures worker HTTP liveness, not controller availability.

Named volumes survive `docker stop` / `docker start` and `docker compose down`.
Keep the same Compose project name when starting again. `docker compose down -v`
removes the volumes and their data.

## Tests

With Python 3.12 and the packages in `requirements.txt` installed:

```sh
python -m pytest tests/test_worker.py -v
```

Tests isolate storage in temporary directories and replace external HTTP only.
For the complete suite on Windows, use the Linux Docker test command in the
controller guide; worker directory syncing is Linux-specific. A repeatable
controlled four-worker integration check is documented there too.

## Known limitations

- Chunk IDs require a lowercase UUID-shaped value plus a nonnegative decimal
  index. UUID version and variant bits are intentionally not enforced for
  controller compatibility. Slashes, backslashes, and traversal strings remain
  invalid.
- Containers currently run as root to keep existing volume permissions
  compatible. Running as a dedicated user requires migrating volume ownership.
- Each worker volume must have exactly one worker process. Striped thread locks
  coordinate requests within that process, not multiple processes sharing data.
- Chunk and sidecar are committed separately, data first. An interrupted write
  can leave a corrupt pair; GET rejects it and PUT can repair it. Startup removes
  abandoned temporary files. Inventory may report a null checksum for a missing
  or malformed sidecar; it does not verify data against the controller's hash.
- The five direct dependencies are pinned; transitive dependencies are not
  locked, and the shared requirements still include test tooling.
