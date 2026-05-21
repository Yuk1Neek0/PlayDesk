"""
Tests for the SSE streaming endpoint (Issue #14).

Uses Django's test client. All LLM calls are mocked via FakeLLMClient
patched into the view layer.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client

from agent.llm_client import FakeLLMClient, LLMResponse, ToolCallRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], stop_reason="end_turn")


def _make_tool_response(tool_name: str, args: dict) -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=[ToolCallRequest(f"tc_{tool_name}", tool_name, args)],
        stop_reason="tool_use",
    )


def _parse_sse(content: bytes) -> list[dict]:
    """Parse raw SSE bytes into a list of {event, data} dicts."""
    events = []
    current: dict = {}
    for line in content.decode("utf-8").splitlines():
        if line.startswith("event:"):
            current["event"] = line[len("event:") :].strip()
        elif line.startswith("data:"):
            raw = line[len("data:") :].strip()
            try:
                current["data"] = json.loads(raw)
            except json.JSONDecodeError:
                current["data"] = raw
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    return Client()


@pytest.fixture()
def conversation(db):
    from core.models import Conversation, ConversationStatus

    return Conversation.objects.create(
        customer_identifier="sse-test-user",
        status=ConversationStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# Conversation creation endpoint
# ---------------------------------------------------------------------------


class TestCreateConversation:
    def test_creates_conversation(self, client, db):
        response = client.post(
            "/api/conversations/",
            data=json.dumps({"customer_identifier": "test-customer"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = json.loads(response.content)
        assert "id" in data
        assert data["status"] == "active"

    def test_defaults_to_anonymous(self, client, db):
        response = client.post(
            "/api/conversations/",
            data=b"{}",
            content_type="application/json",
        )
        assert response.status_code == 201

    def test_invalid_json_returns_400(self, client, db):
        response = client.post(
            "/api/conversations/",
            data=b"not-json",
            content_type="application/json",
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# SSE stream endpoint
# ---------------------------------------------------------------------------


class TestStreamMessage:
    def _post_message(
        self,
        client: Client,
        conversation_id: int,
        content: str,
        fake_client: FakeLLMClient,
        rag_chunks: list[str] | None = None,
    ) -> list[dict]:
        body: dict = {"content": content}
        if rag_chunks:
            body["rag_chunks"] = rag_chunks

        with patch("agent.views.AnthropicClient") as MockAnthropicClient:
            MockAnthropicClient.return_value = fake_client
            response = client.post(
                f"/api/conversations/{conversation_id}/messages/",
                data=json.dumps(body),
                content_type="application/json",
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.get("Content-Type", "")
        return _parse_sse(response.content)

    def test_plain_text_stream(self, client, conversation):
        fake = FakeLLMClient([_make_text_response("Hello from the agent!")])
        events = self._post_message(client, conversation.pk, "Hi there", fake)

        event_types = [e["event"] for e in events]
        assert "token" in event_types
        assert "done" in event_types

        done = next(e for e in events if e["event"] == "done")
        assert "Hello from the agent!" in done["data"]["text"]

    def test_tool_call_events_emitted(self, client, conversation):
        fake = FakeLLMClient(
            [
                _make_tool_response(
                    "check_availability",
                    {
                        "resource_type": "console",
                        "date": "2026-05-23",
                        "time_range": ["20:00", "22:00"],
                        "party_size": 2,
                    },
                ),
                _make_text_response("Saturday 8pm is available!"),
            ]
        )
        events = self._post_message(client, conversation.pk, "Is Saturday 8pm free?", fake)

        event_types = [e["event"] for e in events]
        assert "tool_call_start" in event_types
        assert "tool_call_end" in event_types
        assert "done" in event_types

        start_evt = next(e for e in events if e["event"] == "tool_call_start")
        assert start_evt["data"]["tool_name"] == "check_availability"

        end_evt = next(e for e in events if e["event"] == "tool_call_end")
        assert end_evt["data"]["error"] is None

    def test_404_for_missing_conversation(self, client, db):
        response = client.post(
            "/api/conversations/999999/messages/",
            data=json.dumps({"content": "Hello"}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_400_for_empty_content(self, client, conversation):
        response = client.post(
            f"/api/conversations/{conversation.pk}/messages/",
            data=json.dumps({"content": ""}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_400_for_missing_content(self, client, conversation):
        response = client.post(
            f"/api/conversations/{conversation.pk}/messages/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_tokens_emitted_incrementally(self, client, conversation):
        """Tokens should be split across multiple events, not one blob."""
        fake = FakeLLMClient([_make_text_response("word1 word2 word3 word4 word5")])
        events = self._post_message(client, conversation.pk, "Say some words", fake)

        token_events = [e for e in events if e["event"] == "token"]
        # At least 2 token events for a 5-word response
        assert len(token_events) >= 2

    def test_done_event_has_correct_structure(self, client, conversation):
        fake = FakeLLMClient([_make_text_response("Booking confirmed.")])
        events = self._post_message(client, conversation.pk, "Book something", fake)

        done = next(e for e in events if e["event"] == "done")
        data = done["data"]
        assert "message_id" in data
        assert "text" in data
        assert "booking_id" in data
        assert "iteration_count" in data

    def test_sse_headers(self, client, conversation):
        fake = FakeLLMClient([_make_text_response("Hi")])
        with patch("agent.views.AnthropicClient") as MockAnthropicClient:
            MockAnthropicClient.return_value = fake
            response = client.post(
                f"/api/conversations/{conversation.pk}/messages/",
                data=json.dumps({"content": "Hello"}),
                content_type="application/json",
            )

        assert response.get("Cache-Control") == "no-cache"
        assert "text/event-stream" in response.get("Content-Type", "")
