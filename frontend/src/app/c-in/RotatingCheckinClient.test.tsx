import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import RotatingCheckinClient, { type CheckinBooking } from "./RotatingCheckinClient";

const BRAND = { name: "Test Lounge", logo_url: null, accent: null };

function booking(overrides: Partial<CheckinBooking> = {}): CheckinBooking {
  return {
    id: 11,
    resource_name: "PS5 Door 1",
    start_time: "2026-05-24T19:00:00Z",
    end_time: "2026-05-24T20:00:00Z",
    status: "confirmed",
    checked_in_at: null,
    customer_name: "Alice Tester",
    can_check_in: true,
    ...overrides,
  };
}

function mountClient() {
  return render(
    <RotatingCheckinClient
      brand={BRAND}
      storeSlug="test-store"
      storeName="Test Lounge"
      keyValue="ABCD234567"
    />,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

function mockFetchSequence(responses: Array<{ status: number; body: unknown }>) {
  let i = 0;
  vi.spyOn(global, "fetch").mockImplementation(async () => {
    const r = responses[i++];
    return new Response(JSON.stringify(r.body), { status: r.status });
  });
}

describe("RotatingCheckinClient", () => {
  it("transitions phone → otp on successful request-otp", async () => {
    mockFetchSequence([{ status: 201, body: { request_id: 1 } }]);
    mountClient();
    fireEvent.change(screen.getByTestId("phone-input"), {
      target: { value: "+15551231234" },
    });
    fireEvent.click(screen.getByTestId("phone-submit"));
    await waitFor(() => expect(screen.getByTestId("otp-input")).toBeInTheDocument());
    expect(screen.getByTestId("otp-sent").textContent).toMatch(/\+15551231234/);
  });

  it("renders inline error and stays on OTP step when verify returns 401", async () => {
    mockFetchSequence([
      { status: 201, body: { request_id: 1 } },
      { status: 401, body: { detail: "Invalid code." } },
    ]);
    mountClient();
    fireEvent.change(screen.getByTestId("phone-input"), {
      target: { value: "+15551231234" },
    });
    fireEvent.click(screen.getByTestId("phone-submit"));
    await waitFor(() => expect(screen.getByTestId("otp-input")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("otp-input"), {
      target: { value: "999999" },
    });
    fireEvent.click(screen.getByTestId("otp-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("otp-error").textContent).toMatch(/wrong code/i);
    });
    // Still on the OTP step.
    expect(screen.getByTestId("otp-input")).toBeInTheDocument();
  });

  it("renders the walk-in card when verify returns zero matches", async () => {
    mockFetchSequence([
      { status: 201, body: { request_id: 1 } },
      {
        status: 200,
        body: { bookings: [], store_slug: "test-store", store_name: "Test Lounge" },
      },
    ]);
    mountClient();
    fireEvent.change(screen.getByTestId("phone-input"), {
      target: { value: "+15551231234" },
    });
    fireEvent.click(screen.getByTestId("phone-submit"));
    await waitFor(() => screen.getByTestId("otp-input"));
    fireEvent.change(screen.getByTestId("otp-input"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByTestId("otp-submit"));
    await waitFor(() => expect(screen.getByTestId("walkin-card")).toBeInTheDocument());
    expect(screen.getByTestId("walkin-card").textContent).toMatch(/see staff/i);
  });

  it("renders the disambiguation list when verify returns 2+ matches", async () => {
    mockFetchSequence([
      { status: 201, body: { request_id: 1 } },
      {
        status: 200,
        body: {
          bookings: [
            booking({ id: 11, resource_name: "PS5 Door 1" }),
            booking({ id: 12, resource_name: "PS5 Door 2" }),
          ],
          store_slug: "test-store",
          store_name: "Test Lounge",
        },
      },
    ]);
    mountClient();
    fireEvent.change(screen.getByTestId("phone-input"), {
      target: { value: "+15551231234" },
    });
    fireEvent.click(screen.getByTestId("phone-submit"));
    await waitFor(() => screen.getByTestId("otp-input"));
    fireEvent.change(screen.getByTestId("otp-input"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByTestId("otp-submit"));
    await waitFor(() => expect(screen.getByTestId("multi-match")).toBeInTheDocument());
    expect(screen.getByTestId("multi-checkin-11")).toBeInTheDocument();
    expect(screen.getByTestId("multi-checkin-12")).toBeInTheDocument();
  });

  it("shows confirmation after a successful single-match check-in", async () => {
    mockFetchSequence([
      { status: 201, body: { request_id: 1 } },
      {
        status: 200,
        body: {
          bookings: [booking({ id: 11 })],
          store_slug: "test-store",
          store_name: "Test Lounge",
        },
      },
      {
        status: 200,
        body: booking({
          id: 11,
          status: "checked_in",
          checked_in_at: "2026-05-24T19:01:00Z",
          can_check_in: false,
        }),
      },
    ]);
    mountClient();
    fireEvent.change(screen.getByTestId("phone-input"), {
      target: { value: "+15551231234" },
    });
    fireEvent.click(screen.getByTestId("phone-submit"));
    await waitFor(() => screen.getByTestId("otp-input"));
    fireEvent.change(screen.getByTestId("otp-input"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByTestId("otp-submit"));
    await waitFor(() => screen.getByTestId("single-match"));
    fireEvent.click(screen.getByTestId("single-checkin-btn"));
    await waitFor(() => expect(screen.getByTestId("confirmation")).toBeInTheDocument());
    expect(screen.getByTestId("confirmation").textContent).toMatch(/checked in/i);
  });
});
