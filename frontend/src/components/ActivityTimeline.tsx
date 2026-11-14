import { useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  Play,
  Search,
} from "lucide-react";
import { bytes } from "../format";
import { eventLabel, timeLabel, type ActivityHistory } from "../system";
import type { ActivityEvent, StoredObject, Worker } from "../types";

export function ActivityTimeline({
  history,
  error,
  paused,
  workers,
  workerId,
  onWorkerChange,
  objectId,
  objects,
  onReplay,
  onInspect,
  onRetry,
}: {
  history: ActivityHistory | null;
  error: string | null;
  paused: boolean;
  workers: Worker[];
  workerId: string;
  onWorkerChange: (id: string) => void;
  objectId: string;
  objects: StoredObject[];
  onReplay: (event: ActivityEvent) => void;
  onInspect: (object: StoredObject) => void;
  onRetry: () => void;
}) {
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(12);
  const events = [...(history?.events ?? [])].reverse().filter((event) => {
    const object = objects.find(
      (object) => object.object_id === event.object_id,
    );
    return (
      (!workerId || event.worker_id === workerId) &&
      (!objectId || event.object_id === objectId) &&
      (category === "all" ||
        (category === "transfers"
          ? event.kind.startsWith("transfer_")
          : category === "recovery"
            ? event.kind.startsWith("repair_") || event.kind === "replica_state"
            : !event.kind.startsWith("transfer_"))) &&
      `${eventLabel(event)} ${event.name ?? object?.name ?? ""} ${event.worker_id ?? ""} ${event.chunk_id ?? ""} ${event.detail ?? ""}`
        .toLowerCase()
        .includes(search.toLowerCase().trim())
    );
  });
  return (
    <section
      className="system-section activity-section"
      aria-labelledby="activity-heading"
    >
      <div className="system-section-heading">
        <div>
          <h2 id="activity-heading">
            <Activity size={18} /> Recent activity
          </h2>
          <p>
            Controller observations in this process session. Up to 512 events;
            not a permanent audit log.
          </p>
        </div>
        <span className="system-count">
          {history?.events.length ?? 0} retained
        </span>
      </div>
      {history?.notice && (
        <p className="system-history-notice" role="status">
          {history.notice}
        </p>
      )}
      {error && (
        <div className="system-inline-error" role="alert">
          <p>
            Activity is unavailable. {error} Retained events are historical.
          </p>
          <button className="text-button" onClick={onRetry} disabled={paused}>
            Retry activity
          </button>
        </div>
      )}
      <div className="activity-controls">
        <label className="activity-search">
          <Search size={15} />
          <input
            aria-label="Search activity"
            placeholder="Find a file, chunk or event…"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setLimit(12);
            }}
          />
        </label>
        <select
          aria-label="Activity type"
          value={category}
          onChange={(event) => {
            setCategory(event.target.value);
            setLimit(12);
          }}
        >
          <option value="all">All activity</option>
          <option value="transfers">Transfers</option>
          <option value="recovery">Replicas &amp; recovery</option>
          <option value="changes">State &amp; file changes</option>
        </select>
        <select
          aria-label="Activity worker"
          value={workerId}
          onChange={(event) => onWorkerChange(event.target.value)}
        >
          <option value="">All nodes</option>
          {workers.map((worker) => (
            <option key={worker.worker_id} value={worker.worker_id}>
              {worker.worker_id}
            </option>
          ))}
        </select>
      </div>
      {objectId && (
        <p className="activity-scope">
          Filtered to the selected file. Choose “All files” above to see
          cluster-wide activity.
        </p>
      )}
      {events.length === 0 ? (
        <div className="system-empty">
          <Activity size={24} />
          <p>
            {!history && !error
              ? "Connecting to controller activity…"
              : history?.events.length
                ? "No events match these filters."
                : "No activity recorded yet. Upload, download or node state changes will appear here."}
          </p>
        </div>
      ) : (
        <ol className="activity-list">
          {events.slice(0, limit).map((event) => {
            const object = objects.find(
              (object) => object.object_id === event.object_id,
            );
            const bad =
              event.kind.endsWith("failed") ||
              ["CORRUPT", "MISSING", "DEAD"].includes(event.state ?? "");
            return (
              <li
                key={`${history?.stream_id}-${event.id}`}
                className={bad ? "event-attention" : ""}
              >
                <span className="event-symbol">
                  {event.direction === "to_worker" ? (
                    <ArrowUpFromLine size={16} />
                  ) : event.direction === "from_worker" ? (
                    <ArrowDownToLine size={16} />
                  ) : (
                    <Activity size={16} />
                  )}
                </span>
                <div className="event-content">
                  <strong>
                    {eventLabel(event)}
                    {event.worker_id && <span> · {event.worker_id}</span>}
                  </strong>
                  <p>
                    {event.name ??
                      object?.name ??
                      (event.object_id
                        ? `Object ${event.object_id.slice(0, 8)}`
                        : "Cluster")}
                    {event.chunk_id &&
                      ` · Chunk ${Number(event.chunk_id.split("_").at(-1)) + 1}`}
                    {event.size !== null && ` · ${bytes(event.size)}`}
                  </p>
                  {event.state && (
                    <small>
                      {event.previous_state ? `${event.previous_state} → ` : ""}
                      {event.state}
                    </small>
                  )}
                  {event.detail && <small>{event.detail}</small>}
                </div>
                <div className="event-actions">
                  <time dateTime={event.timestamp} title={event.timestamp}>
                    {timeLabel(event.timestamp)}
                  </time>
                  <div>
                    {object && (
                      <button
                        className="text-button"
                        onClick={() => onInspect(object)}
                        aria-label={`Inspect file for event ${event.id}`}
                      >
                        Inspect
                      </button>
                    )}
                    {["transfer_completed", "repair_completed"].includes(
                      event.kind,
                    ) &&
                      event.direction &&
                      event.worker_id && (
                        <button
                          className="icon-button small"
                          disabled={paused}
                          aria-label={`Replay ${event.kind === "repair_completed" ? "repair" : "transfer"} ${event.id}`}
                          title="Replay this observed transfer"
                          onClick={() => onReplay(event)}
                        >
                          <Play size={14} />
                        </button>
                      )}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {events.length > limit && (
        <button
          className="button secondary activity-more"
          onClick={() => setLimit((value) => value + 24)}
        >
          Show more events ({events.length - limit})
        </button>
      )}
      <p className="system-footnote">
        Acknowledged copies and verified reads describe worker transfers. They
        do not confirm that a browser saved a file. Short transfers remain
        available for labeled replay.
      </p>
    </section>
  );
}
