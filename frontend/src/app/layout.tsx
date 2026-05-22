import type { Metadata } from "next";
import { Inter, Space_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import "./playdesk.css";
import { AuthProvider } from "@/lib/auth";
import Nav from "@/components/Nav";

// Font families the PlayDesk design system references via CSS variables
// (see playdesk.css: --font-body / --font-display / --font-mono).
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
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
        className={`${inter.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}
      >
        <AuthProvider>
          <Nav />
          <main className="pd-main">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
