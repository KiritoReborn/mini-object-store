# Member A controller guide

Start with [HANDOFF.md](HANDOFF.md) for current status and continuation notes. Contract references: [HTTP](../contracts/api-contract.md), [database/recovery](../contracts/db-helpers.md), [schema](../controller/schema.sql).

## Code map

- `main.py`: app factory, lifespan resources, error envelopes, health and worker registration/heartbeat; optional B module hookup.
- `config.py`: shared constants/environment defaults.
- `models.py`: boundary validation, safe filenames/MIME, metadata and domain errors.
- `database.py` / `schema.sql`: short transactions, stable helper contract and persistent object/chunk/worker/replica state.
- `placement.py`: deterministic eligible-worker selection and heartbeat freshness.
- `objects.py`: bounded chunk I/O, upload commit/rollback, verified temp-file downloads, custom metadata/list/delete and shared lifecycle lock.

Run one controller process; multiple Uvicorn workers would duplicate background work and split the in-process locks. SQLite operations run in worker threads for async routes. Downloads use disk rather than whole-object RAM. Expected chunk hashes live in SQLite; worker sidecars are never the integrity authority.

## Run / test

The existing `Dockerfile.controller` now finds `controller.main:app`.

```powershell
docker build -f Dockerfile.controller -t mini-object-store-controller:local .
docker build -f Dockerfile.worker -t mini-object-store-worker:local .
docker run --rm --mount "type=bind,source=$($PWD.Path),target=/review,readonly" -w /review mini-object-store-controller:local python -B -m pytest -q -p no:cacheprovider
```

The image contains controller code; the read-only mount supplies the complete checkout and tests. Temporary test storage stays inside the disposable container. Linux Docker is required for the existing worker directory-sync tests. The controller-only tests can also run on a configured host Python with repository dependencies.

For direct controller development, set DATABASE_PATH and DOWNLOAD_TEMP_DIR to writable local paths, then run `python -m uvicorn controller.main:app --host 127.0.0.1 --port 8000`. The default paths are `/data/metadata.db` and `/data/downloads` for Docker. Native Windows upload commands should use `curl.exe`, not the PowerShell alias.

```powershell
curl.exe -F "file=@sample.bin" -F 'metadata={"course":"CC"}' http://localhost:8000/api/v1/objects
curl.exe http://localhost:8000/api/v1/objects
```

Replace the returned object ID for metadata/download/delete calls; see the contract for exact endpoints. Swagger API docs are available at `/docs`.

## Integration status

B's worker code is present. B's recovery/status/CLI are not present at implementation time. Normal registration therefore leaves workers JOINING and a nonempty upload returns 503 until B supplies inventory reconciliation and ALIVE promotion. This is an intentional safety boundary. Health reports recovery_available=false. Do not patch registration or heartbeat to force ALIVE.

Controlled live tests may verify an empty inventory and explicitly supply eligibility in a disposable test topology to exercise A's object path. That does not prove the unfinished B reconciliation or satisfy the complete C4 recovery gate.

Run the repeatable controlled integration check from the checkout root after the builds above:

```powershell
python tests/live_controller_check.py --controller-image mini-object-store-controller:local --worker-image mini-object-store-worker:local
```

It creates a private Docker network and five disposable containers with their own new volumes, exercises all six public APIs, a 5000001-byte object, worker stop/start, corruption fallback, controller restart and a 50000000-byte streamed object, then removes only those test resources. It publishes no ports and does not touch project volumes. Explicit inventory-based worker eligibility exists only inside the test harness.

## Limits and operational behavior

- Single controller/SQLite metadata DB is a single point of failure; this is a local course project, not a production cloud service.
- Internal APIs trust the local network; authentication, TLS, quotas, controller replication and cloud deployment are outside the agreed scope.
- Metadata is durable in controller_data; workers have independent data volumes. Never delete project volumes when checking persistence.
- Upload rollback and deletion clean reachable copies. Unreachable or late-finishing ambiguous writes require eventual inventory cleanup by B, including live-worker inventory scans.
- Interrupted UPLOADING rows become FAILED on restart; cleanup is scheduled after startup. Existing workers become JOINING and must be reconciled again. Abandoned download temp files are removed only from the controller-owned temp directory.
- Worker network failures are bounded by finite request timeouts; timeouts are not mislabeled as corruption. Under-replication and repair are B's responsibility.
- No dependency was added for A's implementation. Existing dependency warnings are recorded in the handoff.
