// Mock data for the PlayDesk UI, ported from the Claude Design handoff
// (playdeck/project/src/data.js). Shapes mirror docs/contracts/openapi.yaml.
//
// This is the prototype's client-side mock layer. Wiring the pages to the
// real REST API + SSE stream (via src/lib/api.ts and useChatStream) is the
// remaining work of frontend tasks #20-#22.

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

export interface Booking {
  id: number;
  resource_id: number;
  conversation_id: number | null;
  customer_name: string;
  customer_phone: string;
  start_time: string;
  end_time: string;
  status: BookingStatus;
  source: BookingSource;
  created_at: string;
}

export interface Conversation {
  id: number;
  customer_identifier: string;
  started_at: string;
  status: "active" | "closed";
  messages: number;
  last: string;
}

export interface Availability {
  available: string[];
  booked: string[];
}

export const RESOURCES: Resource[] = [
  {
    id: 1,
    type: "console",
    name: "PS5 Station · A",
    capacity: 2,
    price_per_hour: "58.00",
    metadata: { controller_count: 2, has_vr: false, titles: ["Elden Ring", "FIFA 25", "EA UFC 5"] },
  },
  {
    id: 2,
    type: "console",
    name: "PS5 Station · B",
    capacity: 2,
    price_per_hour: "58.00",
    metadata: { controller_count: 2, has_vr: false, titles: ["Tekken 8", "GTA V", "Spider‑Man 2"] },
  },
  {
    id: 3,
    type: "console",
    name: "Switch Station",
    capacity: 4,
    price_per_hour: "48.00",
    metadata: { controller_count: 4, titles: ["Smash Bros.", "Mario Kart 8", "Splatoon 3"] },
  },
  {
    id: 4,
    type: "room",
    name: "Private Room · Neon",
    capacity: 6,
    price_per_hour: "188.00",
    metadata: { consoles: ["PS5", "Switch"], sofa: true, titles: ["Party pack", "FIFA 25"] },
  },
  {
    id: 5,
    type: "room",
    name: "Private Room · Vault",
    capacity: 8,
    price_per_hour: "248.00",
    metadata: { consoles: ["PS5 Pro"], projector: true, titles: ["Co‑op night"] },
  },
  {
    id: 6,
    type: "table",
    name: "Board‑game Table · 01",
    capacity: 6,
    price_per_hour: "38.00",
    metadata: { games: 180, featured: ["Catan", "Wingspan", "Azul"] },
  },
];

// Hourly slots, 10:00 → 23:00.
export const HOURS: string[] = [];
for (let h = 10; h <= 23; h++) HOURS.push(`${String(h).padStart(2, "0")}:00`);

function seededRandom(seed: number): number {
  const x = Math.sin(seed) * 10000;
  return x - Math.floor(x);
}

// Deterministic per (resource, date) availability so the grid is stable.
export function availabilityFor(resourceId: number, dateISO: string): Availability {
  const key =
    resourceId * 99991 +
    dateISO.split("-").reduce((a, b) => a * 31 + parseInt(b, 10), 7);
  const booked = new Set<string>();
  HOURS.forEach((h, i) => {
    if (seededRandom(key + i) < 0.32) booked.add(h);
  });
  return {
    available: HOURS.filter((h) => !booked.has(h)),
    booked: Array.from(booked),
  };
}

