# Verification Record - Issue #32: Stream A - backend REST and SSE

Dev plan section 1.1. Verified against the live stack (docker compose up -d) in
worktree epic-verification, branch epic/verification.

- backend: http://localhost:8000
- db: Postgres+pgvector, store "PlayDesk Flagship", timezone Asia/Shanghai (UTC+8),
  business hours mon-thu 10:00-22:00, fri 10:00-23:00, sat 09:00-23:00, sun 09:00-22:00.

Result: 5 / 5 acceptance criteria PASS (criterion 5 required a fix - see Bugs fixed).

---

## Criterion 1 - Booking CRUD round-trip (POST/GET/PATCH/DELETE)

PASS

Command:
    curl -s -X POST http://localhost:8000/api/bookings/ -H "Content-Type: application/json" \
      -d {"resource_id":1,"customer_name":"Verify Test","customer_phone":"+8613800138000",
          "start_time":"2026-06-01T06:00:00Z","end_time":"2026-06-01T08:00:00Z","source":"manual"}
    # then GET / PATCH / DELETE on the returned id

Observed:
    CREATE -> HTTP 201  {"id":1,"resource_id":1,...,"status":"pending",...}
    GET    -> HTTP 200  {"id":1,...}
    PATCH  -> HTTP 200  {"customer_name":"Verify Test Renamed","status":"confirmed",...}
    DELETE -> HTTP 204
    GET after delete -> HTTP 404  {"detail":"Not found."}
Re-confirmed in a final pass (resource 4, id 20): POST 201 / GET 200 / PATCH 200 / DELETE 204.

---

## Criterion 2 - GET /api/resources/, ?type= filter, availability computation

PASS

    GET /api/resources/                -> HTTP 200, count=5
    GET /api/resources/?type=console   -> HTTP 200, count=3 (PS5 x2 + Switch)
    GET /api/resources/?type=room      -> HTTP 200, count=1 (Private Room A)
    GET /api/resources/?type=table     -> HTTP 200, count=1 (Board Game Table 1)
    GET /api/resources/?type=bogus     -> HTTP 400 (invalid type rejected)

Availability computation (business hours minus bookings):
    GET /api/resources/1/availability/?date=2026-06-02 (empty Tue)
      -> available: [02:00Z - 14:00Z]   # 10:00-22:00 Asia/Shanghai = 02:00-14:00 UTC

    # create booking 04:00-06:00 UTC on 2026-06-03, then:
    GET /api/resources/1/availability/?date=2026-06-03
      -> available: [02:00Z-04:00Z, 06:00Z-14:00Z]   # booked interval subtracted

    # cancel that booking, then:
    GET /api/resources/1/availability/?date=2026-06-03
      -> available: [02:00Z-14:00Z]     # cancelled bookings excluded

    GET /api/resources/1/availability/?date=notadate  -> HTTP 400
    GET /api/resources/1/availability/  (no date)     -> HTTP 400
    GET /api/resources/999/availability/?date=...     -> HTTP 404

---

## Criterion 3 - Two concurrent POST /api/bookings/ -> one 201 + one 409, from Postgres

PASS

Command (two simultaneous background curls, identical resource_id + time window):
    BODY={"resource_id":1,...,"start_time":"2026-06-05T05:00:00Z","end_time":"2026-06-05T07:00:00Z",...}
    curl ... -d "$BODY" &   # A
    curl ... -d "$BODY" &   # B
    wait

Observed:
    A -> HTTP 201  {"id":3,...}
    B -> HTTP 409  {"detail":"The requested time slot is already booked.",
                    "conflicting_booking_id":null,"suggestions":[]}
Exactly one 201, one 409. Re-confirmed in a final pass (resource 5): A 201 / B 409.

409 originates from Postgres, not application code - confirmed three ways:
1. DB-level exclusion constraint exists:
   SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
     WHERE conrelid=core_booking::regclass AND contype=x;
   -> booking_no_overlap |
      EXCLUDE USING gist (resource_id WITH =, tstzrange(start_time,end_time,[)) WITH &&)
2. api/views.py BookingListCreateView.create() has NO Python-level overlap pre-check;
   it calls serializer.save() and catches django.db.IntegrityError, returning HTTP 409.
3. Direct ORM insert of an overlapping booking raises:
   IntegrityError: conflicting key value violates exclusion constraint "booking_no_overlap"
   DETAIL: Key (resource_id, tstzrange(...))=(1,[...]) conflicts with existing key ...

