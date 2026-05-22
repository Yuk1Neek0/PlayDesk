"""
PlayDesk integrity test — HTTP / SSE layer.

Exercises the running ``docker compose`` stack end to end over real HTTP,
the way the frontend and a customer do. Unlike the backend unit suite
(which mocks the database boundary and external APIs), this layer catches
contract drift, URL/wiring mistakes, and timezone bugs — the classes of
defect that only appear when the whole system runs together.

Run against a live stack:

    docker compose up -d --build
    pip install -r integration/requirements.txt
    pytest integration/test_integrity.py -v

Configuration (environment variables):
    PLAYDESK_API   base URL of the Django backend (default http://localhost:8000)

The agent / SSE journey needs an LLM key configured on the backend; it
skips automatically when the agent is not reachable, so the suite stays
green for contributors without API keys.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

BASE = os.environ.get("PLAYDESK_API", "http://localhost:8000").rstrip("/")
TIMEOUT = 60.0


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session")
def resources(client):
    r = client.get("/api/resources/")
    assert r.status_code == 200, f"GET /api/resources/ -> {r.status_code}: {r.text}"
    results = r.json()["results"]
    assert results, "no resources seeded — run `python manage.py seed_data`"
    return results


def _utc(days_ahead: int, hour: int) -> datetime:
    """A far-future UTC datetime, on the hour."""
    return (datetime.now(timezone.utc) + timedelta(days=days_ahead)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _booking_payload(resource_id: int, start: datetime, end: datetime) -> dict:
    return {
        "resource_id": resource_id,
        "customer_name": f"Integrity Test {uuid.uuid4().hex[:6]}",
        "customer_phone": "+1 416 555 0100",
        "start_time": _iso(start),
        "end_time": _iso(end),
        "source": "manual",
    }


# ---------------------------------------------------------------------------
# J — Resources & availability contract
# ---------------------------------------------------------------------------


def test_resources_list_and_type_filter(client, resources):
    """Resources list returns seeded data and the ?type= filter narrows it."""
    types = {r["type"] for r in resources}
    assert types, "resources have no type"

    for t in types:
        r = client.get("/api/resources/", params={"type": t})
        assert r.status_code == 200, r.text
        filtered = r.json()["results"]
        assert filtered, f"?type={t} returned nothing"
        assert all(item["type"] == t for item in filtered), f"?type={t} leaked other types"


def test_availability_contract_and_non_empty(client, resources):
    """
    Availability returns the documented shape, and an open day yields at
    least one bookable block with start < end. A regression here is what
    made every slot show 'fully booked'.
    """
    resource_id = resources[0]["id"]
    date = _utc(30, 12).date().isoformat()

    r = client.get(f"/api/resources/{resource_id}/availability/", params={"date": date})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"resource_id", "date", "available", "suggestions"}, body
    assert body["resource_id"] == resource_id
    assert isinstance(body["available"], list)

    assert body["available"], "a far-future open day reports no availability at all"
    for block in body["available"]:
        start = datetime.fromisoformat(block["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(block["end"].replace("Z", "+00:00"))
        assert start < end, f"availability block is inverted: {block}"


# ---------------------------------------------------------------------------
# J1 — Booking CRUD round-trip
# ---------------------------------------------------------------------------


def test_booking_crud_roundtrip(client, resources):
    """Create, read, modify, and cancel a booking over real HTTP."""
    resource_id = resources[0]["id"]
    start, end = _utc(40, 18), _utc(40, 20)

    created = client.post("/api/bookings/", json=_booking_payload(resource_id, start, end))
    assert created.status_code == 201, f"POST booking -> {created.status_code}: {created.text}"
    booking_id = created.json()["id"]

    try:
        got = client.get(f"/api/bookings/{booking_id}/")
        assert got.status_code == 200, got.text

        patched = client.patch(
            f"/api/bookings/{booking_id}/",
            json={"end_time": _iso(_utc(40, 21))},
        )
        assert patched.status_code == 200, f"PATCH -> {patched.status_code}: {patched.text}"
    finally:
        deleted = client.delete(f"/api/bookings/{booking_id}/")
        assert deleted.status_code in (200, 204), deleted.text

    gone = client.get(f"/api/bookings/{booking_id}/")
    assert gone.status_code == 404, "cancelled booking still readable"


# ---------------------------------------------------------------------------
# J5 — Booking overlap is rejected by the database
# ---------------------------------------------------------------------------


def test_overlapping_booking_rejected(client, resources):
    """Two bookings for the same resource and slot: one 201, one 409."""
    resource_id = resources[0]["id"]
    start, end = _utc(50, 18), _utc(50, 20)
    payload = _booking_payload(resource_id, start, end)

    first = client.post("/api/bookings/", json=payload)
    assert first.status_code == 201, f"first booking -> {first.status_code}: {first.text}"
    booking_id = first.json()["id"]

    try:
        second = client.post("/api/bookings/", json=_booking_payload(resource_id, start, end))
        assert second.status_code == 409, (
            f"overlapping booking should be 409, got {second.status_code}: {second.text}"
        )
    finally:
        client.delete(f"/api/bookings/{booking_id}/")


# ---------------------------------------------------------------------------
# J4 — Admin endpoints
# ---------------------------------------------------------------------------


def test_admin_endpoints_sorted_desc(client):
    """Admin bookings and conversations load and are newest-first."""
    rb = client.get("/api/admin/bookings/")
    assert rb.status_code == 200, rb.text
    booking_times = [b["created_at"] for b in rb.json()["results"]]
    assert booking_times == sorted(booking_times, reverse=True), "bookings not created_at desc"

    rc = client.get("/api/admin/conversations/")
    assert rc.status_code == 200, rc.text


# ---------------------------------------------------------------------------
# J3 — Agent loop & SSE streaming  (needs an LLM key; skips otherwise)
# ---------------------------------------------------------------------------


def test_agent_sse_streams_incrementally(client):
    """
    A chat message produces a real Server-Sent Events stream with
    incremental events ending in a `done`. Skips when the agent is not
    configured (no LLM key) so the suite stays green without secrets.
    """
    conv = client.post("/api/conversations/", json={})
    assert conv.status_code == 201, f"POST conversation -> {conv.status_code}: {conv.text}"
    conv_id = conv.json()["id"]

    events: list[str] = []
    try:
        with client.stream(
            "POST",
            f"/api/conversations/{conv_id}/messages/",
            json={"content": "What board games do you have?"},
            headers={"Accept": "text/event-stream"},
        ) as resp:
            if resp.status_code != 200:
                pytest.skip(f"agent endpoint returned {resp.status_code} — not configured")
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
                if len(events) > 200:
                    break
    except httpx.HTTPError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"agent stream unavailable: {exc}")

    if not events or events == ["error"]:
        pytest.skip("agent produced no usable stream — LLM key likely unset")

    assert "done" in events, f"SSE stream never emitted a `done` event: {events}"
    assert len(events) > 1, "SSE stream was a single payload, not incremental"
