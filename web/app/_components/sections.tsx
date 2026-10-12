import Image, { type StaticImageData } from "next/image";
import { Button } from "./button";
import { appLinks } from "./app-links";
import { Wordmark } from "./logo";
import board from "../../public/screens/board.png";
import documents from "../../public/screens/documents.png";
import messages from "../../public/screens/messages.png";
import programmes from "../../public/screens/programmes.png";

/* ------------------------------------------------------------------ */
/* How the AI works: a real sequence, so it is drawn as one connected line. */
const stages = [
  {
    title: "Reads the official pages",
    body: "It reads each university's and scholarship's own website and keeps the exact sentence behind every requirement, with a link.",
  },
  {
    title: "Matches them to you",
    body: "Your grades, languages, budget and plans are checked against each programme's rules. You see why something fits or does not.",
  },
  {
    title: "Prepares your documents",
    body: "Your CV and letters are written only from facts you confirmed. Nothing is used until you approve it.",
  },
];

export function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-20 py-24 md:py-28">
      <div className="mx-auto max-w-6xl px-5">
        <h2 className="max-w-2xl text-heading01 font-bold">What the AI does, and what you decide</h2>
        <p className="mt-4 max-w-xl text-body01 text-foreground-secondary">
          The slow part of applying is reading. Elmify does the reading and shows its sources.
        </p>

        <ol className="relative mt-16 grid gap-12 md:grid-cols-3 md:gap-10">
          <span
            aria-hidden
            className="pipeline-line absolute left-0 right-0 top-[15px] hidden h-px bg-brand md:block"
          />
          {stages.map((s, i) => (
            <li key={s.title} className="relative">
              <span className="relative grid size-8 place-items-center rounded-full bg-brand text-caption01 font-semibold text-on-brand ring-8 ring-background">
                {i + 1}
              </span>
              <h3 className="mt-6 text-heading02 font-semibold">{s.title}</h3>
              <p className="mt-2 max-w-[22rem] text-body01 text-foreground-secondary">{s.body}</p>
            </li>
          ))}
        </ol>

        <p className="mt-14 border-t border-border pt-6 text-body01 font-medium">
          You press submit. Elmify never applies anywhere without you.
        </p>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Product: a bento of real screens, one cell per feature. */
/** `zoom` crops a wide screen to its top-left corner so small cells stay readable. */
type Cell = { title: string; body: string; shot: StaticImageData; alt: string; className: string; tint?: boolean; zoom?: string };

const cells: Cell[] = [
  {
    title: "Programmes grouped by the money that pays",
    body: "Each scholarship with what it covers, when it closes and the programmes it funds.",
    shot: programmes,
    alt: "Programme match cards grouped under the scholarship that funds them",
    className: "md:col-span-2 md:row-span-2",
    tint: true,
  },
  {
    title: "One board for every application",
    body: "From To start to Decision, with deadlines that turn red early.",
    shot: board,
    alt: "The My applications board with columns for each stage",
    className: "",
    zoom: "w-[230%]",
  },
  {
    title: "Documents in one place",
    body: "Drop in your transcript or CV. See what each application still needs.",
    shot: documents,
    alt: "The documents page with an upload area and document cards",
    className: "",
    zoom: "w-[190%]",
  },
  {
    title: "Your counsellor, beside your applications",
    body: "If you work with an agency, messages sit next to the work, not in another app.",
    shot: messages,
    alt: "A conversation between a student and their counsellor",
    className: "md:col-span-3",
    tint: true,
  },
];

