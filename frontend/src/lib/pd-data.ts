// View-model types and UI constants for the PlayDesk pages.
//
// The shapes mirror docs/contracts/openapi.yaml; the design components
// (pd-ui) and the booking page work against these. Live data now comes from
// the generated REST client (src/lib/api.ts) — the prototype's mock data
// arrays were removed once all three pages were wired to the backend.

export type ResourceType = "console" | "room" | "table";

export interface ResourceMeta {
  controller_count?: number;
  has_vr?: boolean;
  titles?: string[];
  consoles?: string[];
  sofa?: boolean;
  projector?: boolean;
  games?: number;
  featured?: string[];
}

export interface Resource {
  id: number;
  type: ResourceType;
  name: string;
  capacity: number;
  price_per_hour: string;
  metadata: ResourceMeta;
}

export type BookingStatus = "pending" | "pending_payment" | "confirmed" | "cancelled";
export type BookingSource = "manual" | "agent";

// Hourly booking-slot grid the picker renders, 10:00 → 23:00.
export const HOURS: string[] = [];
for (let h = 10; h <= 23; h++) HOURS.push(`${String(h).padStart(2, "0")}:00`);
