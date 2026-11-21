import Image, { type StaticImageData } from "next/image";
import Link from "next/link";
import { Button } from "./button";
import { BOOKING_URL } from "./app-links";
import { CountUp } from "./count-up";
import { Wordmark } from "./logo";
import {
  COPY,
  LOCALES,
  SCHOLARSHIPS,
  type Locale,
  localePath,
  localeUrl,
  localizedAppLinks,
} from "./i18n";
import board from "../../public/screens/board.png";
import documents from "../../public/screens/documents.png";
import messages from "../../public/screens/messages.png";
import programmes from "../../public/screens/programmes.png";

/* ------------------------------------------------------------------ */
/* Big numbers: counted once as they scroll in. */
export function Stats({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale];
  return (
    <section aria-label="Elmify in numbers" className="border-b border-border bg-brand-soft py-14">
      <div className="mx-auto max-w-6xl px-5">
        <dl className="grid grid-cols-2 gap-y-10 md:grid-cols-4">
          {copy.stats.map((s) => (
            <div key={s.label} className="flex flex-col-reverse gap-1">
              <dt className="text-body02 text-foreground-secondary">{s.label}</dt>
              <dd className="text-[clamp(2.25rem,4.5vw,3.5rem)] font-bold leading-none tracking-tight text-brand-text">
                <CountUp value={s.value} suffix={s.suffix} />
              </dd>
            </div>
          ))}
        </dl>
        <div className="mt-12 border-t border-brand/15 pt-6">
          <p className="text-caption01 text-foreground-secondary">{copy.scholarshipsLabel}</p>
          <ul className="marquee mt-3 flex flex-wrap gap-2">
            {SCHOLARSHIPS.map((s) => (
              <li key={s.name}>
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex rounded-full border border-border bg-surface px-3.5 py-1.5 text-body02 font-medium text-foreground transition-colors hover:border-brand hover:text-brand-text"
                >
                  {s.name}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* How it works: a real sequence, so it is numbered and drawn as one line. */
const STEP_ICONS = [
  // a person
  "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0",
  // a target
  "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-4a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0-4a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z",
  // a document
  "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  // a pointer clicking
  "M9 3v10l3-3 2 5 2-1-2-5h4zM4 8h2M5 4l1.5 1.5M8 1v2",
];

export function HowItWorks({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].how;
  return (
    <section id="how" className="scroll-mt-20 py-24 md:py-28">
      <div className="mx-auto max-w-6xl px-5">
        <h2 className="text-heading01 font-bold">{copy.h2}</h2>
        <ol className="relative mt-14 grid gap-10 md:grid-cols-4 md:gap-8">
          <span
            aria-hidden
            className="pipeline-line absolute left-7 right-7 top-7 hidden h-0.5 bg-brand md:block"
          />
          {copy.stages.map((s, i) => (
            <li key={s.title} className="step-in relative" style={{ animationDelay: `${i * 120}ms` }}>
              <span className="relative grid size-14 place-items-center rounded-2xl bg-brand text-on-brand ring-8 ring-background">
                <svg viewBox="0 0 24 24" className="size-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d={STEP_ICONS[i]} />
                </svg>
                <span className="absolute -right-2 -top-2 grid size-6 place-items-center rounded-full bg-foreground text-caption01 font-bold text-background">
                  {i + 1}
                </span>
              </span>
              <h3 className="mt-6 text-heading02 font-semibold">{s.title}</h3>
              <p className="mt-1.5 text-body01 text-foreground-secondary">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* The browser extension, shown working rather than described. */
export function Extension({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].extensionPreview;
  return (
    <section className="bg-brand-soft py-24 md:py-28">
      <div className="mx-auto max-w-6xl px-5">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.6fr)] lg:items-center">
          <div>
            <h2 className="text-heading01 font-bold">{copy.h2}</h2>
            <p className="mt-4 text-body01 text-foreground-secondary">{copy.body}</p>
            <ul className="mt-8 grid gap-3">
              {copy.points.map((p) => (
                <li key={p} className="flex items-center gap-3 text-body01 font-medium">
                  <span className="grid size-6 shrink-0 place-items-center rounded-full bg-brand text-on-brand" aria-hidden>
                    <svg viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />
                    </svg>
                  </span>
                  {p}
                </li>
              ))}
            </ul>
          </div>
          <div className="overflow-hidden rounded-2xl border border-border bg-slate-900 shadow-[0_30px_70px_-30px_rgba(15,23,42,0.45)]">
            <video
              key="tumonline-portal-demo"
              className="block h-auto w-full"
              autoPlay
              loop
              muted
              playsInline
              poster="/screens/extension-poster.png?v=tumonline"
              aria-label={copy.h2}
            >
              <source src="/screens/extension-demo.webm?v=tumonline" type="video/webm" />
              <source src="/screens/extension-demo.mp4?v=tumonline" type="video/mp4" />
            </video>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Product: a bento of real screens, one cell per feature. */
/** `zoom` crops a wide screen to its top-left corner so small cells stay readable. */
type CellLayout = {
  shot: StaticImageData;
  className: string;
  tint?: boolean;
  zoom?: string;
  minHeight?: string;
};

const cellLayouts: readonly CellLayout[] = [
  {
    shot: programmes,
    className: "md:col-span-2 md:row-span-2",
    tint: true,
  },
  {
    shot: board,
    className: "",
    zoom: "w-[230%]",
  },
  {
    shot: documents,
    className: "",
    zoom: "w-[190%]",
  },
  {
    shot: messages,
    className: "md:col-span-3",
    tint: true,
    minHeight: "min-h-80 md:min-h-[34rem]",
  },
];

export function Product({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].product;

  return (
    <section id="product" className="scroll-mt-20 bg-background-secondary py-24 md:py-28">
      <div className="mx-auto max-w-6xl px-5">
        <h2 className="max-w-2xl text-heading01 font-bold">{copy.h2}</h2>

        <div className="mt-14 grid gap-4 md:grid-cols-3 md:gap-5">
          {copy.cells.map((c, idx) => {
            const layout = cellLayouts[idx]!;
            return (
              <article
                key={c.title}
                className={[
                  "flex flex-col overflow-hidden rounded-3xl border border-border",
                  layout.tint ? "bg-brand-soft" : "bg-surface",
                  layout.className,
                ].join(" ")}
              >
                <div className="p-6 pb-5 md:p-7 md:pb-5">
                  <h3 className="text-heading02 font-semibold">{c.title}</h3>
                </div>
                <div
                  className={[
                    "relative mt-auto flex-1 overflow-hidden pl-6 md:pl-7",
                    layout.minHeight ?? "min-h-56",
                  ].join(" ")}
                >
                  <Image
                    src={layout.shot}
                    alt={c.alt}
                    className={[
                      "absolute left-6 top-0 max-w-none rounded-tl-xl border-l border-t border-border md:left-7",
                      layout.zoom ?? "w-[calc(100%-1.5rem)] md:w-[calc(100%-1.75rem)]",
                    ].join(" ")}
                    sizes="(min-width: 768px) 1200px, 100vw"
                    unoptimized
                    loading="eager"
                  />
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
export const faqs: ReadonlyArray<readonly [string, string]> = COPY.en.faq.items;

export function Faq({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].faq;

  return (
    <section id="faq" className="scroll-mt-20 border-t border-border py-24 md:py-28">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 md:grid-cols-[1fr_1.6fr] md:gap-16">
        <div>
          <h2 className="text-heading01 font-bold">{copy.h2}</h2>
        </div>
        <div className="divide-y divide-border border-y border-border">
          {copy.items.map(([q, a]) => (
            <details key={q} className="faq group">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-6 py-5 text-heading03 font-semibold transition-colors duration-200 hover:text-brand-text">
                {q}
                <span
                  className="plus grid size-7 shrink-0 place-items-center rounded-full border border-border-strong text-foreground-secondary"
                  aria-hidden
                >
                  +
                </span>
              </summary>
              <div className="pb-6 pr-12 text-body01 text-foreground-secondary">{a}</div>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
export function Closing({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].closing;
  const app = localizedAppLinks(locale);

  return (
    <section id="start" className="scroll-mt-20 bg-brand-soft px-5 py-24">
      <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
        <h2 className="text-heading01 font-bold">{copy.h2}</h2>
        <p className="mt-4 max-w-xl text-body01 text-foreground-secondary">{copy.body}</p>
        <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
          <Button href={app.signup} size="lg">
            {copy.ctaPrimary}
          </Button>
          <Button href={app.login} variant="secondary" size="lg">
            {copy.ctaSecondary}
          </Button>
          {BOOKING_URL ? (
            <Button href={BOOKING_URL} variant="secondary" size="lg" external>
              {COPY[locale].booking.cta}
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
export function Footer({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].footer;
  const app = localizedAppLinks(locale);
  const links = [
    [copy.links.how, "#how"],
    [copy.links.faq, "#faq"],
    [copy.links.studentDemo, app.studentDemo],
    [copy.links.login, app.login],
    [copy.links.terms, app.terms],
    [copy.links.privacy, app.privacy],
  ] as const;

  return (
    <footer className="border-t border-border py-12">
      <div className="mx-auto flex max-w-6xl flex-col gap-8 px-5 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-4">
          <Wordmark className="h-6" />
          <span className="text-caption01 text-foreground-subtle">
            &copy; 2026{" "}
            <a href={localeUrl(locale)} rel="author" className="underline decoration-border underline-offset-2">
              Elmify
            </a>{" "}
            &middot; {copy.updatedLabel} <time dateTime="2026-11-01">{copy.updatedDateText}</time>
          </span>
          <span className="text-caption01 text-foreground-subtle">&middot;</span>
          <div className="inline-flex items-center gap-2 text-caption01 font-semibold">
            {LOCALES.map((loc) => (
              <Link
                key={loc}
                href={localePath(loc)}
                hrefLang={loc}
                lang={loc}
                aria-current={loc === locale ? "page" : undefined}
                className={
                  loc === locale
                    ? "text-foreground underline decoration-brand underline-offset-4"
                    : "text-foreground-secondary hover:text-foreground"
                }
              >
                {COPY[loc].langLabel}
              </Link>
            ))}
          </div>
        </div>
        <nav aria-label="Footer">
          <ul className="flex flex-wrap gap-x-6 gap-y-2 text-body02 text-foreground-secondary">
            {links.map(([label, href]) => (
              <li key={label}>
                <a href={href} className="transition-colors duration-200 hover:text-foreground">
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </footer>
  );
}
