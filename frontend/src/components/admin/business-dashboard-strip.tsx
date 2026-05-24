"use client";

// BusinessDashboardStrip — six metric cards in a responsive grid, polled
// every 60s. Mounted above "Tonight at PlayDesk" on /admin.
//
// Polling strategy: one setInterval; an AbortController cancels any
// in-flight request when the next tick fires so slow responses don't
// pile up. Unmount cleans up both.

import { useEffect, useRef, useState } from "react";

import {
  adminGetBusinessMetrics,
  type BusinessMetricsPayload,
} from "@/lib/api";
import { useCurrentStore } from "@/lib/store-context";
import { MetricCard } from "./metric-card";

const POLL_MS = 60_000;

export function BusinessDashboardStrip() {
  const [data, setData] = useState<BusinessMetricsPayload | null>(null);
  const [errored, setErrored] = useState(false);
  // Track the latest abort controller so each new fetch cancels the
  // previous in-flight one.
  const abortRef = useRef<AbortController | null>(null);

  // v6 multi-location: re-mount the poll on store switch so the metrics
  // strip immediately reflects the new store. `current?.slug` flowing into
  // the dep array also clears the previous store's stale data.
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;

  useEffect(() => {
    let mounted = true;
    // Reset to skeleton so a switch doesn't briefly show the old store's
    // numbers under the new store's chip.
    setData(null);
    setErrored(false);

    const fetchOnce = () => {
      // Cancel any in-flight request from a prior tick.
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      adminGetBusinessMetrics(undefined, { signal: controller.signal })
        .then((payload) => {
          if (!mounted) return;
          setData(payload);
          setErrored(false);
        })
        .catch((err: unknown) => {
          // AbortError on cleanup / re-fetch is expected — don't flag it.
          if (controller.signal.aborted) return;
          if (!mounted) return;
          // Keep last good data; show error only if we have nothing.
          if (!data) setErrored(true);
          void err;
        });
    };

    fetchOnce();
    const id = setInterval(fetchOnce, POLL_MS);
    return () => {
      mounted = false;
      clearInterval(id);
      abortRef.current?.abort();
    };
    // `data` is intentionally excluded — re-creating the interval on every
    // payload change would defeat the polling cadence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeSlug]);

  if (data === null) {
    return (
      <div className="pd-stat-grid pd-stat-grid--6" data-testid="dashboard-skeleton">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="pd-stat pd-skeleton" aria-hidden />
        ))}
      </div>
    );
  }

  if (errored) {
    return (
      <div className="pd-error">
        <span className="pd-error-dot" />
        Couldn&apos;t load business metrics.
      </div>
    );
  }

  return (
    <div className="pd-stat-grid pd-stat-grid--6" data-testid="dashboard-strip">
      <MetricCard
        label="Bookings today"
        value={data.bookings_today.count}
        href="/admin/bookings?date=today"
        trendPct={data.bookings_today.trend_pct_vs_yesterday}
        secondary={
          data.bookings_today.trend_pct_vs_yesterday === null
            ? "vs. yesterday"
            : undefined
        }
      />
      <MetricCard
        label={`Bookings · last ${data.bookings_window.window_days}d`}
        value={data.bookings_window.count}
        href="/admin/bookings?date=today"
      />
      <MetricCard
        label="Revenue"
        value={formatMoney(data.revenue_window.amount_cents, data.revenue_window.currency)}
        secondary={`last ${data.revenue_window.window_days} days`}
        href="/admin/bookings?status=completed"
      />
      <MetricCard
        label="New customers"
        value={data.new_customers_window.count}
        secondary={`last ${data.new_customers_window.window_days} days`}
        href="/admin/customers"
      />
      <MetricCard
        label="Outbound · 24h"
        value={data.outbound_24h.sent}
        secondary={`${data.outbound_24h.failed} failed / ${data.outbound_24h.queued} queued`}
      />
      <MetricCard
        label="QR engagement"
        value={`${data.qr_window.engagement_pct.toFixed(1)}%`}
        secondary={`${data.qr_window.scans} scans / ${data.qr_window.clicks} clicks · last ${data.qr_window.window_days} days`}
        href="/admin/qr"
      />
      {data.revenue_mtd && (
        <MetricCard
          label="Revenue (MTD)"
          value={`${data.revenue_mtd.currency} ${data.revenue_mtd.amount}`}
          secondary="month to date"
          href="/admin/payments"
        />
      )}
      {data.refunds_mtd && (
        <MetricCard
          label="Refunds (MTD)"
          value={`${data.refunds_mtd.currency} ${data.refunds_mtd.amount}`}
          secondary="month to date"
          href="/admin/payments?kind=refund"
        />
      )}
    </div>
  );
}

function formatMoney(amountCents: number, currency: string): string {
  // Spec-driven format: e.g. `CA$ 12,450`. We render dollars (no cents)
  // since the dashboard headline is a glance-level read; the bookings
  // detail page is where line-item precision lives.
  const dollars = Math.round(amountCents / 100);
  const prefix = currency === "CAD" ? "CA$" : currency;
  return `${prefix} ${dollars.toLocaleString("en-CA")}`;
}

export default BusinessDashboardStrip;
