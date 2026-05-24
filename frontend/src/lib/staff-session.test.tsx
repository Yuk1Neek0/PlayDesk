import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

import { StaffSessionProvider, useStaffSession } from "./staff-session";

// next/navigation is not mounted under vitest/jsdom — mock it. The test
// captures replace/push calls via the mock so we can assert on them.
const routerMock = {
  replace: vi.fn(),
  push: vi.fn(),
  prefetch: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
};

let _pathname = "/admin/customers";

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
  usePathname: () => _pathname,
  useSearchParams: () => new URLSearchParams(),
}));

function json(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status });
}

function Probe() {
  const { user, ready, logout } = useStaffSession();
  return (
    <div>
      <span data-testid="ready">{String(ready)}</span>
      <span data-testid="user">{user?.username ?? "anon"}</span>
      <button data-testid="logout" onClick={() => void logout()}>
        logout
      </button>
    </div>
  );
}

describe("StaffSessionProvider", () => {
  beforeEach(() => {
    routerMock.replace.mockClear();
    routerMock.push.mockClear();
    _pathname = "/admin/customers";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("on /me 200, exposes the user and never redirects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({ id: 9, username: "alice", is_staff: true, is_superuser: false }),
      ),
    );
    render(
      <StaffSessionProvider>
        <Probe />
      </StaffSessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    expect(screen.getByTestId("user").textContent).toBe("alice");
    expect(routerMock.replace).not.toHaveBeenCalled();
  });

  it("on /me 401 with pathname /admin/customers, redirects with ?next=", async () => {
    _pathname = "/admin/customers";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Not authenticated." }, 401)),
    );
    render(
      <StaffSessionProvider>
        <Probe />
      </StaffSessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    expect(screen.getByTestId("user").textContent).toBe("anon");
    expect(routerMock.replace).toHaveBeenCalledWith(
      "/staff/login?next=%2Fadmin%2Fcustomers",
    );
  });

  it("on /me 401 with pathname /staff/login, does NOT redirect (no loop)", async () => {
    _pathname = "/staff/login";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Not authenticated." }, 401)),
    );
    render(
      <StaffSessionProvider>
        <Probe />
      </StaffSessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    expect(routerMock.replace).not.toHaveBeenCalled();
  });

  it("on /me 401 with non-admin pathname, does NOT redirect", async () => {
    _pathname = "/s/playdesk-flagship/book";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Not authenticated." }, 401)),
    );
    render(
      <StaffSessionProvider>
        <Probe />
      </StaffSessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    expect(routerMock.replace).not.toHaveBeenCalled();
  });

  it("logout() posts to /api/staff/logout/, clears state, navigates to /staff/login", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/staff/me/"))
        return json({ id: 1, username: "u", is_staff: true, is_superuser: false });
      if (url.endsWith("/api/staff/logout/")) return json({ ok: true });
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <StaffSessionProvider>
        <Probe />
      </StaffSessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("user").textContent).toBe("u"));

    await act(async () => {
      screen.getByTestId("logout").click();
    });

    await waitFor(() => expect(screen.getByTestId("user").textContent).toBe("anon"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/staff/logout/",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    expect(routerMock.push).toHaveBeenCalledWith("/staff/login");
  });
});
