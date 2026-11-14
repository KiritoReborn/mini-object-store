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

## Workers remain JOINING

JOINING is expected during inventory verification. Check controller and worker logs for registration, inventory failures, stale heartbeats, corrupt chunks or a restarted registration attempt. Containers being `running` or passing `/health` is separate from being eligible for storage.

The default Docker configuration uses `http://controller:8000` for worker registration and `http://workerN:8001` for worker access. `localhost` inside a worker refers to that worker, not the controller. Confirm the containers share the expected Compose network. Never patch a worker directly to ALIVE to make the UI pass.

## Upload returns503

Nonempty chunks need two distinct eligible workers that accept the write. Check ALIVE state, fresh heartbeats, upload-placement pause settings and worker request errors. A worker may be healthy for reads but paused for new upload placement. Failed writes can retry another worker; an upload that cannot meet the policy must fail rather than expose a partial READY object.

## Download returns503 although the object is listed

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

## UI appears stale after a frontend change

Edit `frontend/src`, run `npm run build` from `frontend`, then rebuild/recreate the controller. Normal builds write `controller/static`; Vercel builds write `frontend/dist`. A Vite development server is a separate development path. When refresh fails, the UI deliberately marks observations stale or unknown instead of retaining a green claim.

## Worker tests fail on native Windows

Worker directory syncing uses Linux filesystem behavior. Run the full backend suite inside the documented Linux test container. See [acceptance commands](ACCEPTANCE.md). Frontend tests can run on the host after `npm ci` and browser installation.

## Data appears absent after restarting Compose

Check whether the Compose project name changed, a different set of named volumes was mounted, or volumes were explicitly deleted. Normal `docker compose down` retains them; `down -v` removes them. A tunnel or frontend redeployment does not move the local database or worker disks.

Back up the controller metadata and all four worker volumes together before storage migrations. A database-only backup does not contain the object bytes. Keep backup files and owner credentials out of Git and Vercel uploads.
