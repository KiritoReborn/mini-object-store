import { useCallback, useEffect, useRef, useState } from "react";
import { Download, Pause, Play, Workflow } from "lucide-react";
import { useActivity } from "../useActivity";
import { saveJson, timeLabel } from "../system";
import type {
  ActivityEvent,
  ManagedWorkers,
  Notify,
  Overview,
  StoredObject,
} from "../types";
import { ActivityTimeline } from "./ActivityTimeline";
import { ClusterPanel } from "./ClusterPanel";
import { ObjectPlacement } from "./ObjectPlacement";
import { DistributionChart, RecoveryPanel } from "./RecoveryPanel";
import { TopologyMap } from "./TopologyMap";
import { WorkerManager } from "./WorkerManager";
import { DemoGuide } from "./DemoGuide";
import "./system.css";

export function SystemExplorer({
  overview,
  objects,
  stale,
  capturedAt,
  onInspect,
  managedWorkers,
  onWorkersChanged,
  notify,
  pollInterval,
}: {
  overview: Overview | null;
  objects: StoredObject[];
  stale: boolean;
  capturedAt: string | null;
  onInspect: (object: StoredObject) => void;
  managedWorkers: ManagedWorkers | null;
  onWorkersChanged: () => Promise<void>;
  notify: Notify;
  pollInterval: number;
}) {
  const [paused, setPaused] = useState(false);
  const [snapshot, setSnapshot] = useState({
    overview,
    objects,
    stale,
    capturedAt,
    managedWorkers,
  });
  const [workerId, setWorkerId] = useState("");
  const [objectId, setObjectId] = useState("");
  const [highlights, setHighlights] = useState<string[] | null>(null);
  const [replay, setReplay] = useState<ActivityEvent | null>(null);
  const [now, setNow] = useState(Date.now());
  const topology = useRef<HTMLDivElement>(null);
  const activity = useActivity(paused, pollInterval);
  const onHighlight = useCallback(
    (workers: string[] | null) => setHighlights(workers),
    [],
  );
  useEffect(() => {
    if (!paused)
      setSnapshot({ overview, objects, stale, capturedAt, managedWorkers });
  }, [paused, overview, objects, stale, capturedAt, managedWorkers]);
  useEffect(() => {
    if (paused) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [paused]);
  useEffect(() => {
    if (!replay) return;
    const timer = window.setTimeout(() => setReplay(null), 4000);
    return () => window.clearTimeout(timer);
  }, [replay]);
  useEffect(() => {
    if (
      !paused &&
      objectId &&
      !snapshot.objects.some((object) => object.object_id === objectId)
    ) {
      setObjectId("");
      setHighlights(null);
    }
  }, [snapshot.objects, objectId, paused]);
  const observed =
    snapshot.stale || activity.error || paused
      ? []
      : (activity.history?.events ?? []).filter((event) => {
          const age = now - Date.parse(event.timestamp);
          return (
            age >= 0 &&
            age <= 4000 &&
            (!objectId || event.object_id === objectId)
          );
        });
  function exportDiagnostics() {
    saveJson(
      `artaud-diagnostics-${new Date().toISOString().replaceAll(":", "-")}.json`,
      {
        schema_version: 1,
        exported_at: new Date().toISOString(),
        snapshot_captured_at: snapshot.capturedAt,
        snapshot_stale: snapshot.stale,
        view_paused: paused,
        activity_captured_at: activity.capturedAt,
        activity_error: activity.error,
        activity_stream_id: activity.history?.stream_id ?? null,
        activity_notice: activity.history?.notice ?? null,
        overview: snapshot.overview,
        files: snapshot.objects.map(
          ({ object_id, name, size, num_chunks, sha256 }) => ({
            object_id,
            name,
            size,
            num_chunks,
            sha256,
          }),
        ),
        activity: activity.history?.events ?? [],
        limits: [
          "Recent process-local observations, not a durable audit log",
          "Recorded copy bytes are not disk capacity",
          "A connected recovery service does not prove autonomous repair",
        ],
      },
    );
  }
  return (
    <div className="system-explorer">
      <div className="system-toolbar">
        <div>
          <Workflow size={20} />
          <span>
            <strong>Live system explorer</strong>
            <small>
              {paused
                ? `Paused at ${snapshot.capturedAt ? timeLabel(snapshot.capturedAt) : "an unavailable snapshot"}`
                : `Observations refresh every ${pollInterval / 1000} seconds`}
            </small>
          </span>
        </div>
        <div>
          <button
            className="button secondary"
            aria-pressed={paused}
            onClick={() => {
              setPaused((value) => !value);
              setReplay(null);
            }}
          >
            {paused ? <Play size={15} /> : <Pause size={15} />}
            {paused ? "Resume live view" : "Pause live view"}
          </button>
          <button
            className="button secondary"
            disabled={!snapshot.overview}
            onClick={exportDiagnostics}
          >
            <Download size={15} />
            Export diagnostics
          </button>
        </div>
      </div>
      <div ref={topology}>
        <TopologyMap
          overview={snapshot.overview}
          stale={snapshot.stale}
          paused={paused}
          events={observed}
          selectedWorker={workerId}
          onSelectWorker={setWorkerId}
          replay={replay}
          highlights={highlights}
        />
      </div>
      <DemoGuide overview={snapshot.overview} stale={snapshot.stale} />
      <ObjectPlacement
        pollInterval={pollInterval}
        objects={snapshot.objects}
        overview={snapshot.overview}
        stale={snapshot.stale}
        paused={paused}
        objectId={objectId}
        onObjectChange={setObjectId}
        onInspect={onInspect}
        onHighlight={onHighlight}
        notify={notify}
      />
      <div className="system-lower-grid">
        <WorkerManager
          state={snapshot.managedWorkers}
          stale={snapshot.stale}
          paused={paused}
          onChanged={onWorkersChanged}
          notify={notify}
        />
        <div>
          <RecoveryPanel
            overview={snapshot.overview}
            stale={snapshot.stale}
            events={activity.history?.events ?? []}
          />
          <DistributionChart
            overview={snapshot.overview}
            stale={snapshot.stale}
            onSelect={setWorkerId}
          />
        </div>
        <ActivityTimeline
          history={activity.history}
          error={activity.error}
          paused={paused}
          workers={snapshot.overview?.workers ?? []}
          workerId={workerId}
          onWorkerChange={setWorkerId}
          objectId={objectId}
          objects={snapshot.objects}
          onInspect={onInspect}
          onRetry={activity.refresh}
          onReplay={(event) => {
            setReplay({ ...event });
            topology.current?.scrollIntoView({
              behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
                .matches
                ? "instant"
                : "smooth",
              block: "center",
            });
          }}
        />
      </div>
      <details className="system-node-details">
        <summary>All node details &amp; configuration</summary>
        <ClusterPanel
          overview={snapshot.overview}
          stale={snapshot.stale}
          full
        />
      </details>
    </div>
  );
}
