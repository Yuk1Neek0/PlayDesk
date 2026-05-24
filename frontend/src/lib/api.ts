// Typed REST client for the PlayDesk backend.
//
// Request/response shapes come from `src/types/api.d.ts`, generated from
// docs/contracts/openapi.yaml (`npm run gen:api`). No hand-written wire types.
// The streaming `POST /api/conversations/{id}/messages` endpoint is handled
// separately in `sse.ts`.
//
// Multi-location note (epic #157, task #161): the internal `request()` helper
// delegates to `adminFetch` in `admin-fetch.ts`, which auto-injects the
// `X-PD-Store-Slug` header from the active `<StoreProvider>`. Single-store
// callers (no provider) get the existing behaviour — the backend's
// `CurrentStoreMiddleware` falls back to the alphabetically-first store.

import type { components } from "@/types/api";
import { adminFetch } from "./admin-fetch";

// Empty by default: requests are same-origin and `/api/*` is proxied to the
// backend by the Next.js rewrite in `next.config.mjs` (the backend ships no
// CORS headers, so the browser cannot call it cross-origin directly). An
// explicit `NEXT_PUBLIC_API_BASE_URL` can still override this if needed.
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

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

/**
 * Django's URLConf registers every route with a trailing slash and, with
 * `APPEND_SLASH` on, 301-redirects slash-less GETs and *rejects* slash-less
 * POST/PATCH/DELETE (the body cannot be replayed across a redirect). The
 * OpenAPI contract omits the slash, so normalise it here on every request.
 */
export function withTrailingSlash(path: string): string {
  const [route, query = ""] = path.split("?");
  const normalised = route.endsWith("/") ? route : `${route}/`;
  return query ? `${normalised}?${query}` : normalised;
}

// Re-export so tests / callers can `import { adminFetch } from "@/lib/api"`
// if they prefer the single-entry-point shape. The canonical location is
// `@/lib/admin-fetch`.
export { adminFetch };

// `request()` stays the typed-client primitive. It delegates to `adminFetch`
// so every admin call (adminListBookings, adminGetMembership, …) inherits
// the `X-PD-Store-Slug` header injection without per-callsite changes.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return adminFetch<T>(`${API_BASE_URL}${withTrailingSlash(path)}`, init);
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

export type ConversationChannel =
  | "web_chat"
  | "sms"
  | "whatsapp"
  | "phone"
  | "manual_staff";

