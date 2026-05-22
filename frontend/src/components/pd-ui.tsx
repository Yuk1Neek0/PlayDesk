// Shared UI primitives for the PlayDesk pages — icons, formatting helpers,
// badges, and the resource-art placeholder. Ported from the Claude Design
// handoff (playdeck/project/src/ui.jsx).

import type { ReactNode } from "react";
import type {
  BookingSource,
  BookingStatus,
  ResourceType,
} from "@/lib/pd-data";

// ── Labels ──────────────────────────────────────────────────────────────

export const RESOURCE_TYPE_LABEL: Record<ResourceType, string> = {
  console: "Console",
  room: "Private Room",
  table: "Board‑game Table",
};

const STATUS_LABEL: Record<BookingStatus, string> = {
  pending: "Pending",
  pending_payment: "Pending payment",
  confirmed: "Confirmed",
  cancelled: "Cancelled",
};

// ── Date / time helpers ─────────────────────────────────────────────────

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDate(
  iso: string,
  opts: Intl.DateTimeFormatOptions = { weekday: "short", day: "2-digit", month: "short" },
): string {
  return new Date(iso).toLocaleDateString("en-GB", opts);
}

export function fmtFullDate(d: Date): string {
  return d.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
}

export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function relTime(iso: string): string {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Icons (inline SVG) ──────────────────────────────────────────────────

interface IconProps {
  size?: number;
}

function ControllerIcon({ size = 18 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 8h12a4 4 0 0 1 4 4v3a3 3 0 0 1-5.4 1.8l-1.6-2.1H9l-1.6 2.1A3 3 0 0 1 2 15v-3a4 4 0 0 1 4-4Z" />
      <path d="M8 11v3M6.5 12.5h3" />
      <circle cx="16" cy="12.5" r=".8" fill="currentColor" />
      <circle cx="18" cy="14" r=".8" fill="currentColor" />
    </svg>
  );
}

function RoomIcon({ size = 18 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M3 11 12 4l9 7v9H3z" />
      <path d="M9 20v-6h6v6" />
    </svg>
  );
}

function TableIcon({ size = 18 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <ellipse cx="12" cy="9" rx="9" ry="4" />
      <path d="M3 9v3c0 2.2 4 4 9 4s9-1.8 9-4V9M7 13v6M17 13v6" />
    </svg>
  );
}

function SendIcon({ size = 18 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 12 21 4l-4 17-5-7-8-2Z" />
    </svg>
  );
}

function SparkIcon({ size = 18 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8" />
    </svg>
  );
}

function CheckIcon({ size = 14 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="m4 12 5 5 11-12" />
    </svg>
  );
}

function SearchIcon({ size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

function LogoIcon({ size = 22 }: IconProps) {
  return (
    <svg viewBox="0 0 28 28" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="22" height="22" rx="6" />
      <path d="M9 14h10M14 9v10" />
    </svg>
  );
}

export const Icon = {
  controller: ControllerIcon,
  room: RoomIcon,
  table: TableIcon,
  send: SendIcon,
  spark: SparkIcon,
  check: CheckIcon,
  search: SearchIcon,
  logo: LogoIcon,
};

export function ResourceIcon({
  type,
  size = 18,
}: {
  type?: ResourceType;
  size?: number;
}) {
  if (type === "console") return <ControllerIcon size={size} />;
  if (type === "room") return <RoomIcon size={size} />;
  return <TableIcon size={size} />;
}

// Stylized stripe placeholder with a faint icon — stands in for product art.
export function ResourceArt({ type }: { type: ResourceType }) {
  const grad =
    type === "room"
      ? "linear-gradient(135deg, rgba(120,180,255,.08), rgba(180,90,255,.06))"
      : type === "table"
        ? "linear-gradient(135deg, rgba(200,160,90,.08), rgba(120,220,160,.06))"
        : "linear-gradient(135deg, rgba(80,200,255,.08), rgba(180,90,255,.05))";
  return (
    <div className="pd-art" style={{ background: grad }}>
      <div className="pd-art-stripes" />
      <div className="pd-art-icon" style={{ color: "var(--accent)" }}>
        <ResourceIcon type={type} size={36} />
      </div>
      <div className="pd-art-label">{type}</div>
    </div>
  );
}

// ── Badges ──────────────────────────────────────────────────────────────

type BadgeTone = "ok" | "warn" | "info" | "accent" | "muted" | "neutral";

export function Badge({
  tone = "neutral",
  children,
  dot = false,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  dot?: boolean;
}) {
  return (
    <span className={`pd-badge pd-badge--${tone}`}>
      {dot && <span className="pd-badge-dot" />}
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: BookingStatus }) {
  const tone: BadgeTone =
    status === "confirmed"
      ? "ok"
      : status === "pending"
        ? "warn"
        : status === "pending_payment"
          ? "info"
          : "muted";
  return (
    <Badge tone={tone} dot>
      {STATUS_LABEL[status]}
    </Badge>
  );
}

export function SourceBadge({ source }: { source: BookingSource }) {
  return source === "agent" ? (
    <Badge tone="accent">AI agent</Badge>
  ) : (
    <Badge tone="neutral">Manual</Badge>
  );
}
