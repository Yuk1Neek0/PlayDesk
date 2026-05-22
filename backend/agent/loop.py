"""
Hand-rolled agent loop for PlayDesk.

Loop structure (§1.3 of the dev plan):
  1. Assemble context: system prompt + top-k RAG chunks + last N Message rows.
  2. Call the LLM.
  3. If the response has tool calls: execute them (parallel where safe),
     append structured results to context, persist, iterate.
  4. If the response is plain text: stream to client, persist, end.
  5. Hard cap at AGENT_MAX_ITERATIONS (default 6) with graceful fallback.

Every turn (user / assistant / tool call / tool result) is persisted as a
Message row; tool payloads go into the JSONB tool_call_data column.

The loop emits events via an event_callback so the SSE layer can forward
them to the client without coupling the loop to Django's HTTP machinery.
"""

from __future__ import annotations

import concurrent.futures
import json
from collections.abc import Callable
from typing import Any, Literal

from django.conf import settings

from agent_tools.registry import all_tools, get_tool
from core.models import Conversation, Message, MessageRole

from .language import detect_language
from .llm_client import LLMClientProtocol, LLMResponse, ToolCallRequest
from .prompt import SYSTEM_PROMPT, date_directive, language_directive

# ---------------------------------------------------------------------------
# SSE event dataclasses (lightweight dicts to avoid import cycles)
# ---------------------------------------------------------------------------

AgentEventType = Literal["token", "tool_call_start", "tool_call_end", "done", "error"]
AgentEventCallback = Callable[[AgentEventType, dict[str, Any]], None]

_HANDOFF_MESSAGE = (
    "I've reached the limit of what I can resolve in one turn. "
    "Let me hand this over to a human teammate who can help you further."
)

_PARALLEL_SAFE_TOOLS = {
    "search_knowledge_base",
    "check_availability",
    "get_resource_details",
}


def _build_tool_manifest() -> list[dict[str, Any]]:
    """Convert the tool registry into the Anthropic tool-use manifest format."""
    manifest: list[dict[str, Any]] = []
    for entry in all_tools().values():
        schema = entry.input_schema.model_json_schema()
        # Anthropic requires "input_schema" not "parameters"
        manifest.append(
            {
                "name": entry.name,
                "description": entry.description,
                "input_schema": schema,
            }
        )
    return manifest


def _history_to_messages(history: list[Message]) -> list[dict[str, Any]]:
    """Convert Message ORM rows to the Anthropic messages list format."""
    messages: list[dict[str, Any]] = []
    for msg in history:
        if msg.role == MessageRole.USER:
            messages.append({"role": "user", "content": msg.content})
        elif msg.role == MessageRole.ASSISTANT:
            # Could contain tool-use blocks stored in tool_call_data
            tcd = msg.tool_call_data
            if tcd and tcd.get("type") == "assistant_with_tools":
                messages.append({"role": "assistant", "content": tcd["content"]})
            else:
                messages.append({"role": "assistant", "content": msg.content})
        elif msg.role == MessageRole.TOOL:
            # Tool result messages are already in Anthropic's tool_result format
            tcd = msg.tool_call_data
            if tcd:
                messages.append({"role": "user", "content": tcd.get("content", [])})
    return messages


def _persist_user_message(conversation: Conversation, content: str) -> Message:
    return Message.objects.create(
        conversation=conversation,
        role=MessageRole.USER,
        content=content,
    )


def _persist_assistant_message(
    conversation: Conversation,
    content: str,
    tool_call_data: dict[str, Any] | None = None,
) -> Message:
    return Message.objects.create(
        conversation=conversation,
        role=MessageRole.ASSISTANT,
        content=content,
        tool_call_data=tool_call_data,
    )


def _persist_tool_result(
    conversation: Conversation,
    tool_call_id: str,
    tool_name: str,
    result: Any,
    error: str | None,
) -> Message:
    """Persist a tool result as a TOOL-role Message with JSONB payload."""
    result_str = json.dumps(result, default=str) if result is not None else None
    payload: dict[str, Any] = {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "result": result,
        "error": error,
        # Anthropic tool_result format stored for later history reconstruction
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": result_str if error is None else f"ERROR: {error}",
            }
        ],
    }
    return Message.objects.create(
        conversation=conversation,
        role=MessageRole.TOOL,
        content=result_str or (f"ERROR: {error}" if error else ""),
        tool_call_data=payload,
    )


