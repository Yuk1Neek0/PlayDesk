import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import BookingPage from "@/app/page";
import ChatPage from "@/app/chat/page";
import AdminPage from "@/app/admin/page";

// The booking page loads its resource catalogue from the API on mount.
const RESOURCES_PAYLOAD = {
  count: 2,
  next: null,
  previous: null,
  results: [
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
  ],
};

describe("BookingPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(RESOURCES_PAYLOAD), { status: 200 })),
    );
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

describe("AdminPage", () => {
  it("renders the dashboard heading", () => {
    render(<AdminPage />);
    expect(screen.getByText("Tonight at PlayDesk")).toBeTruthy();
  });

  it("renders the live conversations panel", () => {
    render(<AdminPage />);
    expect(screen.getByText("Live conversations")).toBeTruthy();
  });

  it("renders the bookings table with data", () => {
    render(<AdminPage />);
    expect(screen.getByText("All bookings")).toBeTruthy();
    expect(screen.getByText("Alice Chen")).toBeTruthy();
  });
});
