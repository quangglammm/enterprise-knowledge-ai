import type { Metadata } from "next";
import { Be_Vietnam_Pro } from "next/font/google";
import Link from "next/link";

import { IdentityBar } from "@/components/IdentityBar";
import { IdentityProvider } from "@/components/IdentityProvider";

import "./globals.css";

// Designed for Vietnamese and Latin alike, so diacritics render as intended.
const beVietnam = Be_Vietnam_Pro({
  variable: "--font-be-vietnam",
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "700"],
});

export const metadata: Metadata = {
  title: "Bamboo Harbor Knowledge",
  description: "Ask company documents, and compare direct answers with the planned workflow.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${beVietnam.variable} h-full`}>
      <body className="min-h-full font-sans">
        <IdentityProvider>
          <header className="relative mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-5">
            <nav className="flex items-baseline gap-6">
              <Link href="/" className="text-lg font-bold tracking-tight">
                Bamboo Harbor Knowledge
              </Link>
              <Link href="/" className="text-ink-soft hover:text-ink">
                Ask
              </Link>
              <Link href="/documents" className="text-ink-soft hover:text-ink">
                Documents
              </Link>
            </nav>
            <IdentityBar />
          </header>
          <main className="mx-auto max-w-6xl px-6 pb-16">{children}</main>
        </IdentityProvider>
      </body>
    </html>
  );
}
