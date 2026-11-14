# Dashboard design and implementation plan

Mode: Operate. Audience: project members and demonstrators managing real stored objects.

## Direction contract

THESIS: a precise file workspace, with system truth visible alongside the task. Objects lead; infrastructure explains availability without competing for attention.

OWN-WORLD: cool-white workspace, pale mineral side navigation, deep green primary actions, near-black text, fine neutral separators. One workhorse sans, tabular measurements, consistent Lucide outline icons. File rows rather than a wall of dashboard cards.

STORY: see what's stored and whether storage can accept files; choose/drop files; track sending versus confirmation; inspect metadata and chunk locations; download or deliberately delete.

FIRST VIEWPORT: narrow left navigation; main heading and upload action; compact text-based storage summary; inline upload surface; searchable/sortable paginated object table; right-hand live cluster panel on wide screens. On narrow screens navigation becomes a compact top bar, cluster moves below the file task, and details fit the viewport.

FORM: a file workspace with a live system rail, selected over a chart-heavy monitoring console or a generic metric-card grid. seed: none (unavailable). The user delegated direction and implementation; no existing visual identity was present.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Technical decisions

- React + TypeScript + Vite; plain CSS tokens, Lucide icons. Build output is committed under controller/static so the existing controller Dockerfile can serve the UI without a Node runtime or B-owned Docker edits.
- Same-origin requests to the six existing public APIs; a separate read-only /api/v1/overview returns real worker/replication summaries, distinct from B's /admin/status router.
- Native file input and drag/drop; real upload progress via XMLHttpRequest. Success only after server 201, never after sending reaches 100%.
- Native accessible dialogs for object inspection and protected delete confirmation; keyboard navigation, visible focus, reduced-motion handling, mobile layout.
- No live-demo data switch or fabricated charts in production. Browser QA fixtures remain test-only. Normal empty/degraded states must also be inspected.

## Implementation checklist

- [x] Recheck Member A scope and current upstream work; preserve B ownership.
- [x] Add/test real overview API and safe static serving, including missing API route 404 and snapshot accuracy.
- [x] Build file browsing/search/sort/pagination, upload queue, downloads, metadata editor, chunk inspector, delete confirmation and cluster view.
- [x] Validate errors, unavailable storage, keyboard focus, overflow and narrow layouts.
- [x] Run backend suite, TypeScript/build, frontend behavior/browser tests and direct visual review. Independent visual review was unavailable due service usage limit; no independent visual approval claimed.
- [x] Record the built design system, references, results, remaining dependencies and feature-branch publication destination. Exact Git status is in the handoff/current branch history.

## Research used

- [IBM Carbon data tables](https://carbondesignsystem.com/components/data-table/usage/): clear table hierarchy, search and contextual row actions.
- [IBM Carbon file uploader](https://carbondesignsystem.com/components/file-uploader/usage/): file chooser plus drop target, per-file progress/error states and keyboard access.
- [Vercel Geist](https://vercel.com/geist/introduction): consistent developer-tool primitives and restrained information hierarchy.
- [Cloudflare R2 object workflow](https://developers.cloudflare.com/r2/objects/upload-objects/): object-centric storage operations. This project is not S3 compatible and makes no R2 feature claims.

Research guides interaction patterns; the implementation and product language are original. No external brand assets or raster decoration are required for this operational interface.
