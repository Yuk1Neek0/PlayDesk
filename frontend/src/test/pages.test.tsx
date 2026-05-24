import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
// BookingPage is the interactive client component; `app/page.tsx` is a thin
// server entry that SSR-fetches branding and forwards it as a prop. Tests
// exercise the client component directly with a stub brand.
import BookingPage from "@/app/BookingPage";
import ChatPage from "@/app/chat/page";
import AdminPage from "@/app/admin/page";

const DEFAULT_BRAND = { name: "PlayDesk", logo_url: null, accent: null };

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
    render(<BookingPage brand={DEFAULT_BRAND} />);
    expect(screen.getByText(/Pick your station/i)).toBeTruthy();
    await screen.findByText("PS5 Station · A");
  });

  it("renders the four step titles", async () => {
    render(<BookingPage brand={DEFAULT_BRAND} />);
    expect(screen.getByText("Choose a resource")).toBeTruthy();
    expect(screen.getByText("Pick a date")).toBeTruthy();
    expect(screen.getByText("Choose a time")).toBeTruthy();
    expect(screen.getByText("Confirm booking")).toBeTruthy();
    await screen.findByText("PS5 Station · A");
  });

  it("renders resource cards loaded from the API", async () => {
    render(<BookingPage brand={DEFAULT_BRAND} />);
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

describe("AdminPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
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
