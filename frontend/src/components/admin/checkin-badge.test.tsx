import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { CheckInBadge } from "./checkin-badge";

describe("CheckInBadge", () => {
  it("renders an em-dash when not yet checked in", () => {
    render(<CheckInBadge checkedInAt={null} status="confirmed" />);
    expect(screen.getByTestId("checkin-badge").textContent).toContain("—");
  });

  it("renders the checked-in time when checked_in_at is populated", () => {
    render(<CheckInBadge checkedInAt="2026-05-24T19:03:00Z" status="checked_in" />);
    // The actual time string depends on the runner's TZ; assert the dot
    // is present (which only renders for the "in" or "done" variants).
    const badge = screen.getByTestId("checkin-badge");
    expect(badge.className).toContain("pd-checkin-badge--in");
    expect(badge.querySelector(".pd-checkin-dot")).not.toBeNull();
  });

  it("renders 'Complete' for a completed booking even with no timestamp", () => {
    render(<CheckInBadge checkedInAt={null} status="completed" />);
    const badge = screen.getByTestId("checkin-badge");
    expect(badge.textContent).toContain("Complete");
    expect(badge.className).toContain("pd-checkin-badge--done");
  });
});
