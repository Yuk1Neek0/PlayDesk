import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { adminFetch, setStoreSlugProvider } from "./admin-fetch";
import { ApiError } from "./api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  setStoreSlugProvider(null);
});

afterEach(() => {
  setStoreSlugProvider(null);
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status });
}

describe("adminFetch", () => {
  it("injects X-PD-Store-Slug from the registered provider", async () => {
    setStoreSlugProvider(() => "playdesk-north");
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await adminFetch("/api/admin/bookings/");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("X-PD-Store-Slug")).toBe("playdesk-north");
  });

  it("omits the header when no provider is registered (single-store deploys)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await adminFetch("/api/admin/bookings/");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.has("X-PD-Store-Slug")).toBe(false);
  });

  it("omits the header when the provider returns null", async () => {
    setStoreSlugProvider(() => null);
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await adminFetch("/api/admin/bookings/");

    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.has("X-PD-Store-Slug")).toBe(false);
  });

  it("defaults Content-Type to application/json and sends credentials", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await adminFetch("/api/admin/bookings/", { method: "POST", body: "{}" });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.credentials).toBe("include");
  });

  it("throws ApiError on non-2xx with the parsed body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "nope" }, 403));

    await expect(adminFetch("/api/admin/bookings/")).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      body: { detail: "nope" },
    });
  });

  it("resolves to undefined on a 204 No Content response", async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, 204));

    await expect(adminFetch("/api/admin/bookings/1/")).resolves.toBeUndefined();
  });

  it("ApiError is exported and an instance of Error", () => {
    expect(new ApiError(500, null)).toBeInstanceOf(Error);
  });
});

describe("api.ts request() integration", () => {
  it("typed admin calls inherit the store-slug header", async () => {
    setStoreSlugProvider(() => "playdesk-flagship");
    fetchMock.mockResolvedValue(
      jsonResponse({ count: 0, next: null, previous: null, results: [] }),
    );

    // Dynamic import to ensure adminFetch wires after the provider is set.
    const { adminListBookings } = await import("./api");
    await adminListBookings();

    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("X-PD-Store-Slug")).toBe("playdesk-flagship");
  });
});
