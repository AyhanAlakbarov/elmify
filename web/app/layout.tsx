import type { Metadata, Viewport } from "next";
import { buildLocaleMetadata } from "./_components/landing-page";
import "./globals.css";

export const metadata: Metadata = buildLocaleMetadata("en");

export const viewport: Viewport = {
  themeColor: "#ffffff",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
