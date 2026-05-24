"use client";

// Reusable dashboard metric card used by <BusinessDashboardStrip />.
// Intentionally small and presentational — no data fetching, no
// polling. The composite strip handles all of that and feeds these
// cards the pre-formatted values.
//
// Reuses the existing `pd-stat` / `pd-badge` design tokens from
// playdesk.css (no new CSS file per the task spec).

import Link from "next/link";

export interface MetricCardProps {
  label: string;
  value: string | number;
  href?: string;
  trendPct?: number | null;
  secondary?: string;
}

export function MetricCard({
  label,
  value,
  href,
  trendPct,
  secondary,
}: MetricCardProps) {
  const ariaLabel = `${label}: ${value}`;
  const body = (
    <div className="pd-stat" aria-label={ariaLabel}>
      <div className="pd-stat-label">{label}</div>
      <div className="pd-stat-value pd-mono">{value}</div>
      {trendPct !== undefined && trendPct !== null && (
        <TrendChip pct={trendPct} />
      )}
      {secondary && <div className="pd-stat-delta">{secondary}</div>}
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="pd-stat-link" aria-label={ariaLabel}>
        {body}
      </Link>
    );
  }
  return body;
}

function TrendChip({ pct }: { pct: number }) {
  const tone = pct > 0 ? "ok" : pct < 0 ? "warn" : "info";
  const sign = pct > 0 ? "+" : pct < 0 ? "" : "±";
  const text = `${sign}${pct.toFixed(1)}%`;
  return (
    <span
      className={`pd-badge pd-badge--${tone}`}
      data-testid="metric-trend-chip"
      data-trend={tone}
    >
      {text}
    </span>
  );
}

export default MetricCard;
