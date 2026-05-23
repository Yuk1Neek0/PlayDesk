"""Unit tests for ChannelAdapter implementations — pure Python, no DB."""

from __future__ import annotations

from agent.channels.base import NormalizedMessage
from agent.channels.web_chat import WebChatAdapter


def test_web_chat_normalize_inbound_basic():
    msg = WebChatAdapter().normalize_inbound({"content": "Hi there", "rag_chunks": ["a", "b"]})
    assert isinstance(msg, NormalizedMessage)
    assert msg.text == "Hi there"
    assert msg.channel == "web_chat"
    assert msg.rag_chunks == ["a", "b"]


def test_web_chat_strips_whitespace_and_defaults_rag():
    msg = WebChatAdapter().normalize_inbound({"content": "  spaced  "})
    assert msg.text == "spaced"
    assert msg.rag_chunks == []


def test_web_chat_ignores_non_list_rag_chunks():
    """A client that sends rag_chunks as a dict shouldn't crash the adapter."""
    msg = WebChatAdapter().normalize_inbound({"content": "x", "rag_chunks": {"oops": True}})
    assert msg.rag_chunks == []


def test_web_chat_empty_content_normalises_to_empty():
    msg = WebChatAdapter().normalize_inbound({})
    assert msg.text == ""
    assert msg.channel == "web_chat"


def test_web_chat_format_outbound_matches_done_event_shape():
    out = WebChatAdapter().format_outbound(
        "Booked!", metadata={"message_id": 42, "booking_id": 17, "iteration_count": 2}
    )
    assert out == {"message_id": 42, "text": "Booked!", "booking_id": 17, "iteration_count": 2}


def test_web_chat_format_outbound_tolerates_missing_metadata():
    out = WebChatAdapter().format_outbound("Done")
    assert out == {"message_id": None, "text": "Done", "booking_id": None, "iteration_count": 0}
