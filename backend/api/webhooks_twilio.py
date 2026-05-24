"""
Twilio inbound webhooks (SMS + Voice).

POST /api/webhooks/twilio/sms/           — runs the agent loop and replies via TwiML.
POST /api/webhooks/twilio/voice/         — v5 scaffold: plays a static bilingual
                                           greeting and records a Conversation row
                                           with ``channel='phone'``. No STT/TTS/agent
                                           turn; see
                                           ``docs/voice-implementation-plan.md``
                                           for the next layer of work.
POST /api/webhooks/twilio/voice/status/  — call-status callback. Records a
                                           Conversation row with
                                           ``status='abandoned'`` for missed/failed
                                           calls so the admin filter shows
                                           attempted-but-missed calls too. Skips
                                           ``CallStatus=completed`` to avoid
                                           double-writing the row already created
                                           by the answer-time voice webhook.

All endpoints verify the inbound signature (mandatory — no dev-mode bypass).
When ``TWILIO_AUTH_TOKEN`` is unset they return ``503 not_configured`` cleanly
so CI without secrets stays green.
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
from core.phone import normalize_phone


def _signature_ok(request: HttpRequest, auth_token: str) -> bool:
    """Verify the Twilio request signature for a Django request.

    Thin wrapper around the shared ``verify_twilio_signature`` helper that
    pulls the signature header and absolute URL out of the Django request.
    The shared helper is reused by the WhatsApp + Voice webhooks too.
    """
    signature = request.META.get("HTTP_X_TWILIO_SIGNATURE") or request.META.get(
        "HTTP_X_TWILIO_SIGNATURE".lower()
    )
    # Twilio signs against the public URL the request came in on, which
    # is `<scheme>://<host>/<path>?<query>`. Django's `build_absolute_uri`
    # composes that for us.
    url = request.build_absolute_uri()
    params = {k: v for k, v in request.POST.items()}
    return verify_twilio_signature(url, params, signature or "", auth_token)


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


# ---------------------------------------------------------------------------
# Twilio Voice — v5 scaffold
# ---------------------------------------------------------------------------
# The greeting body is defined here (not loaded from a template) so the
# message is version-controlled and editable in one place. The voice +
# language pairs are Twilio-supported combinations: Polly.Joanna speaks
# en-US, Polly.Zhiyu speaks cmn-CN. The bilingual greeting matches the
# agent's existing locale support.
_VOICE_GREETING_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Response>"
    '<Say voice="Polly.Joanna" language="en-US">'
    "You&#39;ve reached PlayDesk. Voice is coming soon &#8212; please text us "
    "at this number for now."
    "</Say>"
    '<Say voice="Polly.Zhiyu" language="cmn-CN">'
    "&#20013;&#25991;&#24744;&#20063;&#21487;&#20197;&#30332;&#30701;&#20449;"
    "&#32102;&#25105;&#20497;&#12290;"
    "</Say>"
    "</Response>"
)


@csrf_exempt
@require_POST
def twilio_voice_webhook(request: HttpRequest) -> HttpResponse:
    """Answer an inbound Twilio Voice call with static bilingual TwiML.

    Records a ``Conversation`` row with ``channel='phone'`` so the admin
    chip filter for phone calls finally has data to filter. No STT, no
    TTS, no agent turn — that's the whole point of this v5 scaffold. See
    ``docs/voice-implementation-plan.md`` for what comes next.
    """
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "") or ""
    if not token:
        return JsonResponse({"error": "not_configured"}, status=503)

    if not _signature_ok(request, token):
        return JsonResponse({"error": "invalid_signature"}, status=403)

    # Twilio's Voice webhook posts ``From`` (E.164 caller number) and
    # ``CallSid`` among other fields. We only need ``From`` to record the
    # conversation — the rest is logged via Twilio's own dashboards.
    raw_from = str(request.POST.get("From", "")).strip()
    normalised = normalize_phone(raw_from) or raw_from

    # Best-effort Customer lookup so the side-effect of recording a phone
    # row also surfaces existing customer context downstream. We don't
    # store the FK directly (Conversation has no ``customer`` field in v5)
    # — the customer is resolved at read-time via ``customer_identifier``,
    # which already matches the retention slice's E.164 normalisation.
    # Looking up here keeps the linkage explicit and reserves the spot for
    # a future migration that adds the FK without changing this view.
    from core.models import Customer

    Customer.objects.filter(phone=normalised).first()

    # NOTE: ``status='completed'`` is intentional and not (yet) in
    # ``ConversationStatus.choices``. The PRD requires this exact value
    # for the answer-time row so the admin filter can distinguish
    # answered calls from missed-call rows (which the status-callback
    # view writes with ``status='abandoned'``). Django's TextChoices
    # validation is opt-in via ``full_clean()`` so ``save()`` accepts it.
    Conversation.objects.create(
        channel="phone",
        customer_identifier=normalised,
        status="completed",
    )

    return HttpResponse(_VOICE_GREETING_TWIML, content_type="application/xml")


# CallStatus values that indicate the call did NOT connect to a human (or
# to our greeting) — these are the missed-call events we record. The
# ``completed`` value is deliberately excluded: the answer-time
# ``twilio_voice_webhook`` already wrote that row, and Twilio fires this
# status callback for *every* call (answered or not) so we'd double-write
# otherwise.
_MISSED_CALL_STATUSES: frozenset[str] = frozenset({"no-answer", "busy", "failed", "canceled"})


@csrf_exempt
@require_POST
def twilio_voice_status_callback(request: HttpRequest) -> HttpResponse:
    """Capture missed/failed call attempts as Conversation rows.

    Twilio fires this webhook on every call's final ``CallStatus`` event
    (``completed``, ``no-answer``, ``busy``, ``failed``, ``canceled``).
    We only act on the *missed* statuses — the answered case was already
    written by ``twilio_voice_webhook``. Returns 200 with an empty body
    in all success paths; Twilio doesn't read the response payload on
    status callbacks.

    The phone number is configured to call this URL via Twilio's
    "Voice & Fax → Call Status Changes" setting; see
    ``docs/voice-implementation-plan.md`` for operator setup.
    """
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "") or ""
    if not token:
        return JsonResponse({"error": "not_configured"}, status=503)

    if not _signature_ok(request, token):
        return JsonResponse({"error": "invalid_signature"}, status=403)

    call_status = str(request.POST.get("CallStatus", "")).strip().lower()
    if call_status not in _MISSED_CALL_STATUSES:
        # ``completed`` or any unrecognised status — nothing to write.
        # Twilio still expects a 200; an empty body is the documented
        # ack pattern for status callbacks.
        return HttpResponse("", content_type="text/plain")

    raw_from = str(request.POST.get("From", "")).strip()
    normalised = normalize_phone(raw_from) or raw_from

    # NOTE: ``status='abandoned'`` is intentional and not (yet) in
    # ``ConversationStatus.choices``. Mirrors the ``status='completed'``
    # value used by the answer-time webhook — both are PRD-mandated and
    # are written via ``save()`` which doesn't enforce TextChoices.
    # Distinguishing answered vs. missed at read-time is the whole point
    # of the two different values.
    Conversation.objects.create(
        channel="phone",
        customer_identifier=normalised,
        status="abandoned",
    )

    return HttpResponse("", content_type="text/plain")


# Convenience exports so urls.py can import a single symbol per endpoint.
__all__ = [
    "twilio_sms_webhook",
    "twilio_voice_status_callback",
    "twilio_voice_webhook",
]


# `json` import is kept for future JSON-based webhook variants.
_ = json
