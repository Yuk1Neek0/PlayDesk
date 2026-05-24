"""Implicit channel-preference resolver.

`pick_channel_for(customer)` looks at the customer's most recent inbound
Conversation; if that conversation arrived over WhatsApp, future
outbound messages default to WhatsApp; otherwise they default to SMS.

Why implicit rather than stored: an explicit `Customer.preferred_channel`
column would need a UI to set it and a migration to add it. The implicit
lookup gives the right answer (almost everyone replies on the channel
they last used) without either.

Pure Python on the `Conversation` model — no Django request context
needed, so the helper is reusable from signals, management commands,
and the outbound enqueue path alike.
"""

from __future__ import annotations

from core.models import Conversation, Customer

from .models import OutboundChannel

# Conversation channels that are *also* valid outbound delivery channels.
# `web_chat`, `phone`, `manual_staff` aren't routable outbound, so an
# inbound conversation on one of those falls back to the SMS default.
_OUTBOUND_CHANNELS: tuple[str, ...] = (OutboundChannel.SMS, OutboundChannel.WHATSAPP)


def pick_channel_for(customer: Customer) -> str:
    """Return the outbound channel string ('sms' or 'whatsapp') for `customer`.

    Walks the customer's most recent SMS-or-WhatsApp `Conversation` and
    returns that channel. Defaults to `'sms'` when:
    - the customer has no inbound history at all, OR
    - the most recent inbound was web_chat / phone / manual_staff (not
      a routable outbound channel).

    One indexed query — `Conversation` is already ordered by
    `-started_at`, and the inbound-conversation phone is stored in
    `customer_identifier`. SMS and WhatsApp adapters normalise that
    field to bare E.164, matching `Customer.phone`.
    """
    if not customer.phone:
        return OutboundChannel.SMS
    latest = (
        Conversation.objects.filter(
            customer_identifier=customer.phone,
            channel__in=_OUTBOUND_CHANNELS,
        )
        .order_by("-started_at")
        .values_list("channel", flat=True)
        .first()
    )
    return latest or OutboundChannel.SMS
