import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import BookingPage from "@/app/page";
import ChatPage from "@/app/chat/page";
import AdminPage from "@/app/admin/page";

// AdminPage is gated to the staff role — render it as a signed-in staff user.
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { name: "Staff Member", role: "staff" as const },
    ready: true,
    login: () => {},
    logout: () => {},
  }),
}));

// The Next.js app-router context is not mounted under vitest/jsdom.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: () => {},
    replace: () => {},
    prefetch: () => {},
    back: () => {},
    forward: () => {},
    refresh: () => {},
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

function page<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results };
}

const RESOURCES = page([
  {
    id: 1,
    store_id: 1,
    type: "console",
    name: "PS5 Station · A",
    capacity: 2,
    price_per_hour: "58.00",
    metadata: { controller_count: 2, titles: ["Elden Ring"] },
  },
  {
    id: 3,
    store_id: 1,
    type: "console",
    name: "Switch Station",
    capacity: 4,
    price_per_hour: "48.00",
    metadata: { controller_count: 4 },
  },
]);

describe("BookingPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => json(RESOURCES)));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the page heading", async () => {
    render(<BookingPage />);
    expect(screen.getByText(/Pick your station/i)).toBeTruthy();
    await screen.findByText("PS5 Station · A");
  });

  it("renders the four step titles", async () => {
    render(<BookingPage />);
    expect(screen.getByText("Choose a resource")).toBeTruthy();
    expect(screen.getByText("Pick a date")).toBeTruthy();
    expect(screen.getByText("Choose a time")).toBeTruthy();
    expect(screen.getByText("Confirm booking")).toBeTruthy();
    await screen.findByText("PS5 Station · A");
  });

  it("renders resource cards loaded from the API", async () => {
    render(<BookingPage />);
    expect(await screen.findByText("PS5 Station · A")).toBeTruthy();
    expect(await screen.findByText("Switch Station")).toBeTruthy();
  });
});

describe("ChatPage", () => {
  it("renders the chat header", () => {
    render(<ChatPage />);
    expect(screen.getByText("PlayDesk Front Desk")).toBeTruthy();
  });

  it("renders the assistant greeting", () => {
    render(<ChatPage />);
    expect(screen.getByText(/I'm the PlayDesk front desk/i)).toBeTruthy();
  });

  it("renders quick-reply suggestions", () => {
    render(<ChatPage />);
    expect(screen.getByText("What board games do you have?")).toBeTruthy();
  });
});

const BOOKINGS = page([
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
]);

const CONVERSATIONS = page([
  {
    id: 88,
    customer_identifier: "alice·138-0011",
    started_at: "2026-05-21T14:05:00+08:00",
    status: "active",
  },
]);

const CONVERSATION_DETAIL = {
  id: 88,
  customer_identifier: "alice·138-0011",
  started_at: "2026-05-21T14:05:00+08:00",
  status: "active",
  messages: [
    {
      id: 1,
      conversation_id: 88,
      role: "user",
      content: "Is the PS5 free tonight?",
      created_at: "2026-05-21T14:05:10+08:00",
    },
  ],
};

const BUSINESS_METRICS = {
  bookings_today: { count: 0, trend_pct_vs_yesterday: null },
  bookings_window: { count: 0, window_days: 30 },
  revenue_window: { amount_cents: 0, currency: "CAD", window_days: 30 },
  new_customers_window: { count: 0, window_days: 30 },
  outbound_24h: { sent: 0, failed: 0, queued: 0 },
  qr_window: { scans: 0, clicks: 0, engagement_pct: 0.0, window_days: 7 },
};

describe("AdminPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/admin/metrics/business")) return json(BUSINESS_METRICS);
        if (url.includes("/api/admin/bookings")) return json(BOOKINGS);
        if (url.includes("/api/admin/conversations")) return json(CONVERSATIONS);
        if (url.includes("/api/resources")) return json(RESOURCES);
        if (url.includes("/api/conversations/")) return json(CONVERSATION_DETAIL);
        return json({});
      }),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the dashboard heading", async () => {
    render(<AdminPage />);
    expect(screen.getByText("Tonight at PlayDesk")).toBeTruthy();
    await screen.findByText("All bookings");
  });

  it("renders the live conversations panel", async () => {
    render(<AdminPage />);
    expect(await screen.findByText("Live conversations")).toBeTruthy();
  });

  it("renders the bookings table with data from the API", async () => {
    render(<AdminPage />);
    expect(await screen.findByText("All bookings")).toBeTruthy();
    expect(await screen.findByText("Alice Chen")).toBeTruthy();
  });
});
