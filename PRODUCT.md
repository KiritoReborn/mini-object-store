# Artaud object storage

A local distributed object store for a two-person cloud computing project. Member A owns the controller and web interface; Member B owns workers, autonomous recovery/status, Docker and CLI. See docs/HANDOFF.md and AGENTS.md.

Users upload arbitrary files, find and download them, edit custom metadata, and inspect chunk distribution and current storage availability. The browser talks to the real controller on the same origin. One controller and four persistent workers; default 1000000-byte chunks, two distinct copies. Only READY objects are public; controller verifies complete bytes before downloading.

The dashboard should make these tasks easy during development and a course demonstration. Its state comes from APIs, never invented capacity, uptime, throughput or seeded production data. Missing recovery remains a visible dependency; registration never promotes a worker. The UI does not manage Docker containers.

New scope authorized 14 November 2026: a complete responsive frontend, controller integration, remaining Member A checks, durable design and continuation documentation. Keep the local Docker architecture; no separate cloud Site or hosting account is needed to reach local worker services.

Subsequent scope: visualize controller/worker wiring, actual data movement, chunk placement, storage distribution and recovery observations. The Cluster view now explains these with a bounded controller event journal, selectable nodes/chunks, labeled historical replay, pause/reduced-motion controls and diagnostic exports. Current snapshots remain authoritative; no synthetic recovery, packet timing, capacity or throughput is invented. See docs/LIVE_SYSTEM.md and docs/MEMBER_A_READY.md.
