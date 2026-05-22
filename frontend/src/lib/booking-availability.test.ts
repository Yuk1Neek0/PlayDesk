import { describe, it, expect } from "vitest";

import { hourOf, isoAt, pad, storeOffset, toSlotData } from "./booking-availability";
import type { AvailabilityResponse } from "./api";

function availability(
  available: [string, string][],
  suggestions: [string, string][] = [],
): AvailabilityResponse {
  const toSlots = (pairs: [string, string][]) =>
    pairs.map(([start, end]) => ({ start, end }));
  return {
    resource_id: 1,
    date: "2026-05-22",
    available: toSlots(available),
    suggestions: toSlots(suggestions),
  };
}

describe("pad", () => {
  it("zero-pads to two digits", () => {
    expect(pad(9)).toBe("09");
    expect(pad(20)).toBe("20");
  });
});

describe("hourOf", () => {
  it("reads the store-local hour from an ISO timestamp", () => {
    expect(hourOf("2026-05-22T20:00:00+08:00")).toBe(20);
  });

  it("treats a midnight end as hour 24 (end of day)", () => {
    expect(hourOf("2026-05-23T00:00:00+08:00")).toBe(24);
  });
});

describe("toSlotData", () => {
  it("collapses a continuous block into the free hours fully inside it", () => {
    const data = toSlotData(
      availability([["2026-05-22T10:00:00+08:00", "2026-05-22T14:00:00+08:00"]]),
    );
    expect(data.available).toEqual(["10:00", "11:00", "12:00", "13:00"]);
    expect(data.booked).toContain("14:00");
    expect(data.booked).toContain("23:00");
  });

  it("marks every hour free when a block spans the whole day", () => {
    const data = toSlotData(
      availability([["2026-05-22T10:00:00+08:00", "2026-05-23T00:00:00+08:00"]]),
    );
    expect(data.available).toHaveLength(14);
    expect(data.booked).toEqual([]);
  });

  it("marks every hour booked when nothing is available", () => {
    const data = toSlotData(availability([]));
    expect(data.available).toEqual([]);
    expect(data.booked).toHaveLength(14);
  });

  it("aligns suggestion slots to the hour grid", () => {
    const data = toSlotData(
      availability([], [["2026-05-22T21:30:00+08:00", "2026-05-22T23:30:00+08:00"]]),
    );
    expect(data.suggestions).toEqual(["21:00"]);
  });
});

describe("isoAt", () => {
  it("builds a store-local ISO timestamp at the given hour", () => {
    const off = storeOffset(new Date(2026, 4, 22));
    expect(isoAt(new Date(2026, 4, 22), 20)).toBe(`2026-05-22T20:00:00${off}`);
  });

  it("rolls hour 24 into midnight of the next day", () => {
    const off = storeOffset(new Date(2026, 4, 23));
    expect(isoAt(new Date(2026, 4, 22), 24)).toBe(`2026-05-23T00:00:00${off}`);
  });

  it("uses the store timezone offset, not a hardcoded one", () => {
    // America/Toronto is on EDT (-04:00) in late May.
    expect(storeOffset(new Date(2026, 4, 22))).toBe("-04:00");
  });
});
