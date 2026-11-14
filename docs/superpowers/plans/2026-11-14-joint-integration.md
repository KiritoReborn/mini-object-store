# Joint controller and recovery integration

User authorized review/integration of feature/workers, fixing A's fixtures, merging to master after green, and completing the combined demo. B owns the recovery implementation; integrate it and make only demonstrated shared-boundary corrections. Worker source remains unchanged.

- [x] Pin/review B head 2924a6db81c5635462d162c4f683889ad1584231 against master 9b29954. Only recovery.py, recovery tests and B handoff were added. No open PR existed at discovery. Combine locally without committing first.
- [x] Reproduce baseline in isolated Linux Docker: 290 passed/2 failed of 292. False recovery-absence assertions reproduce; snapshot global-connection race is intermittent.
- [x] Isolate A-only application fixtures with explicit missing-recovery module simulation; keep real recovery tests/hooks active. Make snapshot transaction test a direct DB test with no background app.
- [x] Reproduce and correct registration-during-inventory admission and timezone-naive eligibility inconsistencies. Preserve frozen helper shapes/signatures; any registration fence must be atomic and allow normal heartbeat updates. Document the additive shared helper contract.
- [x] Run full Linux suite and frontend regression checks. Review fixed boundaries independently.
- [x] Exercise five real Docker containers using B's actual reconciler: ALIVE admission, exact 5,000,001-byte chunks/two physical copies, 50MB streaming/hash round-trip, stop/fallback/repair/rejoin, corruption fallback and cleanup, and restart persistence. Touch only temporary QA objects or isolated QA volumes; preserve user data.
- [x] Add repeatable joint end-to-end check/demo instructions/scripts and required contracts; reconcile README/handoff with actual delivered functionality. Keep API usable independently of frontend.
- [ ] Create/update reviewable PR as needed, merge verified combined source into master, then sync the checkout and verify exact merged source. Push without force; preserve teammate authorship.
- [x] Finish staged Vercel verification/promotion for existing frontend and verify HTTPS PC connection with the integrated controller. Current ngrok endpoint was verified and Vercel production candidate dpl_HPE3VgKWoUCwFCwcjcpLZsa1QRo7 is READY; promotion is pending, not previously claimed complete.
