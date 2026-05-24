"use client";

// staff-session — the frontend's entire staff-auth surface (v10a).
//
// Mounted at the admin layout root so every /admin/* page is gated. On
// mount the provider calls GET /api/staff/me/; the response is the
// sole source of truth:
//
//   200 → setUser(payload); the rest of the admin app renders.
//   401 → setUser(null); if we're on an /admin/* URL, redirect to the
//         login page with `?next=` so a successful sign-in returns to
//         the originally requested page.
//
// The previous localStorage-based "auth" was trivially spoofable from
// the devtools console. This module deliberately keeps no state in
// localStorage — `request.user` on the backend is the only thing that
// gates admin endpoints, and the StaffOnlyMiddleware enforces it.
//
// Customer auth (v7 phone+OTP) is parallel and untouched — it uses
// its own `pd_customer_session` cookie + `useCustomerSession` hook
// over in /s/[slug]/account.

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";

import { setAdminFetchOn401 } from "./admin-fetch";

export interface StaffUser {
  id: number;
  username: string;
  is_staff: boolean;
  is_superuser: boolean;
}

interface StaffSessionContextValue {
  /** Authenticated staff user or `null` (anonymous / not yet loaded). */
  user: StaffUser | null;
  /** `false` until the initial `/api/staff/me/` call resolves. */
  ready: boolean;
  /** Last error message from the auth flow, if any. */
  error: string | null;
  /** POST /api/staff/logout/ then redirect to the login page. */
  logout: () => Promise<void>;
}

const StaffSessionContext = createContext<StaffSessionContextValue>({
  user: null,
  ready: false,
  error: null,
  logout: async () => {},
});

const LOGIN_PATH = "/staff/login";

interface ProviderProps {
  children: React.ReactNode;
  /**
   * Test seam — when provided, the provider skips the network /me/ call
   * and reports the supplied initial state directly.
   */
  initialUser?: StaffUser | null;
}

export function StaffSessionProvider({ children, initialUser }: ProviderProps) {
  const [user, setUser] = useState<StaffUser | null>(initialUser ?? null);
  const [ready, setReady] = useState<boolean>(initialUser !== undefined);
  const [error, setError] = useState<string | null>(null);

  const router = useRouter();
  const pathname = usePathname();

  // Stable redirect-on-401 helper. We only redirect when the current
  // page is an /admin/* route; the login page itself must NOT redirect
  // (that would infinite-loop), and customer pages aren't our problem.
  const redirectToLogin = useCallback(
    (currentPath: string | null) => {
      if (!currentPath) return;
      if (!currentPath.startsWith("/admin")) return;
      if (currentPath.startsWith(LOGIN_PATH)) return;
      const next = encodeURIComponent(currentPath);
      router.replace(`${LOGIN_PATH}?next=${next}`);
    },
    [router],
  );

  // Initial session check — runs once on mount, never on route changes.
  // The provider lives at the admin layout root and stays mounted across
  // admin navigation, so a re-fetch on every route would needlessly hit
  // the backend.
  useEffect(() => {
    if (initialUser !== undefined) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/staff/me/", {
          credentials: "include",
        });
        if (cancelled) return;
        if (resp.status === 200) {
          const body = (await resp.json()) as StaffUser;
          setUser(body);
          setError(null);
        } else {
          setUser(null);
          redirectToLogin(pathname);
        }
      } catch {
        if (cancelled) return;
        setUser(null);
        setError("Session check failed");
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // pathname is intentionally captured by-value at mount time via
    // redirectToLogin's closure; we don't want this effect to refire
    // every time the user navigates within /admin/*.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/staff/logout/", {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // Logging out a stale session can fail at the network layer; the
      // local state reset below is still correct.
    }
    setUser(null);
    router.push(LOGIN_PATH);
  }, [router]);

  // Wire the adminFetch 401 hook so any admin API call mid-session that
  // discovers an expired cookie triggers the same logout-and-redirect
  // flow without needing the calling component to know about it.
  useEffect(() => {
    setAdminFetchOn401(() => {
      setUser(null);
      redirectToLogin(window.location.pathname);
    });
    return () => setAdminFetchOn401(null);
  }, [redirectToLogin]);

  const value = useMemo<StaffSessionContextValue>(
    () => ({ user, ready, error, logout }),
    [user, ready, error, logout],
  );

  return (
    <StaffSessionContext.Provider value={value}>
      {children}
    </StaffSessionContext.Provider>
  );
}

/**
 * Subscribe to the staff session. Returns the default (anonymous, ready=false)
 * value outside a `<StaffSessionProvider>` so components that happen to mount
 * outside the admin tree (test renderers, customer pages) don't crash.
 */
export function useStaffSession(): StaffSessionContextValue {
  return useContext(StaffSessionContext);
}
