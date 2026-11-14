# Simple demo: Vercel frontend, PC backend

The frontend is a static React/Vite build on Vercel. The FastAPI controller and four Docker workers stay on your PC. The browser calls the controller's HTTPS ngrok address directly. Vercel does not run the Docker stack or proxy file bytes. No extra application server, nginx gateway, VM or cloud database is involved.

```text
Browser → Vercel (frontend files)
Browser → ngrok HTTPS address → PC controller → four Docker workers
```

This is a demonstration setup: the PC, Docker and ngrok must stay online. The assignment's storage topology and persistent volumes remain local. There is no 24/7 hosting guarantee. Recovery and worker code remain owned by Member B; this update does not implement, modify or simulate them.

## 1. Run the PC backend

From the repository folder:

```powershell
.\scripts\Configure-Demo.ps1
.\scripts\Start-Artaud.ps1 -DemoControls
```

Configure-Demo creates a high-entropy owner key in the ignored root .env, preserving existing settings. It never prints the key. Open that local file privately when entering the key in the app. The frontend keeps it in page memory only; reload clears it. Never put it in a VITE_ variable, Vercel build setting, Git commit, screenshot or chat message.

The optional compose.controls.yaml overlay gives the controller access to the PC's Docker Engine socket for the requested demo controls. This is privileged access even though the exposed API only allows start/stop/restart of worker1..worker4 with matching Compose labels. No shell/exec, arbitrary container control, container creation/deletion or volume deletion is exposed. Enable it only on your trusted demo PC, keep the owner key private, and stop the demo when finished. Worker source and existing volume contents are preserved. Without -DemoControls, container controls stay disabled and the original local APIs still work (with owner-key authentication if configured).

The controller host port is loopback-only. No worker ports or Docker daemon TCP port are published.

## 2. Give the PC an HTTPS address

Install the official ngrok agent, sign in/configure its existing account token locally using ngrok's instructions, then run:

```powershell
ngrok http 8000
```

Use the assigned HTTPS address as the API base URL. A browser dashboard login does not configure the local agent token. Do not paste account tokens into this repository or chat. The controller rejects internal worker routes for a public hostname and requires the owner key for /api/v1 APIs. The frontend supplies ngrok's browser-warning bypass header for API calls.

The free plan currently includes an assigned development domain, 1 GB outgoing data and 20,000 HTTP requests per month. It does not include an owned custom ngrok domain. Keep demos brief; polling and downloads consume the allowance. kirrito.com can later point its frontend subdomain to Vercel; it is not required for this setup. [ngrok free-plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits)

## 3. Publish just the frontend to Vercel

Import the existing GitHub repository in Vercel. Select root directory **frontend**, framework **Vite**, build command **npm run build**, output **dist**. frontend/vercel.json records this. Set the public build variable:

```text
VITE_API_BASE_URL=https://YOUR-ASSIGNED-NGROK-DOMAIN
```

Do not create Vercel serverless API rewrites for uploads. The browser sends file requests directly to that backend address. The normal local build still writes controller/static so the app can also be used entirely on the PC. [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite)

Once Vercel gives the frontend URL, allow that exact origin on the PC:

```powershell
.\scripts\Configure-Demo.ps1 -FrontendOrigin 'https://YOUR-FRONTEND.vercel.app'
.\scripts\Start-Artaud.ps1 -DemoControls
```

This uses exact-origin CORS, not a wildcard. In the frontend, open Connection settings, check the HTTPS backend address and enter the owner key from the local .env. If the assigned backend address changes, update VITE_API_BASE_URL and redeploy, or change the address in Connection settings for the current tab. Local HTTP localhost is allowed for development; public backend addresses must use HTTPS. [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)

## 4. Demonstrate without mixing responsibilities

- Files: upload >1 MB, inspect ordered chunks/two locations, edit metadata, download and compare SHA-256.
- Cluster: choose a file/chunk, inspect placement, review operation summaries or switch to individual technical events.
- Manage workers: confirm Stop on one actual container. Its Docker running state updates immediately; controller availability changes according to heartbeat/recovery policy. Its volume remains intact. Start it again to demonstrate B's verified inventory rejoin. The standard docker stop worker2 / docker start worker2 commands exercise the same assignment flow.
- Recovery panel: show only actual replica states and repair events from the teammate's implementation. Starting a container is not proof of completed recovery. No manual ALIVE or fake repair button exists.
- Demo walkthrough: track presentation steps and export self-reported notes. Checkmarks are operator notes, not automated verification.

## Joining diagnosis and current boundary

B delivered controller/recovery.py and its tests. The combined normal stack now has four verified ALIVE workers; nonempty file operations and actual repair/rejoin passed the joint live gate. JOINING remains the correct temporary startup state while inventory is verified. If it persists, inspect recovery/worker logs, heartbeat freshness and inventory errors rather than manually granting ALIVE. The old investigation implementation is not used; current recovery is B's delivered module with reviewed shared-boundary corrections. See HANDOFF.md for live URLs and ACCEPTANCE.md for repeatable evidence.

## Research and selected features

Portainer provides inspectable container state and lifecycle actions; this project adopts only the small demo subset, without general Docker administration. [Portainer containers](https://docs.portainer.io/user/docker/containers)

Grafana Explore emphasizes filtering and correlation when inspecting noisy logs. Here the default feed groups similar successful chunk events by file/direction/minute, omits routine started/healthy bookkeeping, and keeps failures visible. A technical view preserves original events and timestamps. Group counts are events, not inferred network bandwidth or unique bytes. [Grafana logs](https://grafana.com/docs/grafana/latest/visualizations/explore/logs-integration/)

Docker stop sends a termination signal to the existing container; it does not delete the container or its volume. Controls preserve that distinction. Docker socket access is privileged and protected separately from ordinary file actions. [Docker stop](https://docs.docker.com/reference/cli/docker/container/stop/), [Docker socket security](https://docs.docker.com/engine/security/protect-access/)

Useful later additions, after the joint system works: a teammate-backed integrity-check action, measured request latency/history, server-side object pagination, bulk object actions with per-file outcomes, and a repeatable failure/corruption evidence script. Persistent operation history, multi-user permissions and resumable uploads require deliberate backend contracts and tests; they are not claimed in this release. Prioritize the complete assignment demonstration over unrelated S3 compatibility, billing, cloud replication or a generic Docker control panel.
