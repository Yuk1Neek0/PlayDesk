"""Outbound template registry.

One `(en, zh)` tuple per `template_key`. Render with `SafeFormatter`
so a missing context key raises a clear, named `KeyError` at *enqueue*
time — never silently substituting an empty string in production at
send time.

The `"campaign"` key is intentionally absent: the campaigns slice
passes the rendered body verbatim via `enqueue_message(..., body=...)`
override (see `api.py::enqueue_message`).
"""

from __future__ import annotations

import string
from collections.abc import Mapping
from typing import Any


class SafeFormatter(string.Formatter):
    """A `string.Formatter` that raises `KeyError` on any missing field.

    `str.format_map` would just raise `KeyError` too, but the message
    is uninformative (`KeyError: 'foo'`). We want every render error to
    name the template that failed.
    """

    def __init__(self, template_key: str) -> None:
        super().__init__()
        self._template_key = template_key

    def get_field(self, field_name: str, args, kwargs):
        try:
            return super().get_field(field_name, args, kwargs)
        except (KeyError, AttributeError) as exc:
            raise KeyError(
                f"template {self._template_key!r} missing context key {field_name!r}"
            ) from exc

    def get_value(self, key, args, kwargs):
        try:
            return super().get_value(key, args, kwargs)
        except KeyError as exc:
            raise KeyError(f"template {self._template_key!r} missing context key {key!r}") from exc


# ---------------------------------------------------------------------------
# Templates: (en, zh) tuples. Plain prose — no placeholder TODOs.
# ---------------------------------------------------------------------------
TEMPLATES: dict[str, tuple[str, str]] = {
    "booking_confirmation": (
        "Hi {customer_name}, your booking at {store_name} is confirmed for "
        "{start_time} on {resource_name}. See you then!",
        "您好 {customer_name}，您在 {store_name} 的预订已确认："
        "{start_time}，{resource_name}。期待您的光临！",
    ),
    "reminder_24h": (
        "Reminder: your booking at {store_name} is tomorrow at {start_time} "
        "({resource_name}). Reply STOP to opt out of reminders.",
        "提醒：您在 {store_name} 的预订时间为明天 {start_time}（{resource_name}）。"
        "如需停止提醒请回复 STOP。",
    ),
    "no_show_followup": (
        "Hi {customer_name}, we missed you at {store_name} today — want to "
        "rebook? Just reply with a time and we'll set it up.",
        "您好 {customer_name}，今天我们在 {store_name} 没等到您 — 想再预订吗？"
        "回复时间即可重新安排。",
    ),
    "booking_thank_you": (
        "Thanks for visiting {store_name}, {customer_name}! Hope to see you again soon.",
        "感谢您光临 {store_name}，{customer_name}！期待再次见到您。",
    ),
    # v9 billing-payments — receipts + refund + balance-charge link.
    "payment_receipt": (
        "PlayDesk: ${amount} received for your booking on {date}. Thank you!",
        "PlayDesk：已收到您的预订付款 ${amount}（{date}）。感谢您！",
    ),
    "refund_receipt": (
        "PlayDesk: ${amount} refunded to your card. Funds typically arrive in 5-10 business days.",
        "PlayDesk：${amount} 已退回您的银行卡，5-10 个工作日内到账。",
    ),
    "booking_refunded": (
        "PlayDesk: ${amount} refunded to your card for your cancelled booking.",
        "PlayDesk：您取消的预订款项 ${amount} 已退回您的银行卡。",
    ),
    "balance_charge_link": (
        "PlayDesk: complete your booking payment (${balance}): {checkout_url}",
        "PlayDesk：请完成预订余款支付（${balance}）：{checkout_url}",
    ),
}


# Templates whose `template_key` is allowed to bypass quiet hours.
URGENT_TEMPLATE_KEYS: frozenset[str] = frozenset(
    {"booking_confirmation", "payment_receipt", "refund_receipt", "booking_refunded"}
)


def render_template(template_key: str, locale: str, context: Mapping[str, Any]) -> str:
    """Render the registered template for `(template_key, locale)`.

    `locale` falls back to English when an unknown value is passed in.
    Missing context keys raise `KeyError` with the template name baked
    into the message.
    """
    pair = TEMPLATES.get(template_key)
    if pair is None:
        raise KeyError(f"unknown template_key {template_key!r}")
    en, zh = pair
    template_str = zh if locale == "zh" else en
    return SafeFormatter(template_key).vformat(template_str, (), dict(context))
