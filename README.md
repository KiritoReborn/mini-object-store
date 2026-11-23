# Artaud

Artaud is a mini distributed object store for demonstrating replication and recovery. Upload a file, see which workers hold its chunks, and watch the controller restore redundancy when a worker goes offline. One FastAPI controller and four storage workers run locally in Docker Compose.

[Run locally](#run-locally) · [Demo](#demo-checklist) · [HTTP API](#http-api) · [Tests](#run-tests) · [Project report](docs/report/artaud-report.pdf)

## What it does

- Stores arbitrary files as ordered chunks of up to **1,000,000 bytes**, with two copies of each chunk on different workers.
- Verifies downloaded bytes with SHA-256. A surviving verified copy keeps its chunk readable and gives recovery a source.
- Provides six object API operations, persistent volumes, and a dashboard that shows placement and recovery.

```mermaid
flowchart LR
    Client["Dashboard / REST client"] --> Controller
    Controller --- SQLite["SQLite metadata"]
    Controller --> W1["worker1"]
    Controller --> W2["worker2"]
    Controller --> W3["worker3"]
    Controller --> W4["worker4"]
```

## Run locally

Install Git and Docker Compose v2. On Windows or macOS, start Docker Desktop. Use Linux containers on Windows.

```sh
git clone https://github.com/KiritoReborn/mini-object-store.git
cd mini-object-store
docker compose up --build -d
docker compose ps
```

[Open the local dashboard at 127.0.0.1:8000](http://127.0.0.1:8000/). In **Cluster**, wait for all four workers to show **Available**. A fresh base-mode checkout works without an owner key. If you configured `ARTAUD_API_KEY`, unlock the dashboard using the connection steps below.

<details>
<summary>Update an existing checkout</summary>

```sh
git switch master
git pull --ff-only
```

From the directory that contains `compose.yaml`, rerun your original startup command with `--build`. Reuse the same Compose project name to keep its volumes and include the demo overlay if you used it before.

</details>

<img src="docs/images/cluster-dashboard.png" width="860" alt="Artaud cluster dashboard showing the controller and four available storage workers">

### View logs and stop

```sh
docker compose logs --tail 100 controller worker2
docker compose stop
```

`stop` retains containers and data. Use the same startup command to resume. `docker compose down -v` deletes the project's stored objects and metadata.

## Demo checklist

1. Upload a disposable file larger than 1,000,000 bytes. In **Cluster → Where each chunk lives**, select the file and check that each chunk has two healthy locations.
2. Download it. Use **Details → Verify integrity** to compare the downloaded file with the stored SHA-256. Change a custom metadata field and check that the update persists.
3. Stop and rejoin `worker2` using a disposable file with a chunk on that worker.
   - Run `docker stop worker2` and download the file again. Expect the checksum to match, using its surviving copies.
   - Expect `worker2` to show **Offline** after about 15–20 seconds and two available copies per chunk to return around 20 seconds in a small local demo. Timing varies with heartbeat phase and repair work. Check the placement table for recovery before restarting the worker.
   - Run `docker start worker2`. Expect **Joining**, then **Available**. The worker can return with **0 copies** because the controller removes surplus copies once two other copies pass verification. Existing valid copies stay where they are.
4. Corrupt one copy of a disposable object. The dashboard's **Chunk 1** is API index `0` and its ID ends in `_0`. Substitute your uploaded object's ID below. This POSIX shell example uses `curl` and `jq` and selects the first chunk only if it has two available workers, including `worker1`.

   ```sh
   object_id=REPLACE_WITH_OBJECT_ID
   chunk_id=$(curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" "http://127.0.0.1:8000/api/v1/objects/$object_id/metadata" | jq -er '.chunks[] | select(.index == 0 and (.available_workers | length) == 2 and (.available_workers | index("worker1")) != null) | .chunk_id') &&
     docker compose exec -T worker1 sh -c 'printf x >> "/data/chunks/$1"' artaud-demo "$chunk_id"
   ```

   Download and verify the file again. **Recent activity → Replicas & recovery** shows detection and repair. If the healthy copy was read first, wait for the periodic inventory scan. With the controls overlay, **Corrupt this copy** injects a fault from the dashboard.
5. Delete the demo file and confirm it disappears from **Files**. The live test also checks cleanup on disk.

### Enable dashboard worker controls

The demo overlay adds **Start**, **Stop**, **Restart**, and **Corrupt this copy** to the dashboard. It uses the local Docker socket and requires a private owner key.

**Windows PowerShell**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Configure-Demo.ps1
notepad .env
```

**macOS or Linux**

The helper uses OpenSSL and preserves any existing owner-key entry.

```sh
sh scripts/configure-demo.sh
```

**Start or rebuild all five services with the overlay.**

```sh
docker compose -f compose.yaml -f compose.controls.yaml up --build -d
docker compose -f compose.yaml -f compose.controls.yaml ps
```

In **Connection settings**, leave **Backend HTTPS address** empty for the local controller. Paste the value of `ARTAUD_API_KEY` from `.env`, then select **Test connection** and **Connect backend**. A page reload clears the key.

The hosted frontend needs the controller PC, Docker, and the ngrok tunnel to be running. If the backend is offline, see the screenshots in the report. [Hosted dashboard](https://frontend-nine-iota-19.vercel.app/) · [Remote setup](docs/DEMO.md)

## HTTP API

The object API is served under `http://127.0.0.1:8000/api/v1/objects`. When an owner key is configured, send it in the `X-Artaud-Key` header. [OpenAPI reference](http://127.0.0.1:8000/docs) · [HTTP contract](contracts/api-contract.md)

| Method | Path | Operation | Success |
| --- | --- | --- | --- |
| `POST` | `/api/v1/objects` | Upload a file with optional custom metadata | `201` |
| `GET` | `/api/v1/objects` | List stored objects | `200` |
| `GET` | `/api/v1/objects/{id}` | Download the original bytes | `200` |
| `GET` | `/api/v1/objects/{id}/metadata` | Read metadata and the chunk manifest | `200` |
| `PATCH` | `/api/v1/objects/{id}/metadata` | Update custom metadata | `200` |
| `DELETE` | `/api/v1/objects/{id}` | Delete an object | `204` |

<details>
<summary>Run a complete upload, download, and delete with curl</summary>

Use a POSIX shell and a disposable file named `sample.bin`. Export `ARTAUD_API_KEY` in that shell if authentication is enabled. Replace `OBJECT_ID` with the ID from the upload response. `cmp` exits successfully when both files have identical bytes.

```sh
api=http://127.0.0.1:8000/api/v1/objects
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" -F 'file=@sample.bin' \
  -F 'metadata={"demo":"yes"}' "$api"

object_id=OBJECT_ID
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" "$api"
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" "$api/$object_id/metadata"
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" -X PATCH \
  -H 'Content-Type: application/json' -d '{"metadata":{"reviewed":true}}' \
  "$api/$object_id/metadata"
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" -o retrieved.bin "$api/$object_id"
cmp sample.bin retrieved.bin
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" -X DELETE "$api/$object_id"
```

</details>

**Clients** include the dashboard and curl.

## Run tests

### Backend suite in one command

Run from the repository root with Docker running. The live acceptance test below runs separately.

**PowerShell**

```powershell
docker build -f Dockerfile.controller -t mini-object-store-controller:integration .; if ($LASTEXITCODE -eq 0) { docker run --rm --network none --mount "type=bind,source=$($PWD.Path),target=/review,readonly" --workdir /review mini-object-store-controller:integration python -B -m pytest tests -q -p no:cacheprovider --basetemp=/tmp/object-store-tests }
```

**macOS or Linux**

```sh
docker build -f Dockerfile.controller -t mini-object-store-controller:integration . && docker run --rm --network none --mount "type=bind,source=$PWD,target=/review,readonly" --workdir /review mini-object-store-controller:integration python -B -m pytest tests -q -p no:cacheprovider --basetemp=/tmp/object-store-tests
```

### Live five-container test

Use host Python 3.12 or newer. The test creates separate volumes and verifies recovery and a 50 MB round trip.

```sh
docker build -f Dockerfile.controller -t mini-object-store-controller:integration .
docker build -f Dockerfile.worker -t mini-object-store-worker:integration .
python tests/test_end_to_end.py --large
```

After installing Chromium below, add `--browser` to check the real dashboard against that same disposable cluster.

### Frontend tests and build

Use Node.js 22.12 or newer.

```sh
cd frontend
npm ci
npm test
npx playwright install chromium
npm run test:e2e
npm run build
```

Use `npm run dev` to start the Vite development server. `npm run build` regenerates `controller/static`. Rebuild the Docker controller to serve those assets. [Development guide](docs/DEVELOPMENT.md)

## Limits

The default chunk size is 1,000,000 bytes and the final chunk may be smaller. The controller and all four workers share one host. An object becomes unavailable if every verified copy of any of its chunks is unreachable. Repair needs a valid copy and an eligible worker.

## Documentation

| Topic | Where to look |
| --- | --- |
| Chunk placement, checksums, worker recovery, and failure limits | [Architecture](docs/ARCHITECTURE.md) |
| Local connection, worker, and download issues | [Troubleshooting](docs/TROUBLESHOOTING.md) |
| Local demo controls, Vercel, and the HTTPS tunnel | [Demo and deployment](docs/DEMO.md) |
| API and persistent metadata | [HTTP contract](contracts/api-contract.md) · [Database schema](contracts/db-schema.md) |
| Assignment and team plan | [Assignment brief](docs/Mini_Distributed_Cloud_Object_Store.pdf) · [Project plan](docs/Mini_Distributed_Object_Store_Final_Updated_Plan.pdf) |
| Project design, development challenges, screenshots, and verification | [PDF report](docs/report/artaud-report.pdf) · [LaTeX source](docs/report/artaud-report.tex) |

Build the report from its LaTeX source with Tectonic.

```sh
cd docs/report
tectonic artaud-report.tex
```

With TeX Live, run `pdflatex artaud-report.tex` twice from the same directory.

## License

Artaud is released under the [MIT License](LICENSE). The bundled Geist font is distributed under the [SIL Open Font License 1.1](frontend/public/assets/geist-license.txt). [Third-party notices](frontend/public/assets/third-party-notices.txt)
