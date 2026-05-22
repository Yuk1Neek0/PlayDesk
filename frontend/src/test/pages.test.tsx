import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import BookingPage from "@/app/page";
import ChatPage from "@/app/chat/page";
import AdminPage from "@/app/admin/page";

describe("BookingPage", () => {
  it("renders the page heading", () => {
    render(<BookingPage />);
    expect(screen.getByText(/Pick your station/i)).toBeTruthy();
  });

  it("renders the four step titles", () => {
    render(<BookingPage />);
    expect(screen.getByText("Choose a resource")).toBeTruthy();
    expect(screen.getByText("Pick a date")).toBeTruthy();
    expect(screen.getByText("Choose a time")).toBeTruthy();
    expect(screen.getByText("Confirm booking")).toBeTruthy();
  });

  it("renders resource cards", () => {
    render(<BookingPage />);
    expect(screen.getByText("PS5 Station · A")).toBeTruthy();
    expect(screen.getByText("Switch Station")).toBeTruthy();
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
