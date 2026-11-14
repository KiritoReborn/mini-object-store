# Connected workspace completion review

Scope: Member A frontend only after 9b29954, plus exact local allowed-origin configuration and official HTTPS-agent installation. Worker/recovery/status source, Python behavior and shared helper contracts remain unchanged.

Research used first-party SeaweedFS, Garage, RustFS and Ceph source/docs; citations and scope decisions are in ../research/2026-11-14-controller-frontend-features.md. Shipped additions are metadata/ID search, snapshot listing exports, explicit selection/confirmed serial deletion, connection testing and bounded redacted request diagnostics. No new service, backend storage protocol or cloud data store.

## Review findings resolved

Independent source reviewer reproduced JSON escaping preventing literal quote/path metadata matches. Search now collects actual keys/scalar values iteratively, with nested string/quote/path regressions.

Reviewer also reproduced HTTP 200 interrupted downloads, malformed 201 upload responses and malformed 200 probes being hidden from failure diagnostics. Outcomes now preserve status and classify response handling/validation failure separately. Stream and malformed-response tests pass. Late observations after clear/backend changes are discarded by generation.

Deletion checks covered 204/404/409/408/401/403/503, transport failures, invalid responses and backend-origin changes. No deletion classification defect was found. Page selection intentionally accumulates explicit choices across pages, shows the count/other-page note and clears on changed filters. There is no implicit select-all across hidden pages.

The reviewer independently reran 28 frontend unit tests, confirmed both fixes and reported no new material issue. Author inspected desktop/mobile renders and fixed a cramped narrow-screen search field; a width/usability regression and accessibility checks pass. No independent visual certification is claimed.

## Verification

- Frontend units: 28 passed, including original API cases, CSV formula/quoting, literal metadata, redacted/bounded/late request history and post-header failure handling.
- Chromium: 29 passed, including scoped export, mixed and unknown batch outcomes, probe/diagnostic export, existing upload/metadata/download/worker flows, narrow layouts, keyboard and accessibility.
- TypeScript/local production build and Vercel dist build passed.
- Actual PC controller: authenticated overview returns 200 and exact allowed Vercel origin. Real browser smoke tested probe, literal metadata search, CSV export and confirmed bulk removal using only two uniquely named empty QA objects; both were removed. Existing user objects/volumes and worker containers preserved. This is A-only evidence; no nonempty admission/recovery claim.
- Full Linux backend 218-case result belongs to the earlier checkpoint; no new Python or worker code changed in this expansion, so that unchanged suite was not rerun.

## Deployment status and limit

User's Vercel frontend is live with previous demo assets; its same-origin API path is 404 because the public backend URL is unset. The PC origin allowance is configured and verified. Official ngrok agent 3.39.11 is installed, but private agent-account configuration remains absent. The Vercel plugin is enabled; no account-management MCP tools are exposed, and CLI device authorization is still required. No tunnel, Vercel variable change, new production deployment or DNS change is claimed. Continue from HANDOFF.md after user completes those account steps.
