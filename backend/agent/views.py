"""
Django views for the PlayDesk agent SSE streaming endpoint.

Routes (defined in agent/urls.py):
  POST /api/conversations/              — create a conversation
  POST /api/conversations/<id>/messages/ — send a message, stream SSE response
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Generator
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import Conversation, ConversationStatus

from .channels.web_chat import WebChatAdapter
from .llm_client import AnthropicClient
from .loop import AgentLoop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse_event(event_type: str, payload: dict[str, Any]) -> str:
    """Encode a single SSE event as a string."""
    data = json.dumps(payload, default=str)
    return f"event: {event_type}\ndata: {data}\n\n"


_STREAM_DONE = object()  # sentinel: agent loop finished


def _run_agent_stream(
    conversation: Conversation,
    user_content: str,
    rag_chunks: list[str],
) -> Generator[str, None, None]:
    """
    Generator that drives the agent loop and yields SSE-formatted strings.

    The loop runs in a background thread and emits events via callback into a
    thread-safe queue; this generator yields each event to the client as soon
    as it is produced, so tokens stream incrementally rather than buffering
    until the loop completes.
    """
    event_queue: queue.Queue[Any] = queue.Queue()

    def on_event(event_type: str, payload: dict[str, Any]) -> None:
        event_queue.put((event_type, payload))

    llm_client = AnthropicClient(
        api_key=getattr(settings, "ANTHROPIC_API_KEY", ""),
        model=getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-7"),
    )
    loop = AgentLoop(
        llm_client=llm_client,
        rag_chunks=rag_chunks,
        event_callback=on_event,
    )

    def _drive() -> None:
        try:
            loop.run(conversation, user_content)
        except RuntimeError as exc:
            # LLM unavailable after retries — surface as an SSE error event in
            # case the loop raised before emitting one itself.
            event_queue.put(
                (
                    "error",
                    {
                        "code": "llm_unavailable",
                        "detail": str(exc),
                        "retryable": True,
                    },
                )
            )
        finally:
            # This worker thread owns its own DB connection(s); close them so
            # they are not leaked (and do not block test-DB teardown) when the
            # thread exits.
            from django.db import connections

            connections.close_all()
            event_queue.put(_STREAM_DONE)

    worker = threading.Thread(target=_drive, daemon=True)
    worker.start()

    try:
        while True:
            item = event_queue.get()
            if item is _STREAM_DONE:
                break
            event_type, payload = item
            yield _sse_event(event_type, payload)
    finally:
        # Always wait for the worker — even if the client disconnects early —
        # so its DB connection is closed before the request/test completes.
        worker.join()


# ---------------------------------------------------------------------------
# Conversation creation view
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def create_conversation(request: HttpRequest) -> JsonResponse:
    """
    POST /api/conversations/

    Body (JSON):
        { "customer_identifier": "<string>" }   # optional, defaults to "anonymous"

    Returns:
        { "id": <int>, "status": "active", "started_at": "<iso>" }
    """
    try:
        body: dict[str, Any] = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    customer_identifier = body.get("customer_identifier", "anonymous")
    conversation = Conversation.objects.create(
        customer_identifier=str(customer_identifier),
        status=ConversationStatus.ACTIVE,
    )
    return JsonResponse(
        {
            "id": conversation.pk,
            "status": conversation.status,
            "started_at": conversation.started_at.isoformat(),
        },
        status=201,
    )


# ---------------------------------------------------------------------------
# Message streaming view
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def stream_message(
    request: HttpRequest, conversation_id: int
) -> StreamingHttpResponse | JsonResponse:
    """
    POST /api/conversations/<id>/messages/

    Body (JSON):
        {
            "content": "<user message>",
            "rag_chunks": ["<chunk1>", ...]   # optional, injected by RAG layer
        }

    Returns a Server-Sent Events stream.
    """
    # Validate conversation exists
    try:
        conversation = Conversation.objects.get(pk=conversation_id)
    except Conversation.DoesNotExist:
        # Return a JSON error immediately (not SSE) since stream hasn't started
        return JsonResponse(
            {
                "error": "conversation_not_found",
                "detail": f"Conversation {conversation_id} does not exist.",
            },
            status=404,
        )

    # Parse body via the web-chat channel adapter so every channel goes
    # through the same normalisation seam (cross-slice with Twilio SMS).
    try:
        body: dict[str, Any] = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"error": "invalid_message", "detail": "Invalid JSON body."}, status=400
        )

    normalised = WebChatAdapter().normalize_inbound(body)
    if not normalised.text:
        return JsonResponse(
            {
                "error": "invalid_message",
                "detail": "Field 'content' is required and must be non-empty.",
            },
            status=400,
        )

    # Stamp the channel on the conversation if it hasn't been set yet
    # (legacy rows pre-migration default to web_chat anyway, but new
    # conversations posted via this endpoint stay explicit).
    if conversation.channel != "web_chat":
        Conversation.objects.filter(pk=conversation.pk, channel="web_chat").update(
            channel="web_chat"
        )

    response = StreamingHttpResponse(
        _run_agent_stream(conversation, normalised.text, normalised.rag_chunks),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
