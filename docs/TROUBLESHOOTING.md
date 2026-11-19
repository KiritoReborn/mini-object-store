# Troubleshooting

[Overview](../README.md) · [Demo setup](DEMO.md) · [Architecture](ARCHITECTURE.md)

Run commands from the repository root. Begin with read-only checks; retain the existing project name and volumes while investigating.

```sh
docker compose ps
docker compose logs --tail 100 controller worker1 worker2 worker3 worker4
```

## Could not load your workspace / owner access key required

The controller has owner authentication enabled. Open the ignored local `.env` privately, copy only the value after `ARTAUD_API_KEY=`, then use **Connection settings → Owner access key → Test connection → Connect backend**.

The browser intentionally keeps the key in memory, so reload requires re-entry. A visitor to the public demo needs the key from its owner; cloning the repository does not supply it. Do not place it in a `VITE_` variable, publish it in screenshots, or send it in a diagnostic export. If the key is correct but requests fail, check the backend address, exact allowed origin and running tunnel.

## Frontend loads but backend is unavailable

Vercel can serve the page even while the PC backend is offline. Check that the PC is awake, Docker is running, the controller responds locally, and the configured ngrok HTTPS endpoint is active. Test in Connection settings before saving.

If the ngrok URL changed, update `VITE_API_BASE_URL` in Vercel and redeploy, or use the connection override for the current tab. Set `ARTAUD_ALLOWED_ORIGINS` to the exact frontend origin and recreate the controller after changing it. A different Vercel preview URL is a different origin; do not solve that with an unrestricted wildcard. See [the deployment steps](DEMO.md).

## Public downloads are slow or stop while localhost is fast

The browser downloads directly from the PC through ngrok; Vercel only serves frontend assets. Compare a generated test file on both routes before attributing the delay to storage. The controller verifies the complete object before starting a binary response. Browsers without the writable-file picker also buffer the complete response before triggering their save, which can make network waiting look like an unresponsive button.

If the public endpoint returns HTTP403 with `ERR_NGROK_725`, the ngrok account has exhausted its monthly bandwidth allowance. This is a tunnel/account limit, not a Vercel build error. Inspect [ngrok usage](https://dashboard.ngrok.com/usage) and [the official error description](https://ngrok.com/docs/errors/err_ngrok_725). Use the local dashboard while waiting for the billing-cycle reset, or select an account/tunnel provisioned for the required transfer. Restarting the agent or redeploying the frontend does not reset that allowance. Do not assume an upgrade guarantees a particular transfer speed; PC upload bandwidth and routing still matter.

Check integrity separately. A chunk with no healthy surviving copy cannot be downloaded even with a fast network and four running workers. Restore a valid original/backup rather than bypassing checksum verification. For privacy, use disposable synthetic bytes for public-route performance tests and remove the known test object afterward.

## Workers remain JOINING

JOINING is expected during inventory verification. Check controller and worker logs for registration, inventory failures, stale heartbeats, corrupt chunks or a restarted registration attempt. Containers being `running` or passing `/health` is separate from being eligible for storage.

The default Docker configuration uses `http://controller:8000` for worker registration and `http://workerN:8001` for worker access. `localhost` inside a worker refers to that worker, not the controller. Confirm the containers share the expected Compose network. Never patch a worker directly to ALIVE to make the UI pass.

## Upload returns `503`

Nonempty chunks need two distinct eligible workers that accept the write. Check ALIVE state, fresh heartbeats, upload-placement pause settings and worker request errors. A worker may be healthy for reads but paused for new upload placement. Failed writes can retry another worker; an upload that cannot meet the policy must fail rather than expose a partial READY object.

## Download returns `503` although the object is listed

The metadata exists, but at least one required chunk has no verified readable copy. If both holders are stopped, restart a holder with its existing volume and allow verified admission. Recovery cannot create bytes without a surviving source. Do not delete volumes to troubleshoot this error. A recorded HEALTHY copy can later become unavailable or fail verification.

## A restarted worker now has zero chunks

Inspect the original volume and recovery decisions:

```sh
docker inspect worker3 --format '{{json .Mounts}}'
docker compose logs --tail 200 controller worker3
```

Look for `SURPLUS_DELETED`: recovery created replacements while the worker was down and removed obsolete third copies after verifying two others. The named volume survives, but its application-managed contents can change. An empty ALIVE worker can accept new uploads; the current system does not rebalance existing healthy copies back onto it.

`ORPHAN_DELETED` instead identifies chunks whose object/chunk records no longer authorize retention. Corrupt-copy cleanup is another separate case. Do not infer the cause from a zero count alone; correlate the logs and current manifest.

## All workers show equal copy counts

Placement selects the least-loaded healthy chunk count and breaks ties by worker ID. With four empty workers and sequential uploads, pairs often alternate worker1/2, then worker3/4. Each chunk still has only two copies. Counts are not free space or exact byte balance. See [the worked placement example](ARCHITECTURE.md#placement-why-counts-often-look-equal).

## Start/Stop/Restart controls are unavailable

Configure a private owner key and start with `scripts/Start-Artaud.ps1 -DemoControls`, or use the documented Compose controls overlay. Docker Desktop must be running, and the existing containers must match the configured project/service/name. Connect worker registers an existing supported worker; it does not create a Docker container. Forget removes eligible metadata only; it does not erase a disk.

If the API reports `CONTAINER_MISMATCH`, compare the worker's `com.docker.compose.project` label with the controller's `ARTAUD_DOCKER_PROJECT`. The controls overlay derives that setting from Compose's active `COMPOSE_PROJECT_NAME`, including an explicit `-p` project name. Keep the existing project/volumes and recreate only the controller after correcting configuration; do not rename the stack or disable container-identity checks. For the default project, run `docker compose -f compose.yaml -f compose.controls.yaml up -d --no-deps controller`.

`Container: not connected` is an unknown UI state when inspection fails, not proof the worker stopped. If the accompanying error says the controller cannot be reached, verify the current backend HTTPS address and running ngrok agent as well. The local dashboard can connect to `http://127.0.0.1:8000`; the public Vercel dashboard needs the active HTTPS tunnel and exact allowed origin.

## UI appears stale after a frontend change

Edit `frontend/src`, run `npm run build` from `frontend`, then rebuild/recreate the controller. Normal builds write `controller/static`; Vercel builds write `frontend/dist`. A Vite development server is a separate development path. When refresh fails, the UI deliberately marks observations stale or unknown instead of retaining a green claim.

## Worker tests fail on native Windows

Worker directory syncing uses Linux filesystem behavior. Run the full backend suite inside the documented Linux test container. See [test commands](DEVELOPMENT.md#automated-checks). Frontend tests can run on the host after `npm ci` and browser installation.

## Data appears absent after restarting Compose

Check whether the Compose project name changed, a different set of named volumes was mounted, or volumes were explicitly deleted. Normal `docker compose down` retains them; `down -v` removes them. A tunnel or frontend redeployment does not move the local database or worker disks.

Back up the controller metadata and all four worker volumes together before storage migrations. A database-only backup does not contain the object bytes. Keep backup files and owner credentials out of Git and Vercel uploads.
