# Artaud object storage

A local distributed object store for a two-person cloud computing project. Member A owns the controller and web interface; Member B owns workers, autonomous recovery/status, Docker and CLI. See docs/HANDOFF.md and AGENTS.md.

Users upload arbitrary files, find and download them, edit custom metadata, and inspect chunk distribution and current storage availability. The browser talks to the real controller on the same origin. One controller and four persistent workers; default 1000000-byte chunks, two distinct copies. Only READY objects are public; controller verifies complete bytes before downloading.

The dashboard should make these tasks easy during development and a course demonstration. Its state comes from APIs, never invented capacity, uptime, throughput or seeded production data. Missing recovery remains a visible dependency; registration never promotes a worker. Optional owner demo controls can start/stop/restart the four existing worker containers while preserving their disks and separating running state from storage eligibility.

New scope authorized 14 November 2026: a complete responsive frontend, controller integration, remaining Member A checks, durable design and continuation documentation. Keep the local Docker architecture; no separate cloud Site or hosting account is needed to reach local worker services.

Subsequent scope: visualize controller/worker wiring, actual data movement, chunk placement, storage distribution and recovery observations. The Cluster view now explains these with a bounded controller event journal, selectable nodes/chunks, labeled historical replay, pause/reduced-motion controls and diagnostic exports. Current snapshots remain authoritative; no synthetic recovery, packet timing, capacity or throughput is invented. See docs/LIVE_SYSTEM.md and docs/MEMBER_A_READY.md.

Latest user direction: frontend on Vercel, controller/workers on the PC, direct HTTPS API connection. Keep that deployment simple. Worker/recovery source remains exclusively Member B-owned. Demo controls must distinguish actual Docker running state from verified storage availability. Activity should default to a quiet operation summary, with low-level events available explicitly; a walkthrough records operator notes rather than fabricated recovery evidence.

The connected workspace adds literal name/ID/custom-metadata search, filtered/selected listing exports, confirmed serial bulk deletion with per-file outcomes, a connection test and bounded redacted browser request diagnostics. These improve Member A's daily/demo workflow using existing APIs. No storage engine, worker, recovery, upload-resume or multi-user protocol is added. Research and ownership decisions are in docs/research/2026-11-14-controller-frontend-features.md.
