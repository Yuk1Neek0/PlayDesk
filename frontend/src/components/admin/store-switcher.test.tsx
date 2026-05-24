import { describe, it, expect, beforeEach } from "vitest";
import { act, render, screen } from "@testing-library/react";

import { StoreProvider, type Store } from "@/lib/store-context";
import { StoreSwitcher } from "./store-switcher";

const ONE: Store[] = [{ id: 1, slug: "playdesk-flagship", name: "PlayDesk Flagship" }];
const TWO: Store[] = [
  { id: 1, slug: "playdesk-flagship", name: "PlayDesk Flagship" },
  { id: 2, slug: "playdesk-north", name: "PlayDesk North" },
];

beforeEach(() => {
  window.localStorage.clear();
});

describe("StoreSwitcher", () => {
  it("renders nothing when there is only one store", () => {
    render(
      <StoreProvider initialStores={ONE}>
        <StoreSwitcher />
      </StoreProvider>,
    );
    expect(screen.queryByTestId("store-switcher")).toBeNull();
  });

  it("renders one chip per store with the active chip highlighted", async () => {
    render(
      <StoreProvider initialStores={TWO}>
        <StoreSwitcher />
      </StoreProvider>,
    );
    const switcher = await screen.findByTestId("store-switcher");
    const chips = switcher.querySelectorAll("button");
    expect(chips.length).toBe(2);
    expect(chips[0].textContent).toBe("PlayDesk Flagship");
    expect(chips[1].textContent).toBe("PlayDesk North");
    expect(chips[0].className).toContain("is-active");
    expect(chips[1].className).not.toContain("is-active");
    expect(chips[0].getAttribute("aria-selected")).toBe("true");
  });

  it("clicking a chip switches the current store + persists the slug", async () => {
    render(
      <StoreProvider initialStores={TWO}>
        <StoreSwitcher />
      </StoreProvider>,
    );
    const switcher = await screen.findByTestId("store-switcher");
    const chips = Array.from(switcher.querySelectorAll("button"));
    const northChip = chips[1];

    await act(async () => {
      northChip.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(switcher.querySelectorAll("button")[1].className).toContain("is-active");
    expect(switcher.querySelectorAll("button")[0].className).not.toContain("is-active");
    expect(window.localStorage.getItem("pd_store_slug")).toBe("playdesk-north");
  });
});
