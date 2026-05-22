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

// The availability API returns UTC timestamps. America/Toronto in late May
// is on EDT (UTC-4), so a store-local hour H is (H+4):00Z.
describe("hourOf", () => {
  it("converts a UTC instant to the store-local hour", () => {
    // 18:00Z = 14:00 in America/Toronto.
    expect(hourOf("2026-05-22T18:00:00Z")).toBe(14);
  });

  it("treats a store-local midnight as hour 24 (end of day)", () => {
    // 04:00Z on the 23rd = 00:00 America/Toronto.
    expect(hourOf("2026-05-23T04:00:00Z")).toBe(24);
  });
});

describe("toSlotData", () => {
  it("collapses a continuous block into the free hours fully inside it", () => {
    // 14:00Z–18:00Z = 10:00–14:00 store-local.
    const data = toSlotData(
      availability([["2026-05-22T14:00:00Z", "2026-05-22T18:00:00Z"]]),
    );
    expect(data.available).toEqual(["10:00", "11:00", "12:00", "13:00"]);
    expect(data.booked).toContain("14:00");
    expect(data.booked).toContain("23:00");
  });

  it("marks every hour free when a block spans the whole day", () => {
    // 14:00Z–04:00Z(next day) = 10:00–24:00 store-local.
    const data = toSlotData(
      availability([["2026-05-22T14:00:00Z", "2026-05-23T04:00:00Z"]]),
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
    // 01:30Z–03:30Z(next day) = 21:30–23:30 store-local.
    const data = toSlotData(
      availability([], [["2026-05-23T01:30:00Z", "2026-05-23T03:30:00Z"]]),
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
