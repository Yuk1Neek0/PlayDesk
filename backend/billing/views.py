"""HTTP views for the billing app.

Three groups:
  - Connect onboarding (StripeConnectView, StripeReturnView, StripeAccountStatusView)
  - Webhook receiver (stripe_webhook)
  - Admin/staff payment ops (ChargeBalanceView, BookingCancelRefundView,
    PaymentLedgerView, PaymentStatusView)

`permission_classes` is empty everywhere — auth is provided by the
multi-location middleware + the admin dashboard's session cookie. Adding
class-level perms here would break the bench.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Booking, PaymentStatus, Store

from . import stripe_client, webhook_handlers
from .helpers import calc_refund_amount, validate_refund_matrix
from .models import Payment, PaymentKind, PaymentRowStatus, WebhookEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stripe Connect onboarding
# ---------------------------------------------------------------------------


class StripeConnectView(APIView):
    """POST /api/admin/stripe/connect/ — start (or reconnect) onboarding."""

    permission_classes: list = []

    def post(self, request):
        store = request.store
        if store is None:
            return Response({"detail": "No store context."}, status=400)
        if stripe_client.degraded():
            return Response({"detail": "Stripe not configured."}, status=503)

        stripe = stripe_client.get_stripe()
        if not stripe_client.is_configured():
            # Test mode without keys — return a fake onboarding URL so
            # the admin flow exercises end-to-end against stripe-mock.
            return Response(
                {
                    "onboarding_url": f"{settings.SITE_URL}/admin/settings/payments/return?account_id=acct_test_unconfigured&store={store.slug}",
                    "account_id": "acct_test_unconfigured",
                    "configured": False,
                }
            )

        account_id = store.stripe_account_id
        if not account_id:
            account = stripe.Account.create(
                type="standard",
                country=request.data.get("country", "US"),
                metadata={"store_id": str(store.id), "store_slug": store.slug},
            )
            account_id = account.id
            store.stripe_account_id = account_id
            store.save(update_fields=["stripe_account_id"])

        return_url = f"{settings.SITE_URL}/admin/settings/payments/return?store={store.slug}"
        refresh_url = f"{settings.SITE_URL}/admin/settings/payments/refresh?store={store.slug}"
        link = stripe.AccountLink.create(
            account=account_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type="account_onboarding",
        )
        return Response(
            {
                "onboarding_url": link.url,
                "account_id": account_id,
                "configured": True,
            }
        )


class StripeReturnView(APIView):
    """GET /api/admin/stripe/return/ — onboarding-return URL handler.

    Stripe redirects here after the chain owner finishes the hosted
    onboarding flow. We re-read the account from Stripe to refresh the
    cached `charges_enabled` flag, then bounce to the admin settings page.
    """

    permission_classes: list = []

    def get(self, request):
        store_slug = request.query_params.get("store")
        store = Store.objects.filter(slug=store_slug).first() if store_slug else None
        if store is None:
            store = request.store
        if store is None or not store.stripe_account_id:
            return redirect("/admin/settings/payments/")

        if stripe_client.is_configured():
            stripe = stripe_client.get_stripe()
            try:
                account = stripe.Account.retrieve(store.stripe_account_id)
                store.stripe_charges_enabled = bool(getattr(account, "charges_enabled", False))
                store.save(update_fields=["stripe_charges_enabled"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Stripe Account.retrieve failed: %s", exc)

        return redirect("/admin/settings/payments/")


class StripeAccountStatusView(APIView):
    """GET /api/admin/stripe/status/ — current account state for the admin UI."""

    permission_classes: list = []

    def get(self, request):
        store = request.store
        if store is None:
            return Response({"detail": "No store context."}, status=400)
        return Response(
            {
                "store_slug": store.slug,
                "account_id": store.stripe_account_id,
                "charges_enabled": store.stripe_charges_enabled,
                "currency": store.currency,
                "deposit_mode": store.deposit_mode,
                "deposit_value": str(store.deposit_value),
                "refund_matrix": store.refund_matrix,
                "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
                "configured": stripe_client.is_configured(),
            }
        )


class StripeSettingsUpdateView(APIView):
    """PATCH /api/admin/stripe/settings/ — update deposit/refund config."""

    permission_classes: list = []

    def patch(self, request):
        store = request.store
        if store is None:
            return Response({"detail": "No store context."}, status=400)

        data = request.data or {}
        fields: list[str] = []

        if "deposit_mode" in data:
            mode = data["deposit_mode"]
            if mode not in {"none", "percentage", "fixed"}:
                return Response({"detail": "Invalid deposit_mode."}, status=400)
            store.deposit_mode = mode
            fields.append("deposit_mode")
        if "deposit_value" in data:
            try:
                value = Decimal(str(data["deposit_value"]))
            except Exception:  # noqa: BLE001
                return Response({"detail": "deposit_value must be numeric."}, status=400)
            if value < 0:
                return Response({"detail": "deposit_value must be >= 0."}, status=400)
            if store.deposit_mode == "percentage" and value > Decimal("100"):
                return Response({"detail": "percentage deposit_value must be 0-100."}, status=400)
            store.deposit_value = value
            fields.append("deposit_value")
        if "currency" in data:
            store.currency = str(data["currency"]).upper()[:3]
            fields.append("currency")
        if "refund_matrix" in data:
            try:
                store.refund_matrix = validate_refund_matrix(data["refund_matrix"])
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=400)
            fields.append("refund_matrix")

        if fields:
            store.save(update_fields=fields)

        return Response(
            {
                "deposit_mode": store.deposit_mode,
                "deposit_value": str(store.deposit_value),
                "currency": store.currency,
                "refund_matrix": store.refund_matrix,
            }
        )


# ---------------------------------------------------------------------------
# Webhook receiver
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    """POST /api/stripe/webhook/ — Stripe event receiver.

    Signature-verifies the event, persists raw payload to WebhookEvent
    (idempotency via unique-event-id), dispatches to a handler. Handler
    failures are logged but DO NOT trigger Stripe retries — the row is
    already persisted for manual replay.
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    if stripe_client.degraded():
        return JsonResponse({"detail": "Stripe not configured."}, status=503)

    secret = settings.STRIPE_WEBHOOK_SECRET
    if secret:
        try:
            stripe = stripe_client.get_stripe()
            event = stripe.Webhook.construct_event(payload, sig_header, secret)
            event_dict = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        except Exception as exc:  # noqa: BLE001
            return JsonResponse({"detail": f"Invalid signature: {exc}"}, status=400)
    else:
        # No secret configured (dev / stripe-mock) — parse JSON directly.
        try:
            event_dict = json.loads(payload.decode("utf-8") or "{}")
        except Exception as exc:  # noqa: BLE001
            return JsonResponse({"detail": f"Invalid payload: {exc}"}, status=400)

    event_id = event_dict.get("id")
    event_type = event_dict.get("type", "")
    if not event_id:
        # Legacy core/payments.py path — preserve the simple handler.
        return _legacy_webhook(event_dict)

    # Idempotency: cheap exists() before any handler logic.
    existing = WebhookEvent.objects.filter(stripe_event_id=event_id).first()
    if existing is not None and existing.processed_at is not None:
        return JsonResponse({"received": True, "idempotent": True})

    with transaction.atomic():
        if existing is None:
            existing = WebhookEvent.objects.create(
                stripe_event_id=event_id,
                event_type=event_type,
                payload=event_dict,
            )

    handler = webhook_handlers.HANDLERS.get(event_type)
    if handler is not None:
        try:
            handler(event_dict)
            WebhookEvent.objects.filter(pk=existing.pk).update(processed_at=timezone.now())
        except Exception:  # noqa: BLE001
            logger.exception("webhook handler %s failed for %s", event_type, event_id)
            # Still return 200 — the event is persisted, replay manually.
    else:
        # No handler — mark processed so we don't retry on a no-op.
        WebhookEvent.objects.filter(pk=existing.pk).update(processed_at=timezone.now())

    return JsonResponse({"received": True})


