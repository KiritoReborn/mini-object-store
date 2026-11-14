# Frontend development

[Overview](../README.md) · [Live dashboard](https://frontend-nine-iota-19.vercel.app/) · [Design system](../DESIGN.md) · [Demo setup](DEMO.md)

The dashboard is React and TypeScript with Vite, plain CSS, Lucide icons and a self-hosted Geist font. It calls the real controller API. Production assets are committed under `controller/static`; no Node process is needed to serve the local app.

## Develop and build

Use a Node.js version supported by the locked Vite dependencies; Node 22.23.2 was used for local verification. From the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Vite serves http://127.0.0.1:5173 and proxies API/health/docs calls to the local controller at port `8000`. Start that controller separately. An existing owner-key configuration still applies; enter the key through Connection settings.

```sh
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

`npm run build` typechecks and regenerates `controller/static`. Edit source under `frontend/src`, then include the generated static changes and rebuild/recreate the controller. Vercel builds use `dist` instead. Never hand-edit the minified bundle. Normal local builds use the serving controller as the API origin; public builds use `VITE_API_BASE_URL`.

## Main source areas

| Area                              | Files                                                                                                                 |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Application shell and requests    | `src/App.tsx`, `src/api.ts`, `src/connection.ts`                                                                      |
| File tools                        | `components/ObjectTable.tsx`, `UploadPanel.tsx`, `ObjectInspector.tsx`, `BulkDeleteDialog.tsx`, `src/object-tools.ts` |
| Cluster and recovery observations | `components/SystemExplorer.tsx`, `TopologyMap.tsx`, `ObjectPlacement.tsx`, `RecoveryPanel.tsx`, `src/useActivity.ts`  |
| Owner controls and diagnostics    | `components/WorkerManager.tsx`, `ConnectionSettings.tsx`, `RequestDiagnostics.tsx`, `src/diagnostics.ts`              |
| Visual system                     | `src/styles.css`, `components/system.css`, root `DESIGN.md`                                                           |
| Verification                      | `src/*.test.ts`, `e2e/workspace.spec.ts`, explicitly invoked live scripts                                             |

## Behavior to preserve

- Upload100% means the browser finished sending, not that storage is confirmed. Only controller201 produces Stored. Waiting files can be removed; in-flight cancellation and retry have explicit states.
- Downloads use the browser's writable-file capability when supported. The Blob fallback buffers the response and may use browser-managed memory/disk. Chooser cancellation is not success.
- Metadata editing sends only changed/new top-level keys. Unspecified keys survive, same-key conflicts remain last-writer-wins, and the API does not implement key deletion. Refresh must not overwrite unsaved edits.
- Search covers filename, ID and literal custom metadata without reading object bytes. Listing exports preserve capture/snapshot labels; CSV neutralizes formula prefixes.
- Bulk deletion confirms names and DELETE text, performs serial requests, retains unresolved selections and stops after uncertain/auth failures. It never reports an ambiguous response as confirmed deletion.
- The owner key remains in page memory and is cleared on reload. It never enters build variables, browser storage, screenshots or diagnostic output. Connection preferences are distinct from credentials.
- Recorded node bytes/counts are not physical free space or disk capacity. Failed refreshes mark state unknown/stale. Container running state is separate from admission and upload-placement pause.
- Activity is bounded and process-local. Transfer travel/replay is an observation, not packet timing or throughput. Detailed recovery-transfer motion requires explicit events from real recovery. Read [LIVE_SYSTEM.md](LIVE_SYSTEM.md).
- Preserve focus management, native dialog behavior, keyboard search, reduced motion, text/table alternatives and narrow-screen layouts. Browser tests include axe accessibility checks.

## Test scopes

Vitest covers request, metadata, formatting, connection and export boundaries. Playwright's normal UI suite uses explicit HTTP fixtures, including failure/stale states; those fixtures never ship in the runtime bundle. These checks do not by themselves prove Docker recovery.

For the actual production controller/reconciler plus four real workers, build the integration images and run from the repository root:

```sh
python tests/test_end_to_end.py --large --browser
```

Install frontend dependencies and Chromium first. This harness creates its own network, containers and volumes; it never manually grants ALIVE. It covers real browser upload/PATCH/chunks/hash-download/delete and actual failure recovery. See [ACCEPTANCE.md](ACCEPTANCE.md) for builds, backend commands and dated results.

`tests/live_controller_check.py` is historical pre-recovery A-only evidence. Do not use it as the current integration gate. The owner-invoked `frontend/e2e/live-public-demo.mjs` targets the actual public demo, privately reads the local key and creates/removes one uniquely named QA object; it is intentionally separate from the normal fixture suite.

For continuation, read [HANDOFF.md](HANDOFF.md), [PRODUCT.md](../PRODUCT.md), [DESIGN.md](../DESIGN.md) and [the HTTP contract](../contracts/api-contract.md).
