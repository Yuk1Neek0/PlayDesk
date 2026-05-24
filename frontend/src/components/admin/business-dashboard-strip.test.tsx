import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

import { BusinessDashboardStrip } from "./business-dashboard-strip";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const PAYLOAD = {
  bookings_today: { count: 7, trend_pct_vs_yesterday: 12.5 },
  bookings_window: { count: 120, window_days: 30 },
  revenue_window: { amount_cents: 1_245_000, currency: "CAD", window_days: 30 },
  new_customers_window: { count: 19, window_days: 30 },
  outbound_24h: { sent: 42, failed: 1, queued: 5 },
  qr_window: { scans: 80, clicks: 24, engagement_pct: 30.0, window_days: 7 },
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

describe("BusinessDashboardStrip", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("renders six skeleton placeholders before the fetch resolves", () => {
    // Pending fetch — never resolves during this test body.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
    render(<BusinessDashboardStrip />);
    const skeleton = screen.getByTestId("dashboard-skeleton");
    expect(skeleton.children.length).toBe(6);
  });

  it("renders six populated cards after the mocked fetch resolves", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(PAYLOAD)),
    );
    render(<BusinessDashboardStrip />);
    await waitFor(() => expect(screen.queryByTestId("dashboard-strip")).not.toBeNull());

    expect(screen.getByText("Bookings today")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.getByText(/Bookings · last 30d/)).toBeTruthy();
    expect(screen.getByText("Revenue")).toBeTruthy();
    expect(screen.getByText(/CA\$ 12,450/)).toBeTruthy();
    expect(screen.getByText("New customers")).toBeTruthy();
    expect(screen.getByText("Outbound · 24h")).toBeTruthy();
    expect(screen.getByText("QR engagement")).toBeTruthy();
    expect(screen.getByText("30.0%")).toBeTruthy();

    const strip = screen.getByTestId("dashboard-strip");
    // Each of the six cards renders one .pd-stat element.
    expect(strip.querySelectorAll(".pd-stat").length).toBe(6);
  });

  it("polls again after 60s, triggering a second fetch", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(PAYLOAD));
    vi.stubGlobal("fetch", fetchMock);
    // Fake timers from the start so the setInterval (60s) can be advanced
    // deterministically. The component's fetch path uses microtasks (.then),
    // which still run under fake timers — they don't depend on the clock.
    vi.useFakeTimers({ shouldAdvanceTime: true });

    render(<BusinessDashboardStrip />);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
