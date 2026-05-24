// adminFetch — thin wrapper around `fetch` that auto-injects the
// `X-PD-Store-Slug` header so the backend `CurrentStoreMiddleware`
// (task #158) resolves the right store for every admin request.
//
// Architecture note: the existing typed REST client in `api.ts` uses an
// internal `request()` helper. To keep the surface area of this task
// small, `request()` now delegates to `adminFetch` — so every existing
// admin call (adminListBookings, adminGetMembership, …) automatically
// picks up the store header without each callsite needing to change.
//
// The store slug is read from a tiny "current store" provider that the
// `<StoreProvider>` registers on mount (see `store-context.tsx`). Plain
// modules can't subscribe to React context, so the provider pushes the
// active slug into this module via `setStoreSlugProvider`. When no
// provider is mounted (e.g. SSR, customer pages, tests), the header is
// simply omitted and the backend resolver falls back to the default
// store — matching the v6 backward-compat decision in the epic.
//
// `ApiError` mirrors the shape thrown by `api.ts::request` so callers
// can `catch (e) { if (e instanceof ApiError) … }` consistently.

import { ApiError } from "./api";

type StoreSlugProvider = () => string | null;

let _provider: StoreSlugProvider | null = null;

/**
 * Register the source of truth for "what is the current admin store?".
 * `<StoreProvider>` calls this on mount and resets to null on unmount.
 * Exported for the provider — application code should not call this.
 */
export function setStoreSlugProvider(provider: StoreSlugProvider | null): void {
  _provider = provider;
}

/** Read the current store slug, if a provider is registered. */
export function getCurrentStoreSlug(): string | null {
  return _provider ? _provider() : null;
}

/**
 * Lower-level `fetch` shape used by the admin app.
 *
 * - Injects `X-PD-Store-Slug` from the active StoreContext (if any).
 * - Sets `Content-Type: application/json` (overridable via `init.headers`).
 * - Sends cookies (`credentials: "include"`) like the rest of the app.
 * - Throws `ApiError` on non-2xx, returning JSON on success.
 */
export async function adminFetch<T = unknown>(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
  const slug = getCurrentStoreSlug();
  const headers = new Headers(init?.headers);
  // Default JSON content-type, mirroring api.ts::request. Callers that
  // want a different content-type can override via init.headers.
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (slug && !headers.has("X-PD-Store-Slug")) {
    headers.set("X-PD-Store-Slug", slug);
  }

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
      // Non-JSON or empty error body — leave as null.
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
