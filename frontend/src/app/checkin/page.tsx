"use client";

// Customer-facing check-in entry point. Renders a scannable QR that
// points at the default store's One-QR landing (/qr/<slug>) using the
// browser's current origin, so a phone on the same network can scan it
// straight from the page. Staff can also pin this tab on a tablet at
// the desk as a low-friction "scan to start" surface — distinct from
// /admin/settings/checkin/display, which is staff-only and rotates.

import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

interface State {
  status: "loading" | "ready" | "error";
  slug: string | null;
  targetUrl: string | null;
  message: string | null;
}

const INITIAL_STATE: State = {
  status: "loading",
  slug: null,
  targetUrl: null,
  message: null,
};

export default function CheckinPage() {
  const [state, setState] = useState<State>(INITIAL_STATE);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/public/default-store/", { cache: "no-store" });
        if (cancelled) return;
        if (!resp.ok) {
          setState({
            status: "error",
            slug: null,
            targetUrl: null,
            message: "Couldn't reach the backend. Refresh to try again.",
          });
          return;
        }
        const body = (await resp.json()) as { slug: string };
        const targetUrl = `${window.location.origin}/qr/${body.slug}`;
        setState({ status: "ready", slug: body.slug, targetUrl, message: null });
      } catch {
        if (cancelled) return;
        setState({
          status: "error",
          slug: null,
          targetUrl: null,
          message: "Couldn't reach the backend. Refresh to try again.",
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (state.status !== "ready" || !state.targetUrl || !canvasRef.current) return;
    QRCode.toCanvas(canvasRef.current, state.targetUrl, {
      width: 384,
      margin: 2,
      errorCorrectionLevel: "M",
    }).catch(() => {
      // Best-effort — the link below is still tappable on the same device.
    });
  }, [state]);

  return (
    <main
      className="pd-page"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 16,
        padding: "48px 24px",
        textAlign: "center",
      }}
    >
      <div className="pd-eyebrow">Check in</div>
      <h1 className="pd-page-title">Scan to check in</h1>
      <p className="pd-page-sub" style={{ maxWidth: 520 }}>
        Point your phone camera at the QR below. You&apos;ll land on the
        store hub where you can confirm your booking, browse rewards, or
        ask the AI front desk for help.
      </p>

      {state.status === "loading" && <div className="pd-empty">Loading…</div>}

      {state.status === "error" && (
        <div className="pd-error" role="alert">
          <span className="pd-error-dot" />
          {state.message}
        </div>
      )}

      {state.status === "ready" && state.targetUrl && (
        <>
          <canvas
            ref={canvasRef}
            data-testid="checkin-qr-canvas"
            style={{ width: 320, height: 320, marginTop: 8 }}
          />
          <a
            href={state.targetUrl}
            className="pd-btn pd-btn--ghost pd-btn--sm"
            data-testid="checkin-qr-link"
            style={{ marginTop: 4 }}
          >
            Or tap to open on this device →
          </a>
        </>
      )}
    </main>
  );
}
