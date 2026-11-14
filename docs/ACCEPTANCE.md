# Joint acceptance and interview checklist

The combined controller/worker system was verified with the production reconciler, without manually granting ALIVE. See HANDOFF.md for publication/runtime state and docs/reviews/2026-11-14-recovery-integration-review.md for the review.

## Reproduce from a clean checkout

Start Docker Desktop's Linux engine, then build the existing Dockerfiles:

```sh
docker build -f Dockerfile.controller -t mini-object-store-controller:integration .
docker build -f Dockerfile.worker -t mini-object-store-worker:integration .
docker run --rm --network none -v "${PWD}:/review:ro" -w /review mini-object-store-controller:integration python -B -m pytest -q -p no:cacheprovider --basetemp=/tmp/object-store-tests
python tests/test_end_to_end.py --worker-image mini-object-store-worker:integration --large
```

The last command creates five disposable containers/volumes on a private named network, publishes only a random loopback controller port, verifies actual admission/repair and removes only its own labelled resources. Existing Compose services/user files are untouched. Add --browser after installing frontend dependencies/Chromium to include the actual web workflow. scripts/demo.sh is a POSIX wrapper for the same check; set PYTHON=python3 if needed. Normal pytest skips this opt-in check; its standalone live run is separate evidence.

## Required behavior and evidence

| Requirement | Verification |
|---|---|
| POST upload201; GET bytes200; GET metadata200; PATCH200; DELETE204; list200 | API suite and real five-container/public browser roundtrips. The UI is optional; routes are independently usable. |
| multipart file/optional JSON metadata; protected system fields | API validation/metadata tests; real PATCH preserves system hash/size. |
| JSON400/404/409/500/503; invalid framework input400 | Controller/worker API tests and error contracts. Missing/unverified copies produce JSON503 before binary success. |
|0 bytes, exactly1000000 bytes,1000001 bytes | API boundary cases; zero chunks/no workers needed for empty content; real browser1000001-byte two-chunk roundtrip. |
|5000001-byte file |6 ordered chunks: five1000000 bytes and a final1 byte;2 real disk copies/hash-valid sidecars per chunk across4 workers. |
|50MB memory behavior | Client and download checker stream64KiB buffers; server uses spooled multipart/chunk-sized reads.50000000-byte/50-chunk hash-matching transfer passed. No server RSS benchmark is claimed. |
| Mid-upload worker failure, concurrent uploads, Unicode, forged hash, unknown object | Focused API/cancellation tests; real Unicode roundtrip and forged-sidecar corruption check. No READY partial objects. |
| C1 registration/admission |4 actual JOINING→verified ALIVE workers through B's reconciler. |
| C2 upload/download/placement | Real REST and browser workflow; metadata/physical bytes checked independently. |
| C4 failure/recovery | Actual container stop, verified fallback, DEAD detection, factor-two repair on3 survivors, volume-preserving rejoin and surplus trimming; corruption repaired against DB SHA-256. |
| Restart persistence/delete | Controller restart/readmission retains bytes/hash; API deletion removes metadata and all QA disk copies. |

## Explain the demo

Member A: API lifecycle, authoritative SQLite schema/helpers, placement, verification/locks, frontend and observability. Member B: worker files/sidecars/heartbeat and autonomous inventory/repair. Shared integration adds test isolation, a registration admission fence, Compose settings, contracts and acceptance checks.

For the existing PC stack, use docker stop worker2 and docker start worker2 while watching Cluster. Default heartbeat is5s, death threshold15s and recovery pass interval5s; timing is eventual, not an instantaneous SLA. UI Stop/Start/Restart controls call the local Docker Engine only with the optional privileged socket overlay and owner key. They preserve volumes and do not grant storage eligibility. A successful container Start is followed by actual inventory verification.

The public layout remains Vercel frontend → ngrok HTTPS → PC controller → local workers. Vercel never runs Docker or proxies file bodies. Enter the private owner key in Connection settings. The PC/Docker/tunnel must stay online; a changed tunnel address must be updated in Vercel or the tab's connection settings. Core APIs and the local dashboard work without Vercel/ngrok.
