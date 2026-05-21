import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import BookingPage from "@/app/page";
import ChatPage from "@/app/chat/page";
import AdminPage from "@/app/admin/page";

describe("BookingPage", () => {
  it("renders the booking page heading", () => {
    render(<BookingPage />);
    expect(screen.getByText("Book a Station")).toBeTruthy();
  });

  it("renders all four step sections", () => {
    render(<BookingPage />);
    expect(screen.getByText(/Choose a Resource/i)).toBeTruthy();
    expect(screen.getByText(/Pick a Date/i)).toBeTruthy();
    expect(screen.getByText(/Choose a Time Slot/i)).toBeTruthy();
    // "Confirm Booking" appears in both the h2 and the button
    expect(screen.getAllByText(/Confirm Booking/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders resource options", () => {
    render(<BookingPage />);
    expect(screen.getByText("PS5 Station")).toBeTruthy();
    expect(screen.getByText("Switch Station")).toBeTruthy();
    expect(screen.getByText("Private Room")).toBeTruthy();
  });
});

describe("ChatPage", () => {
  it("renders the chat page heading", () => {
    render(<ChatPage />);
    expect(screen.getByText("AI Front Desk")).toBeTruthy();
  });

  it("renders the AI greeting message", () => {
    render(<ChatPage />);
    expect(screen.getByText(/Hi! I'm the PlayDesk AI front desk/i)).toBeTruthy();
  });

  it("renders tool-call hint", () => {
    render(<ChatPage />);
    expect(screen.getByText(/checking availability/i)).toBeTruthy();
  });
});

describe("AdminPage", () => {
  it("renders the admin page heading", () => {
    render(<AdminPage />);
    expect(screen.getByText("Staff Dashboard")).toBeTruthy();
  });

  it("renders the conversations section", () => {
    render(<AdminPage />);
    expect(screen.getByText("Live Conversations")).toBeTruthy();
  });

  it("renders the bookings section", () => {
    render(<AdminPage />);
    expect(screen.getByText("All Bookings")).toBeTruthy();
  });

  it("renders mock booking data", () => {
    render(<AdminPage />);
    expect(screen.getByText("Alice Chen")).toBeTruthy();
    expect(screen.getByText("PS5 Station")).toBeTruthy();
  });
});
