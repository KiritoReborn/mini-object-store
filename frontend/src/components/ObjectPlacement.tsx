import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Layers3,
  RefreshCw,
} from "lucide-react";
import { request } from "../api";
import { bytes, errorMessage } from "../format";
import { replicaLabel, saveJson } from "../system";
import type { ObjectDetails, Overview, StoredObject } from "../types";
import { FileIcon } from "./FileIcon";

export function ObjectPlacement({
  objects,
  overview,
  stale,
  paused,
  objectId,
  onObjectChange,
  onInspect,
  onHighlight,
  pollInterval,
}: {
  objects: StoredObject[];
  overview: Overview | null;
  stale: boolean;
  paused: boolean;
  objectId: string;
  onObjectChange: (id: string) => void;
  onInspect: (object: StoredObject) => void;
  onHighlight: (workers: string[] | null) => void;
  pollInterval: number;
}) {
  const [details, setDetails] = useState<ObjectDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [selectedChunk, setSelectedChunk] = useState<string | null>(null);
  const [manifestTime, setManifestTime] = useState<string | null>(null);
  const selected = objects.find((object) => object.object_id === objectId);
  useEffect(() => {
    setDetails(null);
    setError(null);
    setPage(0);
    setSelectedChunk(null);
    setManifestTime(null);
    onHighlight(null);
  }, [objectId, onHighlight]);
  useEffect(() => {
    const chunk =
      details?.object_id === objectId
        ? details.chunks.find((chunk) => chunk.chunk_id === selectedChunk)
        : null;
    onHighlight(
      stale || error || !chunk
        ? null
        : chunk.replicas
            .filter((replica) => replica.state === "HEALTHY")
            .map((replica) => replica.worker_id),
    );
  }, [details, objectId, selectedChunk, stale, error, onHighlight]);
  useEffect(() => {
    if (!objectId || paused) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const poll = async () => {
      if (document.hidden) {
        timer = window.setTimeout(() => void poll(), pollInterval);
        return;
      }
      setLoading(true);
      try {
        const data = await request<ObjectDetails>(
          `/api/v1/objects/${encodeURIComponent(objectId)}/metadata`,
          {
            signal: AbortSignal.any([
              controller.signal,
              AbortSignal.timeout(15_000),
            ]),
          },
        );
        if (!controller.signal.aborted) {
          setDetails(data);
          setManifestTime(new Date().toISOString());
          setError(null);
        }
      } catch (error) {
        if (!controller.signal.aborted) setError(errorMessage(error));
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          timer = window.setTimeout(() => void poll(), pollInterval);
        }
      }
    };
    void poll();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [objectId, paused, refresh, pollInterval]);
  const validDetails = details?.object_id === objectId ? details : null;
  const workers = overview?.workers ?? [];
  const pages = Math.max(1, Math.ceil((validDetails?.chunks.length ?? 0) / 8));
  const currentPage = Math.min(page, pages - 1);
  const chunks =
    validDetails?.chunks.slice(currentPage * 8, currentPage * 8 + 8) ?? [];
  return (
    <section
      className="system-section placement-section"
      aria-labelledby="placement-heading"
    >
      <div className="system-section-heading">
        <div>
          <h2 id="placement-heading">
            <Layers3 size={18} /> Where each chunk lives
          </h2>
          <p>Select a file, then a chunk to highlight its connections.</p>
        </div>
        <label className="system-select-label">
          File
          <select
            value={objectId}
            onChange={(event) => onObjectChange(event.target.value)}
            aria-label="File to visualize"
            disabled={paused}
          >
            <option value="">All files</option>
            {objects.map((object) => (
              <option key={object.object_id} value={object.object_id}>
                {object.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {!objectId ? (
        <div className="system-empty">
          <Layers3 size={25} />
          <p>
            {objects.length
              ? "Choose a file to trace its ordered chunks and replica locations."
              : "Stored files will appear here with their real chunk locations."}
          </p>
        </div>
      ) : (
        <>
          {selected && (
            <div className="placement-file">
              <FileIcon mime={selected.content_type} />
              <div>
                <strong>{selected.name}</strong>
                <span>
                  {bytes(selected.size)} · {selected.num_chunks} chunks ·{" "}
                  {overview?.replication_factor ?? 2}-copy target
                </span>
              </div>
              <button
                className="text-button"
                onClick={() => onInspect(selected)}
              >
                Inspect file
                <ArrowUpRight size={14} />
              </button>
              <button
                className="text-button"
                disabled={
                  !validDetails || !!error || stale || (loading && !paused)
                }
                onClick={() =>
                  saveJson(`artaud-manifest-${objectId}.json`, {
                    schema_version: 1,
                    captured_at: manifestTime,
                    view_paused: paused,
                    manifest: validDetails,
                  })
                }
              >
                Export manifest
              </button>
            </div>
          )}
          {error && (
            <div className="system-inline-error" role="alert">
              <p>
                Chunk locations could not refresh. {error} Any displayed
                locations are an older snapshot.
              </p>
              <button
                className="text-button"
                disabled={paused}
                onClick={() => setRefresh((value) => value + 1)}
              >
                <RefreshCw size={14} />
                Retry locations
              </button>
            </div>
          )}
          {!validDetails && !error && (
            <p className="system-empty">
              {paused
                ? "Resume to load this file’s chunk locations."
                : "Loading chunk locations…"}
            </p>
          )}
          {validDetails && validDetails.chunks.length === 0 && (
            <p className="system-empty">
              This empty file has no chunks. Its checksum still verifies the
              original empty bytes.
            </p>
          )}
          {chunks.length > 0 && (
            <div
              className="placement-scroll"
              tabIndex={0}
              role="region"
              aria-label="Chunk placement table; scroll horizontally if needed"
            >
              <table className="placement-table">
                <thead>
                  <tr>
                    <th scope="col">Chunk</th>
                    {workers.map((worker) => (
                      <th scope="col" key={worker.worker_id}>
                        {worker.worker_id}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {chunks.map((chunk) => (
                    <tr key={chunk.chunk_id}>
                      <th scope="row">
                        <button
                          className="chunk-select"
                          aria-pressed={selectedChunk === chunk.chunk_id}
                          onClick={() =>
                            setSelectedChunk(
                              selectedChunk === chunk.chunk_id
                                ? null
                                : chunk.chunk_id,
                            )
                          }
                        >
                          Chunk {chunk.index + 1}
                          <small>{bytes(chunk.size)}</small>
                        </button>
                      </th>
                      {workers.map((worker) => {
                        const replica = chunk.replicas.find(
                          (replica) => replica.worker_id === worker.worker_id,
                        );
                        const label = replica
                          ? replicaLabel(
                              replica.state,
                              worker.available,
                              stale || !!error,
                            )
                          : "No recorded copy";
                        return (
                          <td key={worker.worker_id}>
                            <span
                              className={`placement-state ${label === "Healthy" ? "copy-healthy" : ["Corrupt", "Missing"].includes(label) ? "copy-bad" : "copy-neutral"}`}
                            >
                              <i />
                              {label}
                            </span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {validDetails && (
            <div className="placement-pagination">
              <span>
                {paused
                  ? "Paused manifest snapshot"
                  : loading
                    ? "Refreshing locations…"
                    : `Manifest snapshot · ${validDetails.chunks.length} chunks`}
              </span>
              <div>
                <button
                  className="icon-button"
                  aria-label="Previous chunk page"
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                >
                  <ChevronLeft size={17} />
                </button>
                <span>
                  {currentPage + 1} / {pages}
                </span>
                <button
                  className="icon-button"
                  aria-label="Next chunk page"
                  disabled={currentPage + 1 >= pages}
                  onClick={() => setPage(currentPage + 1)}
                >
                  <ChevronRight size={17} />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
