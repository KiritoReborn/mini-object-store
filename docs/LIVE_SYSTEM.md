# Live system explorer

Open the [live dashboard](https://frontend-nine-iota-19.vercel.app/) or local app and choose **Cluster**. Enter the owner key when required. Files remains the object workspace. This is an operational view of the real controller, with optional fixed-worker demo controls; topology observations do not simulate recovery. See [architecture and placement](ARCHITECTURE.md) for how chunks are assigned.

## What the screen explains

- **Topology:** controller-to-worker connections, actual registration/availability, selectable nodes and recorded copy counts/bytes. A solid available connection is different from a joining/unknown connection. On phones, a common controller trunk branches to each worker; workers do not forward data through one another.
- **Transfers:** recent controller-observed worker attempts light the corresponding connection for four seconds. Travel direction distinguishes writes from reads. Timing is a visual summary, not packet timing, bandwidth or an in-flight gauge. Short operations remain in the timeline for explicit replay. Replay uses a blue wire and the original timestamp, including when the live feed is unavailable; it does not change node health.
- **Chunk placement:** select a READY file, inspect its ordered chunk rows across workers, and click a chunk to highlight recorded HEALTHY locations. Selecting the same chunk clears the highlight. Eight rows per page; the table scrolls locally on small screens. Refreshed manifests update highlights; unknown/error states clear them. The file inspector and JSON manifest export are available here too.
- **Distribution:** each bar is that worker's share of recorded healthy copy bytes, including active uploads. Text includes exact bytes/copy counts. These are not disk capacity, physical usage or free-space values.
- **Recovery:** under-replicated chunks, corrupt replica records, available copies and service availability remain visible. Observed CORRUPT/MISSING -> HEALTHY transitions appear as restored replicas. Explicit repair lifecycle events appear when B emits them. A connected hook or restored DB record alone does not prove autonomous repair, and unavailable recovery is never animated as successful.
- **Timeline:** filter by node, selected file, event type or text. Inspect extant files directly from events. Keep deleted-file events as history, without offering an invalid inspector. The browser retains up to 512 events and reports gaps/process restarts.
- **Diagnostics:** export the observed overview, file summaries (without custom metadata), retained events, capture times, pause state and connection errors as versioned JSON. Exports preserve stale labels and do not claim one atomic snapshot across all endpoints. The separate explicit manifest export includes that file's metadata and its own capture time.

Pause live view freezes this view's overview/files, manifest and activity observations and disables travel. Resume fetches current observations. The surrounding workspace can still refresh. Reduced-motion preferences remove packet travel. Text states, native controls, a real chunk table and the detailed node list provide alternatives to the graphical map. Polling is serialized; slow successful responses are allowed to complete. Live requests have a 15-second active-time timeout, with readable error/retry states. Hidden-page polling waits until it can observe again.

## Controller activity contract

`GET /api/v1/activity?after=0` returns:

```json
{
  "stream_id": "process-session-uuid",
  "oldest_id": 0,
  "latest_id": 0,
  "next_cursor": 0,
  "truncated": false,
  "events": []
}
```

The example is an empty session. Each event contains `id`, UTC `timestamp`, `kind` and nullable `object_id`, `chunk_id`, `worker_id`, `transfer_id`, `direction`, `size`, `state`, `previous_state`, `name`, `detail`. `direction` is `to_worker` or `from_worker` for transfers. Text is bounded at 512 characters; sizes are nonnegative signed-64-bit integers. No file bytes, custom metadata, base URLs or exception text are emitted. IDs increase within a process session. All retained events after the cursor are returned chronologically; `next_cursor` is the last returned ID, or the unchanged valid cursor. An ahead-of-stream cursor returns retained history. Eviction or a cursor reset can set `truncated`. A changed stream ID replaces old history; the browser refetches from zero to avoid a cross-session gap.

The journal is thread-safe, bounded to 512 events and process-local. It resets on controller restart, is not a persistent audit log and observes only helper/transfer calls in the serving controller process. Another process directly editing SQLite cannot publish into it. Concurrent mutations publish after committing; events may interleave relative to commit order. **Overview and current manifests are authoritative for current state.** Timeline order represents publication observations.

Kinds: `transfer_started`, `transfer_completed`, `transfer_failed`, `object_ready`, `object_deleted`, `metadata_updated`, `worker_state`, `replica_state`, `repair_started`, `repair_completed`, `repair_failed`.

- Each worker attempt/retry gets a distinct transfer ID. A write completes only with the expected worker acknowledgement; a read completes only after expected size/hash verification. Completion describes worker bytes, not browser save or final object publication. Cancellation/partial-body/network failures terminate the attempt as unsuccessful.
- Worker/replica/object state observations publish only after successful DB commits. Unchanged worker state and heartbeat refreshes do not flood the journal. A replica record removed explicitly has null state; an object cascade deletion is represented by object_deleted, not per-copy physical deletion claims. Abandoned upload cleanup does not masquerade as a user deletion.
- Telemetry publication is best effort and cannot determine storage success. Existing DB helper signatures remain unchanged.

## Integration for Member B

Recovery remains B-owned. Calls to existing worker/replica DB helpers in the controller process automatically produce recorded state changes. For detailed phases, B may call the existing optional observation function from its controller recovery loop:

```python
from controller.telemetry import record_event

record_event("repair_started", object_id=object_id, chunk_id=chunk_id,
             worker_id=target_worker_id, detail="Copying from a verified replica")
# Emit only after the actual operation and verification have succeeded:
record_event("repair_completed", object_id=object_id, chunk_id=chunk_id,
             worker_id=target_worker_id, detail="Replacement copy verified")
```

Use repair_failed when appropriate and fixed, nonsensitive descriptions. If the actual operation transfers bytes between the controller and that worker, include the real `direction="to_worker"` or `direction="from_worker"` (and optional size); that repair observation can then light its wire and completed transfers can be replayed. Do not invent a controller transfer direction for a worker-to-worker operation. Events without direction remain visible as recovery observations without synthetic motion. Do not emit success before hash/size validation, invent history, or use this hook to promote workers. This optional telemetry API does not substitute for object locks, inventory reconciliation, repair policy, tests or actual recovery. Worker-to-worker links are not claimed by this map.

## Verification and references

Commands are in [FRONTEND.md](FRONTEND.md) and [ACCEPTANCE.md](ACCEPTANCE.md). `python tests/test_end_to_end.py --large --browser` checks actual placement/highlights, acknowledged/verified transfer observations and replay as well as upload/download/metadata/delete and B's production recovery. The older `live_controller_check.py` is historical pre-recovery evidence. QA captures remain separate from runtime data; the README screenshot is an explicitly published real dashboard capture. Read [HANDOFF.md](HANDOFF.md) for dated verification and publication details.

Primary references: [W3C complex diagrams](https://www.w3.org/WAI/tutorials/images/complex/) for text equivalents, [W3C pause/stop/hide](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html) for update controls, and [MDN abort composition](https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/any_static) / [timeouts](https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static) for bounded cancellable polling. CSS/SVG line geometry keeps this fixed topology dependency-free.
