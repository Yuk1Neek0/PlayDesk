# Issue #32 - Progress

Status: COMPLETE
Branch: epic/verification (worktree epic-verification)

## Summary

Stream A - backend REST and SSE verification (dev plan section 1.1). All 5
acceptance criteria verified PASS against the live stack. One bug found and
fixed in-stream.

## Criteria

- [x] C1 - Booking CRUD curl round-trip (POST/GET/PATCH/DELETE) - PASS
- [x] C2 - GET /api/resources/, ?type= filter, availability computation - PASS
- [x] C3 - Concurrent POST yields one 201 + one 409 from Postgres EXCLUDE constraint - PASS
- [x] C4 - Admin endpoints, bookings sorted created_at desc - PASS
- [x] C5 - SSE emits tokens incrementally - PASS (after fix)
- [x] C6 - Verification record written to updates/32/ - PASS

## Bugs fixed

1. backend/agent/views.py _run_agent_stream buffered the whole agent run into a
   list and yielded only after loop.run() returned - SSE was a single deferred
   payload (TTFB == total). Fixed: run the loop on a worker thread feeding a
   queue.Queue; generator yields each event as produced. Also updated
   backend/agent/test_agent_sse.py conversation fixture db -> transactional_db
   (worker thread needs committed data). pytest green (62 / 101 passed in scope).

## Notes for #36

- No shared-file changes (config/settings.py, config/urls.py, docker-compose.yml untouched).
- Record written to updates/32/ (issue number); spec body text said updates/002/.
- Minor non-fatal pytest-django teardown warning with transactional_db + worker thread; tests still pass.
