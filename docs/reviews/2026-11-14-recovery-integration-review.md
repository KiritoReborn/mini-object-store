# Recovery integration review

Reviewed B head2924a6db81c5635462d162c4f683889ad1584231 against master9b29954, then the combined working tree. B delivered recovery.py and74 recovery cases; worker source was unchanged. No open PR existed at discovery; the combined integration PR preserves those commits.

## Standards

Independent review found a same-origin re-registration race: promotion used the newest heartbeat after verifying an older process inventory. Real-SQLite regression reproduced false ALIVE after a restart removed an already-verified chunk. Additive registration tokens now rotate in the registration transaction and are checked atomically with JOINING/current heartbeat at promotion. Heartbeats preserve tokens; legacy backfill and frozen helper shapes are tested. Follow-up review found no material issues in the fix; the new helpers are documented in contracts/db-helpers.md.

## Spec

Independent spec review checked both assignment PDFs and shared contracts. Byte verification, distinct replicas, orphan cleanup, UPLOADING protection and lifecycle hooks were implemented. It identified naive-heartbeat eligibility inconsistent with A's placement contract. Recovery now rejects missing timezone information; the regression changed from false admission to JOINING. Optional periodic HEALTHY-byte scrubbing is not a missing requirement. No status.router is included when status.py is absent.

## A fixture corrections

Baseline Linux integration produced290 passes/2 failures from missing-module assumptions. The reported global-connection snapshot race is intermittent. Explicit opt-in missing-recovery fixtures isolate A tests, while B tests keep actual hooks. Snapshot validation now calls the endpoint function without a running app/background reconciler. No production recovery-disable flag was added.

## Execution evidence

Final Linux suite:299 passed,1 skipped opt-in live case,1 existing Starlette/httpx warning. New tests cover generation rotation/migration, atomic admission, same-origin restart, fresh-inventory readmission/repair, normal-heartbeat liveness and exact public chunk boundaries.

The separate live five-container --large --browser run passed C1/C2/C4, physical two-copy/hash validation, Unicode metadata, forged-sidecar corruption repair, restart persistence,50MB streaming and deletion. Only labelled temporary resources were created/removed. Initial restart timeout was a test harness port issue: isolated reproduction confirmed Docker changes random published ports on restart; refresh_port fixed it, and the full rerun passed. No production fix was needed for that test-tool issue.

PC volumes were backed up before controller upgrade. Current PC state is4 available workers,2 preserved objects, zero under-replicated chunks/corrupt replicas. The promoted Vercel frontend passed a real HTTPS owner-authenticated nonempty upload/metadata/chunks/hash-download/delete workflow; temporary object removed. The staging automation bypass was revoked and other protection settings preserved.

Publication and final clean-checkout evidence are recorded in HANDOFF.md. These results establish the tested local/demo scope, not an availability SLA, resumable/S3 protocol, complete durable audit log or independent security certification.
