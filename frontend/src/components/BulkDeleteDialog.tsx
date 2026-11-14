import { useState } from "react";
import { ApiError, request } from "../api";
import { backendOrigin } from "../connection";
import { errorMessage } from "../format";
import type { StoredObject } from "../types";
import { Dialog } from "./Dialog";

type Result = {
  id: string;
  name: string;
  state:
    | "Removed"
    | "Already absent"
    | "Rejected"
    | "Outcome unknown"
    | "Not attempted";
  detail?: string;
};

export function BulkDeleteDialog({
  files,
  stale,
  onClose,
  onFinished,
}: {
  files: StoredObject[];
  stale: boolean;
  onClose: () => void;
  onFinished: (removed: string[]) => Promise<void>;
}) {
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[] | null>(null);
  async function remove() {
    if (stale || busy || confirmation !== "DELETE" || results) return;
    setBusy(true);
    const origin = backendOrigin();
    const current: Result[] = files.map((file) => ({
      id: file.object_id,
      name: file.name,
      state: "Not attempted",
    }));
    const removed: string[] = [];
    for (let index = 0; index < files.length; index++) {
      if (backendOrigin() !== origin) break;
      let stop = false;
      try {
        await request(
          `/api/v1/objects/${encodeURIComponent(files[index].object_id)}`,
          { method: "DELETE", signal: AbortSignal.timeout(15_000) },
        );
        current[index] = { ...current[index], state: "Removed" };
        removed.push(files[index].object_id);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          current[index] = { ...current[index], state: "Already absent" };
          removed.push(files[index].object_id);
        } else {
          const known =
            error instanceof ApiError &&
            error.status !== null &&
            error.status >= 400 &&
            error.status < 500 &&
            error.status !== 408;
          current[index] = {
            ...current[index],
            state: known ? "Rejected" : "Outcome unknown",
            detail: errorMessage(error),
          };
          stop =
            !known ||
            (error instanceof ApiError &&
              [401, 403].includes(error.status ?? 0));
        }
      }
      setResults([...current]);
      if (stop) break;
    }
    setResults([...current]);
    try {
      await onFinished(removed);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="Delete selected files"
      alert
      className="worker-dialog bulk-dialog"
      closeDisabled={busy}
      onClose={onClose}
    >
      <h2>Delete selected files</h2>
      <p>
        {files.length} files. Logical removal is permanent. Offline copies are
        cleaned when the recovery service reconciles them.
      </p>
      {results ? (
        <>
          <p role="status">
            {busy
              ? "Deleting one file at a time…"
              : "Batch finished. Review each result below."}
          </p>
          <p className="worker-origin">
            An unknown outcome may already be removed. The file list is
            refreshed; check it before retrying. Later files are left
            unattempted after a connection failure.
          </p>
          <ul className="batch-results">
            {results.map((result) => (
              <li key={result.id}>
                <span>{result.name}</span>
                <strong>{result.state}</strong>
                {result.detail && <small>{result.detail}</small>}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <ul className="batch-results">
            {files.map((file) => (
              <li key={file.object_id}>{file.name}</li>
            ))}
          </ul>
          <label htmlFor="batch-confirm">Type DELETE to confirm</label>
          <input
            id="batch-confirm"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="off"
          />
          {stale && (
            <p role="alert">Refresh your connection before deleting files.</p>
          )}
        </>
      )}
      <div className="dialog-actions">
        {results ? (
          <button
            className="button secondary"
            disabled={busy}
            onClick={onClose}
          >
            Done
          </button>
        ) : (
          <>
            <button
              className="button secondary"
              disabled={busy}
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              className="button danger"
              disabled={busy || stale || confirmation !== "DELETE"}
              onClick={() => void remove()}
            >
              {busy ? "Deleting…" : `Delete ${files.length} files`}
            </button>
          </>
        )}
      </div>
    </Dialog>
  );
}
