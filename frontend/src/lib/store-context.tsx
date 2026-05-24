"use client";

// StoreContext — the "which store is the admin currently looking at?"
// source of truth for the v6 multi-location frontend (epic #157).
//
// Surfaces:
//   - `<StoreProvider>` fetches /api/admin/stores/ on mount, picks the
//     initial store from localStorage (or the first store as fallback),
//     and renders its children.
//   - `useCurrentStore()` returns the active store and the list of stores.
//   - `setCurrent(slug)` writes to BOTH localStorage AND the
//     `pd_store_slug` cookie. The cookie is what the Django middleware
//     reads on the next request; localStorage is what survives a tab
//     reload before any request fires.
//
// `adminFetch` (see admin-fetch.ts) reads the active slug via a small
// callback the provider registers on mount. That keeps the wrapper a
// plain module-level function while still being store-aware.

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { adminFetch, setStoreSlugProvider } from "./admin-fetch";

export interface Store {
  id: number;
  slug: string;
  name: string;
}

export const STORAGE_KEY = "pd_store_slug";
export const COOKIE_NAME = "pd_store_slug";

interface StoreContextValue {
  /** All stores the signed-in admin has access to. */
  stores: Store[];
  /** The currently-selected store, or `null` while loading / unset. */
  current: Store | null;
  /** Whether the store list has finished its initial fetch. */
  ready: boolean;
  /** Pick a different store. Updates localStorage + cookie. */
  setCurrent: (slug: string) => void;
}

const StoreContext = createContext<StoreContextValue>({
  stores: [],
  current: null,
  ready: false,
  setCurrent: () => {},
});

/**
 * Read the persisted slug from localStorage. Wrapped in try/catch because
 * localStorage can throw on SSR, in private windows, and under strict
 * cookie-blocking policies.
 */
function readPersistedSlug(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Write `pd_store_slug` to localStorage + cookie. SameSite=Lax, no Secure in dev. */
function persistSlug(slug: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, slug);
  } catch {
    // ignore unavailable storage
  }
  try {
    // path=/ so every admin page sees it; SameSite=Lax for top-level GETs.
    document.cookie = `${COOKIE_NAME}=${encodeURIComponent(slug)}; path=/; SameSite=Lax`;
  } catch {
    // document may not exist in some test envs
  }
}

interface ProviderProps {
  children: React.ReactNode;
  /** Test seam: short-circuit the network fetch with a known store list. */
  initialStores?: Store[];
}

export function StoreProvider({ children, initialStores }: ProviderProps) {
  const [stores, setStores] = useState<Store[]>(initialStores ?? []);
  const [currentSlug, setCurrentSlug] = useState<string | null>(() =>
    readPersistedSlug(),
  );
  const [ready, setReady] = useState<boolean>(initialStores !== undefined);

  // Register the slug provider so `adminFetch` (a plain function) can read
  // the current store without subscribing to React context. Cleaned up on
  // unmount so tests / customer pages don't get stale state.
  useEffect(() => {
    setStoreSlugProvider(() => currentSlug);
    return () => setStoreSlugProvider(null);
  }, [currentSlug]);

  // Fetch the store list once on mount (unless seeded by `initialStores`
  // for tests). Falls back to leaving `stores` empty on failure — the
  // switcher hides itself when there's nothing to switch to.
  useEffect(() => {
    if (initialStores !== undefined) return;
    let cancelled = false;
    adminFetch<Store[] | { results: Store[] }>("/api/admin/stores/")
      .then((payload) => {
        if (cancelled) return;
        // Accept both `Store[]` and a DRF-paginated `{results: []}` shape.
        const list = Array.isArray(payload)
          ? payload
          : Array.isArray(payload?.results)
            ? payload.results
            : [];
        setStores(list);
      })
      .catch(() => {
        // Endpoint may 401 (not signed in as staff) or 404 (deployment
        // pre-v6). Either way: leave stores empty, switcher stays hidden.
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [initialStores]);

  // Once we know the store list, lock the current slug to one that
  // actually exists. If the persisted slug is gone (store deleted, or
  // first load on a fresh device), pick the first store.
  useEffect(() => {
    if (stores.length === 0) return;
    const persisted = currentSlug;
    const exists = persisted !== null && stores.some((s) => s.slug === persisted);
    if (!exists) {
      const fallback = stores[0].slug;
      setCurrentSlug(fallback);
      persistSlug(fallback);
    }
  }, [stores, currentSlug]);

  const setCurrent = useCallback((slug: string) => {
    setCurrentSlug(slug);
    persistSlug(slug);
  }, []);

  const current = useMemo<Store | null>(
    () => stores.find((s) => s.slug === currentSlug) ?? null,
    [stores, currentSlug],
  );

  const value = useMemo<StoreContextValue>(
    () => ({ stores, current, ready, setCurrent }),
    [stores, current, ready, setCurrent],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

/**
 * Subscribe to the current store. Safe to call from any component;
 * returns `{ current: null, stores: [] }` outside a `<StoreProvider>`
 * so customer-page components (which never mount the provider) don't
 * blow up.
 */
export function useCurrentStore(): StoreContextValue {
  return useContext(StoreContext);
}
