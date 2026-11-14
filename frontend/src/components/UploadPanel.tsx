import { useEffect, useId, useRef, useState } from "react";
import {
  ArrowUp,
  Check,
  ChevronDown,
  FilePlus2,
  RotateCcw,
  Upload,
  X,
} from "lucide-react";
import { uploadFile } from "../api";
import { bytes, errorMessage, parseMetadata } from "../format";
import type { Notify } from "../types";

type UploadItem = {
  id: string;
  file: File;
  phase:
    "queued" | "sending" | "confirming" | "stored" | "failed" | "cancelled";
  percent: number;
  error?: string;
};

export function UploadPanel({
  availableWorkers,
  onUploaded,
  notify,
}: {
  availableWorkers: number;
  onUploaded: () => Promise<void>;
  notify: Notify;
}) {
  const [items, setItems] = useState<UploadItem[]>([]),
    [dragging, setDragging] = useState(false),
    [running, setRunning] = useState(false);
  const [metadata, setMetadata] = useState("{}"),
    [metadataError, setMetadataError] = useState("");
  const input = useRef<HTMLInputElement>(null),
    controllers = useRef(new Map<string, AbortController>()),
    labelId = useId();
  useEffect(() => {
    const active = controllers.current;
    return () => active.forEach((controller) => controller.abort());
  }, []);
  const addFiles = (files: File[]) => {
    setItems((current) => [
      ...current,
      ...files.map((file) => ({
        id: crypto.randomUUID(),
        file,
        phase: "queued" as const,
        percent: 0,
      })),
    ]);
  };
  const update = (id: string, patch: Partial<UploadItem>) =>
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  const queued = items.filter((item) => item.phase === "queued");
  const storageBlocked =
    availableWorkers < 2 && queued.some((item) => item.file.size > 0);
  async function start() {
    let custom;
    try {
      custom = parseMetadata(metadata);
      setMetadataError("");
    } catch (error) {
      setMetadataError(errorMessage(error));
      return;
    }
    setRunning(true);
    let stored = 0;
    for (const item of queued)
      controllers.current.set(item.id, new AbortController());
    for (const item of queued) {
      const controller = controllers.current.get(item.id)!;
      if (controller.signal.aborted) {
        controllers.current.delete(item.id);
        continue;
      }
      update(item.id, { phase: "sending", percent: 0, error: undefined });
      try {
        await uploadFile(item.file, custom, controller.signal, (percent) =>
          update(item.id, {
            percent,
            phase: percent === 100 ? "confirming" : "sending",
          }),
        );
        update(item.id, { phase: "stored", percent: 100 });
        stored++;
        await onUploaded();
      } catch (error) {
        const cancelled =
          error instanceof DOMException && error.name === "AbortError";
        update(item.id, {
          phase: cancelled ? "cancelled" : "failed",
          error: cancelled
            ? "Cancelled locally. Refresh before retrying; storage may have completed."
            : errorMessage(error),
        });
      } finally {
        controllers.current.delete(item.id);
      }
    }
    setRunning(false);
    if (stored)
      notify(
        `${stored === 1 ? "1 file" : `${stored} files`} added to your storage`,
        "success",
      );
  }
  return (
    <section
      className={`upload-panel ${dragging ? "dragging" : ""}`}
      aria-label="Upload files"
    >
      <input
        className="sr-only"
        ref={input}
        type="file"
        multiple
        tabIndex={-1}
        aria-label="Choose files to upload"
        onChange={(event) => {
          addFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      <div
        className="drop-zone"
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node))
            setDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(Array.from(event.dataTransfer.files));
        }}
      >
        <span className="upload-symbol">
          <Upload size={26} strokeWidth={1.5} />
        </span>
        <div className="drop-copy">
          <h2>
            {dragging ? "Let go to add your files" : "A place for every file"}
          </h2>
          <p>
            Drag files here, or{" "}
            <button
              className="text-button"
              onClick={() => input.current?.click()}
            >
              browse your device
            </button>
          </p>
          <span>Any file type. Your original bytes, preserved.</span>
        </div>
        <button
          className="button secondary choose-button"
          onClick={() => input.current?.click()}
        >
          <FilePlus2 size={17} />
          Choose files
        </button>
      </div>
      {!!items.length && (
        <div className="upload-composer">
          <div className="queue-heading">
            <h3>
              Upload queue <span className="count">{items.length}</span>
            </h3>
            {items.some((item) =>
              ["stored", "failed", "cancelled"].includes(item.phase),
            ) && (
              <button
                className="text-button muted"
                onClick={() =>
                  setItems((current) =>
                    current.filter((item) =>
                      ["queued", "sending", "confirming"].includes(item.phase),
                    ),
                  )
                }
              >
                Clear finished
              </button>
            )}
          </div>
          <ul className="upload-list">
            {items.map((item) => (
              <li className={`upload-item ${item.phase}`} key={item.id}>
                <span className="queue-icon">
                  {item.phase === "stored" ? (
                    <Check size={18} />
                  ) : (
                    <ArrowUp size={18} />
                  )}
                </span>
                <div className="upload-item-main">
                  <div>
                    <strong title={item.file.name}>{item.file.name}</strong>
                    <span>{bytes(item.file.size)}</span>
                  </div>
                  {["sending", "confirming"].includes(item.phase) && (
                    <progress
                      max={100}
                      value={item.percent}
                      aria-label={`Upload progress for ${item.file.name}`}
                    />
                  )}
                  <p className={item.error ? "error-text" : ""}>
                    {item.phase === "stored"
                      ? "Stored"
                      : item.phase === "confirming"
                        ? "Confirming replicas…"
                        : item.phase === "sending"
                          ? `Sending… ${item.percent}%`
                          : (item.error ?? "Ready to upload")}
                  </p>
                </div>
                {["sending", "confirming"].includes(item.phase) ? (
                  <button
                    className="icon-button"
                    aria-label={`Cancel upload of ${item.file.name}`}
                    onClick={() => controllers.current.get(item.id)?.abort()}
                  >
                    <X size={16} />
                  </button>
                ) : ["failed", "cancelled"].includes(item.phase) ? (
                  <button
                    className="icon-button"
                    aria-label={`Requeue ${item.file.name}`}
                    title="Requeue file"
                    onClick={() =>
                      update(item.id, {
                        phase: "queued",
                        percent: 0,
                        error: undefined,
                      })
                    }
                  >
                    <RotateCcw size={16} />
                  </button>
                ) : item.phase === "queued" ? (
                  <button
                    className="icon-button"
                    aria-label={`Remove ${item.file.name} from queue`}
                    onClick={() => {
                      controllers.current.get(item.id)?.abort();
                      setItems((current) =>
                        current.filter((row) => row.id !== item.id),
                      );
                    }}
                  >
                    <X size={16} />
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          <details className="upload-metadata">
            <summary>
              Custom metadata <span>optional</span>
              <ChevronDown size={15} />
            </summary>
            <label htmlFor={labelId}>Metadata for queued files (JSON)</label>
            <textarea
              id={labelId}
              value={metadata}
              onChange={(event) => {
                setMetadata(event.target.value);
                setMetadataError("");
              }}
              spellCheck={false}
              disabled={running}
              rows={3}
              aria-invalid={!!metadataError}
            />
            <p>
              Applied to each file in this upload. Example:{" "}
              {'{"project": "Cloud computing"}'}
            </p>
            {metadataError && (
              <p role="alert" className="error-text">
                {metadataError}
              </p>
            )}
          </details>
          <div className="upload-footer">
            <p>
              {storageBlocked
                ? "At least 2 available nodes are needed to store these files."
                : "Files appear only after storage is confirmed."}
            </p>
            <button
              className="button primary"
              disabled={running || !queued.length || storageBlocked}
              onClick={() => void start()}
            >
              <Upload size={16} />
              {running
                ? "Uploading…"
                : `Upload ${queued.length} ${queued.length === 1 ? "file" : "files"}`}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
