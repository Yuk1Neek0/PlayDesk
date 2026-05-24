import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { MetricCard } from "./metric-card";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe("MetricCard", () => {
  it("renders the label and value", () => {
    render(<MetricCard label="Bookings today" value={42} />);
    expect(screen.getByText("Bookings today")).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
  });

  it("wraps in a link when href is set", () => {
    render(<MetricCard label="Revenue" value="CA$ 1,200" href="/admin/bookings" />);
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/admin/bookings");
  });

  it("renders a positive trend chip with +X.X% and an up-trend style", () => {
    render(<MetricCard label="Bookings today" value={4} trendPct={15.5} />);
    const chip = screen.getByTestId("metric-trend-chip");
    expect(chip.textContent).toBe("+15.5%");
    expect(chip.getAttribute("data-trend")).toBe("ok");
  });

  it("renders a negative trend chip with -X.X% and a down-trend style", () => {
    render(<MetricCard label="Bookings today" value={2} trendPct={-5} />);
    const chip = screen.getByTestId("metric-trend-chip");
    expect(chip.textContent).toBe("-5.0%");
    expect(chip.getAttribute("data-trend")).toBe("warn");
  });

  it("renders a zero trend chip with ±0.0%", () => {
    render(<MetricCard label="Bookings today" value={3} trendPct={0} />);
    const chip = screen.getByTestId("metric-trend-chip");
    expect(chip.textContent).toBe("±0.0%");
  });

  it("renders no chip when trendPct is null", () => {
    render(<MetricCard label="Bookings today" value={1} trendPct={null} />);
    expect(screen.queryByTestId("metric-trend-chip")).toBeNull();
  });

  it("renders the secondary line when provided", () => {
    render(
      <MetricCard
        label="QR engagement"
        value="30.0%"
        secondary="10 scans / 3 clicks · last 7 days"
      />,
    );
    expect(screen.getByText(/10 scans \/ 3 clicks/)).toBeTruthy();
  });
});
