import Link from "next/link";
import { Button } from "./button";
import { Wordmark } from "./logo";
import { COPY, LOCALES, type Locale, localePath, localizedAppLinks } from "./i18n";

export function Nav({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].nav;
  const links = [
    { href: "#how", label: copy.how },
    { href: "#product", label: copy.product },
    { href: "#agencies", label: copy.agencies },
    { href: "#faq", label: copy.faq },
  ];
  const app = localizedAppLinks(locale);

  return (
    <header className="sticky top-0 z-40 border-b border-border/80 bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-2 px-3.5 sm:gap-4 sm:px-5">
        <Link href={localePath(locale)} aria-label={copy.homeAria} className="shrink-0 text-foreground">
          <Wordmark className="h-6 sm:h-7" />
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-8 md:flex">
          {links.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="text-body02 text-foreground-secondary transition-colors duration-200 hover:text-foreground"
            >
              {l.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-2 sm:gap-4">
          <nav
            aria-label={copy.langAria}
            className="inline-flex items-center rounded-full border border-border bg-background-secondary p-0.5 text-caption01 font-semibold"
          >
            {LOCALES.map((loc) => {
              const active = loc === locale;
              return (
                <Link
                  key={loc}
                  href={localePath(loc)}
                  hrefLang={loc}
                  lang={loc}
                  aria-current={active ? "page" : undefined}
                  className={[
                    "rounded-full px-2 py-0.5 transition-colors duration-150 sm:px-2.5 sm:py-1",
                    active
                      ? "bg-surface text-foreground shadow-xs"
                      : "text-foreground-secondary hover:text-foreground",
                  ].join(" ")}
                >
                  {COPY[loc].langLabel}
                </Link>
              );
            })}
          </nav>
          <a
            href={app.login}
            className="hidden text-body02 font-medium text-foreground transition-colors duration-200 hover:text-brand-text sm:inline"
          >
            {copy.login}
          </a>
          <Button href={app.signup}>{copy.signup}</Button>
        </div>
      </div>
      <nav
        aria-label="Mobile sections"
        className="mx-auto flex max-w-6xl items-center gap-5 overflow-x-auto border-t border-border/60 px-5 py-2 md:hidden"
      >
        {links.map((l) => (
          <a
            key={l.href}
            href={l.href}
            className="whitespace-nowrap text-caption01 font-medium text-foreground-secondary transition-colors duration-200 hover:text-foreground"
          >
            {l.label}
          </a>
        ))}
      </nav>
    </header>
  );
}
