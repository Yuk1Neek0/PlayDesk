---
issue: 34
started: 2026-05-22T13:04:00Z
last_sync: 2026-05-22T13:30:00Z
completion: 100%
---

# Issue #34 — Stream C: frontend integration

Status: **complete**. 4 criteria PASS, 2 PASS (code + live-curl) with a
NEEDS-VISUAL note for #36, 0 FAIL.

- Three contract-drift bugs found and fixed in-stream: no backend CORS
  (solved with a Next.js same-origin proxy), Django trailing-slash 500 on
  POST, and `BACKEND_ORIGIN` build-time proxy wiring.
- Files: `frontend/next.config.mjs`, `frontend/src/lib/api.ts`,
  `frontend/src/lib/sse.ts`, `frontend/Dockerfile`, and `docker-compose.yml`
  (shared infra — flagged for #36).
- Suites after fixes: lint clean, typecheck clean, `npm test` 49/49,
  `npm run build` succeeds.
- The stream agent was blocked from committing; the parent agent committed
  the fixes and authored these record files.
- See `verification-record.md` for full criterion-by-criterion evidence.
