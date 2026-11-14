import { useEffect, useState } from "react";
import { clearRequestLog, getRequestLog } from "../diagnostics";
import { saveJson, timeLabel } from "../system";

export function RequestDiagnostics() {
  const [entries, setEntries] = useState(getRequestLog);
  const [showSuccess, setShowSuccess] = useState(false);
  useEffect(() => {
    const update = () => setEntries(getRequestLog());
    window.addEventListener("artaud-request", update);
    return () => window.removeEventListener("artaud-request", update);
  }, []);
  const visible = entries.filter(
    (row) =>
      showSuccess ||
      row.outcome !== "HTTP response" ||
      (row.status ?? 0) >= 400,
  );
  return (
    <details className="request-diagnostics">
      <summary>Recent request diagnostics</summary>
      <p className="worker-origin">
        Last 60 requests in this page’s memory. Browser duration includes
        network, controller and response handling; it is not worker latency or
        throughput. Keys, headers, bodies, file names and object IDs are
        excluded.
      </p>
      <label>
        <input
          type="checkbox"
          checked={showSuccess}
          onChange={(event) => setShowSuccess(event.target.checked)}
        />
        Show successful requests
      </label>
      <ul className="request-log">
        {visible
          .slice()
          .reverse()
          .map((row) => (
            <li key={row.id}>
              <span>
                {row.method} · {row.endpoint}
              </span>
              <strong>
                {row.outcome === "HTTP response"
                  ? `HTTP ${row.status}`
                  : row.outcome}{" "}
                · {row.duration_ms} ms
              </strong>
              <time dateTime={row.started_at}>{timeLabel(row.started_at)}</time>
            </li>
          ))}
      </ul>
      {!visible.length && (
        <p className="worker-origin">
          {entries.length
            ? "No failed requests in the retained history."
            : "No requests recorded yet."}
        </p>
      )}
      <div className="dialog-actions">
        <button
          className="button secondary"
          disabled={!entries.length}
          onClick={() =>
            saveJson("artaud-request-diagnostics.json", {
              captured_at: new Date().toISOString(),
              scope: "bounded browser request observations, not an audit log",
              requests: entries,
            })
          }
        >
          Export request diagnostics
        </button>
        <button
          className="button secondary"
          disabled={!entries.length}
          onClick={clearRequestLog}
        >
          Clear history
        </button>
      </div>
    </details>
  );
}
