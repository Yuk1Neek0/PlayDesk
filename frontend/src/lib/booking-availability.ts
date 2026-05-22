// Pure helpers for the booking page: bridging the REST availability contract
// to the design's hourly slot grid, and building booking timestamps.

import { HOURS, STORE_TIMEZONE } from "@/lib/pd-data";
import type { AvailabilityResponse } from "@/lib/api";

// The store's UTC offset (e.g. "-04:00") on a given day, derived from
// STORE_TIMEZONE via Intl so daylight saving is handled automatically.
export function storeOffset(day: Date): string {
  const tzName =
    new Intl.DateTimeFormat("en-US", {
      timeZone: STORE_TIMEZONE,
      timeZoneName: "longOffset",
    })
      .formatToParts(day)
      .find((p) => p.type === "timeZoneName")?.value ?? "GMT+00:00";
  const m = tzName.match(/GMT([+-]\d{2}:\d{2})/);
  return m ? m[1] : "+00:00";
}

/** Per-hour availability derived from the API's continuous-block response. */
export interface SlotData {
  available: string[];
  booked: string[];
  suggestions: string[];
}

export function pad(n: number): string {
  return String(n).padStart(2, "0");
}

// The store-local hour of an ISO instant. The availability API returns UTC
// timestamps, so the instant is converted into STORE_TIMEZONE rather than
// read off the string. A midnight boundary counts as hour 24 (end of day).
export function hourOf(iso: string): number {
  const h = Number(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: STORE_TIMEZONE,
      hour: "2-digit",
      hourCycle: "h23",
    }).format(new Date(iso)),
  );
  return h === 0 ? 24 : h;
}

// Collapse the API's continuous available blocks into the per-hour grid the
// slot picker renders. An hour is free when a whole H:00–(H+1):00 window
// fits inside one available block.
export function toSlotData(resp: AvailabilityResponse): SlotData {
  const blocks = resp.available.map((s) => [hourOf(s.start), hourOf(s.end)] as const);
  const available = HOURS.filter((h) => {
    const hh = parseInt(h, 10);
    return blocks.some(([start, end]) => start <= hh && hh + 1 <= end);
  });
  const free = new Set(available);
  return {
    available,
    booked: HOURS.filter((h) => !free.has(h)),
    // Align suggestions to the hour grid — the rest of the booking flow
    // works in whole hours, so a picked suggestion must too.
    suggestions: resp.suggestions.map((s) => `${pad(hourOf(s.start) % 24)}:00`),
  };
}

// An ISO timestamp at a store-local hour; hour 24 rolls into the next day.
export function isoAt(date: Date, hour: number): string {
  const day = hour >= 24 ? new Date(date.getTime() + 86_400_000) : date;
  const ymd = `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
  return `${ymd}T${pad(hour % 24)}:00:00${storeOffset(day)}`;
}
