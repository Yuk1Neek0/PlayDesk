"use client";

// StoreSwitcher — chip-group rendered in the admin nav header.
// One chip per store the admin has access to; click switches the current
// store, which (a) updates localStorage + cookie via the StoreContext
// and (b) re-renders every consumer that has `current.slug` in its
// dependency array, triggering in-place re-fetches.
//
// Hidden when there's only one store — single-store deployments don't
// need clutter.

import { useCurrentStore } from "@/lib/store-context";

interface Props {
  /** Optional className for the wrapping pd-seg element. */
  className?: string;
}

export function StoreSwitcher({ className }: Props) {
  const { stores, current, setCurrent } = useCurrentStore();

  // Hide for single-store deployments. Also hide before the list loads so
  // the admin nav doesn't briefly render an empty pill row.
  if (stores.length <= 1) return null;

  return (
    <div
      className={`pd-seg pd-seg--sm ${className ?? ""}`}
      role="tablist"
      aria-label="Switch store"
      data-testid="store-switcher"
    >
      {stores.map((s) => {
        const active = current?.slug === s.slug;
        return (
          <button
            key={s.slug}
            role="tab"
            aria-selected={active}
            className={`pd-seg-item ${active ? "is-active" : ""}`}
            onClick={() => {
              if (!active) setCurrent(s.slug);
            }}
          >
            {s.name}
          </button>
        );
      })}
    </div>
  );
}

export default StoreSwitcher;
