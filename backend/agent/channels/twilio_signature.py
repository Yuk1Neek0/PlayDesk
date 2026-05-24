"""
Shared Twilio request-signature verifier.

Twilio signs every webhook (SMS, WhatsApp, Voice, status callbacks) with the
same HMAC scheme — full URL plus the sorted form params, signed against the
account's auth token. Every channel adapter that takes a Twilio webhook
needs to verify the signature before doing anything else, so the logic lives
here in one place rather than being copy-pasted per channel.

This helper is intentionally framework-agnostic (takes URL + dict + signature
strings, not a Django request) so it can be unit-tested without spinning up
a request object, and so non-Django callers can reuse it too.
"""

from __future__ import annotations

from collections.abc import Mapping


def verify_twilio_signature(
    url: str,
    post_data: Mapping[str, str],
    signature: str,
    auth_token: str,
) -> bool:
    """Return True iff Twilio's ``X-Twilio-Signature`` validates against ``url`` + ``post_data``.

    Parameters
    ----------
    url:
        The full request URL Twilio posted to (scheme + host + path + query).
        Django callers can obtain this via ``request.build_absolute_uri()``.
    post_data:
        Decoded form-encoded body as a flat ``{name: value}`` mapping.
        Django callers pass ``{k: v for k, v in request.POST.items()}``.
    signature:
        The value of the ``X-Twilio-Signature`` request header.
    auth_token:
        The Twilio account auth token. The caller is responsible for refusing
        the request when this is empty (the verifier returns ``False`` in
        that case, but the canonical "not configured" response is a 503
        emitted by the caller, not a 403).

    Returns
    -------
    bool
        True on valid signature; False on missing inputs or signature mismatch.
        Never raises.
    """
    if not signature or not auth_token:
        return False
    # Local import keeps the module importable without the Twilio SDK present
    # (e.g. for static type-checkers or doc builds).
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(auth_token)
    return validator.validate(url, dict(post_data), signature)


__all__ = ["verify_twilio_signature"]
