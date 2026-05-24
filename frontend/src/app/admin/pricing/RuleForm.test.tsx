// RuleForm smoke test — verifies each rule_type renders the right field
// fragment. Doesn't exercise the save path (covered by the backend
// pricing-rules API tests).

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RuleForm, { BLANK_DRAFT, type DraftRule } from "./RuleForm";

const noop = () => {};

function harness(overrides: Partial<DraftRule> = {}) {
  return (
    <RuleForm
      draft={{ ...BLANK_DRAFT, ...overrides }}
      onChange={noop}
      onClose={noop}
      onSave={noop}
      saving={false}
      error=""
    />
  );
}

describe("RuleForm", () => {
  it("renders peak_hours fields", () => {
    render(harness({ rule_type: "peak_hours" }));
    expect(screen.getAllByText(/Days/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Start hour/i)).toBeTruthy();
    expect(screen.getByText(/End hour/i)).toBeTruthy();
    expect(screen.getByText(/Adjustment %/i)).toBeTruthy();
  });

  it("renders day_of_week fields", () => {
    render(
      harness({
        rule_type: "day_of_week",
        params: { days: ["tue"], discount_pct: 20 },
      }),
    );
    expect(screen.getByText(/% discount/i)).toBeTruthy();
    expect(screen.getByText(/Flat rate per hour/i)).toBeTruthy();
  });

  it("renders member_tier fields", () => {
    render(
      harness({
        rule_type: "member_tier",
        params: { tier_id: 1, discount_pct: 15 },
      }),
    );
    expect(screen.getByText(/Tier ID/i)).toBeTruthy();
    expect(screen.getByText(/Discount %/i)).toBeTruthy();
  });

  it("renders min_duration fields", () => {
    render(
      harness({
        rule_type: "min_duration",
        params: { min_hours: 3, discount_pct: 20 },
      }),
    );
    expect(screen.getByText(/Min hours/i)).toBeTruthy();
  });

  it("renders bracket_rate fields with add/remove", () => {
    render(
      harness({
        rule_type: "bracket_rate",
        params: {
          brackets: [
            { max_hours: 2, rate: "50" },
            { max_hours: null, rate: "30" },
          ],
        },
      }),
    );
    expect(screen.getByText(/Add bracket/i)).toBeTruthy();
    expect(screen.getAllByText(/Rate \$\/hr/i)).toHaveLength(2);
  });

  it("disables Save when name is blank", () => {
    render(harness({ name: "" }));
    const saveBtn = screen.getByRole("button", { name: /save/i });
    expect((saveBtn as HTMLButtonElement).disabled).toBe(true);
  });

  // Quiet the unused-import lint when vi is only sometimes used.
  it("vi is importable for future spying", () => {
    expect(typeof vi.fn).toBe("function");
  });
});
