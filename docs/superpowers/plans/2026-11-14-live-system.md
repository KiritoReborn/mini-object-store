# Live System Implementation Plan

> Execute the tasks continuously using subagent-driven-development for the independent backend task and direct frontend integration. Keep this ledger current.

**Goal:** Explain real chunk movement, placement and recovery observations visually from Member A's controller.
**Architecture:** Bounded controller activity journal + existing overview/manifests; SVG/HTML React cluster explorer. Preserve current file workflows and B ownership.
**Tech stack:** Existing FastAPI/SQLite, React/TypeScript/Vite, SVG/CSS, pytest/Vitest/Playwright.
**Spec:** ../specs/2026-11-14-live-system-design.md

## Constraints / review focus

Retain feature/controller checkout. No new runtime dependencies. No B-owned edits. Only confirmed observations; unknown/stale state must lose live claims. Event recording must not alter storage behavior or unboundedly retain data. Cursors must handle eviction/restart. Fast operations remain inspectable after completion. Large chunk lists must paginate; file changes must cancel stale requests. Pausing must actually freeze the live system view. Export must carry capture age/error context.

## Tasks and execution ledger

- [x] Backend telemetry: test journal cursor/bounds/thread safety and transfer/state semantics RED; implement telemetry.py, instrument A-owned objects/database and add dashboard activity route; verify focused and full Linux tests. Preserve helper signatures. Own tests/test_activity.py.
- [x] Frontend explorer: unit-test event merging/labels/placement helpers RED; add activity polling hook, typed contracts, topology, distribution, placement, recovery/activity and diagnostics; integrate under Cluster and preserve file actions. Backend/frontend share spec event contract.
- [x] Browser verification: tests for new interactions, errors/pause/stream reset/export, WCAG, responsive and reduced motion; inspect desktop/mobile renders; fix evidenced failures.
- [x] Integration/review/publication: real Docker workers, review code, rebuild normal controller, docs/contracts/design/handoff, clean commit and push authorized feature branch. Existing project data retained.

Ruling: use a bounded in-memory journal rather than a persistent audit schema — this is operational recent activity, not a compliance log; restart/gaps are visible.
Ruling: no simulated recovery or worker qualification in normal runtime — B's missing reconciler is an explicit integration dependency.

Verification: 128 backend, 16 unit, 20 browser tests passed; TypeScript/build passed. Final real-worker harness passed visual placement/observed events/replay and 5 MB+/50 MB transfer/failure/persistence checks. Startup script ran on the normal stack and preserved volumes. Source review findings and RED/GREEN fixes are in docs/reviews/2026-11-14-live-system-review.md.

Ruling: publish post-commit observations without serializing every DB writer — preserve short transactions; event order is not current-state authority.
Ruling: serialize frontend polling, add 15-second active-time request bounds, and permit timestamped blue historical replay during feed errors — prevents starvation and silent replay failures.
