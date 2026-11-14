import { useEffect, useState } from "react";
import {
  LoaderCircle,
  Pause,
  Pencil,
  Play,
  Plug,
  Server,
  Trash2,
  Power,
  RotateCw,
} from "lucide-react";
import { request } from "../api";
import { errorMessage } from "../format";
import type { ManagedWorker, ManagedWorkers, Notify } from "../types";
import { NodeStatus } from "./ClusterPanel";
import { Dialog } from "./Dialog";

type Form =
  { kind: "connect" } | { kind: "edit" | "forget"; worker: ManagedWorker };

export function WorkerManager({
  state,
  stale,
  paused,
  onChanged,
  notify,
}: {
  state: ManagedWorkers | null;
  stale: boolean;
  paused: boolean;
  onChanged: () => Promise<void>;
  notify: Notify;
}) {
  const [form, setForm] = useState<Form | null>(null);
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [workerId, setWorkerId] = useState("worker5");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [containerState, setContainerState] = useState<{
    enabled: boolean;
    workers: { worker_id: string; container_state: string; running: boolean }[];
  } | null>(null);
  const [containerError, setContainerError] = useState("");
  const [action, setAction] = useState<{
    worker: string;
    kind: "start" | "stop" | "restart";
  } | null>(null);
  const [controlRevision, setControlRevision] = useState(0);
  useEffect(() => {
    const update = () => setControlRevision((value) => value + 1);
    window.addEventListener("artaud-connection", update);
    return () => window.removeEventListener("artaud-connection", update);
  }, []);
  useEffect(() => {
    if (paused) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const read = async () => {
      try {
        const data = await request<NonNullable<typeof containerState>>(
          "/api/v1/demo/workers",
          {
            signal: AbortSignal.any([
              controller.signal,
              AbortSignal.timeout(15_000),
            ]),
          },
        );
        if (!controller.signal.aborted) {
          setContainerState(data);
          setContainerError("");
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setContainerError(errorMessage(error));
          setContainerState(null);
        }
      } finally {
        if (!controller.signal.aborted)
          timer = window.setTimeout(() => void read(), 10_000);
      }
    };
    void read();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [paused, controlRevision]);
  async function performAction() {
    if (!action || disabled) return;
    setBusy("container");
    setContainerError("");
    try {
      await request(`/api/v1/demo/workers/${action.worker}/${action.kind}`, {
        method: "POST",
        headers: { "X-Artaud-Admin": "1" },
      });
      const data = await request<NonNullable<typeof containerState>>(
        "/api/v1/demo/workers",
      );
      setContainerState(data);
      setAction(null);
      await onChanged();
      notify(
        `Container action completed on ${action.worker}. Controller recovery status is separate.`,
        "success",
      );
    } catch (error) {
      setContainerError(errorMessage(error));
    } finally {
      setBusy("");
    }
  }
  const workers = state?.workers ?? [];
  const disabled = stale || paused || !!busy || !state;
  function open(next: Form) {
    setError("");
    setConfirmation("");
    setForm(next);
    if (next.kind === "connect") {
      setName("");
      setNotes("");
      setWorkerId(
        Array.from({ length: 16 }, (_, i) => `worker${i + 1}`).find(
          (id) => !workers.some((worker) => worker.worker_id === id),
        ) ?? "worker1",
      );
    } else {
      setName(next.worker.display_name);
      setNotes(next.worker.notes);
    }
  }
  async function mutate(
    path: string,
    method: string,
    body?: Record<string, unknown>,
  ) {
    return request(path, {
      method,
      headers: {
        "X-Artaud-Admin": "1",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  }
  async function toggle(worker: ManagedWorker) {
    setBusy(worker.worker_id);
    setError("");
    try {
      await mutate(
        `/api/v1/workers/${encodeURIComponent(worker.worker_id)}`,
        "PATCH",
        { placement_enabled: !worker.placement_enabled },
      );
      await onChanged();
      notify(
        worker.placement_enabled
          ? `New uploads paused on ${worker.worker_id}`
          : `New uploads enabled on ${worker.worker_id}`,
        "success",
      );
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy("");
    }
  }
  const changes: Record<string, unknown> = {};
  if (form?.kind === "edit") {
    if (name !== form.worker.display_name) changes.display_name = name;
    if (notes !== form.worker.notes) changes.notes = notes;
  }
  async function submit() {
    if (!form || disabled) return;
    setBusy("form");
    setError("");
    try {
      if (form.kind === "connect")
        await mutate("/api/v1/workers/connect", "POST", {
          worker_id: workerId,
          base_url: `http://${workerId}:8001`,
          display_name: name,
          notes,
        });
      else if (form.kind === "edit")
        await mutate(
          `/api/v1/workers/${encodeURIComponent(form.worker.worker_id)}`,
          "PATCH",
          changes,
        );
      else
        await mutate(
          `/api/v1/workers/${encodeURIComponent(form.worker.worker_id)}`,
          "DELETE",
        );
      await onChanged();
      setForm(null);
      notify(
        form.kind === "connect"
          ? "Worker connection verified; inventory reconciliation is still required"
          : form.kind === "edit"
            ? "Worker settings saved"
            : "Unused offline worker record forgotten",
        "success",
      );
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy("");
    }
  }
  return (
    <section
      className="system-section worker-manager"
      aria-labelledby="worker-manager-heading"
    >
      <div className="system-section-heading">
        <div>
          <h2 id="worker-manager-heading">
            <Server size={18} />
            Manage workers
          </h2>
          <p>
            {state
              ? `${state.placement_available_workers} nodes available for new placements`
              : "Loading worker settings…"}{" "}
            · Read availability and write placement are separate.
          </p>
        </div>
        <button
          className="button secondary"
          disabled={disabled}
          onClick={() => open({ kind: "connect" })}
        >
          <Plug size={15} />
          Connect worker
        </button>
      </div>
      {(stale || paused) && (
        <p className="system-history-notice">
          {paused ? "Resume the live view" : "Refresh the connection"} before
          changing worker settings.
        </p>
      )}
      {!containerState?.enabled && (
        <p className="system-footnote">
          Container actions are{" "}
          {containerError
            ? `unavailable: ${containerError}`
            : "disabled. Enable Demo controls in local startup to start, stop and restart the four existing workers"}
          .
        </p>
      )}
      {error && !form && (
        <p className="system-inline-error" role="alert">
          {error}
        </p>
      )}
      <div className="managed-workers">
        {workers.map((worker) => (
          <div
            className="managed-worker"
            key={worker.worker_id}
            data-managed-worker={worker.worker_id}
          >
            <div className="managed-worker-name">
              <Server size={19} />
              <div>
                <strong>{worker.display_name || worker.worker_id}</strong>
                {worker.display_name && <small>{worker.worker_id}</small>}
                <span>
                  {worker.replica_count} replica records · {worker.base_url}
                </span>
                {worker.notes && <p>{worker.notes}</p>}
              </div>
            </div>
            <div className="managed-worker-state">
              <NodeStatus worker={worker} stale={stale} />
              <span>
                Container:{" "}
                {containerState?.workers.find(
                  (item) => item.worker_id === worker.worker_id,
                )?.container_state ?? "not connected"}
              </span>
              <span>
                {!worker.placement_enabled
                  ? "New uploads paused"
                  : worker.available && !stale
                    ? "Accepting new uploads"
                    : "Waiting for availability"}
              </span>
            </div>
            <div className="managed-worker-actions">
              {containerState?.enabled &&
                containerState.workers.some(
                  (item) => item.worker_id === worker.worker_id,
                ) && (
                  <>
                    <button
                      className="icon-button"
                      aria-label={`${containerState.workers.find((item) => item.worker_id === worker.worker_id)?.running ? "Stop" : "Start"} ${worker.worker_id}`}
                      title="Start or stop this worker container; stored data stays on its volume"
                      disabled={disabled}
                      onClick={() => {
                        setContainerError("");
                        setAction({
                          worker: worker.worker_id,
                          kind: containerState.workers.find(
                            (item) => item.worker_id === worker.worker_id,
                          )?.running
                            ? "stop"
                            : "start",
                        });
                      }}
                    >
                      <Power size={16} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label={`Restart ${worker.worker_id}`}
                      title="Restart worker container"
                      disabled={disabled}
                      onClick={() => {
                        setContainerError("");
                        setAction({
                          worker: worker.worker_id,
                          kind: "restart",
                        });
                      }}
                    >
                      <RotateCw size={15} />
                    </button>
                  </>
                )}
              <button
                className="icon-button"
                aria-label={`Edit ${worker.worker_id}`}
                title="Edit display name and notes"
                disabled={disabled}
                onClick={() => open({ kind: "edit", worker })}
              >
                <Pencil size={15} />
              </button>
              <button
                className="icon-button"
                aria-label={`${worker.placement_enabled ? "Pause" : "Resume"} new uploads on ${worker.worker_id}`}
                title={
                  worker.placement_enabled
                    ? "Pause new upload placement"
                    : "Resume new upload placement"
                }
                disabled={disabled}
                onClick={() => void toggle(worker)}
              >
                {busy === worker.worker_id ? (
                  <LoaderCircle size={15} className="spinning" />
                ) : worker.placement_enabled ? (
                  <Pause size={15} />
                ) : (
                  <Play size={15} />
                )}
              </button>
              <button
                className="icon-button"
                aria-label={`Forget ${worker.worker_id}`}
                disabled={disabled || !worker.can_forget}
                title={
                  worker.replica_count
                    ? "Cannot forget a node with replica records"
                    : !worker.can_forget
                      ? "Only unused nodes with a stale heartbeat can be forgotten"
                      : "Forget unused offline worker record"
                }
                onClick={() => open({ kind: "forget", worker })}
              >
                <Trash2 size={15} />
              </button>
            </div>
          </div>
        ))}
      </div>
      {!workers.length && state && (
        <p className="system-empty">
          No worker has registered yet. Start a service before connecting it
          here.
        </p>
      )}
      {action && (
        <Dialog
          title={`${action.kind} ${action.worker}`}
          className="worker-dialog"
          closeDisabled={!!busy}
          onClose={() => {
            if (!busy) setAction(null);
          }}
        >
          <h2>
            {action.kind[0].toUpperCase() + action.kind.slice(1)}{" "}
            {action.worker}?
          </h2>
          <p>
            This changes the actual Docker container on the host PC. Its
            persistent volume is preserved. Stopping or restarting a node can
            temporarily reduce readable replicas; the controller’s recovery
            service handles detection and repair separately.
          </p>
          {containerError && (
            <p className="error-text" role="alert">
              {containerError}
            </p>
          )}
          <div className="dialog-actions">
            <button
              className="button secondary"
              disabled={!!busy}
              onClick={() => setAction(null)}
            >
              Cancel
            </button>
            <button
              className={`button ${action.kind === "stop" ? "destructive" : "primary"}`}
              disabled={disabled}
              onClick={() => void performAction()}
            >
              {busy ? <LoaderCircle size={15} className="spinning" /> : null}
              {action.kind[0].toUpperCase() + action.kind.slice(1)}{" "}
              {action.worker}
            </button>
          </div>
        </Dialog>
      )}
      <p className="system-footnote">
        Pausing affects subsequent upload selections. In-flight writes may
        finish; downloads and recovery state are preserved. Forgetting a record
        never deletes a container or its disk.
      </p>
      {form && (
        <Dialog
          title={
            form.kind === "connect"
              ? "Connect an existing worker"
              : form.kind === "edit"
                ? `Edit ${form.worker.worker_id}`
                : `Forget ${form.worker.worker_id}`
          }
          className="worker-dialog"
          closeDisabled={!!busy}
          alert={form.kind === "forget"}
          onClose={() => {
            if (!busy) {
              setForm(null);
              setError("");
            }
          }}
        >
          <h2>
            {form.kind === "connect"
              ? "Connect an existing worker"
              : form.kind === "edit"
                ? `Edit ${form.worker.worker_id}`
                : `Forget ${form.worker.worker_id}?`}
          </h2>
          {form.kind === "forget" ? (
            <>
              <p>
                Only an unused worker with no recent heartbeat can be forgotten.
                The container and its disk remain untouched. A returning worker
                can register again.
              </p>
              <label htmlFor="worker-confirmation">
                Type {form.worker.worker_id} to confirm
              </label>
              <input
                id="worker-confirmation"
                autoFocus
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                disabled={!!busy}
              />
            </>
          ) : (
            <>
              {form.kind === "connect" && (
                <>
                  <p>
                    The worker service must already be running on your PC. We
                    verify its identity; it remains Joining until inventory
                    reconciliation.
                  </p>
                  <label htmlFor="worker-id">Worker ID</label>
                  <select
                    id="worker-id"
                    value={workerId}
                    disabled={!!busy}
                    onChange={(event) => {
                      setWorkerId(event.target.value);
                    }}
                  >
                    {Array.from({ length: 16 }, (_, i) => (
                      <option key={i} value={`worker${i + 1}`}>
                        worker{i + 1}
                      </option>
                    ))}
                  </select>
                  <p className="worker-origin">
                    Connection: http://{workerId}:8001
                  </p>
                </>
              )}
              <label htmlFor="worker-name">Display name</label>
              <input
                id="worker-name"
                maxLength={64}
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={!!busy}
                autoFocus={form.kind === "edit"}
                placeholder="Optional friendly name"
              />
              <label htmlFor="worker-notes">Operator notes</label>
              <textarea
                id="worker-notes"
                maxLength={512}
                rows={3}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                disabled={!!busy}
                placeholder="Location, purpose or maintenance notes"
              />
            </>
          )}
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          {(stale || paused) && (
            <p className="error-text" role="status">
              Refresh or resume before saving changes.
            </p>
          )}
          <div className="dialog-actions">
            <button
              className="button secondary"
              disabled={!!busy}
              onClick={() => {
                setForm(null);
                setError("");
              }}
            >
              Cancel
            </button>
            <button
              className={`button ${form.kind === "forget" ? "destructive" : "primary"}`}
              disabled={
                disabled ||
                (form.kind === "edit" && Object.keys(changes).length === 0) ||
                (form.kind === "forget" &&
                  confirmation !== form.worker.worker_id)
              }
              onClick={() => void submit()}
            >
              {busy ? <LoaderCircle size={15} className="spinning" /> : null}
              {form.kind === "connect"
                ? "Verify & connect"
                : form.kind === "edit"
                  ? "Save worker"
                  : "Forget worker record"}
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
