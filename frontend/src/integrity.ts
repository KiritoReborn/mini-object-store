// Web Crypto needs a complete buffer. Check the size before allocating or reading.
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

export function compareFileDigest(file: FileDigest, storedHash: string) {
  return file.sha256 === storedHash ? "MATCH" : "MISMATCH";
}

export function integrityReport(
  file: FileDigest,
  storedHash: string,
  timestamp = new Date().toISOString(),
) {
  // Explicit fields keep File objects, contents and unrelated metadata out.
  return {
    timestamp,
    algorithm: "SHA-256",
    scope: "Local file verification against stored object checksum",
    file: { name: file.name, size: file.size, sha256: file.sha256 },
    expected_hash: storedHash,
    result: compareFileDigest(file, storedHash),
  };
}