def _execute_tool(
    tc: ToolCallRequest,
) -> tuple[ToolCallRequest, Any, str | None]:
    """
    Execute a single tool call.

    Returns (tool_call_request, result, error_message).
    Tool exceptions are caught and returned as structured errors — never raised.
    """
    try:
        entry = get_tool(tc.tool_name)
        validated_input = entry.input_schema.model_validate(tc.arguments)
        result_obj = entry.fn(validated_input)
        return tc, result_obj.model_dump(mode="json"), None
    except KeyError:
        return tc, None, f"Unknown tool: {tc.tool_name!r}"
    except Exception as exc:  # noqa: BLE001
        return tc, None, str(exc)


def _execute_tools_parallel(
    tool_calls: list[ToolCallRequest],
) -> list[tuple[ToolCallRequest, Any, str | None]]:
    """
    Execute tool calls.

    Tools in _PARALLEL_SAFE_TOOLS are dispatched concurrently.
    Any tool NOT in the safe set is run sequentially after the parallel batch.
    """
    parallel: list[ToolCallRequest] = []
    sequential: list[ToolCallRequest] = []
    for tc in tool_calls:
        if tc.tool_name in _PARALLEL_SAFE_TOOLS:
            parallel.append(tc)
        else:
            sequential.append(tc)

    results: list[tuple[ToolCallRequest, Any, str | None]] = []

    if parallel:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(parallel)) as pool:
            futures = {pool.submit(_execute_tool, tc): tc for tc in parallel}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        # Sort back to original order for determinism
        order = {tc.tool_call_id: i for i, tc in enumerate(parallel)}
        results.sort(key=lambda r: order[r[0].tool_call_id])

    for tc in sequential:
        results.append(_execute_tool(tc))

    return results


# ---------------------------------------------------------------------------
# Public agent loop entry point
# ---------------------------------------------------------------------------


