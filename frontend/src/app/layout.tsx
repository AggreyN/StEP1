import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";
import "./globals.css";
import { metaPolicy } from "../../security-headers.mjs";

// Self-hosted at build time by next/font, so no request leaves for a font CDN.
const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});
const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"],
  weight: ["400", "600"],
  style: ["normal", "italic"],
  display: "swap",
});
const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "StEP1", template: "%s · StEP1" },
  description:
    "StEP1 finds internships worth applying to and remembers what happened after you applied.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f1e6" },
    { media: "(prefers-color-scheme: dark)", color: "#17110d" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${sourceSerif.variable} ${plexMono.variable} h-full antialiased`}
    >
      <head>
        {/* The Content-Security-Policy, with the exact origins this build was
            configured with. The host sends a broader copy as a header; the
            browser enforces both. See security-headers.mjs. */}
        <meta httpEquiv="Content-Security-Policy" content={metaPolicy(process.env)} />
      </head>
      <body className="flex min-h-full flex-col text-[15px] leading-normal">{children}</body>
    </html>
  );
}
