# Start Artaud on your Mac

Use the local dashboard for everyday work. Vercel and ngrok give you HTTPS access, including from another device. Both dashboards can use the same Docker controller and stored files.

## 1. Prepare Docker and the owner key

Open Docker Desktop and run the commands below from the repository root, where `compose.yaml` lives. These commands use the current Compose project name, `cloud_project`. Keep the existing project name when restarting, because it determines which named volumes Compose uses. If your stack was started under a different name, use its existing name and make sure `ARTAUD_DOCKER_PROJECT` in the controls overlay matches it.

For Vercel or Docker worker controls, configure the ignored `.env` in the repository root. Reuse the key you already have. For a new `.env`, run `openssl rand -hex 32` in Terminal and use its output as the value on the first line below.

```dotenv
ARTAUD_API_KEY=replace_with_your_generated_key
ARTAUD_ALLOWED_ORIGINS=https://frontend-nine-iota-19.vercel.app
```

Merge these settings into an existing `.env`. Keep the actual key private. Only the ngrok URL belongs in Vercel's `VITE_API_BASE_URL` if you configure a default there.

## 2. Start the stack

This command starts the controller and all four workers with the normal dashboard.

```sh
docker compose -p cloud_project -f compose.yaml up --build -d
```

Use the controls overlay if you want the worker **Start**, **Stop**, and **Restart** buttons on first startup.

```sh
docker compose -p cloud_project -f compose.yaml -f compose.controls.yaml up --build -d
```

On an **already running** stack, target the controller to enable the buttons.

```sh
docker compose -p cloud_project -f compose.yaml -f compose.controls.yaml up -d --no-deps controller
```

The overlay enables demo controls and mounts the Docker socket into the controller. The last command recreates only the controller if its configuration changed. The worker containers and named volumes stay in place. Use the same controller-only command to apply changes to the owner key or allowed Vercel origin while keeping demo controls enabled. The explicit `-f` options select the intended Compose files even if you have a local override.

## 3. Open the local dashboard

Open [127.0.0.1:8000](http://127.0.0.1:8000/) or [localhost:8000](http://localhost:8000/). Both addresses reach the same local controller. The browser treats them as separate origins, so use one consistently to keep its connection settings. The controller serves the bundled frontend directly.

1. Open **Connection settings** and leave **Backend HTTPS address** blank.
2. If `ARTAUD_API_KEY` is set in the controller, paste its value from `.env` into **Owner access key**. This applies on localhost too. The browser keeps the key in page memory, so re-enter it after a reload.
3. Click **Test connection**, then **Connect backend**. Give the workers a moment to join and wait for the dashboard to show **four available workers**.

### Read the worker statuses

| Status | Meaning |
| --- | --- |
| **Available** | The controller has admitted the worker for storage. |
| **Container: not connected** | The UI has no Docker status for this worker. With the base Compose setup, demo controls are disabled and the status stays this way even while storage works. |
| **Container: running** | The controller queried Docker through the socket and confirmed the container is running. The controls overlay enables this check. |
| **Accepting new uploads** | The worker can be selected for new upload placement. The row's **Pause** button changes placement only. Existing downloads and recovery can still use the worker. |
| **0 replica records** | The controller currently records no replicas on that worker. An available worker can still accept new uploads. |

The Docker controls cover `worker1` through `worker4`. Use Docker Desktop or Compose to manage the controller itself. **Forget** removes an eligible unused offline worker record from the controller database. A worker must have a stale heartbeat and no replica records to be eligible.

## 4. Open the Vercel dashboard through ngrok

Open a separate Terminal window to run ngrok while Docker Desktop and your controller are running.

```sh
ngrok http http://127.0.0.1:8000 --inspect=false
```

If ngrok asks for an authtoken, follow the setup instructions in your [ngrok dashboard](https://dashboard.ngrok.com/get-started/your-authtoken). If the agent is already running, get the existing forwarding URL from [the local ngrok interface](http://127.0.0.1:4040/) instead of starting a second agent.

1. Copy the HTTPS URL on ngrok's **Forwarding** line. Use the current URL, for example `https://dock-parish-matter.ngrok-free.dev`, with no `/health` or `/api` path. Keep the ngrok process running while you use Vercel.
2. Open [the Vercel dashboard](https://frontend-nine-iota-19.vercel.app/) and go to **Connection settings**.
3. Paste the ngrok URL into **Backend HTTPS address** and the value of `ARTAUD_API_KEY` from `.env` into **Owner access key**.
4. Click **Test connection**, then **Connect backend**.

Vercel and localhost get the same worker controls when they talk to the same controller. Each serves its own frontend build. On `feature/extras`, open **Files → select a file → Details → Verify integrity** and choose one local file to check against the stored SHA-256. Vercel production gets the tool when a build that includes it is deployed.

## Quick checks

```sh
docker compose -p cloud_project -f compose.yaml ps
curl -fsS http://127.0.0.1:8000/health
```

- **The local dashboard opens but asks for a key.** Enter the value from `.env` in **Connection settings**. Keep the local backend address blank.
- **Vercel loads but cannot connect.** Check that ngrok is running and paste the current HTTPS forwarding URL. If the connection test mentions origin, check `ARTAUD_ALLOWED_ORIGINS` against the exact Vercel site origin and recreate the controller with the appropriate Compose files.
- **Workers are available but the Docker buttons are missing.** Enable the controls overlay in step 2. If the UI reports a container project mismatch, compare the existing Compose project to the value in `compose.controls.yaml`.
- **Workers are still joining.** Check controller status in the dashboard. A healthy `/health` response confirms the controller is up. The worker list confirms which workers have finished admission.

## Stop for the day

Press **Ctrl+C** in the ngrok terminal to close the public tunnel. Stop the local services in the same Compose project to keep their data.

```sh
docker compose -p cloud_project -f compose.yaml stop
```

Next time, use the same project name and whichever set of startup files you want from step 2. Keep the named volumes to retain your files.

See the [full demo guide](docs/DEMO.md) for Windows PowerShell, deployment settings, and the demo walkthrough.
