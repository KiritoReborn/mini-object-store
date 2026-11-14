# Live demo and deployment

[Project overview](../README.md) · [Live dashboard](https://frontend-nine-iota-19.vercel.app/) · [Troubleshooting](TROUBLESHOOTING.md)

Artaud works entirely locally. The optional public demo adds a static Vercel frontend and an ngrok HTTPS connection to the same PC controller. Docker, SQLite and all object bytes stay on the PC.

```text
Browser ── frontend assets ──> Vercel
Browser ── API requests ──> ngrok HTTPS ──> PC controller ──> four Docker workers
```

Vercel does not run the Docker stack or proxy file uploads. The PC must remain awake with Docker and the tunnel running. This is a live demonstration, not always-on hosting. Check current account quotas before a long demo; polling and downloads consume tunnel traffic. [ngrok documentation](https://ngrok.com/docs/gateway/agent/cli)

## Use the existing live website

1. Open **https://frontend-nine-iota-19.vercel.app/**.
2. Choose **Connection settings** and check the backend HTTPS address.
3. Enter the private owner key from the PC's ignored `.env` (`ARTAUD_API_KEY`, value only).
4. Choose **Test connection**, then **Connect backend**. Check available worker count and recovery availability.

The key stays in page memory and clears on reload. A visitor needs the key from the owner; it is intentionally absent from the public build and Git repository. A frontend page loading successfully does not imply that its PC backend is online.

## 1. Prepare the PC

Start Docker Desktop's Linux engine. In PowerShell, from the repository root:

```powershell
.\scripts\Configure-Demo.ps1 -FrontendOrigin 'https://frontend-nine-iota-19.vercel.app'
.\scripts\Start-Artaud.ps1 -DemoControls
```

`Configure-Demo.ps1` preserves existing settings and creates a high-entropy owner key if needed. It does not print the key. The startup helper builds/starts the existing services and checks the local app. The committed UI needs no Node server.

If a local execution policy blocks the helper, a process-scoped invocation is available:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Artaud.ps1 -DemoControls
```

Local dashboard: **http://127.0.0.1:8000/**. Workers may briefly remain JOINING while recovery verifies them. Check the actual available count before uploading a nonempty file.

### Optional container controls

`-DemoControls` adds `compose.controls.yaml`, mounting the Docker Engine socket into the controller. This is privileged access and requires an owner key. The API limits actions to Start/Stop/Restart of existing worker1..worker4 containers with the exact configured project/service/name. It exposes no arbitrary shell, container deletion or volume deletion.

Without the overlay, run `docker compose up --build -d` for normal storage and recovery. Docker actions and storage eligibility are different: starting a container never manually promotes it to ALIVE.

## 2. Start the HTTPS connection

Install the official ngrok agent and configure the account token locally using its official instructions. Browser sign-in alone does not configure the agent. Keep tokens out of Git, screenshots and chat.

```powershell
ngrok http http://127.0.0.1:8000 --inspect=false
```

Use the assigned **HTTPS** origin as the backend address. If an agent is already serving this controller, use its existing endpoint rather than starting a second one. Request inspection is disabled for this file-storage demo.

Do not rewrite the public Host header to `localhost` or `controller`: public internal-worker routes are rejected based on the public hostname. The frontend includes the ngrok browser-warning bypass header on API calls. Only controller loopback port `8000` is published; worker ports and Docker daemon TCP are not exposed.

## 3. Configure Vercel

Import the existing GitHub repository. Its production branch is **master**. Use:

| Setting                         | Value                                              |
| ------------------------------- | -------------------------------------------------- |
| Root directory                  | `frontend`                                         |
| Framework                       | Vite                                               |
| Install command                 | Default npm installation using the lockfile        |
| Build command                   | `npm run build`                                    |
| Output directory                | `dist`                                             |
| Production environment variable | `VITE_API_BASE_URL=https://YOUR-ACTIVE-NGROK-HOST` |

Use only the HTTPS origin, without an API path. `frontend/vercel.json` records the build/output settings. The root `.vercelignore` limits CLI uploads to frontend source and excludes private env files, installed packages and captures. Never upload local `.env`, `.env.local`, data, backups or Vercel credentials.

**The owner key must never be a `VITE_` variable.** Vite's frontend build values are public. Enter the key at runtime in Connection settings. [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite)

For a different frontend URL, allow that exact origin on the PC and recreate its controller:

```powershell
.\scripts\Configure-Demo.ps1 -FrontendOrigin 'https://YOUR-FRONTEND.vercel.app'
.\scripts\Start-Artaud.ps1 -DemoControls
```

Use exact-origin CORS. Preview URLs do not inherit permission from the production domain. When the tunnel address changes, update the production `VITE_API_BASE_URL` and redeploy; a tab-local Connection settings override is useful for testing. No Vercel API rewrite or separate proxy is required. [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)

## 4. Rehearse the demonstration

| Step            | Show                                                | Explain                                                                                    |
| --------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Connect         | Four available workers and recovery connected       | Container liveness and verified storage admission are separate.                            |
| Upload          | A file larger than 1,000,000 bytes                  | Ordered chunks, two distinct copies, READY only after successful placement.                |
| Inspect         | Metadata, SHA-256 and per-chunk locations           | SQLite is authoritative; equal copy counts do not imply every worker holds the whole file. |
| Read            | Download and compare SHA-256                        | Bytes are verified before the binary response starts.                                      |
| Fail one worker | Stop from Manage workers or `docker stop worker2`   | A surviving verified copy supports fallback; default death/reconcile timing is eventual.   |
| Observe repair  | Under-replication followed by restored copy records | Show actual observations, not an invented progress bar or packet-rate claim.               |
| Rejoin          | Start the same worker with its volume               | Inventory verification and surplus cleanup can leave the returning worker empty.           |
| Finish          | Delete only the demonstration object                | Offline physical cleanup can be eventual.                                                  |

If both holders of a required chunk are stopped before repair, show the expected503 failure. Recovery needs a surviving source; restarting a holder can restore access. See the [failure matrix and cloud comparison](ARCHITECTURE.md#failure-matrix).

The walkthrough checklist exports operator notes; checked boxes are not automated acceptance results. For repeatable isolated fault injection, use the [joint acceptance harness](ACCEPTANCE.md), which operates on its own labelled stack.

## Persistence and safe shutdown

Stop/Start preserves named volumes. Recovery can deliberately delete obsolete third copies after verifying two others. Look for `SURPLUS_DELETED`; this is different from a lost or newly mounted volume. Existing healthy chunks are not automatically rebalanced back onto the returned worker.

Stop the foreground ngrok process when the public demo ends. Shut down the local stack with `docker compose down` to retain stored data. Do not use `down -v` unless you intend to erase its volumes. Keep the Compose project name unchanged when restarting. Back up the metadata volume and all worker volumes together before migrations.
