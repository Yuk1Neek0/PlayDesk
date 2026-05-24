"""
Shared Twilio request-signature verification.

Twilio signs every webhook request with HMAC-SHA1 over the full request
URL and the sorted form params, using the account's auth token as the
key. The SMS, WhatsApp, and (in the voice-scaffold slice) Voice webhooks
all need to re-verify that signature before trusting the payload.

Kept Django-free so the helper is reusable from any web framework or a
direct caller in tests.
"""

from __future__ import annotations

from collections.abc import Mapping


def verify_twilio_signature(
    url: str,
    post_data: Mapping[str, str],
    signature: str,
    auth_token: str,
) -> bool:
    """Return True iff `signature` matches Twilio's HMAC over (url, post_data).

    `url` is the public URL Twilio POSTed to (scheme + host + path + query).
    `post_data` is the decoded form-body params (dict-like).
    `signature` is the value of the `X-Twilio-Signature` header.
    `auth_token` is the account's Twilio auth token.

    Returns False (never raises) when any input is empty/missing — callers
    treat False uniformly as "reject with 403".
    """
    if not signature or not auth_token:
        return False
    # Lazy import keeps the Twilio SDK off the import path until the
    # first webhook fires. Modules that never see a webhook stay cheap.
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(auth_token)
    # `validate` expects a plain dict — coerce the Mapping defensively.
    return bool(validator.validate(url, dict(post_data), signature))
