"use client";

// Fullscreen door-QR display (v11a). Designed for a tablet at the door:
// no chrome, just a big QR + caption + countdown to the next rotation.
// Auto-refreshes the key every `rotation_minutes / 2` seconds.

import { useCallback, useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

import { adminFetch } from "@/lib/admin-fetch";
import { useCurrentStore } from "@/lib/store-context";

interface ActiveKey {
  key: string;
  created_at: string;
  expires_at: string;
  rotation_minutes: number;
  qr_url: string;
}

function secondsUntil(iso: string): number {
  const end = new Date(iso).getTime();
  return Math.max(0, Math.round((end - Date.now()) / 1000));
}

export default function CheckinDisplayPage() {
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;
  const [data, setData] = useState<ActiveKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const load = useCallback(() => {
    adminFetch<ActiveKey>("/api/admin/checkin/active-key/")
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch(() => setError("Couldn't load the QR. Staff: please log in to refresh."));
  }, []);

  useEffect(() => {
    load();
  }, [load, storeSlug]);

  // Refresh interval is rotation_minutes / 2 (in seconds → ms),
  // capped at 30s minimum so a 1-min rotation still polls sanely.
  useEffect(() => {
    if (!data) return;
    const intervalMs = Math.max(30, (data.rotation_minutes * 60) / 2) * 1000;
    const t = window.setInterval(load, intervalMs);
    return () => window.clearInterval(t);
  }, [data, load]);

  // Per-second countdown.
  useEffect(() => {
    if (!data) return;
    setCountdown(secondsUntil(data.expires_at));
    const t = window.setInterval(() => setCountdown(secondsUntil(data.expires_at)), 1000);
    return () => window.clearInterval(t);
  }, [data]);

  // Render the QR onto the canvas whenever the URL changes.
  useEffect(() => {
    if (!data || !canvasRef.current) return;
    QRCode.toCanvas(canvasRef.current, data.qr_url, {
      width: 512,
      margin: 2,
      errorCorrectionLevel: "M",
    }).catch(() => {
      // Best-effort; if rendering fails the user still has the caption.
    });
  }, [data]);

  if (error) {
    return (
      <main className="pd-checkin-display-error" data-testid="display-error">
        <p>{error}</p>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="pd-checkin-display-loading">
        <p>Loading…</p>
      </main>
    );
  }

  return (
    <main
      className="pd-checkin-display"
      data-testid="checkin-display"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        padding: "24px",
        background: "#fff",
        textAlign: "center",
      }}
    >
      <canvas
        ref={canvasRef}
        data-testid="display-canvas"
        style={{ width: "min(80vmin, 640px)", height: "min(80vmin, 640px)" }}
      />
      <h2 style={{ marginTop: 32, fontSize: "2rem" }}>Scan to check in</h2>
      <p style={{ color: "#666", marginTop: 8 }} data-testid="display-countdown">
        Refreshes in {Math.floor(countdown / 60)}m {countdown % 60}s
      </p>
    </main>
  );
}
