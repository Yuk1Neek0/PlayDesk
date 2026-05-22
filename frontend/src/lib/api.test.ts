import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import {
  ApiError,
  adminListBookings,
  createBooking,
  deleteBooking,
  getResourceAvailability,
  listResources,
  updateBooking,
} from "./api";

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

const EMPTY_PAGE = { count: 0, next: null, previous: null, results: [] };

describe("listResources", () => {
  it("requests /api/resources and returns the parsed body", async () => {
    fetchMock.mockResolvedValue(jsonResponse(EMPTY_PAGE));

    const result = await listResources();

    expect(result).toEqual(EMPTY_PAGE);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/resources");
  });

  it("serialises query params into the URL", async () => {
    fetchMock.mockResolvedValue(jsonResponse(EMPTY_PAGE));

    await listResources({ type: "console", store_id: 3 });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("type=console");
    expect(url).toContain("store_id=3");
  });

  it("omits undefined query params", async () => {
    fetchMock.mockResolvedValue(jsonResponse(EMPTY_PAGE));

    await listResources({ type: undefined });

    expect(String(fetchMock.mock.calls[0][0])).not.toContain("?");
  });
});

describe("getResourceAvailability", () => {
  it("includes the date query param", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ resource_id: 1, date: "2026-06-01", available: [], suggestions: [] }),
    );

    await getResourceAvailability(1, "2026-06-01");

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/resources/1/availability");
    expect(url).toContain("date=2026-06-01");
  });
});

describe("createBooking", () => {
  it("POSTs the body as JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }, 201));

    await createBooking({
      resource_id: 1,
      customer_name: "Alice",
      customer_phone: "+86-138",
      start_time: "2026-06-01T20:00:00+08:00",
      end_time: "2026-06-01T22:00:00+08:00",
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string).customer_name).toBe("Alice");
  });

  it("throws ApiError carrying status and parsed body on 409", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "Slot taken", conflicting_booking_id: 7 }, 409),
    );

    await expect(
      createBooking({
        resource_id: 1,
        customer_name: "Bob",
        customer_phone: "+86",
        start_time: "2026-06-01T20:00:00+08:00",
        end_time: "2026-06-01T22:00:00+08:00",
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      body: { detail: "Slot taken", conflicting_booking_id: 7 },
    });
  });
});

describe("updateBooking", () => {
  it("uses the PATCH method", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 2 }));

    await updateBooking(2, { status: "confirmed" });

    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("PATCH");
  });
});

describe("deleteBooking", () => {
  it("resolves to undefined on a 204 response", async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, 204));

    await expect(deleteBooking(5)).resolves.toBeUndefined();
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("DELETE");
  });
});

describe("adminListBookings", () => {
  it("hits the admin endpoint", async () => {
    fetchMock.mockResolvedValue(jsonResponse(EMPTY_PAGE));

    await adminListBookings({ status: "confirmed" });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/admin/bookings");
    expect(url).toContain("status=confirmed");
  });
});

describe("ApiError", () => {
  it("tolerates a non-JSON error body", async () => {
    fetchMock.mockResolvedValue(new Response("<html>500</html>", { status: 500 }));

    await expect(listResources()).rejects.toMatchObject({
      status: 500,
      body: null,
    });
  });

  it("is an instance of Error", () => {
    expect(new ApiError(404, null)).toBeInstanceOf(Error);
  });
});
