"""
Injectable LLM client interface for the PlayDesk agent loop.

Production:  AnthropicClient  — calls the real Anthropic API.
Tests:       FakeLLMClient     — scripted responses, no network.

The agent loop depends only on the LLMClientProtocol, so tests swap the
real client without any monkey-patching.
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from django.conf import settings

# ---------------------------------------------------------------------------
# Data types shared between client and loop
# ---------------------------------------------------------------------------


class ToolCallRequest:
    """Represents a single tool-call requested by the LLM."""

    __slots__ = ("tool_call_id", "tool_name", "arguments")

    def __init__(self, tool_call_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        self.arguments = arguments

    def __repr__(self) -> str:  # pragma: no cover
        return f"ToolCallRequest(id={self.tool_call_id!r}, name={self.tool_name!r})"


class LLMResponse:
    """Parsed response from the LLM."""

    __slots__ = ("text", "tool_calls", "stop_reason", "raw")

    def __init__(
        self,
        text: str,
        tool_calls: list[ToolCallRequest],
        stop_reason: str,
        raw: Any = None,
    ) -> None:
        self.text = text
        self.tool_calls = tool_calls
        self.stop_reason = stop_reason
        self.raw = raw

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# ---------------------------------------------------------------------------
# Protocol (the injectable interface)
# ---------------------------------------------------------------------------


class LLMClientProtocol(Protocol):
    """
    The interface the agent loop uses to talk to an LLM.

    Both the real Anthropic client and the fake test client implement this.
    """

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        """Send a completion request; return the parsed response."""
        ...


# ---------------------------------------------------------------------------
# Real Anthropic implementation
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds


class AnthropicClient:
    """
    Thin wrapper around the Anthropic Python SDK.

    Implements exponential backoff (max 3 retries) on transient API errors.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required to use AnthropicClient. "
                "Install it with: pip install anthropic"
            ) from exc

        self._anthropic = anthropic
        self._api_key = api_key or settings.ANTHROPIC_API_KEY
        self._model = model or settings.ANTHROPIC_MODEL
        self._max_tokens = max_tokens
        self._client = anthropic.Anthropic(api_key=self._api_key)

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        last_exc: Exception | None = None
        anthropic = self._anthropic
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system,
                    messages=messages,
                    tools=tools or [],
                )
                return _parse_anthropic_response(response)
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BACKOFF_BASE * (2**attempt))
        raise RuntimeError(
            f"LLM API unavailable after {_MAX_RETRIES} retries: {last_exc}"
        ) from last_exc


def _parse_anthropic_response(response: Any) -> LLMResponse:
    """Convert a raw Anthropic response object into an LLMResponse."""
    text_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []

    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(
                ToolCallRequest(
                    tool_call_id=block.id,
                    tool_name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                )
            )

    return LLMResponse(
        text="".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=response.stop_reason or "end_turn",
        raw=response,
    )


# ---------------------------------------------------------------------------
# Fake client for testing
# ---------------------------------------------------------------------------


class FakeLLMClient:
    """
    Scripted LLM client for tests.

    Feed it a list of LLMResponse objects; each call to `complete` pops the
    next response from the queue. Raises AssertionError if the script runs out.

    Usage in tests::

        fake = FakeLLMClient([
            LLMResponse(
                text="",
                tool_calls=[ToolCallRequest("tc1", "check_availability", {...})],
                stop_reason="tool_use",
            ),
            LLMResponse(
                text="Your booking is confirmed!",
                tool_calls=[],
                stop_reason="end_turn",
            ),
        ])
        loop = AgentLoop(llm_client=fake, ...)
    """

    def __init__(self, script: list[LLMResponse]) -> None:
        self._script = list(script)
        self._call_count = 0
        self.call_log: list[dict[str, Any]] = []

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        if not self._script:
            raise AssertionError(
                f"FakeLLMClient ran out of scripted responses after {self._call_count} call(s)."
            )
        self._call_count += 1
        self.call_log.append(
            {
                "system": system,
                "messages": json.loads(json.dumps(messages, default=str)),
                "tools": tools,
            }
        )
        return self._script.pop(0)
