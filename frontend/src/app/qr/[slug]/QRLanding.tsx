"use client";

// Client island for the public QR landing page. The server component
// already SSR'd the action list — this component only:
//   1. Records the `scan` event once on first mount.
//   2. Records `click` events via navigator.sendBeacon and follows the
//      target URL immediately (the redirect must never wait on the
//      network call).
//   3. Applies the optional brand.accent via an inline CSS variable
//      override so the SSR'd page picks the store's color, not the
//      design system default.

import { useEffect, useRef } from "react";

import { Icon } from "@/components/pd-ui";
import type { QRAction, QRPublicPayload } from "@/lib/api";

const KIND_LABELS_ZH: Record<string, string> = {
  review: "去 Google 评价",
  instagram: "关注 Instagram",
  tiktok: "关注 TikTok",
  rednote: "关注小红书",
  wechat: "添加微信",
  wifi: "连接 WiFi",
};

function localisedLabel(action: QRAction, lang: string): string {
  // The default labels are written for an English audience. For Chinese
  // browsers we swap the built-in `kind`s; custom labels are rendered
  // as-typed by the store admin.
  if (lang === "zh" && action.kind !== "custom") {
    return KIND_LABELS_ZH[action.kind] ?? action.label;
  }
  return action.label;
}

function detectLang(): string {
  if (typeof navigator === "undefined") return "en";
  const tag = navigator.language?.toLowerCase() ?? "";
  return tag.startsWith("zh") ? "zh" : "en";
}

function trackEvent(body: { slug: string; kind: "scan" | "click"; action_id?: number }) {
  // Fire-and-forget: sendBeacon survives page navigation, so a click chip
  // tap can immediately follow up with window.location = target.
  if (typeof navigator === "undefined" || !navigator.sendBeacon) {
    // Fallback for SSR / very old browsers — fire a no-keepalive fetch.
    fetch("/api/qr/event/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => {});
    return;
  }
  const blob = new Blob([JSON.stringify(body)], { type: "application/json" });
  navigator.sendBeacon("/api/qr/event/", blob);
}

export default function QRLanding({ payload }: { payload: QRPublicPayload }) {
  const { store, actions } = payload;
  const scanFiredRef = useRef(false);
  const lang = typeof window !== "undefined" ? detectLang() : "en";

  useEffect(() => {
    if (scanFiredRef.current) return;
    scanFiredRef.current = true;
    trackEvent({ slug: store.slug, kind: "scan" });
  }, [store.slug]);

  function onChipClick(e: React.MouseEvent<HTMLAnchorElement>, action: QRAction) {
    // Let the browser do its normal navigation, but fire the analytics
    // beacon before that takes effect.
    e.preventDefault();
    trackEvent({ slug: store.slug, kind: "click", action_id: action.id });
    window.location.href = action.target_url;
  }

  // Optional brand accent override (oklch string from Store.brand).
  const styleOverride: React.CSSProperties | undefined = store.brand.accent
    ? ({ "--accent": String(store.brand.accent) } as React.CSSProperties)
    : undefined;

  return (
    <div className="pd-qr-public" style={styleOverride}>
      <div className="pd-qr-card">
        <div className="pd-qr-brand">
          {store.brand.logo_url ? (
            // Plain <img> on purpose — we don't know the asset's host or
            // whether it's safe to send through next/image's optimizer.
            // eslint-disable-next-line @next/next/no-img-element
            <img className="pd-qr-logo" src={String(store.brand.logo_url)} alt="" />
          ) : (
            <span className="pd-brand-mark" aria-hidden>
              <Icon.logo size={28} />
            </span>
          )}
          <div className="pd-qr-store-name">{store.name}</div>
          <div className="pd-qr-store-sub">
            {lang === "zh" ? "感谢您的到访 · 请选择一个" : "Thanks for visiting · pick one"}
          </div>
        </div>

        <div className="pd-qr-actions">
          {actions.length === 0 && (
            <div className="pd-empty">
              {lang === "zh" ? "暂无可用操作。" : "No actions configured yet."}
            </div>
          )}
          {actions.map((a) => (
            <a
              key={a.id}
              className="pd-qr-action"
              href={a.target_url}
              onClick={(e) => onChipClick(e, a)}
            >
              <span className="pd-qr-action-label">{localisedLabel(a, lang)}</span>
              {a.reward_points > 0 && (
                <span className="pd-qr-action-points pd-mono">+{a.reward_points} pts</span>
              )}
            </a>
          ))}
        </div>

        <div className="pd-qr-foot">
          {lang === "zh" ? "由 PlayDesk 提供支持" : "Powered by PlayDesk"}
        </div>
      </div>
    </div>
  );
}
