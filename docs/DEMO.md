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

Start Docker Desktop's Linux engine. The controls overlay expects the Compose project name `cloud_project`. In PowerShell, from the repository root, set the project name for the startup helper:

```powershell
$env:COMPOSE_PROJECT_NAME = 'cloud_project'
.\scripts\Configure-Demo.ps1 -FrontendOrigin 'https://frontend-nine-iota-19.vercel.app'
.\scripts\Start-Artaud.ps1 -DemoControls
```

`Configure-Demo.ps1` preserves existing settings and creates a high-entropy owner key if needed. It does not print the key. The startup helper builds/starts the existing services and checks the local app. The committed UI needs no Node server.

If a local execution policy blocks the helper, run this in the same PowerShell session:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Artaud.ps1 -DemoControls
```

Local dashboard: **http://127.0.0.1:8000/**. Workers may briefly remain JOINING while recovery verifies them. Check the actual available count before uploading a nonempty file.

### Optional container controls

`-DemoControls` adds `compose.controls.yaml`, mounting the Docker Engine socket into the controller. This is privileged access and requires an owner key. The API limits actions to Start/Stop/Restart of existing worker1..worker4 containers with the exact configured project/service/name. It exposes no arbitrary shell, container deletion or volume deletion.

The equivalent full-overlay startup command is `docker compose -p cloud_project -f compose.yaml -f compose.controls.yaml up --build -d`. For base storage and recovery, use `docker compose -p cloud_project -f compose.yaml up --build -d`. Docker actions and storage eligibility are different: starting a container never manually promotes it to ALIVE.

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

For a different frontend URL, allow that exact origin on the PC and run the helper in the same PowerShell session:

```powershell
.\scripts\Configure-Demo.ps1 -FrontendOrigin 'https://YOUR-FRONTEND.vercel.app'
.\scripts\Start-Artaud.ps1 -DemoControls
```

Use exact-origin CORS. Preview URLs do not inherit permission from the production domain. When the tunnel address changes, update the production `VITE_API_BASE_URL` and redeploy; a tab-local Connection settings override is useful for testing. No Vercel API rewrite or separate proxy is required. [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)

## 4. Rehearse the demonstration

Use a file you uploaded for this demonstration. Run Docker commands from the Compose project root and use the same project name on every Compose invocation. Existing stacks need their original project name to select their volumes.

| Step | Show |
| ---- | ---- |
| 1. Connect | In **Cluster**, show four available workers and recovery connected. `docker compose -p cloud_project -f compose.yaml ps` shows the controller and four worker containers. Each worker has its own named volume. |
| 2. Upload and read | In **Files**, queue a 5–10 MB binary file such as `demo.bin`. In **Custom metadata**, enter `{"course":"CC","demo":"v1"}`, then choose **Upload 1 file**. Download it as `downloaded-demo.bin` and compare SHA-256. |
| 3. Show placement | In **Cluster → Where each chunk lives**, choose the file. Show the ordered 1,000,000-byte chunks, final chunk size, and two distinct healthy worker locations per chunk. Use **Export manifest** for full chunk IDs and the physical check below to compare on-disk sizes and hashes with the manifest. |
| 4. Update metadata | Open **Inspect file → Metadata** and change `demo` to `"v2"`. Choose **Save changes**, then close and reopen the inspector to read it again. Compare the before/after API results below. |
| 5. Stop and repair | Before stopping, find a chunk held by `worker2` in the placement view. Run `docker stop worker2` and download the file again. Compare SHA-256, show its surviving copy, and watch for DEAD and restored replication on the three surviving workers. |
| 6. Restart and verify | Run `docker start worker2`. Show verified readmission and two healthy copies per chunk. Check the physical copies and recovery logs again. Recovery removes surplus copies after verifying two elsewhere. |
| 7. Corrupt and recover | Change one stored byte on a demo replica as described below. Download the file, compare SHA-256, and show detection and restoration in placement, activity, logs and the physical check. |
| 8. Delete | With all four workers online, confirm **Delete file** for the demonstration object. Show `DELETE /api/v1/objects/{object_id}` returning 204 and the file disappearing from **Files**. Check its chunk IDs on disk. If any files or sidecars remain, allow inventory reconciliation to retry cleanup and check again before reporting physical removal. |

On macOS, compare the original with each download from steps 2, 5 and 7. Substitute the actual saved paths, including any suffix the browser added for a repeated download. For example:

```sh
shasum -a 256 "$HOME/Documents/demo.bin" "$HOME/Downloads/downloaded-demo.bin"
```

### Check the metadata edit

| Request | Compare |
| ------- | ------- |
| `GET /api/v1/objects/{object_id}/metadata` | Read the saved `course: "CC"` and `demo: "v1"`. Note `object_id`, `size`, `num_chunks` and `sha256`. |
| `PATCH /api/v1/objects/{object_id}/metadata` | **Save changes** sends `{"metadata":{"demo":"v2"}}` without resending the file. |
| `GET /api/v1/objects/{object_id}/metadata` | Confirm `demo` is `"v2"` and the object ID, size, chunk count and checksum are identical. |

### Verify replica locations before, during and after the stop

The metadata endpoint and **Export manifest** report the recorded states. Choose a full `chunk_id` from the manifest and use its recorded SHA-256 as the expected hash. The paths below come from worker storage, whose default directory is `/data/chunks`. Repeat for the other chunks as needed. Omit `worker2` from the loop while it is stopped.

```sh
chunk_id='FULL_CHUNK_ID_FROM_MANIFEST'
for worker in worker1 worker2 worker3 worker4; do
  docker compose -p cloud_project -f compose.yaml exec -T "$worker" python3 - "$worker" "$chunk_id" <<'PY'
