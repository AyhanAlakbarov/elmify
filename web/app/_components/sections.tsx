import Image, { type StaticImageData } from "next/image";
import { Button } from "./button";
import { appLinks } from "./app-links";
import { Wordmark } from "./logo";
import board from "../../public/screens/board.png";
import messages from "../../public/screens/messages.png";
import profile from "../../public/screens/profile.png";
import programmes from "../../public/screens/programmes.png";

/* ------------------------------------------------------------------ */
const strip = [
  "Programme matching",
  "Scholarship finder",
  "Funding gap in your currency",
  "Deadline tracker",
  "Document checklist",
  "Application kit",
  "Messages with your counsellor",
  "Search across everything",
];

/** What Elmify does, as one slow line. Duplicated once so the loop is seamless. */
export function FeatureStrip() {
  return (
    <section aria-label="What Elmify does" className="mt-20 border-y border-border py-6">
      <div className="marquee overflow-hidden">
        <ul className="marquee-track flex w-max gap-3">
          {[...strip, ...strip].map((item, i) => (
            <li
              key={`${item}-${i}`}
              aria-hidden={i >= strip.length}
              className="flex items-center gap-2.5 whitespace-nowrap rounded-full border border-border px-4 py-2 text-body02 font-medium text-foreground"
            >
              <span className="size-1.5 bg-brand" aria-hidden />
              {item}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
const steps = [
  ["Tell us about you", "Fourteen short questions: what you studied, your grades, where you would go and whether you need a scholarship."],
  ["See what fits", "Programmes you are eligible for, each grouped under the scholarship that pays for it, with the gap left to cover."],
  ["Apply with everything ready", "Pick programmes, follow each deadline, prepare the documents they ask for and use the kit to fill in the forms."],
];

export function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-20 py-24">
      <div className="mx-auto max-w-6xl px-5">
        <h2 className="max-w-2xl text-heading01 font-extrabold">Three steps, from &ldquo;where do I start&rdquo; to submitted</h2>
        <ol className="mt-14 grid gap-10 md:grid-cols-3 md:gap-8">
          {steps.map(([title, body], i) => (
            <li key={title} className="border-t-2 border-foreground pt-6">
              <span className="text-body02 font-semibold text-brand-text">Step {i + 1}</span>
              <h3 className="mt-2 text-heading02 font-bold">{title}</h3>
              <p className="mt-3 text-body01 text-foreground-secondary">{body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
type Row = { title: string; body: string; points: string[]; shot: StaticImageData; alt: string };

const rows: Row[] = [
  {
    title: "Programmes, grouped by the money that pays for them",
    body: "Most students search for a programme, then for funding, and only then find out the two do not match. Elmify starts from the funding.",
    points: ["Who awards it, what it covers and when it closes", "A link to the official page each fact came from", "Ask us to check a programme you found yourself"],
    shot: programmes,
    alt: "A scholarship on the Programmes page with its holder, what it covers, and the programmes it funds",
  },
  {
    title: "Every application on one board",
    body: "Each programme you choose becomes a card that moves from To start to Decision. Deadlines that are close turn red before they become a problem.",
    points: ["Documents and answers counted per application", "An Application Kit with everything the portal will ask", "Search everything with the / key"],
    shot: board,
    alt: "The application board with cards in the To start column, each showing funding, documents and actions",
  },
  {
    title: "A profile that takes ten minutes, once",
    body: "One question at a time, in plain words. Pick a country from a list, choose an answer, enter your degree the way it is written on your transcript.",
    points: ["Answers are saved as you go", "Change any answer later; the matches update", "Check every answer before your search starts"],
    shot: profile,
    alt: "A profile question asking whether the student can go without a scholarship, with three answers",
  },
  {
    title: "Your counsellor, in the same place",
    body: "If you work with an agency, your counsellor sees the same board and talks to you beside it. No more screenshots in messaging apps.",
    points: ["Messages next to your applications", "Mail from universities, once you connect your inbox", "Every change your counsellor makes is recorded with their name"],
    shot: messages,
    alt: "The Messages page with a conversation between a student and their counsellor",
  },
];

export function Product() {
  return (
    <section id="product" className="scroll-mt-20 bg-background-secondary py-24">
      <div className="mx-auto max-w-6xl px-5">
        <div className="max-w-2xl">
          <h2 className="text-heading01 font-extrabold">What you get when you sign up</h2>
          <p className="mt-4 text-body01 text-foreground-secondary">
            These are screens from the dashboard itself, not mock-ups.
          </p>
        </div>
        <div className="mt-16 space-y-24">
          {rows.map((r, i) => (
            <article key={r.title} className="grid items-center gap-10 md:grid-cols-2 md:gap-14">
              <div className={i % 2 ? "md:order-2" : ""}>
                <h3 className="text-heading02 font-bold md:text-[1.75rem] md:leading-tight">{r.title}</h3>
                <p className="mt-4 text-body01 text-foreground-secondary">{r.body}</p>
                <ul className="mt-6 space-y-3">
                  {r.points.map((p) => (
                    <li key={p} className="flex gap-3 text-body01">
                      <span className="mt-2.5 size-1.5 shrink-0 bg-brand" aria-hidden />
                      {p}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-3xl bg-surface p-3 shadow-[0_1px_2px_rgba(11,7,22,0.04),0_20px_50px_-30px_rgba(11,7,22,0.3)] ring-1 ring-border sm:p-4">
                <Image src={r.shot} alt={r.alt} className="w-full rounded-2xl" sizes="(min-width: 768px) 540px, 100vw" />
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
  ["Your address", "Students sign up and log in on your agency\u2019s own web address."],
  ["Your team", "Assign each student to a counsellor and see who is waiting on whom."],
  ["Your leads", "Demo requests and new students land on one owner page."],
];

export function Agencies() {
  return (
    <section id="agencies" className="scroll-mt-20 px-5 py-24">
      <div className="mx-auto grid max-w-6xl gap-12 rounded-[28px] bg-foreground px-6 py-14 text-background md:grid-cols-[1.1fr_1fr] md:px-14 md:py-16">
        <div>
          <h2 className="text-heading01 font-extrabold">Run your agency on Elmify</h2>
          <p className="mt-4 max-w-md text-body01 text-[#c9c5d4]">
            The same dashboard, under your name. Your counsellors work on each student&rsquo;s board; your students always know
            what is next.
          </p>
          <div className="mt-8">
            <Button href={appLinks.demo} variant="light" size="lg">
              Book a demo
            </Button>
          </div>
        </div>
        <dl className="grid gap-7 self-center">
          {agencyPoints.map(([t, b]) => (
            <div key={t} className="flex gap-4">
              <span className="mt-2 size-2 shrink-0 bg-brand" aria-hidden />
              <div>
                <dt className="text-heading03 font-semibold">{t}</dt>
                <dd className="mt-1 text-body01 text-[#c9c5d4]">{b}</dd>
              </div>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
const faqs = [
  ["Is it free?", "Creating an account and getting your matches is free during early access. We will tell you before anything costs money."],
  ["Which countries and programmes do you cover?", "We start with master's programmes in Europe and the scholarships open to students from Central and South Asia. The list grows as we add funders."],
  ["Do you submit applications for me?", "No. You stay in your own browser and press submit yourself. Elmify prepares the answers and documents and tracks what is left."],
  ["What happens to my data?", "It is used to find programmes for you and nothing else. You can delete your account from Settings at any time."],
];

export function Faq() {
  return (
    <section id="faq" className="scroll-mt-20 pb-24">
      <div className="mx-auto max-w-3xl px-5">
        <h2 className="text-heading01 font-extrabold">Questions</h2>
        <div className="mt-10 divide-y divide-border border-y border-border">
          {faqs.map(([q, a]) => (
            <details key={q} className="faq group">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-6 py-5 text-heading03 font-semibold">
                {q}
                <span className="plus grid size-7 shrink-0 place-items-center rounded-full border border-border-strong text-foreground-secondary" aria-hidden>
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
    <section id="start" className="scroll-mt-20 border-t border-border bg-brand-soft px-5 py-24">
      <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
        <h2 className="text-heading01 font-extrabold">Start with your profile. It takes ten minutes.</h2>
        <p className="mt-4 max-w-xl text-body01 text-foreground-secondary">Your matches are ready as soon as you finish.</p>
        <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
          <Button href={appLinks.signup} size="lg">
            Create your free account
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
  const cols = [
    ["Product", [["How it works", "#how"], ["The dashboard", "#product"], ["Questions", "#faq"]]],
    ["Company", [["For agencies", "#agencies"], ["Book a demo", appLinks.demo], ["Log in", appLinks.login]]],
    ["Legal", [["Terms", appLinks.terms], ["Privacy", appLinks.privacy]]],
  ] as const;
  return (
    <footer className="border-t border-border py-14">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div>
          <Wordmark className="h-6" />
          <p className="mt-4 max-w-xs text-body02 text-foreground-secondary">Find a funded master&rsquo;s and apply with a plan.</p>
        </div>
        {cols.map(([h, items]) => (
          <div key={h}>
            <p className="text-body02 font-semibold">{h}</p>
            <ul className="mt-3 space-y-2 text-body02 text-foreground-secondary">
              {items.map(([label, href]) => (
                <li key={label}>
                  <a href={href} className="hover:text-foreground">{label}</a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <p className="mx-auto mt-12 max-w-6xl px-5 text-caption01 text-foreground-subtle">© 2026 Elmify</p>
    </footer>
  );
}
