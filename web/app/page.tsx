import type { Metadata } from "next";
import {
  LandingPage,
  LocaleHtmlShell,
  buildLocaleMetadata,
} from "./_components/landing-page";

export const metadata: Metadata = buildLocaleMetadata("en");

export default function Home() {
  return (
    <LocaleHtmlShell locale="en">
      <LandingPage locale="en" />
    </LocaleHtmlShell>
  );
}