export function adminListConversations(params?: {
  status?: "active" | "closed";
  channel?: ConversationChannel;
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

// ── Admin: customers (retention) ──────────────────────────────────────────

export interface CustomerSummary {
  id: number;
  phone: string;
  name: string;
  email: string | null;
  locale_pref: "en" | "zh";
  tags: string[];
  total_visits: number;
  last_visit_at: string | null;
  created_at: string;
}

export interface CustomerVisit {
  id: number;
  resource_name: string;
  resource_type: string;
  start_time: string;
  end_time: string;
  status: BookingStatus;
  source: BookingSource;
  created_at: string;
}

export interface CustomerNote {
  id: number;
  body: string;
  author_username: string | null;
  created_at: string;
}

export interface CustomerDetail extends CustomerSummary {
  visits: CustomerVisit[];
  notes: CustomerNote[];
}

export interface PaginatedCustomers {
  count: number;
  next: string | null;
  previous: string | null;
  results: CustomerSummary[];
}

export function adminListCustomers(params?: {
  q?: string;
  page?: number;
}): Promise<PaginatedCustomers> {
  return request(`/api/admin/customers${queryString(params)}`);
}

export function adminGetCustomer(id: number): Promise<CustomerDetail> {
  return request(`/api/admin/customers/${id}`);
}

export function adminAddCustomerNote(id: number, body: string): Promise<CustomerNote> {
  return request(`/api/admin/customers/${id}/notes`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

// ── Admin: outbound messages ──────────────────────────────────────────────

export type OutboundStatus = "queued" | "sent" | "failed" | "cancelled";
export type OutboundChannel = "sms" | "web_chat";

export interface OutboundMessage {
  id: number;
  customer_id: number;
  customer_name: string;
  customer_phone: string;
  channel: OutboundChannel;
  template_key: string;
  body: string;
  status: OutboundStatus;
  scheduled_for: string;
  sent_at: string | null;
  failure_reason: string;
  provider_message_id: string;
  created_at: string;
}

export function adminListOutboundMessages(params: {
  customer_id?: number;
  status?: OutboundStatus;
  limit?: number;
}): Promise<OutboundMessage[]> {
  return request(`/api/admin/outbound${queryString(params)}`);
}

// ── One QR ────────────────────────────────────────────────────────────────

export type QRActionKind =
  | "review"
  | "instagram"
  | "tiktok"
  | "rednote"
  | "wechat"
  | "wifi"
  | "custom";

export interface QRAction {
  id: number;
  kind: QRActionKind;
  label: string;
  target_url: string;
  position: number;
  reward_points: number;
  enabled: boolean;
}

export interface QRStoreBrand {
  logo_url?: string;
  accent?: string;
  [k: string]: unknown;
}

export interface QRPublicPayload {
  store: { id: number; name: string; slug: string; brand: QRStoreBrand };
  actions: QRAction[];
}

export interface QRAnalyticsBreakdown {
  action_id: number;
  action__label: string;
  action__kind: QRActionKind;
  clicks: number;
}

export interface QRAnalytics {
  scans: number;
  clicks: number;
  engagement_rate: number;
  per_action: QRAnalyticsBreakdown[];
  days: number;
}

export function getQRPublic(slug: string): Promise<QRPublicPayload> {
  return request(`/api/qr/${slug}`);
}

export function postQREvent(body: {
  slug: string;
  kind: "scan" | "click";
  action_id?: number;
}): Promise<{ ok: boolean }> {
  return request(`/api/qr/event`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function adminListQRActions(store: number): Promise<QRAction[]> {
  return request(`/api/admin/qr-actions${queryString({ store })}`);
}

export function adminCreateQRAction(body: {
  store: number;
  kind: QRActionKind;
  label: string;
  target_url: string;
  position?: number;
  reward_points?: number;
  enabled?: boolean;
}): Promise<QRAction> {
  return request(`/api/admin/qr-actions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function adminUpdateQRAction(
  id: number,
  body: Partial<Omit<QRAction, "id">>,
): Promise<QRAction> {
  return request(`/api/admin/qr-actions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function adminDeleteQRAction(id: number): Promise<void> {
  return request(`/api/admin/qr-actions/${id}`, { method: "DELETE" });
}

export function adminGetQRAnalytics(store: number, days = 7): Promise<QRAnalytics> {
  return request(`/api/admin/qr-analytics${queryString({ store, days })}`);
}

// ── Admin: business-metrics dashboard ─────────────────────────────────────

export interface BookingsTodayMetric {
  count: number;
  trend_pct_vs_yesterday: number | null;
}

export interface BookingsWindowMetric {
  count: number;
  window_days: number;
}

export interface RevenueWindowMetric {
  amount_cents: number;
  currency: string;
  window_days: number;
}

export interface NewCustomersWindowMetric {
  count: number;
  window_days: number;
}

export interface Outbound24hMetric {
  sent: number;
  failed: number;
  queued: number;
}

export interface QRWindowMetric {
  scans: number;
  clicks: number;
  engagement_pct: number;
  window_days: number;
}

export interface BusinessMetricsPayload {
  bookings_today: BookingsTodayMetric;
  bookings_window: BookingsWindowMetric;
  revenue_window: RevenueWindowMetric;
  new_customers_window: NewCustomersWindowMetric;
  outbound_24h: Outbound24hMetric;
  qr_window: QRWindowMetric;
}

export function adminGetBusinessMetrics(
  days?: number,
  init?: RequestInit,
): Promise<BusinessMetricsPayload> {
  const qs = days === undefined ? "" : queryString({ days });
  return request(`/api/admin/metrics/business${qs}`, init);
}

// ── Campaigns ─────────────────────────────────────────────────────────────

export interface SegmentFilter {
  tags_include?: string[];
  min_total_visits?: number;
  last_visit_within_days?: number;
  locale_pref?: "en" | "zh";
}

export interface Segment {
  id: number;
  store_id: number;
  name: string;
  filter: SegmentFilter;
  created_by_username: string | null;
  created_at: string;
}

export interface PaginatedSegments {
  count: number;
  next: string | null;
  previous: string | null;
  results: Segment[];
}

export interface SegmentPreviewCustomer {
  id: number;
  name: string;
  phone: string;
  tags: string[];
  total_visits: number;
  last_visit_at: string | null;
}

export interface SegmentPreview {
  count: number;
  sample: SegmentPreviewCustomer[];
}

export type CampaignStatus =
  | "draft"
  | "scheduled"
  | "sending"
  | "sent"
  | "cancelled";

export interface Campaign {
  id: number;
  store_id: number;
  name: string;
  segment_id: number;
  segment_name: string;
  body_template: string;
  scheduled_for: string;
  status: CampaignStatus;
  sent_at: string | null;
  recipient_snapshot_count: number;
  created_by_username: string | null;
  sent_by_username: string | null;
  created_at: string;
}

export interface PaginatedCampaigns {
  count: number;
  next: string | null;
  previous: string | null;
  results: Campaign[];
}

export type CampaignRunStatus = "queued" | "sent" | "failed" | "skipped_optout";

export interface CampaignRun {
  id: number;
  customer: number;
  customer_name: string;
  customer_phone: string;
  status: CampaignRunStatus;
  outbound_message_id: string;
  failure_reason: string;
  created_at: string;
  sent_at: string | null;
}

export interface PaginatedCampaignRuns {
  count: number;
  next: string | null;
  previous: string | null;
  results: CampaignRun[];
}

export interface CampaignSendSummary {
  sent: number;
  failed: number;
  skipped: number;
  snapshot_count: number;
}

// Segments
export function adminListSegments(params?: {
  store?: number;
  page?: number;
}): Promise<PaginatedSegments> {
  return request(`/api/admin/segments${queryString(params)}`);
}

export function adminCreateSegment(body: {
  store_id: number;
  name: string;
  filter: SegmentFilter;
}): Promise<Segment> {
  return request(`/api/admin/segments`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function adminUpdateSegment(
  id: number,
  body: Partial<{ name: string; filter: SegmentFilter }>,
): Promise<Segment> {
  return request(`/api/admin/segments/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function adminDeleteSegment(id: number): Promise<void> {
  return request(`/api/admin/segments/${id}`, { method: "DELETE" });
}

export function adminPreviewSegment(id: number, limit = 20): Promise<SegmentPreview> {
  return request(`/api/admin/segments/${id}/preview${queryString({ limit })}`);
}

// Campaigns
export function adminListCampaigns(params?: {
  store?: number;
  page?: number;
}): Promise<PaginatedCampaigns> {
  return request(`/api/admin/campaigns${queryString(params)}`);
}

export function adminGetCampaign(id: number): Promise<Campaign> {
  return request(`/api/admin/campaigns/${id}`);
}

export function adminCreateCampaign(body: {
  store_id: number;
  segment_id: number;
  name: string;
  body_template: string;
  scheduled_for?: string;
}): Promise<Campaign> {
  return request(`/api/admin/campaigns`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function adminUpdateCampaign(
  id: number,
  body: Partial<{ name: string; body_template: string; scheduled_for: string }>,
): Promise<Campaign> {
  return request(`/api/admin/campaigns/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function adminSendCampaign(id: number): Promise<CampaignSendSummary> {
  return request(`/api/admin/campaigns/${id}/send`, {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  });
}

export function adminCancelCampaign(id: number): Promise<Campaign> {
  return request(`/api/admin/campaigns/${id}/cancel`, { method: "POST" });
}

export function adminListCampaignRuns(
  id: number,
  params?: { status?: CampaignRunStatus; page?: number; page_size?: number },
): Promise<PaginatedCampaignRuns> {
  return request(`/api/admin/campaigns/${id}/runs${queryString(params)}`);
}

// ── Memberships ───────────────────────────────────────────────────────────

export type PointSource =
  | "booking"
  | "qr_click"
  | "redemption"
  | "adjustment"
  | "backfill";

export interface PointTransaction {
  id: number;
  delta: number;
  source: PointSource;
  reference: string;
  balance_after: number;
  author_username: string | null;
  created_at: string;
}

export interface RewardTierBadge {
  id: number;
  name: string;
  perks_text: string;
}

export interface NextTier {
  id: number;
  name: string;
  min_lifetime_points: number;
}

export interface AvailableReward {
  id: number;
  store: number;
  name: string;
  description: string;
  cost_points: number;
  enabled: boolean;
  created_at: string;
}

export interface MembershipPayload {
  customer_id: number;
  balance: number;
  lifetime_earned: number;
  tier: RewardTierBadge | null;
  next_tier: NextTier | null;
  points_to_next_tier: number | null;
  recent_transactions: PointTransaction[];
  available_rewards: AvailableReward[];
}

export interface Reward {
  id: number;
  store: number;
  name: string;
  description: string;
  cost_points: number;
  enabled: boolean;
  created_at: string;
}

export interface RewardTier {
  id: number;
  store: number;
  name: string;
  min_lifetime_points: number;
  perks_text: string;
  position: number;
}

export function adminGetMembership(customerId: number): Promise<MembershipPayload> {
  return request(`/api/admin/customers/${customerId}/membership`);
}

export function adminAdjustPoints(
  customerId: number,
  body: { delta: number; reason: string },
): Promise<{ transaction_id: number; balance: number }> {
  return request(`/api/admin/customers/${customerId}/adjust-points`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function adminRedeemReward(
  customerId: number,
  reward_id: number,
): Promise<{ redemption_id: number; transaction_id: number; balance: number }> {
  return request(`/api/admin/customers/${customerId}/redeem`, {
    method: "POST",
    body: JSON.stringify({ reward_id }),
  });
}

export function adminListRewards(store?: number): Promise<Reward[]> {
  return request(`/api/admin/rewards${queryString({ store })}`);
}

export function adminCreateReward(body: {
  store: number;
  name: string;
  description?: string;
  cost_points: number;
  enabled?: boolean;
}): Promise<Reward> {
  return request(`/api/admin/rewards`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function adminUpdateReward(
  id: number,
  body: Partial<Omit<Reward, "id" | "created_at">>,
): Promise<Reward> {
  return request(`/api/admin/rewards/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function adminDeleteReward(id: number): Promise<void> {
  return request(`/api/admin/rewards/${id}`, { method: "DELETE" });
}

export function adminListTiers(store?: number): Promise<RewardTier[]> {
  return request(`/api/admin/tiers${queryString({ store })}`);
}

export function adminCreateTier(body: {
  store: number;
  name: string;
  min_lifetime_points: number;
  perks_text?: string;
  position: number;
}): Promise<RewardTier> {
  return request(`/api/admin/tiers`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function adminUpdateTier(
  id: number,
  body: Partial<Omit<RewardTier, "id">>,
): Promise<RewardTier> {
  return request(`/api/admin/tiers/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function adminDeleteTier(id: number): Promise<void> {
  return request(`/api/admin/tiers/${id}`, { method: "DELETE" });
}
