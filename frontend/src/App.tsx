import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Boxes,
  Check,
  ChevronRight,
  CircleHelp,
  Code2,
  Files,
  HardDrive,
  Info,
  LoaderCircle,
  Network,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  Trash2,
  Upload,
  X,
  Link2,
} from "lucide-react";
import { downloadFile, request } from "./api";
import { bytes, errorMessage } from "./format";
import type {
  ManagedWorkers,
  Notify,
  Overview,
  StoredObject,
  ToastMessage,
} from "./types";
import { ClusterPanel } from "./components/ClusterPanel";
import { Dialog } from "./components/Dialog";
import { ObjectInspector } from "./components/ObjectInspector";
import { ObjectTable } from "./components/ObjectTable";
import { UploadPanel } from "./components/UploadPanel";
import { SystemExplorer } from "./components/SystemExplorer";
import { ConnectionSettings } from "./components/ConnectionSettings";
import { apiUrl } from "./connection";

export default function App() {
  const [objects, setObjects] = useState<StoredObject[]>([]),
    [overview, setOverview] = useState<Overview | null>(null);
  const [managedWorkers, setManagedWorkers] = useState<ManagedWorkers | null>(
    null,
  );
  const [loading, setLoading] = useState(true),
    [refreshing, setRefreshing] = useState(false),
    [error, setError] = useState<string | null>(null),
    [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [view, setView] = useState<"files" | "cluster">("files"),
    [selected, setSelected] = useState<StoredObject | null>(null),
    [toDelete, setToDelete] = useState<StoredObject | null>(null),
    [deleting, setDeleting] = useState(false),
    [deleteError, setDeleteError] = useState("");
  const [helpOpen, setHelpOpen] = useState(false),
    [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null),
    activeLoad = useRef<AbortController | null>(null),
    toastTimers = useRef(new Set<number>());
  const notify: Notify = useCallback((text, kind = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current.slice(-2), { id, text, kind }]);
    const timer = window.setTimeout(
      () => {
        setToasts((current) => current.filter((message) => message.id !== id));
        toastTimers.current.delete(timer);
      },
      kind === "error" ? 12_000 : 6500,
    );
    toastTimers.current.add(timer);
  }, []);
  const load = useCallback(async () => {
    activeLoad.current?.abort();
    const controller = new AbortController();
    activeLoad.current = controller;
    setRefreshing(true);
    try {
      const signal = AbortSignal.any([
        controller.signal,
        AbortSignal.timeout(15_000),
      ]);
      const [files, snapshot, workers] = await Promise.all([
        request<StoredObject[]>("/api/v1/objects", {
          signal,
        }),
        request<Overview>("/api/v1/overview", { signal }),
        request<ManagedWorkers>("/api/v1/workers", { signal }),
      ]);
      if (!controller.signal.aborted) {
        setObjects(files);
        setOverview(snapshot);
        setManagedWorkers(workers);
        setError(null);
        setLastUpdated(new Date());
      }
    } catch (error) {
      if (!controller.signal.aborted) setError(errorMessage(error));
    } finally {
      if (activeLoad.current === controller) activeLoad.current = null;
      if (!controller.signal.aborted) {
        setRefreshing(false);
        setLoading(false);
      }
    }
  }, []);
  useEffect(() => {
    const changed = () => {
      setSelected(null);
      setToDelete(null);
      setObjects([]);
      setOverview(null);
      setManagedWorkers(null);
      setLastUpdated(null);
      setLoading(true);
      void load();
    };
    window.addEventListener("artaud-connection", changed);
    return () => window.removeEventListener("artaud-connection", changed);
  }, [load]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(
      () => {
        if (!document.hidden && !activeLoad.current) void load();
      },
      view === "cluster" ? 2000 : 10_000,
    );
    const visible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      activeLoad.current?.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [load, view]);
  useEffect(() => {
    const timers = toastTimers.current;
    return () => timers.forEach(window.clearTimeout);
  }, []);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (
        event.key === "/" &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        !(
          event.target instanceof HTMLElement &&
          (["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName) ||
            event.target.isContentEditable)
        ) &&
        !document.querySelector("dialog[open]")
      ) {
        event.preventDefault();
        setView("files");
        requestAnimationFrame(() => searchRef.current?.focus());
      }
    };
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, []);
  const onDownload = async (
    object: StoredObject,
    feedback: Notify = notify,
  ) => {
    try {
      const result = await downloadFile(object);
      if (result !== "cancelled")
        feedback(
          result === "saved" ? `${object.name} saved` : "Download started",
          "success",
        );
    } catch (error) {
      feedback(errorMessage(error), "error");
    }
  };
  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await request(
        `/api/v1/objects/${encodeURIComponent(toDelete.object_id)}`,
        { method: "DELETE" },
      );
      setSelected(null);
      setToDelete(null);
      notify("File deleted", "success");
      await load();
      searchRef.current?.focus();
    } catch (error) {
      setDeleteError(errorMessage(error));
    } finally {
      setDeleting(false);
    }
  }
  const needsStorage =
    !loading &&
    !error &&
    managedWorkers !== null &&
    managedWorkers.placement_available_workers < 2;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span>
            <Boxes size={25} strokeWidth={1.8} />
          </span>
          artaud<span className="brand-period">.</span>
        </div>
        <div className="workspace-switch">
          <span className="workspace-avatar">
            <HardDrive size={17} />
          </span>
          <div>
            <strong>Local workspace</strong>
            <span>Object storage</span>
          </div>
        </div>
        <nav aria-label="Workspace">
          <button
            aria-label="Files"
            className={view === "files" ? "active" : ""}
            aria-current={view === "files" ? "page" : undefined}
            onClick={() => setView("files")}
          >
            <Files size={18} />
            Files<span>{objects.length}</span>
          </button>
          <button
            className={view === "cluster" ? "active" : ""}
            aria-current={view === "cluster" ? "page" : undefined}
            onClick={() => setView("cluster")}
          >
            <Network size={18} />
            Cluster
          </button>
        </nav>
        <div className="sidebar-bottom">
          <button onClick={() => setConnectionOpen(true)}>
            <Link2 size={17} />
            Connection settings
          </button>
          <button onClick={() => setHelpOpen(true)}>
            <CircleHelp size={17} />
            How it works
          </button>
          <a href={apiUrl("/docs")} target="_blank" rel="noopener noreferrer">
            <Code2 size={17} />
            API reference
            <ArrowUpRight size={14} />
          </a>
          <div className="connection-indicator">
            <i
              className={`status-dot ${error ? "red" : lastUpdated ? "green" : "amber"}`}
            />
            <div>
              <strong>
                {error
                  ? "Connection interrupted"
                  : lastUpdated
                    ? "Controller connected"
                    : "Connecting…"}
              </strong>
              <span>Local deployment</span>
            </div>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <div className="topbar">
          <div className="breadcrumb">
            Workspace
            <ChevronRight size={14} />
            <span>{view === "files" ? "Object storage" : "Cluster"}</span>
          </div>
          <div className="environment">
            <i />
            Development<span>Local</span>
          </div>
        </div>
        <main id="workspace" tabIndex={-1}>
          <header className="page-heading">
            <div>
              <h1>{view === "files" ? "Object storage" : "Storage cluster"}</h1>
              <p>
                {view === "files"
                  ? "Everything you store, within reach."
                  : "Follow your data, from the first chunk to its verified copies."}
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="icon-button"
                aria-label="Backend connection"
                title="Backend connection"
                onClick={() => setConnectionOpen(true)}
              >
                <Link2 size={17} />
              </button>
              <button
                className="icon-button refresh"
                aria-label="Refresh workspace"
                title="Refresh workspace"
                onClick={() => void load()}
                disabled={refreshing}
              >
                <RefreshCw size={17} className={refreshing ? "spinning" : ""} />
              </button>
              <button
                className="button primary"
                onClick={() => {
                  setView("files");
                  document
                    .querySelector<HTMLInputElement>("input[type=file]")
                    ?.click();
                }}
              >
                <Upload size={16} />
                Upload files
              </button>
            </div>
          </header>
          {error && (
            <div className="notice error-notice" role="alert">
              <TriangleAlert size={19} />
              <div>
                <strong>
                  {lastUpdated
                    ? "Your workspace could not refresh"
                    : "Could not load your workspace"}
                </strong>
                <p>
                  {error}
                  {lastUpdated
                    ? " Displaying the last successful snapshot."
                    : ""}
                </p>
              </div>
              <button className="button secondary" onClick={() => void load()}>
                Try again
              </button>
            </div>
          )}
          {needsStorage && (
            <div className="notice storage-notice">
              <Info size={19} />
              <div>
                <strong>
                  {overview && overview.available_workers >= 2
                    ? "New uploads are paused"
                    : "Storage is connecting"}
                </strong>
                <p>
                  {overview && overview.available_workers >= 2
                    ? "Resume new uploads on at least two available workers in Cluster. Existing files can still be downloaded."
                    : overview?.worker_count
                      ? "Your nodes are joining. File storage becomes available after at least two nodes are checked and ready."
                      : "Waiting for your storage nodes to connect. You can explore the workspace in the meantime."}
                </p>
              </div>
              <button
                className="text-button"
                onClick={() => setView("cluster")}
              >
                View cluster
                <ArrowUpRight size={14} />
              </button>
            </div>
          )}
          <div className="storage-summary" aria-label="Storage summary">
            <span>
              <HardDrive size={16} />
              <strong>{overview ? bytes(overview.logical_bytes) : "—"}</strong>
              stored
            </span>
            <span>
              <Files size={16} />
              <strong>{overview?.object_count ?? "—"}</strong>objects
            </span>
            <span>
              <ShieldCheck size={16} />
              <strong>{overview?.replication_factor ?? 2}-copy target</strong>
              per chunk
            </span>
            <span className="summary-live">
              <i
                className={`status-dot ${error ? "red" : lastUpdated ? "green" : "amber"}`}
              />
              {error
                ? "Snapshot unavailable"
                : view === "cluster"
                  ? `Refreshes every ${2000 / 1000}s`
                  : "Refreshes every 10s"}
            </span>
          </div>
          <div hidden={view !== "files"} className="workspace-layout">
            <div className="files-workspace">
              <UploadPanel
                availableWorkers={
                  error ? 0 : (managedWorkers?.placement_available_workers ?? 0)
                }
                onUploaded={load}
                notify={notify}
              />
              {!loading && error && !lastUpdated ? (
                <div className="workspace-unavailable">
                  <Network size={30} />
                  <h2>Your files will appear here</h2>
                  <p>Reconnect to the controller to load your storage.</p>
                </div>
              ) : (
                <ObjectTable
                  objects={objects}
                  loading={loading}
                  error={error}
                  onInspect={setSelected}
                  onDownload={(object) => void onDownload(object)}
                  searchRef={searchRef}
                />
              )}
            </div>
            <aside className="system-rail">
              <ClusterPanel
                overview={overview}
                stale={!!error}
                onExpand={() => setView("cluster")}
              />
              <div className="integrity-footnote">
                <ShieldCheck size={19} />
                <h3>Trust every byte.</h3>
                <p>
                  Every download is checked against its SHA-256 checksum before
                  it reaches you.
                </p>
                <button
                  className="text-button"
                  onClick={() => setHelpOpen(true)}
                >
                  How integrity works
                  <ArrowUpRight size={13} />
                </button>
              </div>
            </aside>
          </div>
          {view === "cluster" && (
            <div className="cluster-workspace">
              <SystemExplorer
                overview={overview}
                objects={objects}
                stale={!!error}
                capturedAt={lastUpdated?.toISOString() ?? null}
                onInspect={setSelected}
                managedWorkers={managedWorkers}
                onWorkersChanged={load}
                notify={notify}
                pollInterval={2000}
              />
              <div className="cluster-health-note">
                <Info size={18} />
                <p>
                  {error
                    ? "The controller is unreachable. Current node and recovery status cannot be confirmed."
                    : overview?.recovery_available
                      ? "The recovery service is connected. Recorded replica changes and repair events show observed progress."
                      : "Recovery service unavailable. Registered nodes remain joining until their inventories are reconciled. Existing files can still be downloaded when a verified copy is available."}
                </p>
              </div>
            </div>
          )}
          <footer className="workspace-footer">
            <span>
              <Boxes size={14} />
              Built around your original bytes.
            </span>
            {lastUpdated && (
              <span>
                Last synced{" "}
                {lastUpdated.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
          </footer>
        </main>
      </div>
      {selected && (
        <ObjectInspector
          object={selected}
          overview={overview}
          onClose={() => setSelected(null)}
          onDelete={(object) => {
            setDeleteError("");
            setToDelete(object);
          }}
          onDownload={onDownload}
          onUpdated={load}
        />
      )}
      {connectionOpen && (
        <ConnectionSettings onClose={() => setConnectionOpen(false)} />
      )}
      {toDelete && (
        <Dialog
          title="Delete this file?"
          closeDisabled={deleting}
          alert
          onClose={() => {
            if (!deleting) setToDelete(null);
          }}
          className="delete-dialog"
        >
          <span className="destructive-symbol">
            <Trash2 size={23} />
          </span>
          <h2>Delete this file?</h2>
          <p>
            This permanently removes{" "}
            <strong className="delete-filename">{toDelete.name}</strong> from
            your storage.
          </p>
          <p className="muted">
            Copies on offline nodes will need cleanup when those nodes
            reconnect.
          </p>
          {deleteError && (
            <p className="error-text" role="alert">
              {deleteError}
            </p>
          )}
          <div className="dialog-actions">
            <button
              className="button secondary"
              autoFocus
              disabled={deleting}
              onClick={() => setToDelete(null)}
            >
              Keep file
            </button>
            <button
              className="button destructive"
              disabled={deleting}
              onClick={() => void confirmDelete()}
            >
              {deleting ? (
                <LoaderCircle size={16} className="spinning" />
              ) : (
                <Trash2 size={16} />
              )}
              {deleting ? "Deleting…" : "Delete file"}
            </button>
          </div>
        </Dialog>
      )}
      {helpOpen && (
        <Dialog
          title="A little about your storage"
          onClose={() => setHelpOpen(false)}
          className="help-dialog"
        >
          <Boxes size={31} className="help-mark" />
          <h2>A little about your storage</h2>
          <p>
            Your files stay whole to you. Underneath, they’re split into ordered
            chunks and copied across separate nodes.
          </p>
          <dl>
            <div>
              <dt>Two copies, separate nodes</dt>
              <dd>
                Each chunk targets two distinct storage locations so a readable
                copy can survive a node becoming unavailable.
              </dd>
            </div>
            <div>
              <dt>Checksums before downloads</dt>
              <dd>
                The controller checks each chunk and the complete file against
                its recorded SHA-256 checksum before sending a successful
                download.
              </dd>
            </div>
            <div>
              <dt>Metadata without re-uploading</dt>
              <dd>
                Add custom properties in a file’s Metadata tab. Its bytes and
                checksum stay the same.
              </dd>
            </div>
          </dl>
          <p className="muted">
            This workspace connects to your local controller. Automatic repair
            depends on the recovery service shown in Cluster.
          </p>
          <button className="button primary" onClick={() => setHelpOpen(false)}>
            Got it
            <Check size={16} />
          </button>
        </Dialog>
      )}
      <div
        className="toast-region"
        aria-live="polite"
        aria-relevant="additions"
      >
        {toasts.map((toast) => (
          <div className={`toast ${toast.kind}`} key={toast.id}>
            {toast.kind === "success" ? (
              <Check size={17} />
            ) : toast.kind === "error" ? (
              <TriangleAlert size={17} />
            ) : (
              <Info size={17} />
            )}
            <span>{toast.text}</span>
            <button
              className="icon-button small"
              aria-label="Dismiss notification"
              onClick={() =>
                setToasts((current) =>
                  current.filter((item) => item.id !== toast.id),
                )
              }
            >
              <X size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
