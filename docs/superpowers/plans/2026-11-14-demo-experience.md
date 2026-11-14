# Demo experience and simple deployment

Latest user direction: frontend on Vercel, existing FastAPI controller and Docker workers on the PC, with one HTTPS tunnel for connectivity. No extra gateway/server infrastructure. Do not implement or modify worker code or recovery: Member B owns those. The interim recovery module/tests/epoch additions were removed before publication, and the original recovery hooks are retained. Runtime must return to that source baseline; Joining remains an explicit dependency until B provides inventory verification. No manual ALIVE override is introduced.

## Selected features

- [x] Browser connection settings: backend HTTPS address from VITE_API_BASE_URL; owner API key entered in memory, never embedded in the frontend bundle; exact-origin CORS and shared authentication for the public backend.
- [x] Optional controller demo controls: Docker Engine HTTP over its local Unix socket, fixed worker1..worker4 allowlist and Compose-project identity check. Start/stop/restart only; no container creation/deletion, arbitrary shell or volume deletion. Disabled without explicit local configuration and owner key. Docker access remains privileged despite the narrow API.
- [x] Worker UI: actual container running state separate from ALIVE/JOINING, per-node actions with stop/restart confirmation, operation errors and preserved data. Existing labels/notes/placement pause remain useful. No claim that starting a container finishes recovery.
- [x] Quiet activity: default readable operation summaries; low-level chunk attempts in an explicit technical detail view. Filters, bounded pagination, pause/replay and existing timestamps stay available.
- [x] Demo guide: a compact walkthrough for upload/chunks/metadata, worker stop/fallback, teammate recovery and rejoin, with clearly self-reported checklist/export. No simulated repair evidence.
- [x] Vercel static output and environment configuration; direct browser requests to the PC HTTPS API, not Vercel request-body proxying. Exact allowed frontend origin configured on the backend. ngrok free assigned domain/quotas documented; no promised 24/7 availability while PC sleeps.
- [ ] Backend/frontend/security/browser checks, local real-worker controls, README/handoff/feature roadmap and authorized Git push. Actual deployment only claimed after its URL is fetched; preserve a clear sign-in/token blocker if account access is unavailable.

Research: Portainer container controls distinguish state, start/stop/restart and details; Grafana Explore separates query/filter/level context from raw logs; Docker stop preserves the container and its volumes. Existing project UI handles file/chunk truth. References will be captured in docs/DEMO.md rather than turning this into an unrelated cloud platform.
