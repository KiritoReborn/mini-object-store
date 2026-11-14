# Architecture and failure model

[Overview](../README.md) · [HTTP contract](../contracts/api-contract.md) · [Troubleshooting](TROUBLESHOOTING.md)

Artaud runs one controller and four workers. Its purpose is to demonstrate chunked object storage, replicated placement, integrity verification and recovery with a visible operational interface.

## Components and authority

| Component                  | Responsibility                                                                                                           | Persistence                                                                              |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| FastAPI controller         | Public APIs, placement, lifecycle locks, verified downloads, recovery coordination, telemetry and optional demo controls | SQLite in `controller_data`; temporary verified downloads under `/data/downloads`        |
| Four FastAPI workers       | Chunk PUT/GET/DELETE, local checksum sidecars, registration and heartbeat                                                | Separate `worker1_data` through `worker4_data` volumes; chunk files under `/data/chunks` |
| React frontend             | File operations, metadata, cluster observations and explicitly confirmed worker controls                                 | Owner key and diagnostics stay in page memory; connection preferences are separate       |
| Optional Vercel/ngrok path | Vercel serves frontend assets; ngrok carries browser API requests to the PC over HTTPS                                   | Does not store the project's objects or replace Docker volumes                           |

The controller's SQLite chunk size/hash is the integrity authority. A worker's checksum sidecar is a local self-check and cannot override the expected database hash. Internal worker routes use Docker DNS and are intended for the trusted network. The base Compose profile publishes only controller port `8000` on loopback; worker port `8001` is not published.

Run one controller process and one process per worker volume. Object locks and the recovery loop are process-local; increasing Uvicorn worker count does not create a supported highly available deployment.

## Upload and publication

1. Validate the multipart file and optional JSON metadata. Allocate a UUID object in `UPLOADING` state.
2. Read at most one configured chunk at a time from the spooled upload. Default chunk size is 1,000,000 bytes; the last chunk can be smaller.
3. Record each chunk's index, size and SHA-256 in SQLite.
4. Select a worker for a replica. Record uncertain ownership before the request, then accept only a successful acknowledgement matching ID, size and hash. Select another distinct worker for the second replica.
5. Retry eligible alternatives after failed writes. If two confirmed copies cannot be obtained, fail the upload and clean reachable partial copies; never publish a READY partial object.
6. Recheck replication/eligibility and atomically finalize object size, count and whole-object hash as `READY`. Only then return `201` and expose it in public listings.

An empty object has no chunks and the SHA-256 of empty bytes. Public reads expose only READY objects. Long network operations happen outside SQLite transactions; object lifecycle mutations share the per-object lock.

## Placement: why counts often look equal

For each replica, upload placement reads healthy chunk counts for UPLOADING and READY objects, filters to placement-enabled ALIVE workers with fresh timezone-aware heartbeats, and excludes every worker already tried for that chunk. It sorts by `(chunk_count, worker_id)` and takes the first candidate. Successful writes update the count before subsequent selections.

Starting empty, with four healthy workers and no concurrent uploads:

| Displayed chunk | First copy | Second copy | Counts after placement: W1/W2/W3/W4 |
| --------------- | ---------- | ----------- | ----------------------------------- |
| 1               | worker1    | worker2     | 1 /1 /0 /0                          |
| 2               | worker3    | worker4     | 1 /1 /1 /1                          |
| 3               | worker1    | worker2     | 2 /2 /1 /1                          |
| 4               | worker3    | worker4     | 2 /2 /2 /2                          |

Each chunk has two copies, rather than one full-file copy on every worker. Equal chunk counts do not imply equal bytes because final chunks differ in size. Placement is deterministic least-loaded selection, not consistent hashing or capacity-aware scheduling. Concurrent requests can observe the same load snapshot, so this is a balancing preference rather than a strict global fairness guarantee.

Reads and recovery are separate from the UI's upload-placement pause. Recovery reuses eligible-worker selection to restore redundancy but does not automatically rebalance already healthy chunks onto a returned empty worker.

## Download integrity

The controller reads the ordered manifest, tries eligible recorded replicas, and checks each returned chunk against the database size and SHA-256. A missing/corrupt copy can fall back to another; a timeout is not automatically classified as corruption.

Verified chunks are assembled in controller-owned temporary storage. The whole file's size and hash must match before a binary `200` response starts. If any required chunk has no verified readable source, the response is JSON `503` instead of a partial file. A later client/network interruption during transmission is still possible. Temporary download files are released after sending or cancellation.

## Worker admission and repair

