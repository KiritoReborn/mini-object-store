# Controller work handoff

Read this file first when continuing in Codex, Claude or a new chat.

## Scope and baseline

**New user scope (14 November 2026):** complete remaining A work and add a fully connected frontend. Frontend lives in `frontend/`; generated build in `controller/static/` is served by the same controller. Read `docs/FRONTEND.md`, `PRODUCT.md` and `docs/dashboard-design.md` for this extension. Earlier A completion evidence below remains historical; the current extension adds a dashboard overview/static routes and extra cancellation hardening.

**Current completion:** Member A's controller and frontend are implemented, built, tested and running locally at `http://localhost:8000/`. Source/build, design tokens, contracts and continuation notes are included in this feature-branch update. The earlier controller work was merged into `master` as `3e02c61`; this branch was synchronized with that merge without file conflicts. Use `git log` and the branch upstream for the exact current publication commit.

- Member A owns controller config/models/database/placement/object APIs/main and their tests.
- Member B owns worker code, recovery.py, status.py, Docker/Compose, CLI and reliability tests. Those files remain unchanged during A's implementation.
- Baseline: `6a8d653`; working branch: `feature/controller`. User requested synchronization so the completed code can be pushed; any publication belongs on the feature branch, with no force push or merge to the shared branch.
- Design and checklist: `docs/superpowers/plans/2026-11-14-member-a-implementation-plan.md`.
- Worker verification: `docs/reviews/2026-11-14-worker-handoff-review.md`.
- Controller independent review and resolutions: `docs/reviews/2026-11-14-controller-review.md`.

## Execution ledger

Implementation started 14 November 2026 (India time). Update this section at each verified milestone.

- Pre-flight: database helpers -> object services -> routes -> B recovery/status. Keep shared helpers synchronous; async request code runs SQLite calls in a thread pool. Public READY visibility is separate from internal manifest visibility.
- Ruling: reuse this checkout on a feature branch rather than create another worktree; retain existing planning/review artifacts.
- Ruling: keep the flat controller entry point required by B's Dockerfile; the legacy starter entry point will be removed.
- Ruling: keep B-owned recovery/status files absent until B delivers them. Controller reports the missing integration and safely leaves workers JOINING; it does not silently substitute an unfinished reconciler.
- Ruling: controller owns its SQL schema inside controller/ so the existing Dockerfile includes it. Contract docs point to that authoritative source rather than duplicate DDL.
- Ruling: A publishes exact helper shapes now as an implementation contract for B; teammate acceptance is still pending. Freeze changes jointly when integrating.
- Foundation: failing tests observed first, then database/placement implementation; 11 foundation tests passed.
- Object APIs: failing chunking/API tests observed first, then all six routes and transfer/lifecycle implementation. Full Linux suite: **83 passed** (42 existing worker + 41 controller cases). Existing upstream TestClient deprecation warning remains.
- Hardening: reproduced stale-heartbeat placement/commit and upload-storage failure; fixes passed the complete suite. Added concurrent upload, lock-waiter cancellation, response interruption, metadata merge-limit and B hook lifecycle checks.
- Independent review: reviewer found cancellation during thread-pool temp acquisition can leak a file/descriptor. Reproduced that and cancellation during initial object insert in two failing tests; fixed by draining owned thread operations before cancellation cleanup. Full suite: **93 passed**, with one existing upstream TestClient deprecation warning.
- Ruling: async thread work that acquires resources or mutates metadata must complete before cancellation unwinds ownership; cleanup handles any acquired raw descriptor explicitly.
- Ruling: late-finishing timed-out worker writes need B's periodic live-worker inventory sweep as well as rejoin cleanup. Public logical deletion does not claim every offline/uncertain disk write has disappeared.
- Ruling: B's start hook must schedule the loop and return None promptly, not return its long-running Task; A supports sync or awaitable start/stop hooks.
- Controlled live check passed against one real controller and four real workers: 5000001-byte object -> 6 chunks, 2 distinct locations/chunk, distribution over all 4 workers, matching SHA-256; metadata/list/delete; stopped-worker fallback; corruption rejected and CORRUPT recorded with clean fallback; controller restart retained metadata and bytes; 50000000-byte streamed upload/download matched SHA-256. Observed controller peak-RSS increase during the large transfer: **9956 KiB** (single-run diagnostic, not a performance guarantee).
- The controlled check explicitly verified inventories and supplied eligibility in test-only code because B's production reconciler is missing. This is A integration evidence, not a completed C1/C4 release gate.
- Test-only containers, volumes and private network were removed. Existing project volumes were untouched. A's application code builds with the existing controller Dockerfile; no new application dependency was added.
- Final verification: the full suite also passed from the freshly built controller image: **93 passed, 1 existing deprecation warning**. Pytest configuration now gives async fixtures an explicit function scope, removing the earlier scope-configuration warning without suppressing dependency warnings.
- Publication: implementation commit **b9cf180** was pushed successfully to `origin/feature/controller`. The feature branch tracks that remote branch; no merge to master was performed. This documentation follow-up records that successful publication.
- Current work: A's implementation is handed off. Continue with B's remaining integration tasks below. No application behavior remains intentionally unfinished within A's documented scope; B-dependent release gates remain pending.

