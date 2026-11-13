# Controller implementation review

Scope: Member A's controller implementation against baseline `6a8d653`, including SQLite/schema, placement, object APIs, error boundaries and lifecycle tests. One independent reviewer read the implementation, plan and handoff with a fresh context. No B-owned functional code was changed.

## Findings and resolution

1. **Temporary resource acquisition could outlive cancellation.** Cancelling a thread-pool mkstemp await left the coroutine without the returned path/descriptor, so cleanup could not find them. A regression test reproduced a late file leak. Fixed by retaining/draining the owned thread operation and explicitly releasing resources acquired during cancellation. Raw fd cleanup also covers os.fdopen failure.
2. **Initial object insert could outlive cancellation.** The first metadata insert sat outside the rollback block. A focused test reproduced an UPLOADING row left after cancellation. Moved insertion inside lifecycle ownership and used the same cancellation-safe operation completion. The test now verifies no surviving object row.
3. **Recovery hook return convention needed precision.** Documented that start_reconciler schedules its loop and returns None promptly, not its long-running Task. Sync or awaitable hooks are supported; shutdown should drain the task.

The reviewer found no additional important source-level defect in hash verification, READY gating, short transactions, foreign keys, manifest snapshots or the shared object-lock contract. This is a bounded review, not proof that every future failure is impossible.

## Decisions retained

- Late-finishing timed-out writes and offline remnants require B's periodic live-worker inventory sweep as well as rejoin-time cleanup. The integration contract makes that requirement explicit.
- Missing B recovery/status modules are reported honestly. Workers stay JOINING until B's production reconciler supplies eligibility.
- No production recovery substitute was added to A's part. Controlled live checks supply eligibility only in their isolated test harness.

## Verification after fixes

- Full Linux suite: **93 passed, 1 upstream deprecation warning**. Includes 42 unchanged worker cases and 51 controller cases.
- Controller Dockerfile build: passed.
- Controlled five-container check: all six APIs, 5000001-byte/6-chunk binary object, two distinct replicas/chunk and distribution over four workers, stopped-worker fallback, corruption detection/clean fallback, controller restart, 50000000-byte streamed round-trip and matching SHA-256.
- Controller peak-RSS increase during the large transfer: 9956 KiB in one diagnostic run. This is not a benchmark guarantee.
- Actual autonomous re-replication, B's production rejoin/trim/orphan logic and final assignment release gates remain pending.

Current commands and continuing status are maintained in `docs/CONTROLLER.md` and `docs/HANDOFF.md`.