import hashlib
import os
import sys
from worker.storage import chunk_path, sha_path

worker, chunk_id = sys.argv[1:]
sidecar = f"sidecar={sha_path(chunk_id).is_file()}"
try:
    with chunk_path(chunk_id).open("rb") as source:
        size = os.fstat(source.fileno()).st_size
        digest = hashlib.file_digest(source, "sha256").hexdigest()
except FileNotFoundError:
    print(worker, chunk_id, "missing", sidecar)
else:
    print(worker, chunk_id, size, digest, sidecar)
PY
done
```

Before the stop, show two matching disk hashes. During the outage, show fallback from the surviving copy and two matching hashes on surviving workers after repair. After worker2 rejoins, check all four again and show two matching hashes per chunk. Use **Recent activity** and the controller logs to show state transitions or repair that finished between placement refreshes:

```sh
docker compose -p cloud_project -f compose.yaml logs controller | grep -E 'WORKER_(DEAD|JOINING|ALIVE)|REPLICA_REPAIRED|SURPLUS_DELETED'
```

### Corrupt a single replica and check recovery

Choose a demo chunk with two healthy available copies. Get its full `chunk_id` from **Export manifest**. In **Where each chunk lives**, choose **Corrupt this copy** in one holder's cell and confirm its chunk ID and worker. The controller marks the changed copy corrupt as soon as the worker confirms, and recovery can start before the next download. To use the button, apply the controls overlay to the controller and all four workers and enter the owner key in **Backend connection**. Applying the overlay only to the controller of a base stack enables only Docker Start/Stop/Restart.

To demonstrate loss of both replicas, confirm **Corrupt this copy** on each worker in the same chunk row. Recovery runs on its usual schedule. If both flips occur before repair, the file returns JSON `503 OBJECT_UNAVAILABLE` until a verified copy is restored. If repair finishes between the two actions, the file can still download from the repaired copy.

For a terminal demonstration, set `worker` to the lowest worker ID of the two holders and reuse the full `chunk_id` above. The controller tries healthy copies in worker ID order. This flips byte zero of `/data/chunks/<chunk_id>`, preserves the file size and leaves its `.sha256` sidecar untouched.

```sh
worker='LOWEST_ID_ACTUAL_HOLDER_FROM_MANIFEST'
docker compose -p cloud_project -f compose.yaml exec -T "$worker" python3 - "$chunk_id" <<'PY'
import os
import stat
import sys
from worker.storage import chunk_path

path = chunk_path(sys.argv[1])
fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
with os.fdopen(fd, "r+b") as chunk:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SystemExit("Choose a regular demo chunk file with one link")
    first = chunk.read(1)
    if not first:
        raise SystemExit("Choose a nonempty demo chunk")
    chunk.seek(0)
    chunk.write(bytes([first[0] ^ 0x01]))
    chunk.flush()
    os.fsync(fd)
print("Flipped byte 0 of", path)
PY
```

Download and compare the original and downloaded SHA-256. In **Recent activity**, choose **Replicas & recovery** and look for **Replica corrupt** and **Replica restored**. Recheck placement and use the physical command to confirm the restored bytes match the manifest checksum and size. For a terminal flip, the controller can log `REPLICA_CORRUPT` when a download detects the fault or `CHUNK_CORRUPTED` when recovery detects it. Both demo paths can produce `REPLICA_REPAIRED`:

```sh
docker compose -p cloud_project -f compose.yaml logs controller | grep -E 'CHUNK_CORRUPTED|REPLICA_CORRUPT|REPLICA_REPAIRED'
```

| Assignment §10 item | Demo evidence |
| ------------------- | ------------- |
| Object storage | Step 2 upload, download and SHA-256 comparison |
| Chunking and distribution | Step 3 ordered chunk sizes and worker locations |
| Replication | Step 3 two physical copies per chunk, checked again in steps 5 and 6 |
| Metadata | Steps 2 and 4 custom metadata on upload, then GET, PATCH and GET |
| Worker failure | Steps 5 and 6 stop, fallback download, repair and verified rejoin |
| Data integrity | Step 7 byte flip, matching download and repaired disk hash |

If both holders of a required chunk are stopped before repair, show the expected503 failure. Recovery needs a surviving source; restarting a holder can restore access. See the [failure matrix and cloud comparison](ARCHITECTURE.md#failure-matrix).

The walkthrough checklist exports operator notes; checked boxes are not automated acceptance results. For repeatable isolated fault injection, use the [joint acceptance harness](ACCEPTANCE.md), which operates on its own labelled stack.

## Persistence and safe shutdown

Stop/Start preserves named volumes. Recovery can deliberately delete obsolete third copies after verifying two others. Look for `SURPLUS_DELETED`; this is different from a lost or newly mounted volume. Existing healthy chunks are not automatically rebalanced back onto the returned worker.

Stop the foreground ngrok process when the public demo ends. Stop the local stack with `docker compose -p cloud_project -f compose.yaml stop` to retain stored data. Keep the Compose project name unchanged when restarting. Back up the metadata volume and all worker volumes together before migrations.
