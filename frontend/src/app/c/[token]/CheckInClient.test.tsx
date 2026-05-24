import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import CheckInClient, { type CheckInPayload } from "./CheckInClient";

const BRAND = { name: "Test Lounge", logo_url: null, accent: null };

function payload(overrides: Partial<CheckInPayload> = {}): CheckInPayload {
  return {
    booking_id: 42,
    status: "confirmed",
    checked_in_at: null,
    customer_name: "Tora Tester",
    resource_name: "PS5 Station 2",
    start_time: "2026-05-24T19:00:00Z",
    end_time: "2026-05-24T20:00:00Z",
    store_slug: "lounge",
    can_check_in: true,
    message: "Ready to check in",
    ...overrides,
  };
}

beforeEach(() => {
  // Default to a successful POST that flips the booking to CHECKED_IN.
  vi.spyOn(global, "fetch").mockImplementation(async () =>
    new Response(
      JSON.stringify(
        payload({
          status: "checked_in",
          checked_in_at: "2026-05-24T19:01:00Z",
          can_check_in: false,
          message: "Already checked in at 19:01",
        }),
      ),
      { status: 200 },
    ),
  );
});

describe("CheckInClient", () => {
  it("renders the welcome card with the I'm here button for a CONFIRMED booking", () => {
    render(<CheckInClient initial={payload()} brand={BRAND} token="ABCD2345" />);
    expect(screen.getByText("Hi Tora,")).toBeInTheDocument();
    expect(screen.getByTestId("checkin-button")).toHaveTextContent("I'm here");
    expect(screen.getByText("PS5 Station 2")).toBeInTheDocument();
  });

  it("flips to the welcome confirmation after a successful check-in", async () => {
    render(<CheckInClient initial={payload()} brand={BRAND} token="ABCD2345" />);
    fireEvent.click(screen.getByTestId("checkin-button"));
    await waitFor(() => expect(screen.getByTestId("checkin-message")).toBeInTheDocument());
    expect(screen.getByTestId("checkin-message").textContent).toMatch(/Already checked in/);
    expect(screen.getByText("Welcome, Tora!")).toBeInTheDocument();
  });

  it("renders the cancelled message instead of the button when can_check_in is false", () => {
    render(
      <CheckInClient
        initial={payload({
          status: "cancelled",
          can_check_in: false,
          message: "This booking was cancelled",
        })}
        brand={BRAND}
        token="ABCD2345"
      />,
    );
    expect(screen.queryByTestId("checkin-button")).toBeNull();
    expect(screen.getByTestId("checkin-message").textContent).toMatch(/cancelled/);
  });
});