## Validation

Frontend extension complete: read-only overview/static routes have 14 new tests; an audit added two repeated/AnyIO cancellation regressions and fixed their resource leak. Final backend suite **109 passed** (one existing upstream deprecation). Frontend boundary tests **13 passed**; Chromium workflow suite **12 passed**, including axe checks at desktop/inspector/mobile and regressions for queue removal, unrelated concurrent metadata changes, stale snapshot state, corruption-driven inspector refresh, modal feedback and keyboard search across views. TypeScript and production Vite build passed. Real four-worker browser upload/PATCH/chunk inspection/checksum download/delete also passed; the final controlled topology passed 5 MB+/50 MB transfer, worker stop, corruption fallback and controller restart checks. The author inspected desktop/mobile/inspector captures directly; the separate independent visual reviewer hit a service usage limit, so no independent visual approval is claimed. See docs/reviews/2026-11-14-dashboard-review.md. DESIGN.md and .impeccable/design.json record the built system; QA captures are ignored, not production data.

Before the frontend extension, 93 tests passed (42 worker + 51 controller). The current backend total is 109 as above. Worker disk synchronization is Linux-specific; use Linux Docker for the complete suite. Exact commands live in `docs/CONTROLLER.md`; frontend commands are in `docs/FRONTEND.md`. `tests/live_controller_check.py --browser` adds real browser checks to the disposable Docker topology. One Starlette TestClient/httpx deprecation remains upstream; dependencies were not changed to hide it.

Normal Compose is now running: controller + four workers; `/`, `/health` and `/api/v1/overview` return 200. All four workers register and heartbeat, but correctly remain JOINING because B's production reconciler is still absent. The UI truthfully shows storage connecting. No QA files or ALIVE shortcuts were inserted into the normal project database. Stop normally with `docker compose down` to preserve volumes; never use `-v` on project data casually.

## Remaining integration work (Member B + shared review)

1. Implement recovery.py with JOINING inventory/hash reconciliation, DEAD detection/fresh-heartbeat rejoin, repair from verified copies, safe surplus trimming, pending-deletion retry and periodic live-worker orphan scanning.
2. Implement status.py router and CLI, plus recovery/integrity reliability tests. A's lifespan/router hookup is ready and tested with hook doubles.
3. Review and accept the exact helper dictionaries and lock/state rules in `contracts/db-helpers.md`; no teammate acceptance is claimed yet.
4. Forward the supported environment settings through Compose; its current defaults work, but most `.env` values are not forwarded. A did not edit B's Compose or Dockerfiles.
5. Run normal Compose integration and all assignment demos with the actual reconciler. C4/C5/C6 release completion and autonomous repair are still unverified.

Completed A files: controller main/config/models/database/schema/placement/objects; focused database/placement/chunking/API/lifecycle tests; shared contract docs; controller guide; controlled live test utility. The old controller/app starter was removed so there is one app entry point. README was updated jointly; B's functional files remain unchanged.

## Continue safely

1. Read this ledger and `git status`, then inspect current code and tests; do not redo completed work.
2. Run the documented Linux test command and address evidenced failures.
3. Preserve file ownership; record contract changes and remaining integration limits here.

## Reference checks

Official references consulted: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [HTTPX async clients](https://www.python-httpx.org/async/), [SQLite PRAGMA](https://www.sqlite.org/pragma.html), [Starlette responses](https://starlette.dev/responses/). They support lifespan-managed resources, scoped HTTP connection pooling, explicit SQLite connection settings and file responses. Project correctness rules come from the assignment/team blueprint, not these libraries.
