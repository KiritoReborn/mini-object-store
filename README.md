# Artaud · Mini Distributed Object Store

Artaud stores files across four Docker workers. The dashboard shows where each chunk lives and how the controller restores two-copy redundancy after a worker fails. The local demo runs entirely in Docker.

[Run locally](#run-locally) · [Demo checklist](#demo-checklist) · [Test commands](#run-tests) · [Project report](docs/report/artaud-report.pdf)

## Run locally

Install Git and Docker Compose v2. On Windows or macOS, start Docker Desktop with Linux containers. Run the commands from the repository root.

```sh
git clone https://github.com/KiritoReborn/mini-object-store.git
cd mini-object-store
```

For an existing checkout, update from GitHub.

```sh
git switch master
git pull --ff-only
```

Keep the existing Compose project name to retain its volumes. If you originally used `-p PROJECT`, use it on every Compose command.

### Start the full demo

On **Windows**, create or reuse the owner key in PowerShell.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Configure-Demo.ps1
notepad .env
```

On **macOS or Linux**, run the following in Terminal. Keep an existing `ARTAUD_API_KEY` if it already has at least 32 characters. Otherwise, use the generated line in `.env` and save the file beside `compose.yaml`.

```sh
openssl rand -hex 32 | sed 's/^/ARTAUD_API_KEY=/'
nano .env
```

In Nano, press **Ctrl+O**, **Enter** and **Ctrl+X** to save and exit.

On either platform, start all five services with the demo overlay.

```sh
docker compose -f compose.yaml -f compose.controls.yaml up --build -d
docker compose -f compose.yaml -f compose.controls.yaml ps
```

Open the local dashboard. In **Connection settings**, leave **Backend HTTPS address** empty, paste the `ARTAUD_API_KEY` value including any trailing `=` signs, and select **Test connection**, then **Connect backend**. Open **Cluster** and wait for four available workers. A reload clears the key. [Local dashboard](http://127.0.0.1:8000/)

The overlay grants the controller access to the Docker socket and enables deliberate replica corruption. Use the corruption control on disposable demo uploads. Keep `.env` private.

### Start the standard stack

Use the base configuration for storage, downloads, and automatic recovery. Enter the owner key in the dashboard if your existing `.env` sets one.

```sh
docker compose -f compose.yaml up --build -d
```

### Check status and stop

```sh
docker compose -f compose.yaml ps
docker compose -f compose.yaml logs --tail 100 controller worker2
docker compose -f compose.yaml stop
```

`stop` retains the containers and volumes. Run the same startup command again to resume. `docker compose down -v` deletes the stored volumes.

## Demo checklist

1. Upload a disposable file larger than 1 MB with custom metadata. Open **Cluster → Where each chunk lives** and select it. Each chunk should show two healthy locations, and the final chunk may be smaller.
2. Download the file, then use **Details → Verify integrity** to compare it with the stored SHA-256. Edit a custom metadata field and reopen the inspector to confirm the change.
3. Select a chunk held by `worker2`. Stop that worker, download the file again, and watch for replacement copies on surviving workers. Restart the worker and wait for verified readmission.

   ```sh
   docker stop worker2
   # Observe download fallback and wait for repair here.
   docker start worker2
   ```

4. With the full overlay, use **Corrupt this copy** on one replica that also has a healthy counterpart. Verify the download and observe repair. Either **CORRUPT** bytes or a **MISSING** copy can be replaced from a verified surviving copy of that chunk.
5. Delete the demo file and confirm it disappears from **Files**. The isolated acceptance test checks physical copies and deletion on disk.

The dashboard distinguishes Docker running status from worker availability. If admission, authentication or a download fails, see [Troubleshooting](docs/TROUBLESHOOTING.md). The hosted frontend needs a running controller and an HTTPS tunnel. [Hosted dashboard](https://frontend-nine-iota-19.vercel.app/) · [Remote demo setup](docs/DEMO.md)

## Use the API

Open `/docs` to explore the API. When the owner key is configured, send the `X-Artaud-Key` header. The following commands work in a POSIX shell on a fresh base stack. With authentication enabled, export `ARTAUD_API_KEY` in that shell before running them. Use a real `sample.bin` and replace `OBJECT_ID` with the result of the upload. [Interactive API documentation](http://127.0.0.1:8000/docs)

```sh
api=http://127.0.0.1:8000/api/v1/objects
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" -F 'file=@sample.bin' \
  -F 'metadata={"demo":"yes"}' "$api"
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" "$api"
object_id=OBJECT_ID
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" "$api/$object_id/metadata"
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" -X PATCH \
  -H 'Content-Type: application/json' -d '{"metadata":{"reviewed":true}}' \
  "$api/$object_id/metadata"
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" -o retrieved.bin "$api/$object_id"
shasum -a 256 sample.bin retrieved.bin
curl -fsS -H "X-Artaud-Key: ${ARTAUD_API_KEY:-}" -X DELETE "$api/$object_id"
```

On Linux, you can also use `sha256sum sample.bin retrieved.bin`. In PowerShell, compare files with `Get-FileHash -Algorithm SHA256 -Path sample.bin,retrieved.bin`. Full request shapes and status codes are in the [HTTP contract](contracts/api-contract.md).

## Run tests

**Backend suite as one command in PowerShell**, from the repository root with Docker running.

```powershell
docker build -f Dockerfile.controller -t mini-object-store-controller:integration .; if ($LASTEXITCODE -eq 0) { docker run --rm --network none --mount "type=bind,source=$($PWD.Path),target=/review,readonly" --workdir /review mini-object-store-controller:integration python -B -m pytest tests -q -p no:cacheprovider --basetemp=/tmp/object-store-tests }
```

**Backend suite as one command in macOS/Linux Terminal.**

```sh
docker build -f Dockerfile.controller -t mini-object-store-controller:integration . && docker run --rm --network none --mount "type=bind,source=$PWD,target=/review,readonly" --workdir /review mini-object-store-controller:integration python -B -m pytest tests -q -p no:cacheprovider --basetemp=/tmp/object-store-tests
```

**Live acceptance**, from the repository root with Python 3.12 or newer. It brings up a disposable cluster with separate volumes and includes a 50 MB round trip.

```sh
docker build -f Dockerfile.controller -t mini-object-store-controller:integration .
docker build -f Dockerfile.worker -t mini-object-store-worker:integration .
python tests/test_end_to_end.py --large
```

To include the live browser workflow, install the frontend dependencies and Chromium using the commands below. Then run `python tests/test_end_to_end.py --large --browser` from the repository root.

**Frontend tests and build**, with Node.js 22.12+ and npm.

```sh
cd frontend
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Use `npm run dev` for the frontend development server on port 5173. Start the controller separately for real uploads. `npm run build` regenerates `controller/static`; rebuild the controller to serve the updated dashboard. [Development guide](docs/DEVELOPMENT.md)

## Project report

The report covers the storage design, recovery behavior and verification results. Its figures and LaTeX source are included in the repository. Build the PDF with Tectonic from the report directory.

```sh
cd docs/report
tectonic artaud-report.tex
```

With TeX Live, run `pdflatex artaud-report.tex` twice from the same directory.

[PDF report](docs/report/artaud-report.pdf) · [LaTeX source](docs/report/artaud-report.tex) · [Architecture](docs/ARCHITECTURE.md) · [Database schema](contracts/db-schema.md)
