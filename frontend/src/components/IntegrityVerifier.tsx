import { useEffect, useId, useRef, useState } from "react";
import { Copy, Download, ShieldCheck } from "lucide-react";
import {
  compareFileDigests,
  hashFile,
  integrityReport,
  localHashUnavailable,
  MAX_INTEGRITY_FILE_BYTES,
  normalizeExpectedHash,
  type FileDigest,
  type HashProgress,
} from "../integrity";
import { saveJson } from "../system";
import "./integrity.css";

const roles = ["original", "downloaded"] as const;
type FileRole = (typeof roles)[number];
const labels = { original: "Original", downloaded: "Downloaded" };

export function IntegrityVerifier({ expectedHash }: { expectedHash: string }) {
  const id = useId();
  const [files, setFiles] = useState<Record<FileRole, File | null>>({
    original: null,
    downloaded: null,
  });
  const [hashes, setHashes] = useState<Record<FileRole, FileDigest> | null>(
    null,
  );
  const [expected, setExpected] = useState(expectedHash);
  const [progress, setProgress] = useState<
    (HashProgress & { role: FileRole }) | null
  >(null);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const active = useRef<AbortController | null>(null);
  const root = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const element = root.current!;
    // File-picker cancellation bubbles; keep it from dismissing the inspector.
    const stopCancel = (event: Event) => event.stopPropagation();
    element.addEventListener("cancel", stopCancel);
    return () => {
      element.removeEventListener("cancel", stopCancel);
      active.current?.abort();
    };
  }, []);

  const unavailable = localHashUnavailable();
  let expectedError = "";
  try {
    normalizeExpectedHash(expected);
  } catch {
    expectedError =
      "Enter exactly 64 hexadecimal characters, or leave the expected hash empty.";
  }
  const tooLarge = roles.some(
    (role) => (files[role]?.size ?? 0) > MAX_INTEGRITY_FILE_BYTES,
  );
  const comparison =
    hashes && !expectedError
      ? compareFileDigests(hashes.original, hashes.downloaded, expected)
      : null;

  function cancel() {
    active.current?.abort();
    active.current = null;
    setProgress(null);
  }
  function choose(role: FileRole, file: File | undefined) {
    if (!file) return; // Closing the picker preserves the existing comparison.
    cancel();
    setFiles((current) => ({ ...current, [role]: file }));
    setHashes(null);
    setError("");
    setFeedback("");
  }
  async function compare() {
    if (
      !files.original ||
      !files.downloaded ||
      unavailable ||
      expectedError ||
      tooLarge
    )
      return;
    cancel();
    const controller = new AbortController();
    active.current = controller;
    setHashes(null);
    setError("");
    setFeedback("");
    const read = (role: FileRole) =>
      hashFile(files[role]!, {
        signal: controller.signal,
        onProgress: (next) => {
          if (active.current === controller && !controller.signal.aborted)
            setProgress({ role, ...next });
        },
      });
    try {
      const original = await read("original");
      const downloaded = await read("downloaded");
      if (active.current === controller && !controller.signal.aborted)
        setHashes({ original, downloaded });
    } catch {
      if (active.current === controller && !controller.signal.aborted)
        setError(
          "Could not read or hash these files. Select them again and retry.",
        );
    } finally {
      if (active.current === controller) {
        active.current = null;
        setProgress(null);
      }
    }
  }
  async function copy(role: FileRole) {
    if (!hashes) return;
    try {
      await navigator.clipboard.writeText(hashes[role].sha256);
      setFeedback(`${labels[role]} SHA-256 copied`);
    } catch {
      setFeedback(
        "Clipboard access is unavailable. Select and copy the hash instead.",
      );
    }
  }

  return (
    <details className="integrity-tool" ref={root}>
      <summary>
        <ShieldCheck size={17} aria-hidden="true" />
        Verify integrity
      </summary>
      <div className="integrity-content">
        <p id={`${id}-privacy`}>
          Compare two local files using SHA-256. File contents stay in this
          browser and are never uploaded by this tool.
        </p>
        <p id={`${id}-limit`}>
          Limit: 128 MiB (134,217,728 bytes) per file. Files are read one at a
          time; Web Crypto buffers a complete file in memory.
        </p>
        {unavailable && (
          <p role="alert" className="error-text">
            {unavailable}
          </p>
        )}
        {roles.map((role) => {
          const file = files[role];
          const oversized = !!file && file.size > MAX_INTEGRITY_FILE_BYTES;
          return (
            <div className="integrity-file" key={role}>
              <label htmlFor={`${id}-${role}`}>{labels[role]} file</label>
              <input
                id={`${id}-${role}`}
                type="file"
                disabled={!!unavailable}
                aria-invalid={oversized}
                aria-describedby={`${id}-limit${oversized ? ` ${id}-${role}-error` : ""}`}
                onChange={(event) =>
                  choose(role, event.currentTarget.files?.[0])
                }
              />
              {oversized && (
                <p
                  id={`${id}-${role}-error`}
                  role="alert"
                  className="error-text"
                >
                  This file exceeds 128 MiB (134,217,728 bytes). Choose a
                  smaller file.
                </p>
              )}
              {file && (
                <dl>
                  <div>
                    <dt>Name</dt>
                    <dd>{file.name}</dd>
                  </div>
                  <div>
                    <dt>Size</dt>
                    <dd>{file.size.toLocaleString()} bytes</dd>
                  </div>
                  <div>
                    <dt>SHA-256</dt>
                    <dd>
                      {hashes ? (
                        <>
                          <code>{hashes[role].sha256}</code>
                          <button
                            className="icon-button"
                            aria-label={`Copy ${role} SHA-256`}
                            onClick={() => void copy(role)}
                          >
                            <Copy size={15} />
                          </button>
                        </>
                      ) : (
                        "Not yet calculated"
                      )}
                    </dd>
                  </div>
                </dl>
              )}
            </div>
          );
        })}
        <div className="integrity-expected">
          <label htmlFor={`${id}-expected`}>Expected SHA-256 (optional)</label>
          <input
            id={`${id}-expected`}
            value={expected}
            onChange={(event) => {
              setExpected(event.target.value);
              setFeedback("");
            }}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            aria-invalid={!!expectedError}
            aria-describedby={`${id}-expected-help${expectedError ? ` ${id}-expected-error` : ""}`}
          />
          <p id={`${id}-expected-help`}>
            Prefilled from this object's stored checksum. Paste a different
            SHA-256 or clear it to compare only the two local files.
          </p>
          <button
            className="text-button"
            onClick={() => setExpected(expectedHash)}
          >
            Use object checksum
          </button>
          {expectedError && (
            <p id={`${id}-expected-error`} role="alert" className="error-text">
              {expectedError}
            </p>
          )}
        </div>
        <div className="integrity-actions">
          <button
            className="button primary"
            disabled={
              !!unavailable ||
              !files.original ||
              !files.downloaded ||
              tooLarge ||
              !!expectedError ||
              !!progress
            }
            onClick={() => void compare()}
          >
            <ShieldCheck size={16} />
            Compare files
          </button>
          {progress && (
            <button
              className="button secondary"
              onClick={() => {
                cancel();
                setFeedback(
                  "Comparison cancelled. Compare files to try again.",
                );
              }}
            >
              Cancel comparison
            </button>
          )}
        </div>
        {progress && (
          <div className="integrity-progress" aria-busy="true">
            <p role="status">
              {progress.phase === "reading"
                ? `Reading ${labels[progress.role].toLowerCase()} file…`
                : `Computing ${labels[progress.role].toLowerCase()} SHA-256…`}
            </p>
            <progress
              aria-label={`${labels[progress.role]} file ${progress.phase === "reading" ? "read progress" : "hashing"}`}
              max={Math.max(1, progress.totalBytes)}
              value={
                progress.phase === "reading" ? progress.bytesRead : undefined
              }
            />
          </div>
        )}
        {error && (
          <p role="alert" className="error-text">
            {error}
          </p>
        )}
        {comparison && (
          <div
            className={`integrity-result ${comparison.result === "MATCH" ? "match" : "mismatch"}`}
            role="status"
            aria-atomic="true"
          >
            <h3>Files: {comparison.result}</h3>
            <p>
              {comparison.result === "MATCH"
                ? "The files have the same size and SHA-256."
                : "The files differ in size or SHA-256."}
            </p>
            {comparison.expected_hash && (
              <>
                <p>
                  Original vs expected:{" "}
                  {comparison.original_matches_expected ? "MATCH" : "MISMATCH"}
                </p>
                <p>
                  Downloaded vs expected:{" "}
                  {comparison.downloaded_matches_expected
                    ? "MATCH"
                    : "MISMATCH"}
                </p>
              </>
            )}
          </div>
        )}
        <p>
          Selecting the same file twice will match, but does not prove an
          upload/download round trip. Choose the original and retrieved copy
          separately.
        </p>
        <button
          className="button secondary"
          disabled={!comparison || !!progress}
          onClick={() => {
            if (!hashes || !comparison) return;
            try {
              saveJson(
                "artaud-integrity-report.json",
                integrityReport(hashes.original, hashes.downloaded, expected),
              );
            } catch {
              setFeedback("Could not export the report. Please try again.");
            }
          }}
        >
          <Download size={16} />
          Export integrity report
        </button>
        <p role="status" aria-atomic="true">
          {feedback}
        </p>
      </div>
    </details>
  );
}
