import { notFound } from "next/navigation";
import type { Metadata } from "next";
import type { Locale } from "../_components/i18n";
import {
  LandingPage,
  LocaleHtmlShell,
  buildLocaleMetadata,
} from "../_components/landing-page";

const SUPPORTED_SUBPATH_LOCALES: readonly Locale[] = ["az", "ru"] as const;

export function generateStaticParams() {
  return SUPPORTED_SUBPATH_LOCALES.map((locale) => ({ locale }));
}

function resolveLocale(raw: string): Locale {
  if (raw === "az" || raw === "ru") {
    return raw;
  }
  notFound();
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale: raw } = await params;
  const locale = resolveLocale(raw);
  return buildLocaleMetadata(locale);
}

export default async function LocalizedHomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale: raw } = await params;
  const locale = resolveLocale(raw);
  return (
    <LocaleHtmlShell locale={locale}>
      <LandingPage locale={locale} />
    </LocaleHtmlShell>
  );
}