---

## Criterion 4 - Admin endpoints (staff-visible, bookings sorted created_at desc)

PASS

    GET /api/admin/bookings/      -> HTTP 200; results ordered id 8,7,6 (created_at DESC)
    GET /api/admin/conversations/ -> HTTP 200; results ordered newest-first (-started_at)

AdminBookingListView queryset: Booking.objects...order_by("-created_at").
AdminConversationListView queryset: Conversation.objects...order_by("-started_at").

---

## Criterion 5 - SSE messages endpoint emits tokens incrementally

PASS (after fix - see Bugs fixed #1)

Before fix: the endpoint buffered the entire agent run, then flushed every event in
a single ~2 ms burst. TTFB == time_total proved no incremental emission:
    curl -sN -X POST .../conversations/<id>/messages/ -d {"content":"...no tools..."} \
      -w "TTFB: %{time_starttransfer}s  total: %{time_total}s"
    -> TTFB: 2.540s   total: 2.542s    # whole stream arrives in a 2 ms window

After fix, per-event arrival timestamps (curl -N + awk date):
    [..31.178] event: tool_call_start
    [..31.307] event: tool_call_end
    [..32.845] event: token       <-- 1.5 s real gap (2nd LLM call) before first token
    [..32.962] event: token
    [..33.077] event: token
       ... 9 more token events, ~110 ms apart ...
    [..34.118] event: done
The endpoint emits multiple distinct event:token SSE frames over time - the
tool_call_start/tool_call_end events reach the client ~1.5 s before the first
token, proving genuine incremental wall-clock streaming, not a single payload.

---

## Criterion 6 - Verification record written

PASS - this file (updates/32/).

Note: the task spec body text says updates/002/; the issue is GitHub #32 and the
epic folder convention is updates/32/ (matching sibling issues 31/33/34/35).
Record written to updates/32/. Flagged here for #36.

---

# Bugs fixed

## Bug #1 - SSE endpoint buffered the whole agent run instead of streaming (FIXED)

File: backend/agent/views.py, function _run_agent_stream.

Root cause: the generator registered an on_event callback that merely appended
events to a Python list, ran loop.run(...) to completion (synchronously, in the
generator body), and only afterwards iterated the list to yield. No event could
reach the client until the entire agent loop - including the multi-second LLM
call(s) - had finished. The SSE stream was effectively a single deferred payload.

Fix (minimal, scoped to backend/agent/): run the agent loop on a background worker
thread; the on_event callback now pushes each event into a queue.Queue; the
generator drains the queue and yields each event the moment it is produced. A
_STREAM_DONE sentinel terminates the stream. The generator finally always
worker.join()s (even on early client disconnect), and the worker finally calls
connections.close_all() so its DB connection is not leaked.

Verified: tool_call_* events now arrive ~1.5 s before token events (real
wall-clock gap); token events arrive as distinct frames. pytest green (below).

Test change required by the fix:
backend/agent/test_agent_sse.py - the conversation fixture was changed from db to
transactional_db. The SSE view now drives the agent loop on a worker thread with
its own DB connection; an uncommitted test-transaction row is invisible to that
connection, so the conversation must be committed. Standard pytest-django pattern
for threaded DB access. All 11 SSE tests pass.

Known minor item (not a failure): with transactional_db + the worker thread,
pytest-django occasionally logs a non-fatal teardown warning ("database
test_playdesk is being accessed by other users" - pytest-django retries and
succeeds; final result is always passed). All targeted suites pass. Flagged for #36.

# Shared-file changes for #36 reconciliation

None. No changes to config/settings.py, config/urls.py, or docker-compose.yml.
All edits are within backend/agent/ (in scope for the SSE fix):
- backend/agent/views.py          - SSE streaming fix
- backend/agent/test_agent_sse.py - fixture db -> transactional_db

Folder-name note for #36: record written to updates/32/ (actual issue number),
not updates/002/ as the spec body text says.

# Test results

docker compose exec -T backend python -m pytest tests/test_api_rest.py
 tests/test_booking_overlap.py agent/test_agent_sse.py agent/test_agent_loop.py -q
-> 62 passed.

docker compose exec -T backend python -m pytest agent/ tests/test_api_rest.py
 tests/test_booking_overlap.py tests/test_agent_tools.py -q
-> 101 passed.

(backend/api/ itself contains no test modules; the api app tests live in
backend/tests/test_api_rest.py and test_booking_overlap.py, both green.)
