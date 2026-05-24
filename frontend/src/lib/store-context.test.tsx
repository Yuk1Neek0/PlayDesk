import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";

import {
  COOKIE_NAME,
  STORAGE_KEY,
  StoreProvider,
  useCurrentStore,
  type Store,
} from "./store-context";

const STORES: Store[] = [
  { id: 1, slug: "playdesk-flagship", name: "PlayDesk Flagship" },
  { id: 2, slug: "playdesk-north", name: "PlayDesk North" },
];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status });
}

function Probe() {
  const { current, stores, ready } = useCurrentStore();
  return (
    <div>
      <span data-testid="ready">{String(ready)}</span>
      <span data-testid="count">{stores.length}</span>
      <span data-testid="current">{current?.slug ?? "none"}</span>
      <span data-testid="name">{current?.name ?? ""}</span>
    </div>
  );
}

function PickerProbe() {
  const { current, setCurrent } = useCurrentStore();
  return (
    <div>
      <span data-testid="current">{current?.slug ?? "none"}</span>
      <button data-testid="pick-north" onClick={() => setCurrent("playdesk-north")}>
        pick north
      </button>
    </div>
  );
}

function clearCookies() {
  if (typeof document === "undefined") return;
  for (const c of document.cookie.split(";")) {
    const [name] = c.trim().split("=");
    if (name) document.cookie = `${name}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
  }
}

beforeEach(() => {
  window.localStorage.clear();
  clearCookies();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoreProvider (seeded)", () => {
  it("picks the first store when localStorage is empty", async () => {
    render(
      <StoreProvider initialStores={STORES}>
        <Probe />
      </StoreProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("playdesk-flagship");
    });
    expect(screen.getByTestId("name").textContent).toBe("PlayDesk Flagship");
    expect(screen.getByTestId("count").textContent).toBe("2");
    expect(screen.getByTestId("ready").textContent).toBe("true");
  });

  it("initialises from localStorage when a slug is persisted", async () => {
    window.localStorage.setItem(STORAGE_KEY, "playdesk-north");
    render(
      <StoreProvider initialStores={STORES}>
        <Probe />
      </StoreProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("playdesk-north");
    });
  });

  it("falls back to the first store when persisted slug is unknown", async () => {
    window.localStorage.setItem(STORAGE_KEY, "ghost-store");
    render(
      <StoreProvider initialStores={STORES}>
        <Probe />
      </StoreProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("playdesk-flagship");
    });
  });

  it("setCurrent writes BOTH localStorage AND the pd_store_slug cookie", async () => {
    render(
      <StoreProvider initialStores={STORES}>
        <PickerProbe />
      </StoreProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("current").textContent).toBe("playdesk-flagship"),
    );

    await act(async () => {
      screen.getByTestId("pick-north").click();
    });

    expect(screen.getByTestId("current").textContent).toBe("playdesk-north");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("playdesk-north");
    expect(document.cookie).toContain(`${COOKIE_NAME}=playdesk-north`);
  });
});

describe("StoreProvider (network fetch)", () => {
  it("fetches /api/admin/stores/ on mount and uses the first as default", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValue(jsonResponse(STORES));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <StoreProvider>
        <Probe />
      </StoreProvider>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId("current").textContent).toBe("playdesk-flagship"),
    );
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/admin/stores/");
  });

  it("survives a failed /api/admin/stores/ fetch (empty list, no current)", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValue(new Response("nope", { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <StoreProvider>
        <Probe />
      </StoreProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    expect(screen.getByTestId("current").textContent).toBe("none");
    expect(screen.getByTestId("count").textContent).toBe("0");
  });

  it("accepts a DRF-paginated {results: []} payload", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValue(jsonResponse({ results: STORES }));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <StoreProvider>
        <Probe />
      </StoreProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("2"));
  });
});

describe("useCurrentStore outside a provider", () => {
  it("returns null current + empty stores without throwing", () => {
    render(<Probe />);
    expect(screen.getByTestId("current").textContent).toBe("none");
    expect(screen.getByTestId("count").textContent).toBe("0");
  });
});