class AgentLoop:
    """
    Stateless agent loop.  Instantiate once per request (or re-use across requests).

    Parameters
    ----------
    llm_client:
        Any object implementing LLMClientProtocol.  Inject FakeLLMClient in tests.
    rag_chunks:
        Pre-retrieved RAG context to inject into the system prompt.  The RAG agent
        is responsible for retrieval; this layer just inserts whatever it gets.
    max_iterations:
        Hard cap (defaults to settings.AGENT_MAX_ITERATIONS).
    event_callback:
        Called for every SSE event.  Signature: (event_type, payload_dict) → None.
        The SSE view provides this; tests can inspect it.
    """

    def __init__(
        self,
        llm_client: LLMClientProtocol,
        rag_chunks: list[str] | None = None,
        max_iterations: int | None = None,
        event_callback: AgentEventCallback | None = None,
    ) -> None:
        self._llm = llm_client
        self._rag_chunks = rag_chunks or []
        self._max_iterations = (
            max_iterations
            if max_iterations is not None
            else getattr(settings, "AGENT_MAX_ITERATIONS", 6)
        )
        self._emit = event_callback or (lambda _t, _p: None)
        self._tool_manifest = _build_tool_manifest()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        conversation: Conversation,
        user_content: str,
        persist_user_message: bool = True,
    ) -> dict[str, Any]:
        """
        Drive the agent loop for one user turn.

        Returns a summary dict:
            {
                "message_id": int,
                "text": str,
                "booking_id": int | None,
                "iteration_count": int,
            }
        """
        if persist_user_message:
            _persist_user_message(conversation, user_content)

        # Emit user-content token so streaming SSE can show it immediately
        # (omitted — the user message isn't streamed back, only assistant tokens)

        # Detect the customer's language from this turn so the agent both
        # replies in it and retrieves KB chunks tagged with it.
        lang = detect_language(user_content)
        system = self._build_system_prompt(lang)
        iteration = 0
        booking_id: int | None = None
        final_text = ""
        final_message: Message | None = None

        # Load full conversation history from DB
        history = list(conversation.messages.order_by("created_at"))

        # Build initial messages list for the LLM
        llm_messages = _history_to_messages(history)

        while iteration < self._max_iterations:
            iteration += 1

            try:
                response: LLMResponse = self._llm.complete(
                    system=system,
                    messages=llm_messages,
                    tools=self._tool_manifest,
                )
            except RuntimeError as exc:
                self._emit(
                    "error",
                    {
                        "code": "llm_unavailable",
                        "detail": str(exc),
                        "retryable": True,
                    },
                )
                raise

            if not response.has_tool_calls:
                # Plain-text final response
                final_text = response.text
                # Emit tokens incrementally (split into words for chunked streaming)
                words = final_text.split(" ")
                for i, word in enumerate(words):
                    token = word if i == 0 else " " + word
                    self._emit("token", {"delta": token})

                # Persist assistant message
                final_message = _persist_assistant_message(conversation, final_text)
                break

            # --- Tool-call branch ---
            # Bilingual retrieval: pin search_knowledge_base to the detected
            # language so a Chinese question hits lang="zh" KB chunks,
            # regardless of what the model passed for `lang`.
            for tc in response.tool_calls:
                if tc.tool_name == "search_knowledge_base":
                    tc.arguments["lang"] = lang

            # Persist assistant turn with tool calls in tool_call_data
            tool_call_content = [
                {
                    "type": "tool_use",
                    "id": tc.tool_call_id,
                    "name": tc.tool_name,
                    "input": tc.arguments,
                }
                for tc in response.tool_calls
            ]
            if response.text:
                tool_call_content.insert(0, {"type": "text", "text": response.text})

            _persist_assistant_message(
                conversation,
                content=response.text,
                tool_call_data={
                    "type": "assistant_with_tools",
                    "content": tool_call_content,
                },
            )

            # Append assistant message to llm_messages
            llm_messages.append({"role": "assistant", "content": tool_call_content})

            # Emit tool_call_start for each tool
            for tc in response.tool_calls:
                self._emit(
                    "tool_call_start",
                    {
                        "tool_call_id": tc.tool_call_id,
                        "tool_name": tc.tool_name,
                        "arguments": tc.arguments,
                    },
                )

            # Execute tools (parallel where safe)
            tool_results = _execute_tools_parallel(response.tool_calls)

            # Collect tool results into a single user message (Anthropic format)
            tool_result_content: list[dict[str, Any]] = []
            for tc, result, error in tool_results:
                # Emit tool_call_end SSE event
                self._emit(
                    "tool_call_end",
                    {
                        "tool_call_id": tc.tool_call_id,
                        "tool_name": tc.tool_name,
                        "result": result,
                        "error": error,
                    },
                )

                # Persist the tool result row
                _persist_tool_result(conversation, tc.tool_call_id, tc.tool_name, result, error)

                # Extract booking_id if this was a successful create_booking call
                if tc.tool_name == "create_booking" and result and error is None:
                    inner = result.get("result", {})
                    if isinstance(inner, dict) and inner.get("success"):
                        booking_id = inner.get("booking_id")

                # Build tool_result block for the next LLM call
                content_str = (
                    json.dumps(result, default=str) if error is None else f"ERROR: {error}"
                )
                tool_result_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.tool_call_id,
                        "content": content_str,
                    }
                )

            # Append tool results to LLM message list
            llm_messages.append({"role": "user", "content": tool_result_content})

        else:
            # Iteration cap reached — graceful handoff
            final_text = _HANDOFF_MESSAGE
            self._emit("token", {"delta": final_text})
            self._emit(
                "error",
                {
                    "code": "iteration_limit",
                    "detail": "Agent hit the maximum iteration limit.",
                    "retryable": False,
                },
            )
            final_message = _persist_assistant_message(conversation, final_text)

        message_id = final_message.pk if final_message else None

        self._emit(
            "done",
            {
                "message_id": message_id,
                "text": final_text,
                "booking_id": booking_id,
                "iteration_count": iteration,
            },
        )

        return {
            "message_id": message_id,
            "text": final_text,
            "booking_id": booking_id,
            "iteration_count": iteration,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self, lang: str) -> str:
        prompt = SYSTEM_PROMPT + date_directive() + language_directive(lang)
        if not self._rag_chunks:
            return prompt
        chunks_text = "\n\n".join(
            f"[Knowledge chunk {i + 1}]\n{chunk}" for i, chunk in enumerate(self._rag_chunks)
        )
        return prompt + "\n\n## Relevant Knowledge Base Excerpts\n\n" + chunks_text
