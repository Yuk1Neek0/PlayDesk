import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { customerFetch } from "./customer-fetch";
import { ApiError } from "./api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status });
}

describe("customerFetch", () => {
  it("injects X-PD-Store-Slug from the URL slug arg", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await customerFetch("playdesk-north", "/api/resources/");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("X-PD-Store-Slug")).toBe("playdesk-north");
  });

  it("overrides any pre-set X-PD-Store-Slug — URL is authoritative", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await customerFetch("playdesk-flagship", "/api/resources/", {
      headers: { "X-PD-Store-Slug": "should-be-replaced" },
    });

    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("X-PD-Store-Slug")).toBe("playdesk-flagship");
  });

  it("defaults Content-Type to application/json and sends credentials", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await customerFetch("flag", "/api/bookings/", { method: "POST", body: "{}" });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.credentials).toBe("include");
  });

  it("respects an explicit Content-Type override", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await customerFetch("flag", "/api/resources/", {
      headers: { "Content-Type": "text/plain" },
    });

    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("Content-Type")).toBe("text/plain");
  });

  it("throws ApiError on non-2xx with the parsed body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "conflict" }, 409));

    await expect(customerFetch("flag", "/api/bookings/")).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      body: { detail: "conflict" },
    });
  });

  it("returns the parsed JSON body on 2xx", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 7 }));

    const result = await customerFetch<{ id: number }>("flag", "/api/bookings/1/");

    expect(result).toEqual({ id: 7 });
  });

  it("resolves to undefined on a 204 No Content response", async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, 204));

    await expect(
      customerFetch("flag", "/api/bookings/1/", { method: "DELETE" }),
    ).resolves.toBeUndefined();
  });

  it("ApiError re-export is reachable", () => {
    expect(new ApiError(500, null)).toBeInstanceOf(Error);
  });
});
