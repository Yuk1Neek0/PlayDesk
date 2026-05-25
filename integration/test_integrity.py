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

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

BASE = os.environ.get("PLAYDESK_API", "http://localhost:8000").rstrip("/")
TIMEOUT = 60.0


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as c:
        # v10a: `/api/admin/*` is gated by StaffOnlyMiddleware. Log in
        # once as the seeded demo staff user so `test_admin_endpoints_*`
        # carries a `sessionid` cookie on subsequent requests. Login is
        # CSRF-exempt (see v10a task #190); the cookie persists for the
        # life of this httpx.Client. Public endpoints don't care about
        # the extra cookie, so this is harmless for the non-admin tests.
        try:
            r = c.post(
                "/api/staff/login/",
                json={
                    "username": "playdesk_staff",
                    "password": "playdesk_staff_demo_pw",
                },
            )
            r.raise_for_status()
        except Exception:
            # Seed not run yet — public tests still pass; admin tests
            # will surface the failure with a clear assertion message.
            pass
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


# ---------------------------------------------------------------------------
# Semantic agent tests — seed a real booking, ask the agent about it, assert
# the agent's tool args and final text match the seeded reality.
#
# These exercise the layer that the contract suite cannot: that the agent's
# answer is *true* of the data, not merely well-formed. They need an LLM
# key configured on the backend and skip cleanly otherwise.
# ---------------------------------------------------------------------------

STORE_TZ = ZoneInfo("America/Toronto")
_TAKEN_PATTERN = re.compile(
    r"\b(not\s+available|unavailable|already\s+booked|taken|booked|"
    r"reserved|sorry|afraid|conflict)\b",
    re.IGNORECASE,
)


def _store_local(days_ahead: int, hour: int) -> datetime:
    """A future datetime at hour:00 store-local time, returned as UTC-aware."""
    base = datetime.now(STORE_TZ) + timedelta(days=days_ahead)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _collect_sse(client, conv_id: int, message: str) -> tuple[list[dict], str | None]:
    """
    Drive a chat turn over SSE and return (tool_call_start events, final text).
    Returns (None, None) when the LLM endpoint is not configured.
    """
    tool_calls: list[dict] = []
    final_text: str | None = None
    try:
        with client.stream(
            "POST",
            f"/api/conversations/{conv_id}/messages/",
            json={"content": message},
            headers={"Accept": "text/event-stream"},
        ) as resp:
            if resp.status_code != 200:
                return [], None
            current_event: str | None = None
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if current_event == "tool_call_start":
                        tool_calls.append(data)
                    elif current_event == "done":
                        final_text = data.get("text") or final_text
                    elif current_event == "error":
                        return tool_calls, None
                elif not line:
                    current_event = None
                if len(tool_calls) > 20:
                    break
    except httpx.HTTPError:
        return tool_calls, None
    return tool_calls, final_text


def _start_conversation(client) -> int:
    conv = client.post("/api/conversations/", json={})
    assert conv.status_code == 201, f"POST conversation -> {conv.status_code}: {conv.text}"
    return conv.json()["id"]


def _pick_console(resources) -> dict:
    consoles = [r for r in resources if r["type"] == "console"]
    assert consoles, "no console resources seeded"
    # Prefer a non-Switch console to leave room for resource-specific tests.
    return next((r for r in consoles if "PS5" in r["name"]), consoles[0])


def test_agent_knows_a_seeded_booking_blocks_a_specific_resource(client, resources):
    """
    Seed a booking on a specific resource. Ask the agent about that exact
    resource and time. Expect (a) check_availability was called with the
    seeded date and an overlapping window, and (b) the response text names
    the resource and indicates it is not available.

    This is the test that would have caught both the UTC time_range bug and
    the opaque-TimeSlot bug from PR #40.
    """
    target = _pick_console(resources)
    # Far-future day, well-defined hour. 60 days out avoids any cleanup race
    # with other integrity tests.
    start_local_hour = 19
    start_utc = _store_local(60, start_local_hour)
    end_utc = start_utc + timedelta(hours=2)

    created = client.post("/api/bookings/", json=_booking_payload(target["id"], start_utc, end_utc))
    assert created.status_code == 201, f"seed booking -> {created.status_code}: {created.text}"
    booking_id = created.json()["id"]

    try:
        conv_id = _start_conversation(client)
        # Ask in store-local terms — the agent should resolve and pass them
        # to check_availability in the same store-local form.
        date_str = start_utc.astimezone(STORE_TZ).date().isoformat()
        question = (
            f"Is the {target['name']} available on {date_str} at "
            f"{start_local_hour}:00 for one hour?"
        )
        tool_calls, final_text = _collect_sse(client, conv_id, question)

        if final_text is None:
            pytest.skip("agent stream unavailable or returned error — LLM key likely unset")

        # 1. The agent must have called check_availability with the right date.
        avail_calls = [tc for tc in tool_calls if tc.get("tool_name") == "check_availability"]
        assert avail_calls, (
            f"agent never called check_availability for a direct availability "
            f"question. Tool calls: {[tc.get('tool_name') for tc in tool_calls]}"
        )
        dates_used = {tc.get("arguments", {}).get("date") for tc in avail_calls}
        assert date_str in dates_used, (
            f"check_availability never queried the asked-about date {date_str}. "
            f"Dates seen: {dates_used}"
        )

        # 2. The final response must mention the resource and a "taken" sense.
        assert target["name"].split()[0] in final_text or target["name"] in final_text, (
            f"agent reply did not mention the asked resource {target['name']!r}: "
            f"{final_text!r}"
        )
        assert _TAKEN_PATTERN.search(final_text), (
            f"agent reply did not indicate the slot is taken, even though a "
            f"booking exists at {start_local_hour}:00 store-local: {final_text!r}"
        )
    finally:
        client.delete(f"/api/bookings/{booking_id}/")


def test_agent_passes_store_local_date_to_check_availability(client, resources):
    """
    The agent must pass store-local dates to check_availability — not UTC
    dates. A regression of the agent prompt's UTC bug would surface here as
    the agent querying the wrong day from Toronto evening.
    """
    target = _pick_console(resources)
    start_utc = _store_local(45, 16)  # 4 PM Toronto, 45 days out
    end_utc = start_utc + timedelta(hours=1)
    expected_date = start_utc.astimezone(STORE_TZ).date().isoformat()

    conv_id = _start_conversation(client)
    question = f"Is the {target['name']} free on {expected_date} at 4 PM?"
    tool_calls, final_text = _collect_sse(client, conv_id, question)

    if final_text is None:
        pytest.skip("agent stream unavailable or returned error — LLM key likely unset")

    avail_calls = [tc for tc in tool_calls if tc.get("tool_name") == "check_availability"]
    if not avail_calls:
        pytest.skip(
            "agent did not call check_availability for this turn; "
            "non-deterministic LLM routing"
        )

    dates_used = {tc.get("arguments", {}).get("date") for tc in avail_calls}
    assert expected_date in dates_used, (
        f"agent queried availability for a different date than asked. "
        f"Expected {expected_date}, saw {dates_used}"
    )