export function Product() {
  return (
    <section id="product" className="scroll-mt-20 bg-background-secondary py-24 md:py-28">
      <div className="mx-auto max-w-6xl px-5">
        <h2 className="max-w-2xl text-heading01 font-bold">Everything for your applications, in one place</h2>
        <p className="mt-4 max-w-xl text-body01 text-foreground-secondary">These are screens from the product itself.</p>

        <div className="mt-14 grid gap-4 md:grid-cols-3 md:gap-5">
          {cells.map((c) => (
            <article
              key={c.title}
              className={[
                "flex flex-col overflow-hidden rounded-3xl border border-border",
                c.tint ? "bg-brand-soft" : "bg-surface",
                c.className,
              ].join(" ")}
            >
              <div className="p-6 pb-5 md:p-7 md:pb-5">
                <h3 className="text-heading03 font-semibold">{c.title}</h3>
                <p className="mt-1.5 max-w-md text-body02 text-foreground-secondary">{c.body}</p>
              </div>
              <div className="relative mt-auto min-h-56 flex-1 overflow-hidden pl-6 md:pl-7">
                <Image
                  src={c.shot}
                  alt={c.alt}
                  className={[
                    "absolute left-6 top-0 max-w-none rounded-tl-xl border-l border-t border-border md:left-7",
                    c.zoom ?? "w-[calc(100%-1.5rem)] md:w-[calc(100%-1.75rem)]",
                  ].join(" ")}
                  sizes="(min-width: 768px) 720px, 100vw"
                  loading="lazy"
                />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
const agencyPoints = [
  ["Your address", "Students sign up and log in on your agency’s own web address."],
  ["Your team", "Assign each student to a counsellor and see who is waiting on whom."],
  ["Your leads", "Demo requests and new students arrive on one owner page."],
];

export function Agencies() {
  return (
    <section id="agencies" className="scroll-mt-20 py-24 md:py-28">
      <div className="mx-auto grid max-w-6xl gap-12 px-5 md:grid-cols-[1fr_1fr] md:gap-16">
        <div>
          <h2 className="text-heading01 font-bold">Run your agency on Elmify</h2>
          <p className="mt-4 max-w-md text-body01 text-foreground-secondary">
            The same product under your name. Counsellors work on each student&rsquo;s board, and students always
            know what is next.
          </p>
          <div className="mt-8">
            <Button href={appLinks.demo} size="lg">
              Book a demo
            </Button>
          </div>
        </div>
        <dl className="divide-y divide-border self-center border-y border-border">
          {agencyPoints.map(([t, b]) => (
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
const faqs = [
  [
    "Is it free?",
    "Creating an account and getting your matches is free during early access. We will tell you before anything costs money.",
  ],
  [
    "Which countries and programmes do you cover?",
    "We start with master’s programmes in Europe and the scholarships open to students from Central and South Asia. The list grows as we add funders.",
  ],
  [
    "Does the AI make things up?",
    "Every requirement links to the official page it was read from, and your documents use only facts you confirmed. If the AI is unsure, it says so instead of guessing.",
  ],
  [
    "Do you submit applications for me?",
    "No. You stay in your own browser and press submit yourself. Elmify prepares the answers and documents and tracks what is left.",
  ],
  [
    "What happens to my data?",
    "It is used to find programmes for you and nothing else. You can delete your account from Settings at any time.",
  ],
];

export function Faq() {
  return (
    <section id="faq" className="scroll-mt-20 border-t border-border py-24 md:py-28">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 md:grid-cols-[1fr_1.6fr] md:gap-16">
        <div>
          <h2 className="text-heading01 font-bold">Questions</h2>
          <p className="mt-4 max-w-xs text-body01 text-foreground-secondary">
            Anything else? Ask us during a demo.
          </p>
        </div>
        <div className="divide-y divide-border border-y border-border">
          {faqs.map(([q, a]) => (
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
export function Closing() {
  return (
    <section id="start" className="scroll-mt-20 bg-brand-soft px-5 py-24">
      <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
        <h2 className="text-heading01 font-bold">Your profile takes ten minutes</h2>
        <p className="mt-4 max-w-xl text-body01 text-foreground-secondary">
          Your first matches are ready as soon as you finish.
        </p>
        <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
          <Button href={appLinks.signup} size="lg">
            Sign up free
          </Button>
          <Button href={appLinks.login} variant="secondary" size="lg">
            Log in
          </Button>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
export function Footer() {
  const links = [
    ["How it works", "#how"],
    ["For agencies", "#agencies"],
    ["Book a demo", appLinks.demo],
    ["Log in", appLinks.login],
    ["Terms", appLinks.terms],
    ["Privacy", appLinks.privacy],
  ] as const;
  return (
    <footer className="border-t border-border py-12">
      <div className="mx-auto flex max-w-6xl flex-col gap-8 px-5 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4">
          <Wordmark className="h-6" />
          <span className="text-caption01 text-foreground-subtle">&copy; 2026</span>
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
