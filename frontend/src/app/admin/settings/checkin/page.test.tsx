import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/store-context", () => ({
  useCurrentStore: () => ({
    current: { id: 1, slug: "test-store", name: "Test Store" },
    stores: [],
    ready: true,
    setCurrent: () => {},
  }),
}));

import CheckinSettingsPage from "./page";

const ACTIVE_KEY = {
  key: "ABCD234XYZ",
  created_at: "2026-05-24T19:00:00Z",
  expires_at: "2026-05-24T19:15:00Z",
  rotation_minutes: 15,
  qr_url: "http://localhost:3000/c-in/?k=ABCD234XYZ",
};

function mockFetchResponse(status: number, body: unknown) {
  vi.spyOn(global, "fetch").mockImplementation(
    async () => new Response(JSON.stringify(body), { status }),
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("CheckinSettingsPage", () => {
  it("renders the masked key on load and reveals on toggle", async () => {
    mockFetchResponse(200, ACTIVE_KEY);
    render(<CheckinSettingsPage />);
    await waitFor(() => {
      expect(screen.getByTestId("active-key")).toBeInTheDocument();
    });
    // Default = masked.
    expect(screen.getByTestId("active-key").textContent).not.toBe("ABCD234XYZ");
    expect(screen.getByTestId("active-key").textContent).toMatch(/•/);
    // Click reveal.
    fireEvent.click(screen.getByTestId("reveal-toggle"));
    expect(screen.getByTestId("active-key").textContent).toBe("ABCD234XYZ");
  });

  it("shows an error card when the active-key endpoint fails", async () => {
    mockFetchResponse(500, { detail: "boom" });
    render(<CheckinSettingsPage />);
    await waitFor(() => {
      expect(screen.getByTestId("checkin-settings-error")).toBeInTheDocument();
    });
  });
});