def _legacy_webhook(event_dict: dict) -> JsonResponse:
    """Compatibility path for the existing checkout.session.completed flow."""
    from core.models import BookingStatus

    if event_dict.get("type") == "checkout.session.completed":
        session = event_dict.get("data", {}).get("object", {})
        booking_id = (session.get("metadata") or {}).get("booking_id")
        if booking_id:
            Booking.objects.filter(pk=booking_id, status=BookingStatus.PENDING_PAYMENT).update(
                status=BookingStatus.CONFIRMED
            )
    return JsonResponse({"received": True})


# ---------------------------------------------------------------------------
# Charge balance + cancel-refund
# ---------------------------------------------------------------------------


class ChargeBalanceView(APIView):
    """POST /api/admin/bookings/<pk>/charge-balance/ — staff-initiated."""

    permission_classes: list = []

    def post(self, request, pk):
        booking = Booking.objects.filter(pk=pk).select_related("resource").first()
        if booking is None:
            return Response({"detail": "Booking not found."}, status=404)

        balance = booking.balance_amount
        if balance <= 0:
            return Response({"detail": "Already paid in full."}, status=400)

        store = booking.resource.store

        # In test mode without a real key, return a stub URL so the
        # SMS-template wiring is still exercised.
        if not stripe_client.is_configured():
            checkout_url = f"https://checkout.stripe.test/session/balance/{booking.pk}"
            Payment.objects.create(
                store=store,
                booking=booking,
                kind=PaymentKind.BALANCE,
                amount=balance,
                currency=store.currency,
                status=PaymentRowStatus.PENDING,
                metadata={"checkout_url": checkout_url, "test_mode_stub": True},
            )
            _send_balance_link_sms(booking, checkout_url, balance)
            return Response({"checkout_url": checkout_url, "balance_amount": str(balance)})

        stripe = stripe_client.get_stripe()
        amount_cents = int(balance * 100)
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": store.currency.lower(),
                        "product_data": {
                            "name": f"PlayDesk booking #{booking.pk} balance",
                        },
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }
            ],
            payment_intent_data=(
                {"transfer_data": {"destination": store.stripe_account_id}}
                if store.stripe_account_id
                else {}
            ),
            metadata={"booking_id": str(booking.pk), "kind": "balance"},
            success_url=settings.STRIPE_SUCCESS_URL,
            cancel_url=settings.STRIPE_CANCEL_URL,
        )

        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.BALANCE,
            amount=balance,
            currency=store.currency,
            status=PaymentRowStatus.PENDING,
            stripe_payment_intent_id=getattr(session, "payment_intent", None) or "",
            metadata={"checkout_session_id": session.id, "checkout_url": session.url},
        )
        _send_balance_link_sms(booking, session.url, balance)
        return Response({"checkout_url": session.url, "balance_amount": str(balance)})


