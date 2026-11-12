import Image, { type StaticImageData } from "next/image";
import Link from "next/link";
import { Button } from "./button";
import { Wordmark } from "./logo";
import {
  COPY,
  LOCALES,
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
/* How the AI works: a real sequence, so it is drawn as one connected line. */
export function HowItWorks({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].how;
  const ext = copy.extensionPreview;

  return (
    <section id="how" className="scroll-mt-20 py-24 md:py-28">
      <div className="mx-auto max-w-6xl px-5">
        <h2 className="max-w-2xl text-heading01 font-bold">{copy.h2}</h2>
        <p className="mt-4 max-w-2xl text-body01 text-foreground-secondary">{copy.intro}</p>

        <ol className="relative mt-16 grid gap-10 md:grid-cols-4 md:gap-8">
          <span
            aria-hidden
            className="pipeline-line absolute left-0 right-0 top-[15px] hidden h-px bg-brand md:block"
          />
          {copy.stages.map((s, i) => (
            <li key={s.title} className="relative">
              <span className="relative grid size-8 place-items-center rounded-full bg-brand text-caption01 font-semibold text-on-brand ring-8 ring-background">
                {i + 1}
              </span>
              <h3 className="mt-6 text-heading03 font-semibold">{s.title}</h3>
              <p className="mt-2 text-body02 text-foreground-secondary">{s.body}</p>
            </li>
          ))}
        </ol>

        <div id="about" className="mt-16 scroll-mt-24 rounded-3xl border border-border bg-surface p-6 md:p-8">
          <div className="flex flex-col gap-2 md:flex-row md:items-baseline md:justify-between">
            <h3 className="text-heading02 font-semibold">{copy.tableHeading}</h3>
            <p className="text-caption01 text-foreground-subtle">
              <cite className="not-italic">{copy.tableSub}</cite>
            </p>
          </div>
          <p className="mt-2 max-w-3xl text-body02 text-foreground-secondary">{copy.tableIntro}</p>
          <div className="mt-6 overflow-x-auto">
            <table className="w-full min-w-[42rem] border-collapse text-left text-body02">
              <thead>
                <tr className="border-b border-border text-caption01 font-semibold text-foreground-secondary">
                  <th scope="col" className="py-3 pr-4">
                    {copy.tableHeaders[0]}
                  </th>
                  <th scope="col" className="py-3 px-4">
                    {copy.tableHeaders[1]}
                  </th>
                  <th scope="col" className="py-3 px-4">
                    {copy.tableHeaders[2]}
                  </th>
                  <th scope="col" className="py-3 pl-4">
                    {copy.tableHeaders[3]}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {copy.rows.map((row) => (
                  <tr key={row.funder} className="align-top">
                    <th scope="row" className="py-3.5 pr-4 font-semibold text-foreground">
                      <a
                        href={row.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline decoration-border underline-offset-4 transition-colors hover:text-brand-text"
                      >
                        {row.funder}
                      </a>
                    </th>
                    <td className="py-3.5 px-4 text-foreground-secondary">{row.scope}</td>
                    <td className="py-3.5 px-4 text-foreground-secondary">{row.funding}</td>
                    <td className="py-3.5 pl-4 text-foreground-secondary">{row.rules}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-10 border-t border-border pt-8">
            <div className="flex flex-col gap-2 md:flex-row md:items-baseline md:justify-between">
              <h3 className="text-heading02 font-semibold">{copy.hiddenHeading}</h3>
              <p className="text-caption01 text-foreground-subtle">{copy.hiddenSub}</p>
            </div>
            <p className="mt-2 max-w-3xl text-body02 text-foreground-secondary">{copy.hiddenIntro}</p>
            <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {copy.hiddenLayers.map((layer) => (
                <article
                  key={layer.title}
                  className="flex flex-col justify-between rounded-2xl border border-border bg-background-secondary p-5"
                >
                  <div>
                    <span className="inline-flex items-center rounded-full border border-border bg-surface px-2.5 py-0.5 text-caption01 font-semibold text-brand-text">
                      {layer.badge}
                    </span>
                    <h4 className="mt-3 text-heading03 font-semibold text-foreground">{layer.title}</h4>
                    <p className="mt-2 text-body02 text-foreground-secondary">{layer.examples}</p>
                  </div>
                  <p className="mt-4 border-t border-border pt-3 text-caption01 text-foreground-subtle">
                    {layer.howFound}
                  </p>
                </article>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-10 rounded-3xl border border-border bg-brand-soft p-6 md:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="inline-flex items-center rounded-full border border-border bg-surface px-3 py-1 text-caption01 font-semibold text-brand-text">
              {ext.badge}
            </span>
            <span className="text-caption01 font-semibold text-brand-text">
              {ext.sidePanelStatus}
            </span>
          </div>
          <h3 className="mt-3 text-heading02 font-semibold text-foreground">{ext.heading}</h3>
          <p className="mt-2 max-w-3xl text-body02 text-foreground-secondary">{ext.sub}</p>

          <div className="mt-6 overflow-hidden rounded-2xl border border-border bg-slate-900 shadow-lg">
            <video
              key="tumonline-portal-demo"
              className="block h-auto w-full"
              autoPlay
              loop
              muted
              playsInline
              poster="/screens/extension-poster.png?v=tumonline"
              aria-label={ext.heading}
            >
              <source src="/screens/extension-demo.webm?v=tumonline" type="video/webm" />
              <source src="/screens/extension-demo.mp4?v=tumonline" type="video/mp4" />
            </video>
          </div>

          <ul className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {ext.sidePanelItems.map((item) => (
              <li
                key={item}
                className="flex items-start gap-2.5 rounded-xl border border-border bg-surface p-3.5 text-caption01 text-foreground-secondary shadow-2xs"
              >
                <span
                  aria-hidden
                  className="mt-1 inline-block size-2 shrink-0 rounded-full bg-brand"
                />
                <span>{item}</span>
              </li>
            ))}
          </ul>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-caption01 font-semibold text-foreground">
            <span>{ext.sidePanelNote}</span>
            <span className="text-brand-text">{ext.submitGuard}</span>
          </div>
        </div>

        <p className="mt-10 border-t border-border pt-6 text-body01 font-medium">{copy.closingNote}</p>
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
        <p className="mt-4 max-w-xl text-body01 text-foreground-secondary">{copy.intro}</p>

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
                  <h3 className="text-heading03 font-semibold">{c.title}</h3>
                  <p className="mt-1.5 max-w-md text-body02 text-foreground-secondary">{c.body}</p>
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
                    loading="lazy"
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
export function Agencies({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].agencies;
  const app = localizedAppLinks(locale);

  return (
    <section id="agencies" className="scroll-mt-20 py-24 md:py-28">
      <div className="mx-auto grid max-w-6xl gap-12 px-5 md:grid-cols-[1fr_1fr] md:gap-16">
        <div>
          <h2 className="text-heading01 font-bold">{copy.h2}</h2>
          <p className="mt-4 max-w-md text-body01 text-foreground-secondary">{copy.body}</p>
          <div className="mt-8">
            <Button href={app.agencyDemo} size="lg">
              {copy.cta}
            </Button>
          </div>
        </div>
        <dl className="divide-y divide-border self-center border-y border-border">
          {copy.points.map(([t, b]) => (
            <div key={t} className="grid gap-1 py-5 sm:grid-cols-[9rem_1fr] sm:gap-6">
              <dt className="text-heading03 font-semibold">{t}</dt>
              <dd className="text-body01 text-foreground-secondary">{b}</dd>
            </div>
          ))}
        </dl>
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
          <p className="mt-4 max-w-xs text-body01 text-foreground-secondary">{copy.intro}</p>
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
          <Button href={app.studentDemo} variant="secondary" size="lg">
            {copy.ctaStudentDemo}
          </Button>
          <Button href={app.login} variant="secondary" size="lg">
            {copy.ctaSecondary}
          </Button>
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
    [copy.links.about, "#about"],
    [copy.links.agencies, "#agencies"],
    [copy.links.studentDemo, app.studentDemo],
    [copy.links.demo, app.agencyDemo],
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
