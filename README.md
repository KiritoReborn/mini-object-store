# Mini Distributed Cloud Object Store — workers

The workers store chunks under `/data/chunks`, using one named Docker volume per
worker. The controller's SQLite hash remains the source of truth for integrity;
the worker sidecar is a local self-check.

## Run locally

The controller application must provide `controller/main.py` with a FastAPI
`app`. That application is not present in this checkout yet. Until it is added,
start only the workers:

```sh
docker compose up --build -d worker1 worker2 worker3 worker4
docker compose ps
```

Once the controller application is available, use `docker compose up --build -d`
for the full stack. Workers retry registration while the controller is offline,
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

Tests isolate storage in temporary directories and mock controller requests.

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
