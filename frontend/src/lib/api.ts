// Typed REST client for the PlayDesk backend.
//
// Request/response shapes come from `src/types/api.d.ts`, generated from
// docs/contracts/openapi.yaml (`npm run gen:api`). No hand-written wire types.
// The streaming `POST /api/conversations/{id}/messages` endpoint is handled
// separately in `sse.ts`.

import type { components } from "@/types/api";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Schemas = components["schemas"];

export type Resource = Schemas["Resource"];
export type ResourceType = Schemas["ResourceType"];
export type TimeSlot = Schemas["TimeSlot"];
export type AvailabilityResponse = Schemas["AvailabilityResponse"];
export type Booking = Schemas["Booking"];
export type BookingCreate = Schemas["BookingCreate"];
export type BookingPatch = Schemas["BookingPatch"];
export type BookingStatus = Schemas["BookingStatus"];
export type BookingSource = Schemas["BookingSource"];
export type Conversation = Schemas["Conversation"];
export type ConversationCreate = Schemas["ConversationCreate"];
export type ConversationDetail = Schemas["ConversationDetail"];
export type Message = Schemas["Message"];
export type PaginatedResources = Schemas["PaginatedResources"];
export type PaginatedBookings = Schemas["PaginatedBookings"];
export type PaginatedConversations = Schemas["PaginatedConversations"];

/** Thrown for any non-2xx response; `body` carries the parsed error payload. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`PlayDesk API request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

type QueryParams = Record<string, string | number | undefined>;

function queryString(params?: QueryParams): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const serialized = search.toString();
  return serialized ? `?${serialized}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Non-JSON or empty error body — leave as null.
    }
    throw new ApiError(response.status, body);
  }

  // 204 No Content (e.g. deleteBooking) has no body to parse.
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ── Resources ──────────────────────────────────────────────────────────────

export function listResources(params?: {
  type?: ResourceType;
  store_id?: number;
}): Promise<PaginatedResources> {
  return request(`/api/resources${queryString(params)}`);
}

export function getResource(id: number): Promise<Resource> {
  return request(`/api/resources/${id}`);
}

export function getResourceAvailability(
  id: number,
  date: string,
): Promise<AvailabilityResponse> {
  return request(`/api/resources/${id}/availability${queryString({ date })}`);
}

// ── Bookings ───────────────────────────────────────────────────────────────

export function listBookings(params?: {
  resource_id?: number;
  status?: BookingStatus;
  date?: string;
  source?: BookingSource;
}): Promise<PaginatedBookings> {
  return request(`/api/bookings${queryString(params)}`);
}

export function createBooking(body: BookingCreate): Promise<Booking> {
  return request("/api/bookings", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getBooking(id: number): Promise<Booking> {
  return request(`/api/bookings/${id}`);
}

export function updateBooking(id: number, body: BookingPatch): Promise<Booking> {
  return request(`/api/bookings/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteBooking(id: number): Promise<void> {
  return request(`/api/bookings/${id}`, { method: "DELETE" });
}

// ── Conversations ──────────────────────────────────────────────────────────

export function createConversation(
  body?: ConversationCreate,
): Promise<Conversation> {
  return request("/api/conversations", {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}

export function getConversation(id: number): Promise<ConversationDetail> {
  return request(`/api/conversations/${id}`);
}

// ── Admin ──────────────────────────────────────────────────────────────────

export function adminListConversations(params?: {
  status?: "active" | "closed";
  ordering?: string;
}): Promise<PaginatedConversations> {
  return request(`/api/admin/conversations${queryString(params)}`);
}

export function adminListBookings(params?: {
  status?: BookingStatus;
  resource_id?: number;
  date?: string;
}): Promise<PaginatedBookings> {
  return request(`/api/admin/bookings${queryString(params)}`);
}
