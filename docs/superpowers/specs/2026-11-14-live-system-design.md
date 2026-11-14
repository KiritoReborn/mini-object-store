# Live system explorer

User request: finish Member A's side and add visual controller/worker wiring, data movement, worker graphs and recovery visibility. The user delegated feature and implementation decisions. This extends the existing Operate surface and its green/mineral visual system.

## Approach

Use the existing React app, SVG geometry, CSS motion and same-origin controller APIs. A graph library would add unnecessary layout/runtime weight for this fixed one-controller/four-worker topology. Snapshot-only animation cannot distinguish traffic from an idle connection, so add a bounded, process-local controller event journal alongside actual metadata snapshots.

## Deliverables

- Cluster map: controller connected to registered workers, selectable nodes, explicit available/joining/offline/unknown states. Animate observed recent transfers only; completed events are labeled recent, never in flight. Pause freezes this surface; reduced motion disables travel. No Docker control actions.
- Object placement: choose a READY file, show chunk rows across worker columns and inspect the file. Fetch real manifest; cancel obsolete requests and preserve useful errors. Paginate large manifests.
- Distribution chart: recorded healthy copy bytes per worker, text alternatives and values; not disk capacity or throughput.
- Activity: bounded recent controller events with timestamps, worker/object filters, object inspection and JSON export. Explain eviction, restart and session scope. No custom metadata content, file bytes or base URLs in events.
- Recovery: actual available copies, under-replicated chunks, corrupt copies and observed replica transitions. Missing recovery is explicit. A helper-boundary state change proves the recorded change, not an autonomous repair algorithm. B can emit explicit repair lifecycle events using the documented optional event function.
- Support export: versioned JSON diagnostic snapshot, including capture times and stale/error status. No secrets or invented history. Document setup and integration.

## Event API

`GET /api/v1/activity?after=0` returns `{stream_id, oldest_id, latest_id, next_cursor, truncated, events}`. One controller process; thread-safe journal retains 512 events, resets on process restart. All retained events after the cursor are returned in chronological order; cursor ahead of stream returns retained events with truncated=true. Each event has `id`, `timestamp`, `kind`, nullable `object_id`, `chunk_id`, `worker_id`, `transfer_id`, `direction`, `size`, `state`, `previous_state`, `name`, `detail`. Kinds: transfer_started/completed/failed, object_ready/deleted/metadata_updated, worker_state, replica_state, repair_started/completed/failed. Directions: to_worker/from_worker. Transfer completion means acknowledged/verified worker bytes, not browser delivery. Publication cannot influence storage success, cancellation, or transaction semantics.

## Validation and limits

Test bounded/concurrent journal, cursor gaps/restart, observed transfers/corruption and committed state changes. Browser tests cover map selection, placement, activity filters, pause, stale/failed streams, diagnostic export, reduced motion, accessibility and narrow screens. Run complete Linux backend tests, frontend unit/build/browser checks and disposable real-worker checks. Do not change B's files or falsely qualify normal JOINING workers. Recovery remains B-owned. No persistent audit log, wire-level bandwidth measurement, or worker-to-worker transfers are claimed.

References: [W3C complex diagrams](https://www.w3.org/WAI/tutorials/images/complex/), [pause/stop/hide](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html), [MDN motion paths](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/offset-path). They inform text equivalents, pause controls and motion; project facts come from the controller.
