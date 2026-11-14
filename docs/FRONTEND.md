# Artaud storage dashboard

The user authorized a frontend in addition to the original API/CLI scope on 14 November 2026. The React/TypeScript interface talks to the real controller on the same origin. It uses original plain-CSS components, Lucide icons and a self-hosted Geist font. No separate cloud hosting service, Node production runtime or third-party runtime font request is needed.

## Run

The built UI is committed under `controller/static` and is copied by the existing controller Dockerfile. `docker compose up --build -d` serves it at `http://localhost:8000/` alongside the object APIs. Never manufacture ALIVE workers to make the screen look healthy; normal registration remains JOINING until B's reconciler verifies inventories.

For frontend development:

```powershell
cd frontend
npm ci
npm run dev
```

Vite serves `http://127.0.0.1:5173` and forwards API/health/docs calls to the local controller at port 8000. Start the controller as documented in CONTROLLER.md. Node 22.23.2 was used in this implementation; dependency versions are locked by package-lock.json.

After editing, run `npm run build` to typecheck and regenerate the committed controller/static output, then restart/rebuild the controller to load its assets. The output directory is generated and owned by the frontend build; edit frontend/src, not minified assets.

## Features and state boundaries

- File search, MIME-based filtering, sorting and ten-row pagination.
- Native chooser/drag-and-drop, multi-file queue, per-file cancellation/requeue/error state and actual upload progress. Sending 100% is followed by confirmation; only controller 201 means Stored. Removing a waiting file prevents its later upload.
- Downloads stream to a user-selected writable file when the browser supports that capability. Other browsers use a Blob/object-URL fallback, which buffers the response and may use browser-managed memory/disk. File chooser cancellation is not reported as download success. Errors stay inside the workspace/inspector.
- The inspector exposes required metadata, checksum, ordered chunk/replica states, and JSON custom metadata editing. It sends only edited/new top-level keys so unrelated concurrent edits survive. The server still uses last-writer-wins for the same key. Omitting a key preserves it; key deletion is not part of the API.
- Chunk details refresh when opened, when the overview polls while that tab is open, and after downloads that can discover corruption. Background snapshots never overwrite unsaved metadata text or its edit baseline.
- Delete requires specific confirmation. In-flight deletion visibly disables the close/keep controls. Offline physical cleanup remains eventual.
- The cluster rail/page reports actual registered nodes, recorded copies/bytes, fresh-heartbeat availability and replication coverage. It does not invent capacity or throughput. Failed refreshes mark node/replica state unknown; old file lists are labeled as snapshots.
- Native dialogs supply focus trapping and Escape behavior. Search has a `/` shortcut outside editors/dialogs. Focus rings, contrast, reduced motion and structural layouts at 320/390/768/1280+ widths are tested.

## Tests

```powershell
cd frontend
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Frontend unit tests exercise metadata/format/API boundaries. Playwright tests exercise the UI against clearly test-only HTTP fixtures and include WCAG A/AA checks with axe. Fixtures never ship in the production app or replace real API data.

For an actual controller + four real workers, from the checkout root after building both existing Dockerfiles:

```powershell
python tests/live_controller_check.py --controller-image mini-object-store-controller:review --worker-image mini-object-store-worker-review:6a8d653 --browser
```

Use image names you built. The harness creates a private test topology and a temporary loopback-only controller port. It first verifies real empty/JOINING state. It then verifies inventories and supplies eligibility in test-only code to exercise browser upload/PATCH/chunks/download/delete, controller failure/corruption handling and large transfers. It removes only its own test resources. It does not substitute for or prove B's production reconciler.

## Sources, visual truth and continuation

Interaction references and direction are in dashboard-design.md; built design tokens belong in the root DESIGN.md. User-facing factual state comes from `/api/v1/objects`, object metadata and `/api/v1/overview`, not the design references.

The Sites plugin was considered and its local-only workflow used: cloud-hosting an interface to private local Docker services would introduce an unnecessary connectivity boundary. The design context binary was unavailable, so product context and the design references were read directly; no automated design detector is claimed. The author inspected browser screenshots directly. An independent visual reviewer could not complete because its service usage limit was reached; no independent visual approval is claimed.

Read HANDOFF.md for current verified counts, publication status and B-owned work still pending.
