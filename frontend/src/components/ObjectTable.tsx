import { useEffect, useMemo, useState, type RefObject } from "react";
import {
  ArrowDown,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Download,
  Files,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { bytes, dateLabel, fileKind } from "../format";
import type { StoredObject } from "../types";
import { FileIcon } from "./FileIcon";
import { matchesObject, saveCsv, type SearchScope } from "../object-tools";
import { saveJson } from "../system";
import { BulkDeleteDialog } from "./BulkDeleteDialog";

export function ObjectTable({
  objects,
  loading,
  error,
  onInspect,
  onDownload,
  searchRef,
  onChanged,
}: {
  objects: StoredObject[];
  loading: boolean;
  error: string | null;
  onInspect: (object: StoredObject) => void;
  onDownload: (object: StoredObject) => void;
  searchRef: RefObject<HTMLInputElement | null>;
  onChanged: () => Promise<void>;
}) {
  const [search, setSearch] = useState(""),
    [kind, setKind] = useState("All types");
  const [scope, setScope] = useState<SearchScope>("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batch, setBatch] = useState<StoredObject[] | null>(null);
  const [sort, setSort] = useState<"name" | "size" | "created_at">(
      "created_at",
    ),
    [ascending, setAscending] = useState(false),
    [page, setPage] = useState(0);
  const filtered = useMemo(
    () =>
      objects
        .filter(
          (o) =>
            matchesObject(o, search, scope) &&
            (kind === "All types" || fileKind(o.content_type) === kind),
        )
        .sort(
          (a, b) =>
            (sort === "size"
              ? a.size - b.size
              : a[sort].localeCompare(b[sort])) * (ascending ? 1 : -1),
        ),
    [objects, search, scope, kind, sort, ascending],
  );
  useEffect(() => {
    setPage(0);
    setSelectedIds(new Set());
  }, [search, kind, scope]);
  const pages = Math.max(1, Math.ceil(filtered.length / 10)),
    currentPage = Math.min(page, pages - 1),
    rows = filtered.slice(currentPage * 10, (currentPage + 1) * 10);
  const selected = objects.filter((file) => selectedIds.has(file.object_id));
  const unavailable = loading || !!error;
  const pageSelected =
    rows.length > 0 && rows.every((file) => selectedIds.has(file.object_id));
  const exportJson = (files: StoredObject[]) =>
    saveJson("artaud-file-listing.json", {
      captured_at: new Date().toISOString(),
      snapshot_status: error ? "stale" : "current",
      query: search,
      scope,
      type_filter: kind,
      count: files.length,
      files,
    });
  const toggleSort = (key: typeof sort) => {
    setAscending(sort === key ? !ascending : key === "name");
    setSort(key);
  };
  return (
    <section className="file-section" aria-labelledby="files-heading">
      <div className="section-title">
        <h2 id="files-heading">
          All files <span className="count">{objects.length}</span>
        </h2>
        <span className="quiet-label">Only completed uploads</span>
      </div>
      <div className="table-toolbar">
        <div className="search-field">
          <Search size={17} aria-hidden="true" />
          <input
            ref={searchRef}
            type="search"
            aria-label="Search files"
            placeholder="Search files…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {search ? (
            <button
              className="icon-button small"
              aria-label="Clear search"
              onClick={() => setSearch("")}
            >
              <X size={15} />
            </button>
          ) : (
            <kbd>/</kbd>
          )}
        </div>
        <select
          aria-label="Search scope"
          value={scope}
          onChange={(event) => setScope(event.target.value as SearchScope)}
        >
          <option value="all">Name, ID & metadata</option>
          <option value="name">Filename</option>
          <option value="id">Object ID</option>
          <option value="metadata">Custom metadata</option>
        </select>
        <select
          aria-label="Filter file type"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
        >
          {[
            "All types",
            "Document",
            "Image",
            "Video",
            "Audio",
            "Archive",
            "Code",
            "File",
          ].map((type) => (
            <option key={type}>{type}</option>
          ))}
        </select>
      </div>
      <div className="listing-actions">
        <span>
          {selected.length
            ? `${selected.length} selected`
            : "Exports include custom metadata; file bytes stay in storage."}
        </span>
        {!!selected.length && (
          <>
            <button
              className="button secondary"
              onClick={() => setSelectedIds(new Set())}
            >
              Clear selection
            </button>
            <button
              className="button secondary"
              disabled={unavailable}
              onClick={() => exportJson(selected)}
            >
              Export selected JSON
            </button>
            <button
              className="button danger"
              disabled={unavailable}
              onClick={() => setBatch([...selected])}
            >
              <Trash2 size={14} />
              Delete selected
            </button>
          </>
        )}
        <button
          className="button secondary"
          disabled={loading || !filtered.length}
          onClick={() => saveCsv(filtered, !!error)}
        >
          Export filtered CSV
        </button>
        <button
          className="button secondary"
          disabled={loading || !filtered.length}
          onClick={() => exportJson(filtered)}
        >
          Export filtered JSON
        </button>
      </div>
      {selected.some(
        (file) => !rows.some((row) => row.object_id === file.object_id),
      ) && (
        <p className="selection-note">
          Includes files you selected on other pages. Changing search or filters
          clears selection.
        </p>
      )}
      {batch && (
        <BulkDeleteDialog
          files={batch}
          stale={unavailable}
          onClose={() => setBatch(null)}
          onFinished={async (removed) => {
            setSelectedIds(
              (current) =>
                new Set([...current].filter((id) => !removed.includes(id))),
            );
            await onChanged();
          }}
        />
      )}
      {loading ? (
        <div
          className="table-skeleton"
          aria-label="Loading files"
          role="status"
        >
          {[1, 2, 3, 4].map((n) => (
            <div key={n}>
              <span />
              <i />
              <i />
            </div>
          ))}
        </div>
      ) : !objects.length && !error ? (
        <div className="empty-state">
          <span className="empty-icon">
            <Files size={28} strokeWidth={1.3} />
          </span>
          <h3>Make room for your first file</h3>
          <p>
            Documents, photos, code, or something entirely different.
            <br />
            Choose a file above to get started.
          </p>
          <span className="empty-footnote">
            Your original bytes. Safely chunked and replicated.
          </span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state compact">
          <Search size={26} />
          <h3>No matching files</h3>
          <p>Try another name, object ID, metadata value or file type.</p>
          <button
            className="button secondary"
            onClick={() => {
              setSearch("");
              setKind("All types");
            }}
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="object-table">
            <thead>
              <tr>
                {(["name", "size"] as const).map((key) => (
                  <th
                    key={key}
                    aria-sort={
                      sort === key
                        ? ascending
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    {key === "name" && (
                      <input
                        type="checkbox"
                        aria-label="Select this page"
                        checked={pageSelected}
                        disabled={unavailable}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setSelectedIds((current) => {
                            const next = new Set(current);
                            rows.forEach((file) =>
                              checked
                                ? next.add(file.object_id)
                                : next.delete(file.object_id),
                            );
                            return next;
                          });
                        }}
                      />
                    )}
                    <button onClick={() => toggleSort(key)}>
                      {key === "name" ? "Name" : "Size"}
                      {sort === key ? (
                        <ArrowDown
                          size={13}
                          className={ascending ? "flipped" : ""}
                        />
                      ) : (
                        <ArrowUpDown size={13} />
                      )}
                    </button>
                  </th>
                ))}
                <th className="hide-narrow">Chunks</th>
                <th
                  className="hide-medium"
                  aria-sort={
                    sort === "created_at"
                      ? ascending
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button onClick={() => toggleSort("created_at")}>
                    Added{" "}
                    <ArrowDown
                      size={13}
                      className={ascending ? "flipped" : ""}
                    />
                  </button>
                </th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((object) => (
                <tr key={object.object_id}>
                  <td>
                    <div className="file-name-cell">
                      <input
                        type="checkbox"
                        aria-label={`Select ${object.name}`}
                        checked={selectedIds.has(object.object_id)}
                        disabled={unavailable}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setSelectedIds((current) => {
                            const next = new Set(current);
                            checked
                              ? next.add(object.object_id)
                              : next.delete(object.object_id);
                            return next;
                          });
                        }}
                      />
                      <FileIcon mime={object.content_type} />
                      <button
                        className="file-name"
                        aria-label={object.name}
                        onClick={() => onInspect(object)}
                        title={object.name}
                      >
                        {object.name}
                        <span>
                          {fileKind(object.content_type)}{" "}
                          <span className="mobile-size">
                            · {bytes(object.size)}
                          </span>
                        </span>
                      </button>
                    </div>
                  </td>
                  <td className="size-cell">{bytes(object.size)}</td>
                  <td className="hide-narrow muted">{object.num_chunks}</td>
                  <td className="hide-medium muted">
                    {dateLabel(object.created_at)}
                  </td>
                  <td className="row-action">
                    <button
                      className="icon-button"
                      aria-label={`Download ${object.name}`}
                      title="Download file"
                      onClick={() => onDownload(object)}
                    >
                      <Download size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!!filtered.length && !loading && (
        <div className="table-footer">
          <span>
            {currentPage * 10 + 1}–
            {Math.min((currentPage + 1) * 10, filtered.length)} of{" "}
            {filtered.length} files
          </span>
          <div>
            <button
              className="icon-button"
              aria-label="Previous page"
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
              aria-label="Next page"
              disabled={currentPage + 1 >= pages}
              onClick={() => setPage(currentPage + 1)}
            >
              <ChevronRight size={17} />
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
