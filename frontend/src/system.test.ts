import { describe, expect, it } from "vitest";
import {
  eventLabel,
  mergeActivity,
  replicaLabel,
  quietActivity,
} from "./system";
import type { ActivityBatch, ActivityEvent } from "./types";

const event = (id: number, kind = "transfer_completed"): ActivityEvent => ({
  id,
  kind,
  timestamp: "2026-11-14T09:00:00Z",
  worker_id: "worker1",
  direction: "to_worker",
  size: 100,
  state: null,
  previous_state: null,
  object_id: "file",
  chunk_id: "file_0",
  transfer_id: "tx",
  name: null,
  detail: null,
});
const batch = (
  stream_id: string,
  events: ActivityEvent[],
  truncated = false,
): ActivityBatch => ({
  stream_id,
  events,
  truncated,
  oldest_id: 1,
  latest_id: events.at(-1)?.id ?? 0,
  next_cursor: events.at(-1)?.id ?? 0,
});

describe("recent activity observations", () => {
  it("condenses successful chunk traffic and omits routine bookkeeping without hiding failures", () => {
    const rows = quietActivity([
      event(1, "transfer_started"),
      event(2),
      event(3),
      event(4, "transfer_failed"),
      { ...event(5, "replica_state"), state: "HEALTHY" },
    ]);
    expect(rows.map((row) => row.id)).toEqual([3, 4]);
    expect(rows[0].group_count).toBe(2);
  });
  it("deduplicates polls and bounds history", () => {
    const initial = mergeActivity(null, batch("one", [event(1), event(2)]));
    const next = mergeActivity(initial, batch("one", [event(2), event(3)]));
    expect(next.events.map((e) => e.id)).toEqual([1, 2, 3]);
    const large = mergeActivity(
      next,
      batch(
        "one",
        Array.from({ length: 600 }, (_, i) => event(i + 4)),
      ),
    );
    expect(large.events).toHaveLength(512);
    expect(large.events[0].id).toBe(92);
  });
  it("replaces history on process restart and retains a visible gap notice", () => {
    const initial = mergeActivity(null, batch("one", [event(8)]));
    const reset = mergeActivity(initial, batch("two", [event(1)]));
    expect(reset.events.map((e) => e.id)).toEqual([1]);
    expect(reset.notice).toContain("restarted");
    expect(mergeActivity(reset, batch("two", [], true)).notice).toContain(
      "gap",
    );
  });
  it("distinguishes worker acknowledgement from browser delivery and state restoration from repair", () => {
    expect(eventLabel(event(1))).toBe("Copy acknowledged");
    expect(eventLabel({ ...event(2), direction: "from_worker" })).toBe(
      "Chunk verified",
    );
    expect(
      eventLabel({
        ...event(3, "replica_state"),
        previous_state: "CORRUPT",
        state: "HEALTHY",
      }),
    ).toBe("Replica restored");
    expect(eventLabel(event(4, "repair_started"))).toBe("Repair started");
    expect(replicaLabel("HEALTHY", false, false)).toBe("Node unavailable");
    expect(replicaLabel("HEALTHY", true, true)).toBe("Unknown");
    expect(replicaLabel("CORRUPT", true, false)).toBe("Corrupt");
  });
});
