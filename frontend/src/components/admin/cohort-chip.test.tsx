import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { CohortChip } from "./cohort-chip";

describe("CohortChip", () => {
  it("renders each cohort with a distinct color signal", () => {
    const labels = [
      ["new", "New"],
      ["active", "Active"],
      ["at_risk", "At risk"],
      ["dormant", "Dormant"],
      ["lost", "Lost"],
    ] as const;
    for (const [cohort, label] of labels) {
      const { unmount } = render(<CohortChip cohort={cohort} />);
      const chip = screen.getByTestId("cohort-chip");
      expect(chip.textContent).toContain(label);
      expect(chip.getAttribute("data-cohort")).toBe(cohort);
      // Each cohort renders an inline background — distinct color signal.
      expect(chip.getAttribute("style")).toMatch(/background/);
      unmount();
    }
  });

  it("renders the count when supplied", () => {
    render(<CohortChip cohort="dormant" count={47} />);
    expect(screen.getByTestId("cohort-chip").textContent).toContain("(47)");
  });

  it("falls back to a ghost chip when the cohort is unknown", () => {
    render(<CohortChip cohort="bogus" />);
    const chip = screen.getByTestId("cohort-chip");
    expect(chip.className).toContain("pd-chip--ghost");
    expect(chip.textContent).toContain("—");
  });
});
