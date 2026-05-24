# Outbound message sender — operator wiring

`python manage.py send_outbound` drains the `OutboundMessage` queue
once: it selects due rows (`status='queued' AND scheduled_for <= now()`),
calls the registered channel adapter's `send()`, and updates the row.
The command is **idempotent** (rows are taken with `SELECT … FOR UPDATE
SKIP LOCKED`) and **bounded** (200 rows per run by default).

Wire it to fire on a short interval. ~60 seconds is the recommended
cadence — it balances latency-to-delivery against unnecessary DB churn.
Faster (30s) is fine if the queue regularly has work waiting.

## What to monitor

- `[outbound] skipped: twilio not configured` — adapter is missing
  `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER`.
  Rows stay `queued`. Expected on CI; investigate in staging/prod.
  The WhatsApp adapter reads the same SID/token plus its own
  `TWILIO_WHATSAPP_FROM` (e.g. the Twilio sandbox sender
  `+14155238886`); missing any of the three keeps rows queued the same
  way.
- `[outbound] processed N row(s)` — N = rows handled (sent, cancelled,
  rescheduled). Trend; should track booking volume.
- Rows with `status='failed'` — query `?status=failed` on the admin API
  to inspect (`failure_reason` carries the adapter error).

## Cron — bare-metal Linux

Add to a service-account crontab. The Django venv must be on PATH or
called explicitly.

```cron
* * * * * cd /srv/playdesk/backend && /srv/playdesk/.venv/bin/python manage.py send_outbound >> /var/log/playdesk/outbound.log 2>&1
```

The `* * * * *` runs once a minute. Replace `/srv/playdesk` with your
deploy root.

## systemd timer — Linux (modern)

`/etc/systemd/system/playdesk-outbound.service`:

```ini
[Unit]
Description=PlayDesk outbound message sender (one shot)
After=postgresql.service

[Service]
Type=oneshot
User=playdesk
WorkingDirectory=/srv/playdesk/backend
Environment="DJANGO_SETTINGS_MODULE=config.settings"
EnvironmentFile=/etc/playdesk/env
ExecStart=/srv/playdesk/.venv/bin/python manage.py send_outbound
```

`/etc/systemd/system/playdesk-outbound.timer`:

```ini
[Unit]
Description=Run PlayDesk outbound sender every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Unit=playdesk-outbound.service

[Install]
WantedBy=timers.target
```

Enable with `systemctl enable --now playdesk-outbound.timer`. Verify
with `systemctl list-timers | grep playdesk`.

## Docker sidecar (development / staging)

If the rest of the stack runs via `docker compose`, add a sidecar that
loops with `sleep 60` between runs (avoids per-tick container start cost):

```yaml
  outbound-sender:
    build: ./backend
    restart: unless-stopped
    environment:
      DATABASE_URL: ${DATABASE_URL:-postgres://playdesk:playdesk@db:5432/playdesk}
      SECRET_KEY: ${SECRET_KEY:-django-insecure-change-me-in-production}
      TWILIO_ACCOUNT_SID: ${TWILIO_ACCOUNT_SID:-}
      TWILIO_AUTH_TOKEN: ${TWILIO_AUTH_TOKEN:-}
      TWILIO_FROM_NUMBER: ${TWILIO_FROM_NUMBER:-}
      TWILIO_WHATSAPP_FROM: ${TWILIO_WHATSAPP_FROM:-}
    volumes:
      - ./backend:/app
    depends_on:
      db:
        condition: service_healthy
    command: >
      sh -c "while true; do python manage.py send_outbound; sleep 60; done"
```

Both invocations are safe to run concurrently — `SELECT … FOR UPDATE
SKIP LOCKED` ensures one row is processed by exactly one worker per
run.

## Notes

- The command leaves rows `queued` (not `failed`) when Twilio is not
  configured. This keeps CI without secrets clean and means an operator
  can wire creds in later and the backlog drains on the next tick.
- Quiet hours are per-store (`Store.quiet_hours_start` / `_end`), in
  the store's local timezone. `booking_confirmation` is the only
  template allowed to bypass quiet hours.
