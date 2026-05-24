// customerFetch — the customer-facing twin of `adminFetch`. Injects
// `X-PD-Store-Slug: <slug>` so the backend `CurrentStoreMiddleware`
// (task #158) resolves the URL store rather than falling back to the
// cookie or the alphabetically-first store.
//
// Why a separate helper from `adminFetch`?
//   - `adminFetch` reads its slug from a React StoreContext that the
//     admin layout mounts. Customer pages never mount that provider —
//     they get their slug directly from the URL `params.slug` instead.
//   - Coupling customer calls to the admin context would mean an admin
//     who's switched to "PlayDesk North" and then opens the public
//     `/s/playdesk-flagship/book` URL in the same tab would have their
//     bookings cross-leak to North. The URL store must always win on a
//     `/s/[slug]/book` route.
//
// Throws `ApiError` from `api.ts` to keep error handling symmetric with
// the existing typed admin calls.

import { ApiError } from "./api";

/**
 * Fetch wrapper for the customer-facing `/s/[slug]/book` flow.
 *
 * @param slug - The store slug from the URL. Forwarded as the
 *   `X-PD-Store-Slug` header so the middleware resolves this store
 *   regardless of cookies / fallback rules.
 * @param input - Same as `fetch`'s first arg.
 * @param init - Same as `fetch`'s second arg. `Content-Type` defaults
 *   to `application/json` (overridable); `credentials` defaults to
 *   `"include"`.
 */
export async function customerFetch<T = unknown>(
  slug: string,
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  // Always set the URL slug, even if the caller pre-set one — the URL
  // route is the authoritative source on a `/s/[slug]/book` page.
  headers.set("X-PD-Store-Slug", slug);

  const response = await fetch(input, {
    ...init,
    credentials: init?.credentials ?? "include",
    headers,
  });

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Non-JSON error body — leave as null.
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
