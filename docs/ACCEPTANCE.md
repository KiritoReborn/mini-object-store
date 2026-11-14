# Acceptance and testing

[Overview](../README.md) · [Architecture](ARCHITECTURE.md) · [Current handoff](HANDOFF.md)

Use the Linux backend suite for unit/API coverage and the separate five-container harness for actual admission and recovery. Frontend fixture tests and real browser checks provide different evidence; neither substitutes for the other.

## Backend suite

Start Docker's Linux engine and build from the repository root:

```sh
docker build -f Dockerfile.controller -t mini-object-store-controller:integration .
docker build -f Dockerfile.worker -t mini-object-store-worker:integration .
```

In PowerShell:

```powershell
docker run --rm --network none --mount "type=bind,source=$($PWD.Path),target=/review,readonly" --workdir /review mini-object-store-controller:integration python -B -m pytest -q -p no:cacheprovider --basetemp=/tmp/object-store-tests
```

In a POSIX shell:

```sh
docker run --rm --network none --mount "type=bind,source=$PWD,target=/review,readonly" --workdir /review mini-object-store-controller:integration python -B -m pytest -q -p no:cacheprovider --basetemp=/tmp/object-store-tests
```

The mount supplies the full checkout and tests; temporary test storage stays in the disposable container. No normal Compose volume is attached. Linux is needed because worker durability tests exercise directory syncing. Normal pytest explicitly skips the live Docker acceptance test unless its opt-in flag is set.

## Actual five-container acceptance

With the integration images above and Python 3.12+ on the host:

```sh
python tests/test_end_to_end.py --large
```

The standalone runner uses the Python standard library and Docker CLI. It creates a UUID-prefixed labelled network, controller, four workers and five volumes, publishing only a random loopback controller port. Existing Compose containers, user objects and volumes are not used. Cleanup checks ownership and removes only resources created by that run.

The actual production reconciler performs JOINING-to-ALIVE admission; the harness never patches eligibility. It checks six-chunk replication using the actual worker files and database hashes, actual worker stop/fallback/death/repair/rejoin, surplus cleanup, forged-sidecar corruption, controller restart and deletion. `--large` adds a streamed 50,000,000-byte roundtrip. Each convergence poll has a finite timeout; on failure the runner prints bounded diagnostics and still attempts its scoped cleanup.

```sh
python tests/test_end_to_end.py --help
sh scripts/demo.sh --large
```

The POSIX wrapper runs the same harness; use `PYTHON=python3` where needed. To use other already-built image tags, pass `--controller-image` and `--worker-image` explicitly. The defaults are `mini-object-store-controller:integration` and `mini-object-store-worker:integration`.

## Frontend and real browser checks

```sh
cd frontend
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:e2e
cd ..
python tests/test_end_to_end.py --large --browser
```

Vitest and the normal Playwright suite exercise explicit UI fixtures, error states, accessibility and narrow layouts. The final command adds an actual web workflow against the disposable five-container system. It covers upload, metadata, chunks, placement/highlights, observed transfer replay, hash-matching download and deletion before fault injection.

The owner-invoked public demo check is separate:

```sh
node frontend/e2e/live-public-demo.mjs https://YOUR-FRONTEND.vercel.app https://YOUR-ACTIVE-NGROK-HOST
```

It requires the configured private local key and running public backend, creates one uniquely named QA object, verifies the roundtrip and deletes that object. It does not intentionally stop normal workers. Avoid running it against someone else's endpoint. Captures stay in ignored frontend test-results; the README image is a separately published read-only capture.

## Recorded results: 14 November 2026

The integrated source at `30e6e88` was verified from a fresh committed checkout and merged through PR #4 at `cfe2ecf`. Later documentation-only commits do not change application behavior.

| Verification                       | Observed result                                                                                                       |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Linux backend suite                | 299 passed,1 explicit live skip,1 existing Starlette/httpx deprecation warning                                        |
| Frontend unit suite                | 28 passed                                                                                                             |
| Chromium UI suite                  | 29 passed                                                                                                             |
| Clean frontend build               | Typecheck/build passed; generated static assets matched committed content, normalizing license-text line endings      |
| Five-container `--large --browser` | Passed actual admission, physical replication, failure/rejoin/repair, corruption, restart, large transfer and cleanup |
| Public Vercel-to-PC browser        | Passed authenticated nonempty upload, PATCH, chunks, hash-download, delete and visibility of worker controls          |

Full execution details and reviewed integration fixes are recorded in [the integration review](reviews/2026-11-14-recovery-integration-review.md). These are dated results, not a hosted CI badge or future availability guarantee.

## Assignment behavior covered

| Requirement                                                                             | Evidence                                                                                                             |
| --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Six APIs and exact 201/200/204 success codes                                            | API suite and real REST/browser roundtrips                                                                           |
| Multipart file, optional JSON metadata, PATCH envelope and protected system keys        | Validation/metadata tests and real metadata edit                                                                     |
| JSON 400/404/409/500/503; invalid framework input maps to 400                           | API/worker error checks and contract                                                                                 |
| 0 bytes, exactly 1,000,000 bytes,1,000,001 bytes                                        | API boundary cases and actual two-chunk browser transfer                                                             |
| 5,000,001 bytes                                                                         | Six ordered chunks: five 1,000,000-byte chunks and a final 1 byte; two physical copies across four workers           |
| 50 MB                                                                                   | 50,000,000-byte/50-chunk streamed hash roundtrip; no server RSS benchmark is claimed                                 |
| Mid-upload failure, concurrent uploads, Unicode names, wrong hashes and unknown objects | Focused API/cancellation tests plus real Unicode/forged-sidecar checks                                               |
| C1 admission                                                                            | Four workers verified by B's actual inventory reconciliation                                                         |
| C2 placement/roundtrip                                                                  | Independent checks of metadata, chunk files, sidecars and hashes                                                     |
| C4 recovery                                                                             | Actual container stop, read fallback, DEAD detection, repair on survivors, volume-preserving rejoin and surplus trim |
| Restart and physical delete                                                             | Controller persistence/readmission and removal of all QA disk copies                                                 |

The verified single-worker fault workflow does not imply tolerance of both holders failing. See the [failure matrix](ARCHITECTURE.md#failure-matrix). No versioning, erasure coding, multi-region availability or independent security certification is claimed. The historical `tests/live_controller_check.py` used test-only admission before recovery was delivered; use the current harness for integrated evidence.
