import { useEffect, useId, useState } from "react";
import {
  Check,
  Copy,
  Download,
  FileKey2,
  Layers3,
  LoaderCircle,
  Trash2,
  X,
} from "lucide-react";
import { request } from "../api";
import { bytes, dateLabel, errorMessage, parseMetadata } from "../format";
import type { Notify, ObjectDetails, Overview, StoredObject } from "../types";
import { Dialog } from "./Dialog";
import { FileIcon } from "./FileIcon";

const tabs = ["Details", "Metadata", "Chunks"] as const;
type Tab = (typeof tabs)[number];

export function ObjectInspector({
  object,
  overview,
  onClose,
  onDelete,
  onDownload,
  onUpdated,
}: {
  object: StoredObject;
  overview: Overview | null;
  onClose: () => void;
  onDelete: (object: StoredObject) => void;
  onDownload: (object: StoredObject, feedback?: Notify) => Promise<void>;
  onUpdated: () => Promise<void>;
}) {
  const [details, setDetails] = useState<ObjectDetails | null>(null),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0);
  const [tab, setTab] = useState<Tab>("Details"),
    [metadata, setMetadata] = useState(""),
    [saving, setSaving] = useState(false),
    [saveError, setSaveError] = useState(""),
    [downloading, setDownloading] = useState(false),
    [chunkLimit, setChunkLimit] = useState(20);
  const [metadataBase, setMetadataBase] = useState<Record<string, unknown>>({});
  const [feedback, setFeedback] = useState<{
    text: string;
    kind: string;
  } | null>(null);
  const notify: Notify = (text, kind = "info") => setFeedback({ text, kind });
  const id = useId();
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    request<ObjectDetails>(
      `/api/v1/objects/${encodeURIComponent(object.object_id)}/metadata`,
      { signal: controller.signal },
    )
      .then((data) => {
        setDetails(data);
        setMetadata(JSON.stringify(data.metadata, null, 2));
        setMetadataBase(data.metadata);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(errorMessage(error));
      });
    return () => controller.abort();
  }, [object.object_id, retry]);
  useEffect(() => {
    if (tab !== "Chunks") return;
    const controller = new AbortController();
    request<ObjectDetails>(
      `/api/v1/objects/${encodeURIComponent(object.object_id)}/metadata`,
      { signal: controller.signal },
    )
      .then(setDetails)
      .catch((error) => {
        if (!controller.signal.aborted)
          setFeedback({ text: errorMessage(error), kind: "error" });
      });
    return () => controller.abort();
  }, [object.object_id, overview, tab]);
  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      notify(`${label} copied`, "success");
    } catch {
      notify(
        "Clipboard access is unavailable. Select and copy the text instead.",
        "error",
      );
    }
  }
  async function save() {
    let custom;
    try {
      custom = parseMetadata(metadata);
    } catch (error) {
      setSaveError(errorMessage(error));
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      // PATCH merges top-level keys; do not resend stale, unedited values.
      const changes = Object.fromEntries(
        Object.entries(custom).filter(
          ([key, value]) =>
            JSON.stringify(value) !== JSON.stringify(metadataBase[key]),
        ),
      );
      const data = await request<ObjectDetails>(
        `/api/v1/objects/${encodeURIComponent(object.object_id)}/metadata`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ metadata: changes }),
        },
      );
      setDetails(data);
      setMetadata(JSON.stringify(data.metadata, null, 2));
      setMetadataBase(data.metadata);
      notify("Metadata updated", "success");
      await onUpdated();
    } catch (error) {
      setSaveError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }
  const healthyCopies = (
    replicas: ObjectDetails["chunks"][number]["replicas"],
  ) =>
    replicas.filter(
      (r) =>
        r.state === "HEALTHY" &&
        overview?.workers.some(
          (w) => w.worker_id === r.worker_id && w.available,
        ),
    ).length;
  return (
    <Dialog title={object.name} onClose={onClose} className="inspector">
      <header className="inspector-header">
        <FileIcon mime={object.content_type} large />
        <h2>{object.name}</h2>
        <p>
          {bytes(object.size)} <span>·</span> {object.content_type}
        </p>
      </header>
      <div
        className="inspector-tabs"
        role="tablist"
        aria-label="Object information"
      >
        {tabs.map((name, index) => (
          <button
            key={name}
            role="tab"
            id={`${id}-${name}`}
            aria-selected={tab === name}
            tabIndex={tab === name ? 0 : -1}
            aria-controls={`${id}-panel`}
            onClick={() => setTab(name)}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowRight"
                  ? (index + 1) % tabs.length
                  : event.key === "ArrowLeft"
                    ? (index + tabs.length - 1) % tabs.length
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? tabs.length - 1
                        : null;
              if (next !== null) {
                event.preventDefault();
                setTab(tabs[next]);
                event.currentTarget.parentElement
                  ?.querySelectorAll<HTMLButtonElement>("[role=tab]")
                  [next].focus();
              }
            }}
          >
            {name}
          </button>
        ))}
      </div>
      <div
        className="inspector-body"
        role="tabpanel"
        id={`${id}-panel`}
        aria-labelledby={`${id}-${tab}`}
      >
        {error ? (
          <div className="panel-error" role="alert">
            <p>{error}</p>
            <button
              className="button secondary"
              onClick={() => setRetry((n) => n + 1)}
            >
              Try again
            </button>
          </div>
        ) : !details ? (
          <div className="inspector-loading" role="status">
            <LoaderCircle size={20} className="spinning" />
            Loading object details…
          </div>
        ) : (
          <>
            {tab === "Details" && (
              <>
                <div className="detail-status">
                  <Check size={15} />
                  Ready
                  <span>
                    {details.num_chunks} ordered{" "}
                    {details.num_chunks === 1 ? "chunk" : "chunks"}
                  </span>
                </div>
                <dl className="properties">
                  <div>
                    <dt>File name</dt>
                    <dd>{details.name}</dd>
                  </div>
                  <div>
                    <dt>Size</dt>
                    <dd>
                      {bytes(details.size)}{" "}
                      <span className="muted">
                        ({details.size.toLocaleString()} bytes)
                      </span>
                    </dd>
                  </div>
                  <div>
                    <dt>Content type</dt>
                    <dd>{details.content_type}</dd>
                  </div>
                  <div>
                    <dt>Created</dt>
                    <dd title={details.created_at}>
                      {dateLabel(details.created_at)}
                    </dd>
                  </div>
                  <div>
                    <dt>Last modified</dt>
                    <dd title={details.updated_at}>
                      {dateLabel(details.updated_at)}
                    </dd>
                  </div>
                </dl>
                <div className="data-block">
                  <div>
                    <h3>Object ID</h3>
                    <button
                      className="icon-button"
                      aria-label="Copy object ID"
                      onClick={() => void copy(details.object_id, "Object ID")}
                    >
                      <Copy size={15} />
                    </button>
                  </div>
                  <code>{details.object_id}</code>
                </div>
                <div className="data-block">
                  <div>
                    <h3>SHA-256 checksum</h3>
                    <button
                      className="icon-button"
                      aria-label="Copy checksum"
                      onClick={() => void copy(details.sha256, "Checksum")}
                    >
                      <Copy size={15} />
                    </button>
                  </div>
                  <code>{details.sha256}</code>
                  <p>
                    <FileKey2 size={14} />
                    The complete file is verified against this checksum before
                    download.
                  </p>
                </div>
              </>
            )}
            {tab === "Metadata" && (
              <section className="metadata-editor">
                <h3>A little more context</h3>
                <p>
                  Add custom properties without changing your original file.
                  Saving merges these keys with existing metadata.
                </p>
                <label htmlFor={`${id}-metadata`}>Custom metadata (JSON)</label>
                <textarea
                  id={`${id}-metadata`}
                  rows={12}
                  spellCheck={false}
                  value={metadata}
                  onChange={(event) => {
                    setMetadata(event.target.value);
                    setSaveError("");
                  }}
                  aria-invalid={!!saveError}
                  aria-describedby={
                    saveError ? `${id}-metadata-error` : undefined
                  }
                  disabled={saving}
                />
                <p>
                  Up to 32 kB. System fields such as name and checksum are
                  protected.
                </p>
                {saveError && (
                  <p
                    id={`${id}-metadata-error`}
                    className="error-text"
                    role="alert"
                  >
                    {saveError}
                  </p>
                )}
                <button
                  className="button primary"
                  disabled={
                    saving || metadata === JSON.stringify(metadataBase, null, 2)
                  }
                  onClick={() => void save()}
                >
                  {saving ? (
                    <LoaderCircle size={16} className="spinning" />
                  ) : (
                    <Check size={16} />
                  )}
                  {saving ? "Saving…" : "Save changes"}
                </button>
              </section>
            )}
            {tab === "Chunks" && (
              <section className="chunk-inspector">
                <h3>Every piece, accounted for</h3>
                <p>
                  {details.num_chunks
                    ? `${details.num_chunks} ordered chunks. Copies are placed on different storage nodes.`
                    : "This empty file has no chunks. Its empty-content checksum is still verified."}
                </p>
                <div className="chunk-list">
                  {details.chunks.slice(0, chunkLimit).map((chunk) => (
                    <div className="chunk-row" key={chunk.chunk_id}>
                      <div className="chunk-title">
                        <span>
                          <Layers3 size={15} />
                          Chunk {chunk.index}
                        </span>
                        <span>{bytes(chunk.size)}</span>
                      </div>
                      <div className="replica-list">
                        {chunk.replicas.map((replica) => (
                          <span
                            key={replica.worker_id}
                            className={`replica ${replica.state === "HEALTHY" && overview?.workers.some((w) => w.worker_id === replica.worker_id && w.available) ? "available" : "unavailable"}`}
                          >
                            <i />
                            <span>{replica.worker_id}</span>
                            <small>
                              {replica.state === "HEALTHY"
                                ? replica.worker_status === "ALIVE"
                                  ? "Recorded"
                                  : replica.worker_status.toLowerCase()
                                : replica.state.toLowerCase().replace("_", " ")}
                            </small>
                          </span>
                        ))}
                      </div>
                      <p>
                        {healthyCopies(chunk.replicas)} available{" "}
                        {healthyCopies(chunk.replicas) === 1
                          ? "copy"
                          : "copies"}{" "}
                        <span>·</span>{" "}
                        <code title={chunk.sha256}>
                          {chunk.sha256.slice(0, 12)}…
                        </code>
                      </p>
                    </div>
                  ))}
                </div>
                {chunkLimit < details.chunks.length && (
                  <button
                    className="button secondary"
                    onClick={() => setChunkLimit((n) => n + 20)}
                  >
                    Show more chunks
                  </button>
                )}
              </section>
            )}
          </>
        )}
      </div>
      {feedback && (
        <div
          className={`inspector-feedback ${feedback.kind}`}
          role={feedback.kind === "error" ? "alert" : "status"}
        >
          <span>{feedback.text}</span>
          <button
            className="icon-button small"
            aria-label="Dismiss message"
            onClick={() => setFeedback(null)}
          >
            <X size={15} />
          </button>
        </div>
      )}
      <footer className="inspector-footer">
        <button className="button danger-text" onClick={() => onDelete(object)}>
          <Trash2 size={16} />
          Delete file
        </button>
        <button
          className="button primary"
          disabled={downloading}
          onClick={() => {
            setDownloading(true);
            void onDownload(object, notify)
              .then(async () => {
                try {
                  setDetails(
                    await request<ObjectDetails>(
                      `/api/v1/objects/${encodeURIComponent(object.object_id)}/metadata`,
                    ),
                  );
                  await onUpdated();
                } catch (error) {
                  notify(errorMessage(error), "error");
                }
              })
              .finally(() => setDownloading(false));
          }}
        >
          {downloading ? (
            <LoaderCircle size={16} className="spinning" />
          ) : (
            <Download size={16} />
          )}
          {downloading ? "Preparing…" : "Download file"}
        </button>
      </footer>
    </Dialog>
  );
}
