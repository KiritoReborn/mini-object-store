import { GitBranch, ShieldCheck } from "lucide-react";
import { bytes } from "../format";
import { eventLabel, timeLabel } from "../system";
import type { ActivityEvent, Overview } from "../types";

export function RecoveryPanel({
  overview,
  stale,
  events,
}: {
  overview: Overview | null;
  stale: boolean;
  events: ActivityEvent[];
}) {
  const problem =
    (overview?.under_replicated_chunks ?? 0) > 0 ||
    (overview?.corrupt_replicas ?? 0) > 0;
  const recent = events
    .filter(
      (event) =>
        event.kind.startsWith("repair_") ||
        (event.kind === "replica_state" &&
          (["CORRUPT", "MISSING"].includes(event.state ?? "") ||
            ["CORRUPT", "MISSING"].includes(event.previous_state ?? ""))),
    )
    .slice(-5)
    .reverse();
  const target =
    (overview?.chunk_count ?? 0) * (overview?.replication_factor ?? 2);
  return (
    <section
      className="system-section recovery-section"
      aria-labelledby="recovery-heading"
    >
      <div className="system-section-heading">
        <div>
          <h2 id="recovery-heading">
            <ShieldCheck size={18} /> Recovery &amp; integrity
          </h2>
          <p>Detection, reconciliation and confirmed replica state.</p>
        </div>
      </div>
      <div
        className={`recovery-status ${stale || !overview ? "unknown" : !overview.recovery_available || problem ? "waiting" : "healthy"}`}
      >
        <GitBranch size={22} />
        <div>
          <strong>
            {stale
              ? "Recovery status unknown"
              : !overview
                ? "Checking recovery"
                : !overview.recovery_available
                  ? "Recovery service unavailable"
                  : problem
                    ? "Replicas need attention"
                    : "No under-replication observed"}
          </strong>
          <p>
            {stale
              ? "Reconnect before drawing conclusions from this snapshot."
              : !overview?.recovery_available
                ? "Automatic rejoin and repair depend on the recovery service. This view does not run or simulate repairs."
                : problem
                  ? "The service is connected. Repair progress requires its events or confirmed replica changes; a connected service alone does not prove repair."
                  : "Current metadata meets the available-copy target. This is an observation, not a background scrub guarantee."}
          </p>
        </div>
      </div>
      <ol className="recovery-stages">
        <li>
          <span>Detect</span>
          <strong>
            {stale || !overview
              ? "Unknown"
              : `${overview.under_replicated_chunks} under-replicated chunks`}
          </strong>
          <small>
            {stale || !overview
              ? "Unavailable"
              : `${overview.corrupt_replicas} corrupt replica records`}
          </small>
        </li>
        <li>
          <span>Reconcile</span>
          <strong>
            {stale || !overview
              ? "Unknown"
              : overview.recovery_available
                ? "Service connected"
                : "Service required"}
          </strong>
          <small>Verify inventory before availability</small>
        </li>
        <li>
          <span>Verify</span>
          <strong>
            {stale || !overview
              ? "Unknown"
              : `${overview.healthy_replica_count} available copies`}
          </strong>
          <small>
            {target
              ? `${target} copies targeted across ${overview?.chunk_count} chunks`
              : "No stored chunks to verify"}
          </small>
        </li>
      </ol>
      {recent.length > 0 && (
        <div className="recovery-observations">
          <h3>Observed changes</h3>
          {recent.map((event) => (
            <div key={event.id}>
              <span>
                {eventLabel(event)}
                <small>
                  {event.worker_id ?? "Recovery service"}
                  {event.chunk_id ? ` · ${event.chunk_id}` : ""}
                </small>
              </span>
              <time dateTime={event.timestamp}>
                {timeLabel(event.timestamp)}
              </time>
            </div>
          ))}
        </div>
      )}
      <p className="system-footnote">
        A restored replica is a recorded state change. Detailed repair steps
        appear when the recovery service emits them. No synthetic recovery
        animation is shown.
      </p>
    </section>
  );
}

export function DistributionChart({
  overview,
  stale,
  onSelect,
}: {
  overview: Overview | null;
  stale: boolean;
  onSelect: (id: string) => void;
}) {
  const workers = overview?.workers ?? [];
  const total = workers.reduce((sum, worker) => sum + worker.stored_bytes, 0);
  return (
    <section
      className="system-section distribution-section"
      aria-labelledby="distribution-heading"
    >
      <div className="system-section-heading">
        <div>
          <h2 id="distribution-heading">Storage distribution</h2>
          <p>
            {bytes(total)} recorded healthy copy bytes
            {stale ? " · Last known snapshot" : ""}
          </p>
        </div>
      </div>
      <div className="distribution-chart">
        {workers.map((worker) => {
          const share = total ? (worker.stored_bytes / total) * 100 : 0;
          return (
            <button
              key={worker.worker_id}
              className="distribution-row"
              onClick={() => onSelect(worker.worker_id)}
              aria-label={`${worker.worker_id}: ${bytes(worker.stored_bytes)}, ${Math.round(share)}% of recorded copy bytes`}
            >
              <span>{worker.worker_id}</span>
              <span className="distribution-track" aria-hidden="true">
                <i
                  style={{ width: `${share}%` }}
                  className={stale || !worker.available ? "unavailable" : ""}
                />
              </span>
              <strong>{bytes(worker.stored_bytes)}</strong>
              <small>{worker.chunk_count} copies</small>
            </button>
          );
        })}
      </div>
      {workers.length === 0 && (
        <p className="system-empty">Registered workers will appear here.</p>
      )}
      <p className="system-footnote">
        Bar lengths are shares of recorded copy bytes, including active uploads.
        They do not measure physical disk usage, free space or capacity.
      </p>
    </section>
  );
}
