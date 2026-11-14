import { useState } from "react";
import { ClipboardCheck, Download, RotateCcw } from "lucide-react";
import { saveJson } from "../system";
import type { Overview } from "../types";

const steps = [
  [
    "Store an object",
    "Upload a file larger than 1 MB, then download it and compare its checksum.",
  ],
  [
    "Explain chunk placement",
    "Choose the file in the placement table. Show two distinct worker copies for each chunk.",
  ],
  [
    "Edit metadata",
    "Change a custom property without re-uploading the file. Its checksum stays the same.",
  ],
  [
    "Stop one worker",
    "Use the confirmed Stop action. Explain container state versus heartbeat-based availability.",
  ],
  [
    "Show fallback and repair",
    "Download through the remaining copy. Watch your teammate’s recovery service restore redundancy.",
  ],
  [
    "Start the worker again",
    "Show Joining followed by verified availability after the recovery service reconciles its inventory.",
  ],
  [
    "Explain integrity handling",
    "Use the teammate’s corruption demo. Show detected corruption, safe fallback and observed repair.",
  ],
];

export function DemoGuide({
  overview,
  stale,
}: {
  overview: Overview | null;
  stale: boolean;
}) {
  const [completed, setCompleted] = useState<number[]>([]);
  return (
    <details className="system-section demo-guide">
      <summary>
        <ClipboardCheck size={18} />
        <strong>Demo walkthrough</strong>
        <span>
          {completed.length} / {steps.length} checked
        </span>
      </summary>
      <p className="system-footnote">
        Mark steps as you demonstrate them. These checkmarks are your notes, not
        automated test results.
      </p>
      {!stale && overview && !overview.recovery_available && (
        <p className="system-history-notice">
          Recovery is not connected yet. Admission, repair and rejoin
          demonstrations require your teammate’s module.
        </p>
      )}
      <ol>
        {steps.map(([title, body], index) => (
          <li key={title}>
            <label>
              <input
                type="checkbox"
                checked={completed.includes(index)}
                onChange={(event) =>
                  setCompleted((previous) =>
                    event.target.checked
                      ? [...previous, index]
                      : previous.filter((value) => value !== index),
                  )
                }
              />
              <span>
                <strong>{title}</strong>
                <small>{body}</small>
              </span>
            </label>
          </li>
        ))}
      </ol>
      <div className="demo-guide-actions">
        <button
          className="button secondary"
          onClick={() =>
            saveJson("artaud-demo-notes.json", {
              exported_at: new Date().toISOString(),
              source:
                "Operator self-reported walkthrough notes; not automated verification",
              snapshot_stale: stale,
              overview,
              steps: steps.map(([title], index) => ({
                title,
                operator_checked: completed.includes(index),
              })),
            })
          }
        >
          <Download size={15} />
          Export demo notes
        </button>
        <button className="text-button" onClick={() => setCompleted([])}>
          <RotateCcw size={14} />
          Reset checklist
        </button>
      </div>
    </details>
  );
}
