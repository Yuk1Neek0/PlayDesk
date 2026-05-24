"""
Twilio SMS webhook.

POST /api/webhooks/twilio/sms/

Verifies the inbound signature (mandatory — no dev-mode bypass), runs
the agent loop synchronously over the normalised message, and returns
TwiML carrying the assembled assistant reply. When ``TWILIO_AUTH_TOKEN``
is unset the endpoint returns ``503 not_configured`` cleanly so CI
without secrets stays green.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from agent.channels.twilio_signature import verify_twilio_signature
from agent.channels.twilio_sms import TwilioSmsAdapter
from agent.llm_client import AnthropicClient
from agent.loop import AgentLoop
from core.models import Conversation


def _signature_ok(request: HttpRequest, auth_token: str) -> bool:
    """Verify the Twilio request signature via the shared helper.

    Pulls the signature header (Django uppercases `X-Twilio-Signature`
    into `HTTP_X_TWILIO_SIGNATURE`), composes the public URL Twilio
    signed against, and defers the HMAC check to
    `agent.channels.twilio_signature.verify_twilio_signature`.
    """
    signature = request.META.get("HTTP_X_TWILIO_SIGNATURE") or request.META.get(
        "HTTP_X_TWILIO_SIGNATURE".lower()
    )
    if not signature:
        return False
    url = request.build_absolute_uri()
    params = {k: v for k, v in request.POST.items()}
    return verify_twilio_signature(url, params, signature, auth_token)


@csrf_exempt
@require_POST
def twilio_sms_webhook(request: HttpRequest) -> HttpResponse:
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "") or ""
    if not token:
        return JsonResponse({"error": "not_configured"}, status=503)

    if not _signature_ok(request, token):
        return JsonResponse({"error": "invalid_signature"}, status=403)

    # Twilio posts form-encoded data; the adapter expects a dict-like
    # payload. `request.POST` already decodes it.
    form_payload = {k: v for k, v in request.POST.items()}
    adapter = TwilioSmsAdapter()
    inbound = adapter.normalize_inbound(form_payload)

    if not inbound.text:
        # Empty SMS body — silently ack with empty TwiML so Twilio
        # doesn't retry. Nothing for the agent to respond to.
        return HttpResponse(adapter.format_outbound(""), content_type="application/xml")

    # Find-or-create the conversation by (channel, customer_identifier).
    # SMS conversations are one-per-customer so the agent can hold a
    # multi-turn thread without a session id.
    conv, _ = Conversation.objects.get_or_create(
        customer_identifier=inbound.customer_identifier,
        channel="sms",
        defaults={},
    )

    # Run the agent loop synchronously and collect the final reply text.
    # No event callback — SMS is one-shot, no streaming.
    loop = AgentLoop(
        llm_client=AnthropicClient(),
        rag_chunks=inbound.rag_chunks,
    )
    try:
        summary = loop.run(conversation=conv, user_content=inbound.text)
        final_text = summary.get("text") or ""
        booking_id = summary.get("booking_id")
        iteration_count = summary.get("iteration_count", 0)
    except Exception:  # noqa: BLE001
        final_text = "Sorry — I hit a problem just now. A human will follow up."
        booking_id = None
        iteration_count = 0

    reply = adapter.format_outbound(
        final_text,
        metadata={"booking_id": booking_id, "iteration_count": iteration_count},
    )
    return HttpResponse(reply, content_type="application/xml")


# Convenience export so urls.py can import a single symbol.
__all__ = ["twilio_sms_webhook"]


# `json` import is kept for future JSON-based webhook variants.
_ = json
