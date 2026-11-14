# Controller development

Start with [architecture](ARCHITECTURE.md) for lifecycle/placement/failure behavior and [HANDOFF.md](HANDOFF.md) for continuation notes. Contract references: [HTTP](../contracts/api-contract.md), [database/recovery](../contracts/db-helpers.md), [schema](../controller/schema.sql). Operational problems are covered in [troubleshooting](TROUBLESHOOTING.md).

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
curl.exe --fail-with-body -F "file=@sample.bin" http://127.0.0.1:8000/api/v1/objects
curl.exe --fail-with-body http://127.0.0.1:8000/api/v1/objects
```

Use an existing sample.bin. Replace the returned object ID for metadata/download/delete calls; see the contract for exact endpoints. Swagger API docs are available at `/docs`. The README's metadata curl example uses POSIX quoting; for native PowerShell JSON requests, use Invoke-RestMethod with ContentType application/json and a ConvertTo-Json body, or send a JSON file with curl.exe --data-binary.
When ARTAUD_API_KEY is configured, protected API requests also require X-Artaud-Key from the private local .env. The default clean-checkout local profile does not require that optional demo key; the public demo does.

## Integration status

B's worker and recovery code are integrated. Normal registration writes JOINING; B verifies inventory and DB-authoritative bytes before atomic admission. The installed module reports recovery_available=true, and actual worker availability remains a separate overview result. Existing startup/shutdown hooks required no production change. Optional status.py/standalone B CLI remain separate; no missing status router is included.

The historical live_controller_check.py exercised A's path with test-only eligibility before B existed. It intentionally expects absent recovery and is not the current joint gate. Use the production-recovery acceptance check below; it never sets ALIVE itself.

Run the joint integration check from the checkout root after the builds above:

```powershell
python tests/test_end_to_end.py --controller-image mini-object-store-controller:local --worker-image mini-object-store-worker:local --large
```

It creates a private Docker network and five disposable containers with new labelled volumes, publishing only a random loopback controller port. It exercises all six APIs, a 5000001-byte object/two physical copies, actual B admission/stop/repair/rejoin/corruption, restart and optional 50000000-byte streaming, then removes only its own resources. Add --browser for the actual UI workflow. See ACCEPTANCE.md for scope and evidence.

## Configuration

The base Compose profile forwards these environment values from the shell or ignored root `.env`. Recreate services after changing them; editing a file does not change a running container.

| Setting                  | Default                  | Meaning                                                                                               |
| ------------------------ | ------------------------ | ----------------------------------------------------------------------------------------------------- |
| `CHUNK_SIZE`             | `1000000` bytes          | Shared controller/worker chunk boundary; retain the default for assignment cases.                     |
| `HEARTBEAT_INTERVAL`     | `5` seconds              | Worker heartbeat interval.                                                                            |
| `WORKER_DEAD_TIMEOUT`    | `15` seconds             | Controller's heartbeat age threshold.                                                                 |
| `RECONCILE_INTERVAL`     | `5` seconds              | Recovery pass interval.                                                                               |
| `HTTP_TIMEOUT`           | `5` seconds              | A's worker-request timeout; B's recovery uses separate operation limits.                              |
| `CONTROLLER_URL`         | `http://controller:8000` | Worker registration/heartbeat destination within Docker.                                              |
| `ARTAUD_API_KEY`         | Empty                    | Optional owner authentication for all `/api/v1/*` calls; required for demo controls/public operation. |
| `ARTAUD_ALLOWED_ORIGINS` | Empty                    | Comma-separated exact remote frontend origins.                                                        |

Replication is fixed at two. Controller port `8000`, worker port `8001` and named volume mounts are defined by Compose/Dockerfiles. Application settings such as `DATABASE_PATH`, `DOWNLOAD_TEMP_DIR` and `WORKER_STORAGE_PATH` can be set for direct process development; a variable in `.env.example` is not automatically forwarded unless Compose explicitly references it. Do not assume `CONTROLLER_PORT` or `REPLICATION_FACTOR` changes reconfigure this stack.

## Limits and operational behavior

- Single controller/SQLite metadata DB is a single point of failure; this is a local course project, not a production cloud service.
- Internal worker APIs trust the Docker network and are rejected through the public tunnel. Optional owner-key API protection and exact CORS support the Vercel/PC HTTPS demo; controller replication, multi-user permissions and durable audit history are outside this release.
- Metadata is durable in controller_data; workers have independent data volumes. Never delete project volumes when checking persistence.
- Upload rollback and deletion clean reachable copies. Unreachable or late-finishing ambiguous writes require eventual inventory cleanup by B, including live-worker inventory scans.
- Interrupted UPLOADING rows become FAILED on restart; cleanup is scheduled after startup. Existing workers become JOINING and must be reconciled again. Abandoned download temp files are removed only from the controller-owned temp directory.
- Worker network failures are bounded by finite request timeouts; timeouts are not mislabeled as corruption. Under-replication and repair are B's responsibility.
- Existing dependency warnings and the dated verification scope are recorded in the handoff and acceptance guide.
