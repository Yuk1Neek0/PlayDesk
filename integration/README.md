# PlayDesk integrity suite

End-to-end tests that exercise the **whole running stack** the way a user
does — to catch the contract / wiring / timezone bugs that the mock-based
unit suites (`backend` pytest, `frontend` vitest) structurally cannot.

Two layers:

| Layer | Location | What it covers |
|-------|----------|----------------|
| HTTP / SSE | `integration/test_integrity.py` | REST contracts, availability, booking CRUD, overlap → 409, admin endpoints, agent SSE |
| Browser E2E | `frontend/e2e/*.e2e.ts` | Manual booking journey, **picked time == admin time**, admin auth gate, chat |

Both run against a live `docker compose` stack. In CI they run via
`.github/workflows/integrity.yml` (on push to `main`, PRs, nightly, and
manual dispatch).

## Run it locally

Start the stack first:

```bash
docker compose up -d --build
```

### HTTP / SSE layer

```bash
pip install -r integration/requirements.txt
pytest integration/test_integrity.py -v
```

### Browser E2E layer

```bash
cd frontend
npm ci
npx playwright install chromium
npm run e2e
```

## Notes

- The Playwright config pins the browser to `Asia/Tokyo` on purpose: the app
  must render all times in the store timezone (`America/Toronto`) regardless
  of the viewer's clock. If that regresses, `booking.e2e.ts` fails.
- Tests that need an LLM key (the agent journeys) **skip automatically** when
  the key is absent — set `PLAYDESK_LLM=1` (and configure the backend key) to
  run them.
- The booking E2E creates a real booking each run (named `Playwright <ts>`).
  Harmless on the ephemeral CI stack; locally it adds a row you can ignore.
- Override the targets with `PLAYDESK_API` (backend) and `PLAYDESK_WEB`
  (frontend) if not on the default ports.
