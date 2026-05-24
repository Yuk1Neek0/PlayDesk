// Stripe.js loader helper. Fetches the publishable key from the v9
// `/api/admin/stripe/status/` endpoint instead of baking it into the
// build, so an operator can rotate keys without redeploying.
//
// In v9 the booking page itself doesn't yet mount `<Elements>` (that's a
// v9.1 follow-on once `@stripe/react-stripe-js` is added as a dep) — but
// when it does, this helper is the single seam.

import { adminFetch } from "./admin-fetch";

let _keyPromise: Promise<string> | null = null;

export function getStripePublishableKey(): Promise<string> {
  if (_keyPromise) return _keyPromise;
  _keyPromise = adminFetch<{ publishable_key: string }>(
    "/api/admin/stripe/status/",
  )
    .then((d) => d.publishable_key || "")
    .catch(() => "");
  return _keyPromise;
}

// Reset for tests / store-switch.
export function _resetStripeKeyCache(): void {
  _keyPromise = null;
}
