import type { Metadata } from "next";
import { Inter, Newsreader, Space_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import "./playdesk.css";
import Nav from "@/components/Nav";

// Font families the PlayDesk design system references via CSS variables
// (see playdesk.css: --font-body / --font-display / --font-display-serif /
// --font-mono). The Newsreader serif is reserved for the largest hero
// titles only (.pd-page-title + .pd-confirmed-title) — Phase 2 editorial
// pivot. Body and display sans stay Inter + Space Grotesk respectively.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const newsreader = Newsreader({
  subsets: ["latin"],
  variable: "--font-newsreader",
  style: ["normal", "italic"],
  weight: ["400", "500", "600", "700"],
});
const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: "PlayDesk — Game Lounge Booking",
  description: "AI-powered booking platform for game lounges",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${inter.variable} ${newsreader.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}
      >
        <Nav />
        <main className="pd-main">{children}</main>
      </body>
    </html>
  );
}
