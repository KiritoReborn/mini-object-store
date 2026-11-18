// Web Crypto needs a complete buffer. Bound it before allocating or reading,
// and process the two files sequentially rather than retaining both buffers.
export const MAX_INTEGRITY_FILE_BYTES = 128 * 1024 * 1024;
const READ_CHUNK_BYTES = 256 * 1024;

export interface FileDigest {
  name: string;
  size: number;
  sha256: string;
}

export interface HashProgress {
  phase: "reading" | "hashing";
  bytesRead: number;
  totalBytes: number;
}

export function localHashUnavailable(): string | null {
  if (!globalThis.isSecureContext)
    return "Local SHA-256 verification requires HTTPS or localhost. Open this page in a secure context.";
  if (!globalThis.crypto?.subtle)
    return "This browser does not support Web Crypto SHA-256. Use a browser with Web Crypto support over HTTPS or localhost.";
  return null;
}

export async function hashFile(
  file: File,
  options: {
    signal?: AbortSignal;
    onProgress?: (progress: HashProgress) => void;
  } = {},
): Promise<FileDigest> {
  const unavailable = localHashUnavailable();
  if (unavailable) throw new Error(unavailable);
  if (file.size > MAX_INTEGRITY_FILE_BYTES)
    throw new Error(
      "Choose a file no larger than 128 MiB (134,217,728 bytes).",
    );
  const { signal, onProgress } = options;
  signal?.throwIfAborted();
  const bytes = new Uint8Array(file.size);
  onProgress?.({ phase: "reading", bytesRead: 0, totalBytes: file.size });
  for (let offset = 0; offset < file.size; offset += READ_CHUNK_BYTES) {
    signal?.throwIfAborted();
    const end = Math.min(offset + READ_CHUNK_BYTES, file.size);
    const chunk = await file.slice(offset, end).arrayBuffer();
    signal?.throwIfAborted();
    if (chunk.byteLength !== end - offset)
      throw new Error("The file changed while reading. Select it again.");
    bytes.set(new Uint8Array(chunk), offset);
    onProgress?.({ phase: "reading", bytesRead: end, totalBytes: file.size });
  }
  signal?.throwIfAborted();
  onProgress?.({
    phase: "hashing",
    bytesRead: file.size,
    totalBytes: file.size,
  });
  const digest = await crypto.subtle.digest("SHA-256", bytes.buffer);
  // digest() cannot be cancelled. Discard its result if selection changed.
  signal?.throwIfAborted();
  return {
    name: file.name,
    size: file.size,
    sha256: Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join(""),
  };
}

export function normalizeExpectedHash(value: string): string | null {
  const hash = value.trim().toLowerCase();
  if (!hash) return null;
  if (!/^[0-9a-f]{64}$/.test(hash))
    throw new Error(
      "Enter exactly 64 hexadecimal characters, or leave the expected hash empty.",
    );
  return hash;
}

export function compareFileDigests(
  original: FileDigest,
  downloaded: FileDigest,
  expected = "",
) {
  const expectedHash = normalizeExpectedHash(expected);
  return {
    result:
      original.size === downloaded.size && original.sha256 === downloaded.sha256
        ? ("MATCH" as const)
        : ("MISMATCH" as const),
    expected_hash: expectedHash,
    original_matches_expected: expectedHash
      ? original.sha256 === expectedHash
      : null,
    downloaded_matches_expected: expectedHash
      ? downloaded.sha256 === expectedHash
      : null,
  };
}

export function integrityReport(
  original: FileDigest,
  downloaded: FileDigest,
  expected = "",
  timestamp = new Date().toISOString(),
) {
  // Explicit fields keep File objects, contents and unrelated metadata out.
  const summary = (file: FileDigest) => ({
    name: file.name,
    size: file.size,
    sha256: file.sha256,
  });
  return {
    timestamp,
    algorithm: "SHA-256",
    scope: "Local file comparison; not a live replica audit",
    original: summary(original),
    downloaded: summary(downloaded),
    ...compareFileDigests(original, downloaded, expected),
  };
}
