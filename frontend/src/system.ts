import type { ActivityBatch, ActivityEvent } from "./types";

export interface ActivityHistory {
  stream_id: string;
  cursor: number;
  events: ActivityEvent[];
  notice: string | null;
}

export function mergeActivity(
  previous: ActivityHistory | null,
  batch: ActivityBatch,
): ActivityHistory {
  const restarted = previous !== null && previous.stream_id !== batch.stream_id;
  const events = new Map(
    (restarted ? [] : (previous?.events ?? [])).map((e) => [e.id, e]),
  );
  for (const event of batch.events) events.set(event.id, event);
  return {
    stream_id: batch.stream_id,
    cursor: batch.next_cursor,
    events: [...events.values()].sort((a, b) => a.id - b.id).slice(-512),
    notice: restarted
      ? "Controller restarted. Activity now belongs to a new session."
      : batch.truncated
        ? "There is a gap in activity. Older events have left the controller’s recent history."
        : (previous?.notice ?? null),
  };
}

export function eventLabel(event: ActivityEvent): string {
  if (event.kind === "transfer_completed")
    return event.direction === "to_worker"
      ? "Copy acknowledged"
      : "Chunk verified";
  if (event.kind === "transfer_started")
    return event.direction === "to_worker" ? "Sending copy" : "Reading copy";
  if (event.kind === "transfer_failed") return "Copy transfer unsuccessful";
  if (event.kind === "replica_state") {
    if (
      event.state === "HEALTHY" &&
      ["CORRUPT", "MISSING"].includes(event.previous_state ?? "")
    )
      return "Replica restored";
    if (!event.state) return "Replica record removed";
    return `Replica ${event.state.toLowerCase().replaceAll("_", " ")}`;
  }
  return (
    (
      {
        object_ready: "File stored",
        object_deleted: "File deleted",
        metadata_updated: "Metadata updated",
        worker_state: "Node state changed",
        repair_started: "Repair started",
        repair_completed: "Repair completed",
        repair_failed: "Repair unsuccessful",
      } as Record<string, string>
    )[event.kind] ?? event.kind.replaceAll("_", " ")
  );
}

export function replicaLabel(
  state: string,
  available: boolean,
  stale: boolean,
): string {
  if (stale) return "Unknown";
  if (state === "HEALTHY") return available ? "Healthy" : "Node unavailable";
  return (
    (
      {
        CORRUPT: "Corrupt",
        MISSING: "Missing",
        PENDING_DELETE: "Cleanup pending",
      } as Record<string, string>
    )[state] ?? state
  );
}

export function saveJson(name: string, value: unknown): void {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function timeLabel(timestamp: string): string {
  const date = new Date(timestamp);
  return Number.isNaN(date.valueOf())
    ? "Unknown time"
    : date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}