Workers register as `JOINING`, then send heartbeats. Heartbeats prove recent communication; they do not grant storage eligibility. Recovery inventories a joining worker, verifies its actual bytes, reconciles missing/orphan/surplus chunks, and admits it as ALIVE only after an atomic registration-token check. A restart during inventory invalidates the old admission attempt, while an ordinary heartbeat does not.

With defaults, heartbeats run every 5 seconds, a heartbeat older than 15 seconds can mark a worker DEAD, and reconciliation runs every 5 seconds. These are eventual thresholds, not an exact recovery-time promise; transfer duration, inventory and retries also matter. Periodic live inventory runs separately. B's operation-specific HTTP timeouts are documented in the shared contract.

Recovery reads a verified surviving replica before creating and verifying a replacement on an eligible distinct worker. Surplus cleanup verifies two other good copies before deleting a third. The same object lock protects recovery and API deletion, and UPLOADING chunks remain protected from orphan cleanup.

## Failure matrix

| Event                                           | Current behavior                                                                                                                                                |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| One of a chunk's two holders stops              | Read fallback can work immediately; death detection and repair restore the target when an eligible destination exists.                                          |
| Both holders stop before repair                 | No verified live source for that chunk. The affected file's download returns503; repair waits for a source. Other files can remain readable.                    |
| One holder restarts with valid persistent bytes | Verified admission can make the source usable again; repair can rebuild the second copy.                                                                        |
| All physical copies are permanently destroyed   | The chunk is unrecoverable without an external backup. No parity fragments exist in this implementation.                                                        |
| A returning worker has three-copy surplus       | Its original chunks can be deliberately removed after two copies elsewhere are verified. The volume itself persists; an ALIVE worker with zero chunks is valid. |
| Controller process restarts                     | SQLite metadata persists. Interrupted uploads become failed/cleanup candidates, workers must be readmitted, and process-local activity history resets.          |
| Physical PC or its disk fails                   | The controller and all four workers share that failure domain. The local deployment cannot provide machine-level or zone-level availability.                    |

Replication factor two can tolerate one lost holder per chunk. It does not guarantee survival of any two worker failures. If a first failure is fully repaired before the second, the result can differ because replacement copies already exist.

## How this differs from enterprise object storage

**Availability** means a client can read now; **durability** means the bytes have not been permanently lost. Stopped workers with intact volumes can mean temporary unavailability without lost durability. Losing every copy is a durability failure.

Enterprise placement accounts for independent failure domains such as hosts, racks and availability zones; four containers on one PC do not provide that independence. Protection also depends on the selected storage class and replication option:

| Service/option                        | Documented protection                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Amazon S3 Standard                    | Stores data across a minimum of three availability zones. Single-zone classes have different protection; this does not imply an exact three-full-copy internal layout. [AWS storage classes](https://aws.amazon.com/s3/storage-classes/)                                                                                                               |
| Azure Storage ZRS                     | Synchronous redundancy across three or more availability zones. GRS/GZRS add asynchronous replication to a secondary region, with lag and failover/read-access considerations. [Azure redundancy](https://learn.microsoft.com/en-us/azure/storage/common/storage-redundancy)                                                                           |
| Google Cloud Storage regional buckets | Redundancy in at least two availability zones before acknowledging writes; Google documents erasure coding, checksum validation and automatic correction. Dual/multi-region options add geographic redundancy with their own replication behavior. [Google availability and durability](https://cloud.google.com/storage/docs/availability-durability) |

Erasure coding stores data and parity fragments rather than only full copies. For example, an appropriate Reed-Solomon `k=3, m=2` layout can reconstruct data from any three of five fragments, tolerating two missing fragments when placement and decoding requirements are satisfied. It still needs enough surviving information. [Ceph erasure-code explanation](https://docs.ceph.com/en/latest/rados/operations/erasure-code/)

Redundancy is also different from a backup: accidental deletion can be replicated to every copy. Versioning, retention and independent backups address different failure cases. No redundancy scheme offers unlimited failure tolerance.

Artaud deliberately retains the assignment's two-copy policy. Changing a single replication constant would be insufficient: upload finalization, recovery thresholds, cleanup, tests, UI and contracts must agree. More replicas, failure-domain-aware placement, erasure coding and a replicated metadata/control plane are possible future work, not current guarantees.

## Shared references

- [HTTP and wire contracts](../contracts/api-contract.md)
- [Database relationships and invariants](../contracts/db-schema.md)
- [Stable database/recovery helper interface](../contracts/db-helpers.md)
- [Observed activity and visualization semantics](LIVE_SYSTEM.md)
- [Verified acceptance scope](ACCEPTANCE.md)
