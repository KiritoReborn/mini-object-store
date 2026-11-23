# Artaud

Artaud is a mini distributed object store for demonstrating replication and recovery. Upload a file, see which workers hold its chunks, and watch the controller restore redundancy when a worker goes offline. One FastAPI controller and four storage workers run locally in Docker Compose.

[Run locally](#run-locally) · [Demo](#demo-checklist) · [HTTP API](#http-api) · [Tests](#run-tests) · [Project report](docs/report/artaud-report.pdf)

## Run locally

Install Git and Docker Compose v2. On Windows or macOS, start Docker Desktop. Use Linux containers on Windows.

```sh
git clone https://github.com/KiritoReborn/mini-object-store.git
cd mini-object-store
docker compose up --build -d
docker compose ps
```

Open **Cluster** in the dashboard and wait for all four workers to show **Available**. If the controller asks for an owner key, open **Connection settings**, leave **Backend HTTPS address** empty, paste the `ARTAUD_API_KEY` value from `.env`, and select **Test connection**, then **Connect backend**. [Local dashboard](http://127.0.0.1:8000/)

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
3. Find a chunk held by `worker2`, then run `docker stop worker2`. Download the same file and watch the controller restore two-copy redundancy on surviving workers. Run `docker start worker2` and wait for it to rejoin.
4. With the controls enabled below, select **Corrupt this copy** on a chunk replica with a healthy counterpart. Download or wait for an inventory scan, then check that recovery restores a valid copy.
5. Delete the demo file and confirm it disappears from **Files**.

### Enable dashboard worker controls

The demo overlay adds **Start**, **Stop**, **Restart**, and **Corrupt this copy** to the dashboard. It uses the local Docker socket and requires a private owner key.

**Windows PowerShell**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Configure-Demo.ps1
notepad .env
```

**macOS or Linux**

Keep your existing key if it has at least 32 characters. Otherwise, copy the generated `ARTAUD_API_KEY=...` line into `.env` next to `compose.yaml`. Keep a single key entry.

```sh
openssl rand -hex 32 | sed 's/^/ARTAUD_API_KEY=/'
nano .env
```

In Nano, press **Ctrl+O**, **Enter**, then **Ctrl+X**.

**Start or rebuild all five services with the overlay.**

```sh
docker compose -f compose.yaml -f compose.controls.yaml up --build -d
docker compose -f compose.yaml -f compose.controls.yaml ps
```

Reconnect the dashboard with the owner key. A page reload clears the key. Use fault injection on disposable uploads. For a remote presentation, keep Docker and the HTTPS tunnel running on the controller machine. [Hosted dashboard](https://frontend-nine-iota-19.vercel.app/) · [Remote setup](docs/DEMO.md)

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

## Documentation

| Topic | Where to look |
| --- | --- |
| Chunk placement, checksums, worker recovery, and failure limits | [Architecture](docs/ARCHITECTURE.md) |
| Local connection, worker, and download issues | [Troubleshooting](docs/TROUBLESHOOTING.md) |
| Local demo controls, Vercel, and the HTTPS tunnel | [Demo and deployment](docs/DEMO.md) |
| API and persistent metadata | [HTTP contract](contracts/api-contract.md) · [Database schema](contracts/db-schema.md) |
| Project design, development challenges, screenshots, and verification | [PDF report](docs/report/artaud-report.pdf) · [LaTeX source](docs/report/artaud-report.tex) |

Build the report from its LaTeX source with Tectonic.

```sh
cd docs/report
tectonic artaud-report.tex
```

With TeX Live, run `pdflatex artaud-report.tex` twice from the same directory.
