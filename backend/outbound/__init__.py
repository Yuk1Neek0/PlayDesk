"""Outbound messaging app.

Houses the `OutboundMessage` queue, the booking-driven signals that
populate it, the public `enqueue_message` API, the template registry,
and the `send_outbound` management command. See `.claude/prds/outbound.md`.
"""

default_app_config = "outbound.apps.OutboundConfig"
