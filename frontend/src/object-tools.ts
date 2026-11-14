import type { StoredObject } from "./types";

export type SearchScope = "all" | "name" | "id" | "metadata";

function metadataText(metadata: Record<string, unknown>): string {
  const pending: unknown[] = [metadata];
  const text: string[] = [];
  while (pending.length) {
    const value = pending.pop();
    if (Array.isArray(value)) pending.push(...value);
    else if (value !== null && typeof value === "object") {
      for (const [key, child] of Object.entries(value)) {
        text.push(key);
        pending.push(child);
      }
    } else text.push(String(value));
  }
  return text.join(" ");
}

export function matchesObject(
  file: StoredObject,
  query: string,
  scope: SearchScope,
): boolean {
  const needle = query.trim().toLocaleLowerCase();
  const values = {
    name: file.name,
    id: file.object_id,
    metadata:
      scope === "name" || scope === "id" ? "" : metadataText(file.metadata),
  };
  return (scope === "all" ? Object.values(values).join(" ") : values[scope])
    .toLocaleLowerCase()
    .includes(needle);
}

export function listingCsv(
  files: StoredObject[],
  stale = false,
  capturedAt = new Date().toISOString(),
): string {
  const cell = (value: unknown) => {
    const text = String(value);
    const safe =
      /^[\s]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text) ? "'" + text : text;
    return '"' + safe.replaceAll('"', '""') + '"';
  };
  const rows = files.map((file) => [
    stale ? "stale" : "current",
    capturedAt,
    file.name,
    file.object_id,
    file.size,
    file.content_type,
    file.created_at,
    file.sha256,
    JSON.stringify(file.metadata),
  ]);
  return [
    [
      "snapshot_status",
      "captured_at",
      "name",
      "object_id",
      "bytes",
      "content_type",
      "created_at",
      "sha256",
      "custom_metadata",
    ],
    ...rows,
  ]
    .map((row) => row.map(cell).join(","))
    .join("\r\n");
}

export function saveCsv(files: StoredObject[], stale = false): void {
  const url = URL.createObjectURL(
    new Blob(["\uFEFF", listingCsv(files, stale)], {
      type: "text/csv;charset=utf-8",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "artaud-file-listing.csv";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
