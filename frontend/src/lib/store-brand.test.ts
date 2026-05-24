import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { fetchStoreBrand } from "./store-brand";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("fetchStoreBrand", () => {
  it("returns the payload on a 200 with valid fields", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        name: "Branded Store",
        logo_url: "https://cdn.example.com/logo.png",
        accent: "oklch(0.78 0.16 200)",
      }),
    );

    const result = await fetchStoreBrand();

    expect(result).toEqual({
      name: "Branded Store",
      logo_url: "https://cdn.example.com/logo.png",
      accent: "oklch(0.78 0.16 200)",
    });
  });

  it("hits the public/store-brand endpoint with default cache", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ name: "X", logo_url: null, accent: null }),
    );

    await fetchStoreBrand();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/public/store-brand/");
    expect(init).toMatchObject({ cache: "default" });
  });

  it("preserves explicit nulls in the payload", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ name: "Plain", logo_url: null, accent: null }),
    );

    const result = await fetchStoreBrand();

    expect(result).toEqual({ name: "Plain", logo_url: null, accent: null });
  });

  it("falls back to the default brand on a 500", async () => {
    fetchMock.mockResolvedValue(new Response("oops", { status: 500 }));

    const result = await fetchStoreBrand();

    expect(result).toEqual({ name: "PlayDesk", logo_url: null, accent: null });
  });

  it("falls back to the default brand on a network error", async () => {
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));

    const result = await fetchStoreBrand();

    expect(result).toEqual({ name: "PlayDesk", logo_url: null, accent: null });
  });
});
