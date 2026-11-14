import { Boxes, Database, Server } from "lucide-react";
import { bytes, seenAgo } from "../format";
import { eventLabel, timeLabel } from "../system";
import type { ActivityEvent, Overview } from "../types";
import { NodeStatus } from "./ClusterPanel";

export function TopologyMap({
  overview,
  stale,
  paused,
  events,
  selectedWorker,
  onSelectWorker,
  replay,
  highlights,
}: {
  overview: Overview | null;
  stale: boolean;
  paused: boolean;
  events: ActivityEvent[];
  selectedWorker: string;
  onSelectWorker: (id: string) => void;
  replay: ActivityEvent | null;
  highlights: string[] | null;
}) {
  const nodes = overview?.workers ?? [];
  const height = Math.max(360, nodes.length * 85 + 20);
  const latest = new Map<string, ActivityEvent>();
  for (const event of events)
    if (
      event.worker_id &&
      event.direction &&
      (event.kind.startsWith("transfer_") || event.kind.startsWith("repair_"))
    )
      latest.set(event.worker_id, event);
  const selected = nodes.find((node) => node.worker_id === selectedWorker);
  return (
    <section
      className="system-section topology-section"
      aria-labelledby="topology-heading"
    >
      <div className="system-section-heading">
        <div>
          <h2 id="topology-heading">The path of your data</h2>
          <p>
            One controller. Separate storage nodes. Every copy has a
            destination.
          </p>
        </div>
        <span className={`system-live-label ${stale ? "system-warning" : ""}`}>
          <i className={`status-dot ${paused || stale ? "amber" : "green"}`} />
          {paused
            ? "Paused snapshot"
            : stale
              ? "Snapshot unavailable"
              : "Observed connections"}
        </span>
      </div>
      <div
        className={`topology-board ${paused ? "motion-paused" : ""} ${stale ? "topology-stale" : ""}`}
        style={{ aspectRatio: `1000 / ${height}` }}
        aria-label="Controller and registered storage workers"
      >
        <svg
          className="topology-wires"
          viewBox={`0 0 1000 ${height}`}
          aria-hidden="true"
        >
          {nodes.map((node, index) => {
            const y = 20 + index * 85 + 32;
            const path = `M 280 ${height / 2} C 460 ${height / 2}, 490 ${y}, 690 ${y}`;
            const isReplay = replay?.worker_id === node.worker_id;
            const event = isReplay ? replay : latest.get(node.worker_id);
            const highlighted = highlights?.includes(node.worker_id);
            const tone = isReplay
              ? "replay"
              : stale
                ? "unknown"
                : event?.kind.endsWith("failed")
                  ? "failed"
                  : highlighted || event
                    ? "observed"
                    : node.available
                      ? "ready"
                      : "waiting";
            return (
              <g
                key={node.worker_id}
                className={`wire-group wire-${tone}`}
                data-wire-worker={node.worker_id}
              >
                <path d={path} className="wire-base" />
                {(!stale || isReplay) &&
                  event &&
                  !event.kind.endsWith("failed") && (
                    <path
                      key={`${event.id}-${isReplay ? "replay" : "live"}`}
                      d={path}
                      className={`wire-packet ${event.direction === "from_worker" ? "wire-return" : ""}`}
                    />
                  )}
                <circle cx="690" cy={y} r="3" className="wire-port" />
              </g>
            );
          })}
        </svg>
        <div
          className="topology-controller topology-node"
          style={{ left: "5%", top: `${((height / 2 - 50) / height) * 100}%` }}
        >
          <Boxes size={27} strokeWidth={1.5} />
          <div>
            <strong>Controller</strong>
            <span>
              <Database size={12} /> Metadata &amp; integrity
            </span>
          </div>
          <small>
            {stale
              ? "Connection unknown"
              : `${overview?.available_workers ?? 0} nodes available`}
          </small>
        </div>
        {nodes.map((node, index) => (
          <button
            key={node.worker_id}
            className={`topology-worker topology-node ${selectedWorker === node.worker_id ? "selected" : ""} ${highlights?.includes(node.worker_id) ? "holds-copy" : ""}`}
            style={{
              left: "69%",
              top: `${((20 + index * 85) / height) * 100}%`,
            }}
            onClick={() =>
              onSelectWorker(
                selectedWorker === node.worker_id ? "" : node.worker_id,
              )
            }
            aria-pressed={selectedWorker === node.worker_id}
            aria-label={`Inspect ${node.worker_id}`}
          >
            <Server size={21} strokeWidth={1.5} />
            <div>
              <strong>{node.worker_id}</strong>
              <span>
                {node.chunk_count} copies · {bytes(node.stored_bytes)}
              </span>
            </div>
            <NodeStatus worker={node} stale={stale} />
          </button>
        ))}
        {nodes.length === 0 && (
          <p className="topology-empty">
            {overview
              ? "Waiting for workers to register"
              : "Loading the cluster…"}
          </p>
        )}
      </div>
      <div className="topology-caption">
        <span>
          {replay
            ? `Replay of observed event · ${timeLabel(replay.timestamp)} · ${eventLabel(replay)}`
            : highlights
              ? "Highlighted connections hold recorded copies of the selected chunk."
              : "Lines show configured connections. Moving marks show recent controller-observed transfers."}
        </span>
        {selectedWorker && (
          <button className="text-button" onClick={() => onSelectWorker("")}>
            Show all nodes
          </button>
        )}
      </div>
      {selected && (
        <dl
          className="node-inspection"
          aria-label={`${selected.worker_id} details`}
        >
          <div>
            <dt>Selected node</dt>
            <dd>{selected.worker_id}</dd>
          </div>
          <div>
            <dt>Heartbeat at snapshot</dt>
            <dd>
              {stale ? "Unknown" : seenAgo(selected.heartbeat_age_seconds)}
            </dd>
          </div>
          <div>
            <dt>Recorded copies</dt>
            <dd>{selected.chunk_count}</dd>
          </div>
          <div>
            <dt>Recorded copy bytes</dt>
            <dd>{bytes(selected.stored_bytes)}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
