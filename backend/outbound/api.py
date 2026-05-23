"""Public Python API for the outbound app.

`enqueue_message` is the single entry point the booking signals call
(task #116) and the `campaigns` slice imports. Everything else in the
outbound package is internal.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from django.utils import timezone

from core.models import Customer

from .models import OutboundChannel, OutboundMessage, OutboundStatus
from .templates import TEMPLATES, render_template


def enqueue_message(
    customer: Customer,
    template_key: str,
    context: Mapping[str, Any] | None = None,
    scheduled_for: datetime | None = None,
    channel: str = OutboundChannel.SMS,
    reference: str = "",
    body: str | None = None,
) -> OutboundMessage:
    """Enqueue one outbound message for `customer`.

    Behaviour:
    - Renders the registered template against `customer.locale_pref`
      unless `body` is passed in (the campaigns slice uses `body=`
      with `template_key="campaign"` to ship raw bodies that were
      pre-rendered upstream).
    - Defaults `scheduled_for` to "send immediately" (now).
    - Idempotent on `(reference, template_key)` when `reference` is
      non-empty: if a row with the same key already exists in `queued`
      or `sent` status, returns the existing row without inserting.
      Lets the booking signals re-fire freely without double-sending.
    """
    if scheduled_for is None:
        scheduled_for = timezone.now()
    if context is None:
        context = {}

    # Idempotence guard — the cheap query first.
    if reference:
        existing = (
            OutboundMessage.objects.filter(
                reference=reference,
                template_key=template_key,
                status__in=[OutboundStatus.QUEUED, OutboundStatus.SENT],
            )
            .order_by("id")
            .first()
        )
        if existing is not None:
            return existing

    # Render the body — unless the caller supplied one (campaigns path).
    if body is None:
        if template_key not in TEMPLATES:
            raise KeyError(f"unknown template_key {template_key!r}")
        body = render_template(template_key, customer.locale_pref, context)

    return OutboundMessage.objects.create(
        customer=customer,
        channel=channel,
        template_key=template_key,
        body=body,
        scheduled_for=scheduled_for,
        reference=reference,
    )
