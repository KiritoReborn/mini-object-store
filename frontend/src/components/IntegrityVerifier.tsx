import { useEffect, useId, useRef, useState } from "react";
import { Copy, Download, ShieldCheck } from "lucide-react";
import {
  compareFileDigest,
  hashFile,
  integrityReport,
  localHashUnavailable,
  MAX_INTEGRITY_FILE_BYTES,
  type FileDigest,
  type HashProgress,
} from "../integrity";
import { saveJson } from "../system";
import "./integrity.css";

export function IntegrityVerifier({ expectedHash }: { expectedHash: string }) {
  const id = useId();
  const [file, setFile] = useState<File | null>(null);
  const [digest, setDigest] = useState<FileDigest | null>(null);
  const [progress, setProgress] = useState<HashProgress | null>(null);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const active = useRef<AbortController | null>(null);
  const root = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const element = root.current!;
    // File-picker cancellation bubbles. Keep it from dismissing the inspector.
    const stopCancel = (event: Event) => event.stopPropagation();
    element.addEventListener("cancel", stopCancel);
    return () => {
      element.removeEventListener("cancel", stopCancel);
      active.current?.abort();
    };
  }, []);

  const storedHash = /^[0-9a-f]{64}$/i.test(expectedHash)
    ? expectedHash.toLowerCase()
    : null;
  const unavailable =
    localHashUnavailable() ??
    (storedHash ? null : "The stored checksum is unavailable for this object.");
  const tooLarge = (file?.size ?? 0) > MAX_INTEGRITY_FILE_BYTES;
  const result =
    digest && storedHash ? compareFileDigest(digest, storedHash) : null;

  function cancel() {
    active.current?.abort();
    active.current = null;
    setProgress(null);
  }

  function choose(selection: File | undefined) {
    if (!selection) return; // Closing the picker preserves the selection.
    cancel();
    setFile(selection);
    setDigest(null);
    setError("");
    setFeedback("");
  }

  async function verify() {
    if (!file || unavailable || tooLarge || active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setDigest(null);
    setError("");
    setFeedback("");
    try {
      const computed = await hashFile(file, {
        signal: controller.signal,
        onProgress: (next) => {
          if (active.current === controller && !controller.signal.aborted)
            setProgress(next);
        },
      });
      if (active.current === controller && !controller.signal.aborted)
        setDigest(computed);
    } catch {
      if (active.current === controller && !controller.signal.aborted)
        setError(
          "Could not read or hash this file. Select it again and retry.",
        );
    } finally {
      if (active.current === controller) {
        active.current = null;
        setProgress(null);
      }
    }
  }

  async function copy() {
    if (!digest) return;
    try {
      await navigator.clipboard.writeText(digest.sha256);
      setFeedback("File SHA-256 copied");
    } catch {
      setFeedback(
        "Clipboard access is unavailable. Select and copy the hash instead.",
      );
    }
  }

  function exportReport() {
    if (!digest || !storedHash) return;
    try {
      saveJson(
        "artaud-integrity-report.json",
        integrityReport(digest, storedHash),
      );
    } catch {
      setFeedback("Could not export the report. Please try again.");
    }
  }

  return (
    <details className="integrity-tool" ref={root}>
      <summary>
        <ShieldCheck size={17} aria-hidden="true" />
        Verify integrity
      </summary>
      <div className="integrity-content">
        <p id={`${id}-help`}>
          Choose the original file or a downloaded copy to check it against the
          stored SHA-256. The file stays in this browser. Limit: 128 MiB.
        </p>
        {unavailable && (
          <p role="alert" className="error-text">
            {unavailable}
          </p>
        )}
        <div className="integrity-file">
          <label htmlFor={`${id}-file`}>File to verify</label>
          <input
            id={`${id}-file`}
            type="file"
            disabled={!!unavailable}
            aria-invalid={tooLarge}
            aria-describedby={`${id}-help${tooLarge ? ` ${id}-size-error` : ""}`}
            onChange={(event) => choose(event.currentTarget.files?.[0])}
          />
          {tooLarge && (
            <p id={`${id}-size-error`} role="alert" className="error-text">
              This file exceeds 128 MiB (134,217,728 bytes). Choose a smaller
              file.
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
              {digest && (
                <div>
                  <dt>SHA-256</dt>
                  <dd>
                    <code>{digest.sha256}</code>
                    <button
                      className="icon-button"
                      aria-label="Copy file SHA-256"
                      onClick={() => void copy()}
                    >
                      <Copy size={15} />
                    </button>
                  </dd>
                </div>
              )}
            </dl>
          )}
        </div>
        <div className="integrity-actions">
          <button
            className="button primary"
            disabled={!!unavailable || !file || tooLarge || !!progress}
            onClick={() => void verify()}
          >
            <ShieldCheck size={16} />
            Verify file
          </button>
          {progress && (
            <button
              className="button secondary"
              onClick={() => {
                cancel();
                setFeedback(
                  "Verification cancelled. Select Verify file to try again.",
                );
              }}
            >
              Cancel verification
            </button>
          )}
        </div>
        {progress && (
          <div className="integrity-progress">
            <p role="status">
              {progress.phase === "reading"
                ? "Reading file…"
                : "Computing SHA-256…"}
            </p>
            <progress
              aria-label={
                progress.phase === "reading"
                  ? "File read progress"
                  : "Hashing file"
              }
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
        {result && (
          <div
            className={`integrity-result ${result === "MATCH" ? "match" : "mismatch"}`}
            role="status"
            aria-atomic="true"
          >
            <h3>{result}</h3>
            <p>
              {result === "MATCH"
                ? "This file matches the stored checksum."
                : "This file’s SHA-256 differs from the stored checksum."}
            </p>
          </div>
        )}
        <button
          className="button secondary"
          disabled={!result}
          onClick={exportReport}
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