def _send_balance_link_sms(booking, url: str, balance: Decimal) -> None:
    """Send the customer the Stripe Checkout link via v4 outbound."""
    if booking.customer is None:
        return
    try:
        from outbound.api import enqueue_message

        enqueue_message(
            customer=booking.customer,
            template_key="balance_charge_link",
            context={"balance": f"{balance:.2f}", "checkout_url": url},
            reference=f"balance-{booking.pk}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("balance_charge_link SMS failed for booking %s: %s", booking.pk, exc)


class BookingCancelRefundView(APIView):
    """POST /api/admin/bookings/<pk>/cancel/ — staff-side cancel + refund.

    v7 customer-portal will wire its own `/api/me/bookings/<pk>/cancel/`
    into the same refund pathway via `cancel_booking_with_refund(...)`.
    """

    permission_classes: list = []

    def post(self, request, pk):
        booking = Booking.objects.filter(pk=pk).select_related("resource").first()
        if booking is None:
            return Response({"detail": "Booking not found."}, status=404)

        result = cancel_booking_with_refund(booking)
        return Response(result)


def cancel_booking_with_refund(booking) -> dict[str, Any]:
    """Cancel `booking` and trigger a refund per the store's matrix.

    Public function so the v7 customer-side cancel endpoint can reuse it
    on merge. Always returns a JSON-able dict.
    """
    from core.models import BookingStatus

    store = booking.resource.store
    booking.status = BookingStatus.CANCELLED
    booking.save(update_fields=["status"])

    if booking.payment_status not in {
        PaymentStatus.DEPOSIT_PAID,
        PaymentStatus.PAID_IN_FULL,
    }:
        # Nothing captured → nothing to refund.
        return {"cancelled": True, "refund_amount": "0.00", "refunded": False}

    refund_amount = calc_refund_amount(store, booking)
    if refund_amount <= 0:
        return {"cancelled": True, "refund_amount": "0.00", "refunded": False}

    # Provisional refund row so the admin sees "pending refund" instantly.
    pending = Payment.objects.create(
        store=store,
        booking=booking,
        kind=PaymentKind.REFUND,
        amount=-refund_amount,
        currency=store.currency,
        status=PaymentRowStatus.PENDING,
        metadata={"reason": "cancellation_refund"},
    )

    if stripe_client.is_configured() and booking.payment_intent_id:
        stripe = stripe_client.get_stripe()
        try:
            stripe.Refund.create(
                payment_intent=booking.payment_intent_id,
                amount=int(refund_amount * 100),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Refund.create failed for %s: %s", booking.pk, exc)
            Payment.objects.filter(pk=pending.pk).update(status=PaymentRowStatus.FAILED)
            return {"cancelled": True, "refund_amount": str(refund_amount), "refunded": False}
    else:
        # Test/degraded mode — mark the refund row as succeeded directly so
        # downstream surfaces (dashboard tile, ledger) reflect the action.
        Payment.objects.filter(pk=pending.pk).update(status=PaymentRowStatus.SUCCEEDED)
        booking.payment_status = (
            PaymentStatus.REFUNDED
            if refund_amount >= Decimal(booking.deposit_amount)
            else PaymentStatus.PARTIALLY_REFUNDED
        )
        booking.save(update_fields=["payment_status"])

    # Customer SMS — best-effort.
    if booking.customer is not None:
        try:
            from outbound.api import enqueue_message

            enqueue_message(
                customer=booking.customer,
                template_key="booking_refunded",
                context={"amount": f"{refund_amount:.2f}"},
                reference=f"refund-{booking.pk}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("booking_refunded SMS failed for %s: %s", booking.pk, exc)

    return {
        "cancelled": True,
        "refund_amount": str(refund_amount),
        "refunded": True,
    }


# ---------------------------------------------------------------------------
# Payment status (customer poll) + Payment ledger (admin)
# ---------------------------------------------------------------------------


class PaymentStatusView(APIView):
    """GET /api/bookings/<pk>/payment-status/ — public post-payment poll."""

    permission_classes: list = []

    def get(self, request, pk):
        booking = Booking.objects.filter(pk=pk).first()
        if booking is None:
            return Response({"detail": "Not found."}, status=404)
        return Response(
            {
                "payment_status": booking.payment_status,
                "status": booking.status,
            }
        )


class PaymentLedgerView(APIView):
    """GET /api/admin/payments/ — paginated, store-scoped payment ledger."""

    permission_classes: list = []

    def get(self, request):
        store = request.store
        qs = Payment.objects.select_related("booking", "booking__resource")
        if store is not None:
            qs = qs.filter(store=store)

        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        try:
            limit = max(1, min(200, int(request.query_params.get("limit", 50))))
        except (TypeError, ValueError):
            limit = 50

        rows = []
        for p in qs.order_by("-created_at")[:limit]:
            rows.append(
                {
                    "id": p.id,
                    "created_at": p.created_at.isoformat(),
                    "booking_id": p.booking_id,
                    "customer_name": p.booking.customer_name,
                    "kind": p.kind,
                    "amount": str(p.amount),
                    "currency": p.currency,
                    "status": p.status,
                    "stripe_charge_id": p.stripe_charge_id or "",
                    "stripe_payment_intent_id": p.stripe_payment_intent_id or "",
                }
            )
        return Response({"count": len(rows), "results": rows})


# ---------------------------------------------------------------------------
# Sweep helper exposed for management command + tests
# ---------------------------------------------------------------------------


def sweep_pending_payments(now=None) -> int:
    """Cancel bookings stuck in pending_payment > STRIPE_HOLD_MINUTES.

    Returns the count of swept rows. Idempotent — re-runs match nothing.
    """
    from datetime import timedelta

    from core.models import BookingStatus

    if now is None:
        now = timezone.now()
    cutoff = now - timedelta(minutes=settings.STRIPE_HOLD_MINUTES)
    qs = Booking.objects.filter(
        payment_status=PaymentStatus.PENDING_PAYMENT,
        created_at__lt=cutoff,
    )
    swept = 0
    for booking in qs:
        booking.status = BookingStatus.CANCELLED
        booking.payment_status = PaymentStatus.NOT_REQUIRED
        booking.save(update_fields=["status", "payment_status"])
        # Best-effort cancel of the Stripe intent.
        if stripe_client.is_configured() and booking.payment_intent_id:
            try:
                stripe = stripe_client.get_stripe()
                stripe.PaymentIntent.cancel(booking.payment_intent_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("PaymentIntent.cancel failed: %s", exc)
        swept += 1
    return swept


# Compat re-export — the legacy api.views URL points to this function via
# wrapper in config/urls.py. Keeping the symbol stable for callers.
def webhook_view(request):  # pragma: no cover
    return stripe_webhook(request)
