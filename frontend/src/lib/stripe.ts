// Stripe.js loader helpers.
//
// Two surfaces use Stripe in PlayDesk:
//   - Admin (settings → payments): fetches the publishable key from the
//     `/api/admin/stripe/status/` endpoint (allows key rotation without
//     rebuild).
//   - Customer booking page: receives the publishable key inline on the
//     booking-create response when a deposit is required. Calls
//     `loadStripeFromKey(publishableKey)` to mount `<Elements>`.
//
// `loadStripe` from @stripe/stripe-js is cached internally by Stripe — a
// `loadStripe(pk)` call with the same key is a no-op after the first one,
// so the customer page doesn't need its own caching layer.

import { loadStripe, type Stripe } from "@stripe/stripe-js";

import { adminFetch } from "./admin-fetch";

let _adminKeyPromise: Promise<string> | null = null;

export function getStripePublishableKey(): Promise<string> {
  if (_adminKeyPromise) return _adminKeyPromise;
  _adminKeyPromise = adminFetch<{ publishable_key: string }>(
    "/api/admin/stripe/status/",
  )
    .then((d) => d.publishable_key || "")
    .catch(() => "");
  return _adminKeyPromise;
}

/**
 * Load Stripe.js for the customer-facing booking page.
 * The publishable key comes from the booking-create response, so this
 * helper is just a thin wrapper around @stripe/stripe-js's loadStripe.
 * Returns null if the key is empty (Stripe not configured) so callers
 * can short-circuit the Elements mount.
 */
export function loadStripeFromKey(
  publishableKey: string,
): Promise<Stripe | null> | null {
  if (!publishableKey) return null;
  return loadStripe(publishableKey);
}

// Reset for tests / store-switch.
export function _resetStripeKeyCache(): void {
  _adminKeyPromise = null;
}