export const BOOKINGS: Booking[] = [
  {
    id: 4112,
    resource_id: 1,
    conversation_id: 88,
    customer_name: "Alice Chen",
    customer_phone: "+86 138 0011 2233",
    start_time: "2026-05-22T20:00:00+08:00",
    end_time: "2026-05-22T22:00:00+08:00",
    status: "confirmed",
    source: "agent",
    created_at: "2026-05-21T14:08:11+08:00",
  },
  {
    id: 4111,
    resource_id: 4,
    conversation_id: null,
    customer_name: "Bob Kim",
    customer_phone: "+86 159 8814 7720",
    start_time: "2026-05-22T18:00:00+08:00",
    end_time: "2026-05-22T20:00:00+08:00",
    status: "confirmed",
    source: "manual",
    created_at: "2026-05-21T13:55:02+08:00",
  },
  {
    id: 4110,
    resource_id: 3,
    conversation_id: 86,
    customer_name: "Carol Wu",
    customer_phone: "+86 188 4423 5099",
    start_time: "2026-05-23T14:00:00+08:00",
    end_time: "2026-05-23T16:00:00+08:00",
    status: "pending_payment",
    source: "agent",
    created_at: "2026-05-21T13:42:30+08:00",
  },
  {
    id: 4109,
    resource_id: 6,
    conversation_id: null,
    customer_name: "Daniel Park",
    customer_phone: "+86 137 2218 0044",
    start_time: "2026-05-22T19:00:00+08:00",
    end_time: "2026-05-22T22:00:00+08:00",
    status: "confirmed",
    source: "manual",
    created_at: "2026-05-21T13:18:55+08:00",
  },
  {
    id: 4108,
    resource_id: 2,
    conversation_id: 84,
    customer_name: "Erin Zhang",
    customer_phone: "+86 152 7711 9930",
    start_time: "2026-05-22T16:00:00+08:00",
    end_time: "2026-05-22T18:00:00+08:00",
    status: "pending",
    source: "agent",
    created_at: "2026-05-21T13:02:48+08:00",
  },
  {
    id: 4107,
    resource_id: 5,
    conversation_id: null,
    customer_name: "Frank Liu",
    customer_phone: "+86 186 5523 6611",
    start_time: "2026-05-24T19:00:00+08:00",
    end_time: "2026-05-24T23:00:00+08:00",
    status: "confirmed",
    source: "manual",
    created_at: "2026-05-21T12:40:12+08:00",
  },
  {
    id: 4106,
    resource_id: 1,
    conversation_id: 82,
    customer_name: "Grace Tan",
    customer_phone: "+86 139 8841 2200",
    start_time: "2026-05-22T14:00:00+08:00",
    end_time: "2026-05-22T16:00:00+08:00",
    status: "cancelled",
    source: "agent",
    created_at: "2026-05-21T11:55:01+08:00",
  },
  {
    id: 4105,
    resource_id: 3,
    conversation_id: null,
    customer_name: "Henry Ma",
    customer_phone: "+86 158 1199 3344",
    start_time: "2026-05-23T11:00:00+08:00",
    end_time: "2026-05-23T13:00:00+08:00",
    status: "confirmed",
    source: "manual",
    created_at: "2026-05-21T11:32:20+08:00",
  },
];

export const CONVERSATIONS: Conversation[] = [
  {
    id: 88,
    customer_identifier: "alice·138‑0011",
    started_at: "2026-05-21T14:05:00+08:00",
    status: "active",
    messages: 7,
    last: "Booked PS5 Station · A · 20:00–22:00",
  },
  {
    id: 87,
    customer_identifier: "anon·7af2",
    started_at: "2026-05-21T14:02:15+08:00",
    status: "active",
    messages: 3,
    last: "Asking about Switch controller count…",
  },
  {
    id: 86,
    customer_identifier: "carol·188‑4423",
    started_at: "2026-05-21T13:38:42+08:00",
    status: "active",
    messages: 12,
    last: "Awaiting payment for Switch Station",
  },
  {
    id: 85,
    customer_identifier: "anon·d810",
    started_at: "2026-05-21T13:21:00+08:00",
    status: "closed",
    messages: 5,
    last: "Resolved · refund policy question",
  },
  {
    id: 84,
    customer_identifier: "erin·152‑7711",
    started_at: "2026-05-21T13:00:11+08:00",
    status: "active",
    messages: 9,
    last: "Reserved PS5 · B 16:00–18:00",
  },
  {
    id: 83,
    customer_identifier: "anon·11ab",
    started_at: "2026-05-21T12:48:30+08:00",
    status: "closed",
    messages: 4,
    last: "Closed · asked for directions",
  },
];
