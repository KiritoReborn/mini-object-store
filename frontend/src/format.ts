const reserved = new Set([
  "object_id",
  "name",
  "size",
  "content_type",
  "created_at",
  "updated_at",
  "sha256",
  "num_chunks",
  "chunks",
  "status",
]);

export function bytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 1000) return `${value} B`;
  const exponent = Math.min(Math.floor(Math.log10(value) / 3), 4);
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value / 1000 ** exponent)} ${["B", "kB", "MB", "GB", "TB"][exponent]}`;
}

export function parseMetadata(text: string): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(
      'Enter valid JSON, for example {"project": "Cloud computing"}.',
    );
  }
  if (value === null || Array.isArray(value) || typeof value !== "object")
    throw new Error("Metadata must be a JSON object with key-value pairs.");
  if (Object.keys(value).some((key) => reserved.has(key)))
    throw new Error(
      "System fields such as name, size and checksum cannot be changed.",
    );
  const encoded = JSON.stringify(value, (_key, item) => {
    if (typeof item === "number" && !Number.isFinite(item))
      throw new Error("Metadata numbers must be finite.");
    return item;
  });
  if (new TextEncoder().encode(encoded).length > 32_768)
    throw new Error("Metadata must be no larger than 32 kB.");
  return value as Record<string, unknown>;
}

export function fileKind(mime: string): string {
  if (mime.startsWith("image/")) return "Image";
  if (mime.startsWith("video/")) return "Video";
  if (mime.startsWith("audio/")) return "Audio";
  if (/zip|compressed|tar|gzip|7z/.test(mime)) return "Archive";
  if (/json|javascript|xml/.test(mime)) return "Code";
  if (mime.startsWith("text/") || mime === "application/pdf") return "Document";
  return "File";
}

export function dateLabel(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.valueOf())
    ? "—"
    : new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      }).format(date);
}

export function seenAgo(age: number | null): string {
  if (age === null) return "No heartbeat";
  if (age < 0) return "Clock mismatch";
  if (age < 2) return "Just now";
  if (age < 60) return `${Math.floor(age)}s ago`;
  return `${Math.floor(age / 60)}m ago`;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}
