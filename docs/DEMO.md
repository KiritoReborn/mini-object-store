# Demo and Vercel connection

[Local setup](../README.md#setup-and-start) · [Troubleshooting](TROUBLESHOOTING.md) · [Architecture](ARCHITECTURE.md)

## Run the backend

Follow the README for your platform and keep your existing Compose project name. Normal storage uses `compose.yaml`. Full demo controls require both files on **all five services**:

```sh
docker compose -f compose.yaml -f compose.controls.yaml up --build -d
```

The overlay requires a private `ARTAUD_API_KEY` in root `.env`. It mounts the Docker socket, enables fixed-worker lifecycle controls and opts the workers into deliberate byte corruption. Windows helpers generate/preserve the key; macOS/Linux setup is in the README. The active Compose project automatically supplies the container allowlist. A custom `-p` name must be reused on future commands to retain the correct volumes.

If only controller configuration changed, this reapplies it without recreating workers:

```sh
docker compose -f compose.yaml -f compose.controls.yaml up -d --no-deps controller
```

Use the full command to enable fault injection on workers started without the overlay. Start/Stop/Restart targets only the four existing containers with matching project/service/name. Connect worker registers an existing supported worker; it does not create a container. Forget removes eligible unused offline metadata, not disk contents.

## Connect the live frontend

The existing website is **https://frontend-nine-iota-19.vercel.app/**. The PC, Docker and HTTPS agent must remain running. Requests go directly from the browser through ngrok to the controller; Vercel does not proxy file bodies or run Docker.

With the official ngrok agent/account configured locally:

```sh
ngrok http http://127.0.0.1:8000 --inspect=false
```

If the agent is already running, reuse its Forwarding URL or inspect http://127.0.0.1:4040/ locally. Keep account tokens private. Use the assigned HTTPS origin with no `/api`, `/health` or credentials. Preserve the public Host header; rewriting it to localhost would defeat the controller's public/internal route distinction.

Open the website's **Connection settings**, set **Backend HTTPS address**, enter the key from local `.env`, and choose **Test connection → Connect backend**. The key clears on reload; an old tab can retain an outdated backend-address override. For local use, open http://127.0.0.1:8000/ and leave the backend address empty.

Only the exact website origin should be in `ARTAUD_ALLOWED_ORIGINS`:

```dotenv
ARTAUD_ALLOWED_ORIGINS=https://frontend-nine-iota-19.vercel.app
```

Changing it requires recreating the controller. The Windows equivalent is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Configure-Demo.ps1 -FrontendOrigin "https://frontend-nine-iota-19.vercel.app"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Artaud.ps1 -DemoControls
```

A preview domain is a different origin. Keep the exact-origin check rather than allowing every website. Public `/internal/*` requests are rejected; worker registration remains on the trusted Docker network. The frontend sends the ngrok browser-warning bypass header for its API calls.

## Vercel project settings

The repository is public, and production tracks `master`.

| Setting                   | Value                                              |
| ------------------------- | -------------------------------------------------- |
| Root directory            | `frontend`                                         |
| Framework                 | Vite                                               |
| Build command             | `npm run build`                                    |
| Output directory          | `dist`                                             |
| Production build variable | `VITE_API_BASE_URL=https://YOUR-ACTIVE-NGROK-HOST` |

Set only the backend origin as the build variable, then redeploy. The owner key belongs in the browser at runtime, never in a `VITE_` variable. Those values are public. The root `.vercelignore` limits CLI uploads to frontend source; env files, local data, backups, captures and account credentials stay outside deployments. Local builds still generate `controller/static`.

On public repositories Vercel supports free Git collaboration. A previously blocked private-repository deployment may need a fresh deployment after visibility changes; preserve the teammate's authorship. A successful frontend deployment does not apply controller/worker commits to the PC: pull and rebuild its Docker services separately. [Vercel collaboration](https://vercel.com/docs/deployments/troubleshoot-project-collaboration), [Vite deployment](https://vercel.com/docs/frameworks/frontend/vite)

### Tunnel limits

If ngrok returns `ERR_NGROK_725`, the account's monthly bandwidth is exhausted. The frontend may load while all remote API requests fail. Use localhost while resolving the account allowance; restarting the agent or redeploying the frontend does not reset it. Check [ngrok usage](https://dashboard.ngrok.com/usage) and [the error reference](https://ngrok.com/docs/errors/err_ngrok_725). Transfer speed also depends on PC upload bandwidth and routing; no internet throughput is guaranteed.

## Presentation sequence

Use a disposable demonstration file and leave recovery on its normal schedule.

| Step             | Show and explain                                                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Admission     | Four available workers. Container running state and verified storage admission are distinct.                                              |
| 2. Upload        | A 5–10 MB file with metadata such as `{"course":"CC","demo":"v1"}`. Only 201 means Stored.                                                |
| 3. Placement     | Ordered 1,000,000-byte chunks, final-chunk size and two distinct healthy locations. Export the manifest if full IDs/hashes are needed.    |
| 4. Read          | Download and compare SHA-256 with the original. The browser integrity checker can do this without uploading the selected bytes.           |
| 5. Metadata      | PATCH a custom key; confirm content hash, size and object ID stay unchanged.                                                              |
| 6. Failure       | Pick a worker that actually holds a selected chunk, stop it, demonstrate read fallback and wait for death detection/repair.               |
| 7. Rejoin        | Start that same worker with its volume; show inventory-based readmission and surplus-copy cleanup. An empty returned worker can be valid. |
| 8. Corruption    | In the chunk inspector, confirm **Corrupt this copy** for one demo replica; read using another valid copy and observe repair.             |
| 9. Failure limit | If demonstrating permanent loss, corrupt both worker copies of the same chunk before repair. No valid source remains; expect JSON `503`.  |
| 10. Cleanup      | Delete only the demo file. Its 204 hides the object and attempts physical deletion; offline remnants are reconciled later.                |

Terminal lifecycle commands exercise the same container behavior:

```sh
docker stop worker2
docker start worker2
```

Default heartbeat/death/reconcile intervals are 5/15/5 seconds, with additional transfer/inventory time. Show actual observations, not an instantaneous recovery promise. For logs:

```sh
docker compose -f compose.yaml logs --tail 100 controller worker2
```

A corruption action affects one `(chunk_id, worker_id)` replica. Two workers listed in the same chunk row hold the same chunk. If one damaged copy is deleted during reconciliation, its record can change from CORRUPT to MISSING. A missing record tracks the absent expected data; it does not imply a new corruption click.

For exact physical two-copy/hash checks, use the isolated real-container acceptance harness in [development and testing](DEVELOPMENT.md#real-five-container-acceptance). The UI walkthrough checkboxes are operator notes, not automated proof. Detailed transfer motion appears only for observed events from real operations.

## End the demo

Press Ctrl+C in a foreground ngrok terminal to close public access. Stop the same local Compose project:

```sh
docker compose -f compose.yaml stop
```

Volumes persist. Keep the same project name and reuse the appropriate startup command next time. Back up controller metadata and all four worker volumes together before storage migrations. `down -v` removes them.
