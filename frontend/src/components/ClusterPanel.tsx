import {
  ArrowUpRight,
  Check,
  CircleHelp,
  Layers3,
  Network,
  Server,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { bytes, seenAgo } from "../format";
import type { Overview, Worker } from "../types";

export function NodeStatus({
  worker,
  stale = false,
}: {
  worker: Worker;
  stale?: boolean;
}) {
  const text = stale
    ? "Unknown"
    : worker.available
      ? "Available"
      : worker.status === "JOINING"
        ? "Joining"
        : worker.status === "ALIVE"
          ? "Unreachable"
          : "Offline";
  return (
    <span
      className={`status-tag ${stale ? "neutral" : worker.available ? "success" : worker.status === "JOINING" ? "waiting" : "danger"}`}
    >
      <i />
      {text}
    </span>
  );
}

export function ClusterPanel({
  overview,
  onExpand,
  full = false,
  stale = false,
}: {
  overview: Overview | null;
  onExpand?: () => void;
  full?: boolean;
  stale?: boolean;
}) {
  const nodes = overview?.workers ?? [];
  return (
    <section
      className={`cluster-panel ${full ? "cluster-full" : ""}`}
      aria-labelledby={full ? "cluster-details-heading" : "cluster-heading"}
    >
      <div className="section-title">
        <h2 id={full ? "cluster-details-heading" : "cluster-heading"}>
          <Network size={17} />
          {full ? "Registered nodes" : "Your cluster"}
        </h2>
        {onExpand && (
          <button
            className="icon-button"
            aria-label="View cluster details"
            onClick={onExpand}
          >
            <ArrowUpRight size={17} />
          </button>
        )}
      </div>
      <div className="cluster-availability">
        <span>
          <i
            className={`status-dot ${!stale && overview?.available_workers === 4 ? "green" : "amber"}`}
          />
          {stale
            ? "Last known snapshot"
            : overview
              ? `${overview.available_workers} of 4 nodes available`
              : "Checking nodes…"}
        </span>
        <span className="muted">Local network</span>
      </div>
      <div className="node-list">
        {nodes.length ? (
          nodes.map((worker) => (
            <div key={worker.worker_id} className="node-row">
              <span
                className={`node-icon ${worker.available && !stale ? "" : "inactive"}`}
              >
                <Server size={18} strokeWidth={1.5} />
              </span>
              <div className="node-name">
                <strong>{worker.worker_id}</strong>
                <span>
                  {worker.chunk_count} recorded copies{" "}
                  <span className="separator-dot">·</span>{" "}
                  {bytes(worker.stored_bytes)}
                </span>
              </div>
              <div className="node-state">
                <NodeStatus worker={worker} stale={stale} />
                <span>
                  {stale
                    ? "Last observed"
                    : seenAgo(worker.heartbeat_age_seconds)}
                </span>
              </div>
            </div>
          ))
        ) : (
          <div className="nodes-empty">
            <Server size={24} />
            <p>No nodes have connected yet.</p>
            <span>They’ll appear here when they register.</span>
          </div>
        )}
      </div>
      {overview && (
        <>
          <div className="cluster-config">
            <span>
              <Layers3 size={16} />
              Chunk size<strong>{bytes(overview.chunk_size)}</strong>
            </span>
            <span>
              <ShieldCheck size={16} />
              Target replicas
              <strong>{overview.replication_factor} per chunk</strong>
            </span>
          </div>
          <div
            className={`replication-note ${stale ? "unknown" : overview.under_replicated_chunks ? "attention" : ""}`}
          >
            {stale ? (
              <CircleHelp size={17} />
            ) : overview.under_replicated_chunks ? (
              <TriangleAlert size={17} />
            ) : overview.chunk_count ? (
              <Check size={17} />
            ) : (
              <CircleHelp size={17} />
            )}
            <div>
              <strong>
                {stale
                  ? "Replica status unavailable"
                  : overview.under_replicated_chunks
                    ? `${overview.under_replicated_chunks} chunks need another copy`
                    : overview.chunk_count
                      ? "Replication target met"
                      : overview.available_workers < 2
                        ? "Waiting for storage nodes"
                        : "Ready for your first object"}
              </strong>
              <p>
                {stale
                  ? "Reconnect to check current replica coverage."
                  : overview.chunk_count
                    ? `${overview.healthy_replica_count} available copies across ${overview.chunk_count} chunks.`
                    : "Replica coverage appears after a file is stored."}
              </p>
            </div>
          </div>
          {full && (
            <div className="cluster-explanation">
              <h3>How your files stay intact</h3>
              <p>
                Files are split into ordered chunks. Each chunk is stored on two
                different nodes. Downloads are checked against the controller’s
                SHA-256 checksums before they reach you.
              </p>
              <p>
                Node availability uses both registration state and recent
                heartbeats. Stored sizes reflect recorded copies, not free disk
                capacity.
              </p>
              {!overview.recovery_available && (
                <p className="inline-warning">
                  The recovery service is not connected. Joining nodes will
                  remain unavailable until their inventories are checked.
                </p>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
