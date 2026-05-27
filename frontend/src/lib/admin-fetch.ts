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

// v10a staff-auth — 401 handler hook. `<StaffSessionProvider>` registers a
// callback on mount that triggers its logout-and-redirect flow whenever
// any admin API call returns 401 (typically: the session expired mid-use).
// Kept as a module-level callback so adminFetch (a plain function) stays
// React-free. The provider clears the registration on unmount.
type On401Handler = () => void;
let _on401: On401Handler | null = null;

export function setAdminFetchOn401(handler: On401Handler | null): void {
  _on401 = handler;
}

/**
 * Lower-level `fetch` shape used by the admin app.
 *
 * - Injects `X-PD-Store-Slug` from the active StoreContext (if any).
 * - Sets `Content-Type: application/json` (overridable via `init.headers`).
 * - Sends cookies (`credentials: "include"`) like the rest of the app.
 * - Throws `ApiError` on non-2xx, returning JSON on success.
 */
// Read a cookie value by name from `document.cookie`. Returns null when
// not in a browser (SSR) or when the cookie isn't set.
function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const target = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(target)) return decodeURIComponent(trimmed.slice(target.length));
  }
  return null;
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

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
  // Django's CsrfViewMiddleware enforces a token on unsafe methods when the
  // request is session-authenticated (admin APIs). The staff login response
  // sets a non-HttpOnly `csrftoken` cookie; mirror it into `X-CSRFToken` so
  // admin POST/PATCH/DELETE calls aren't rejected with "CSRF Failed".
  const method = (init?.method ?? "GET").toUpperCase();
  if (UNSAFE_METHODS.has(method) && !headers.has("X-CSRFToken")) {
    const csrf = readCookie("csrftoken");
    if (csrf) headers.set("X-CSRFToken", csrf);
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
    // 401 mid-session = the cookie expired or was cleared. Trigger the
    // logout flow (registered by StaffSessionProvider) so the user lands
    // on /staff/login with `?next=` instead of seeing a cryptic error.
    // When a handler is registered we also hold the Promise unresolved so
    // the caller's `.catch` never runs — otherwise pages paint "Couldn't
    // reach the backend" over the in-flight redirect.
    if (response.status === 401 && _on401) {
      try {
        _on401();
      } catch {
        // Provider unmounted between registration and dispatch — fine.
      }
      return new Promise<T>(() => {});
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
