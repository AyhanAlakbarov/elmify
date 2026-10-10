import { Button } from "./button";
import { DashboardMock } from "./dashboard-mock";
import { Mark, Wordmark } from "./logo";

/* ------------------------------------------------------------------ */
export function DashboardSection() {
  return (
    <section id="dashboard" className="scroll-mt-20 bg-background-secondary py-20">
      <div className="mx-auto max-w-6xl px-5">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <h2 className="text-heading01 font-extrabold">Every application, in one place</h2>
          <p className="mt-4 text-body01 text-foreground-secondary">
            See your programmes with their funding attached, what to do today, and every deadline, without opening ten tabs.
          </p>
        </div>
        <DashboardMock />
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
const funders = [
  "Erasmus Mundus (EACEA)",
  "DAAD",
  "Swedish Institute",
  "Türkiye Burslari",
  "MEXT (JASSO)",
  "Eiffel Excellence",
];

export function Funders() {
  return (
    <section aria-label="Funders we read from" className="border-b border-border py-10">
      <div className="mx-auto max-w-6xl px-5 text-center">
        <p className="text-body02 text-foreground-subtle">We read funding rules straight from official pages, including</p>
        <ul className="mt-4 flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-heading03 font-semibold text-foreground-secondary">
          {funders.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
function Chip({ children, tone = "brand" }: { children: React.ReactNode; tone?: "brand" | "ok" | "warn" | "mute" }) {
  const t = {
    brand: "bg-brand-soft text-brand-text",
    ok: "bg-success-soft text-success",
    warn: "bg-warning-soft text-warning",
    mute: "bg-background-secondary text-foreground-subtle",
  }[tone];
  return <span className={`rounded-full px-2 py-0.5 text-caption02 font-medium ${t}`}>{children}</span>;
}

const mockBox = "h-52 overflow-hidden rounded-xl border border-border bg-background-secondary p-4 text-body02";

const features = [
  {
    title: "Programmes with their funding",
    body: "Every master’s you see comes with the scholarships that can pay for it, so you compare net cost, not sticker price.",
    mock: (
      <div className="space-y-3 rounded-lg bg-surface p-3 shadow-sm">
        <div className="flex items-start justify-between">
          <div>
            <p className="font-medium">M.Sc. Data Science</p>
            <p className="text-caption01 text-foreground-subtle">Northgate University · 24 months</p>
          </div>
          <Chip tone="ok">Fully funded</Chip>
        </div>
        <div className="flex h-2 overflow-hidden rounded-full">
          <span className="w-[55%] bg-brand" />
          <span className="w-[45%] bg-brand/45" />
        </div>
        <div className="flex justify-between text-caption01 text-foreground-secondary">
          <span>Fee waiver · 55%</span>
          <span>Stipend · 45%</span>
        </div>
        <p className="tabular font-mono text-heading03">Net cost €0 / yr</p>
      </div>
    ),
  },
  {
    title: "Scholarship matching",
    body: "Government, university and programme awards checked against your profile, with the reason each one fits or doesn’t.",
    mock: (
      <ul className="space-y-2">
        {[
          ["Government award", "Eligible", "ok"],
          ["University excellence grant", "Eligible", "ok"],
          ["Regional stipend", "Needs one document", "warn"],
          ["Industry fellowship", "Not eligible", "mute"],
        ].map(([n, s, t]) => (
          <li key={n} className="flex items-center justify-between rounded-lg bg-surface px-3 py-2 shadow-sm">
            <span>{n}</span>
            <Chip tone={t as "ok" | "warn" | "mute"}>{s}</Chip>
          </li>
        ))}
      </ul>
    ),
  },
  {
    title: "Profile check",
    body: "See how your grades, experience and documents line up with each programme’s published requirements, and what is missing.",
    mock: (
      <div className="space-y-2.5">
        {[
          ["Academic record", 86],
          ["Language proof", 100],
          ["Relevant experience", 64],
          ["Documents", 70],
        ].map(([l, v]) => (
          <div key={l as string}>
            <div className="mb-1 flex justify-between text-caption01 text-foreground-secondary">
              <span>{l}</span>
              <span className="tabular">{v}%</span>
            </div>
            <div className="h-1.5 rounded-full bg-surface">
              <div className="h-full rounded-full bg-brand" style={{ width: `${v}%` }} />
            </div>
          </div>
        ))}
      </div>
    ),
  },
  {
    title: "Application roadmap",
    body: "A dated plan for documents, letters and forms, built around each deadline and the order things need to happen in.",
    mock: (
      <ol className="space-y-2">
        {[
          ["Nov 04", "Upload transcript", true],
          ["Nov 20", "Confirm your facts", true],
          ["Dec 12", "Approve motivation letter", false],
          ["Jan 15", "Submit Northgate", false],
        ].map(([d, l, done]) => (
          <li key={d as string} className="flex items-center gap-3 rounded-lg bg-surface px-3 py-2 shadow-sm">
            <span className={`size-2.5 shrink-0 ${done ? "bg-brand" : "border border-border-strong"}`} />
            <span className="tabular font-mono text-caption01 text-foreground-subtle">{d}</span>
            <span className={done ? "text-foreground-subtle line-through" : ""}>{l}</span>
          </li>
        ))}
      </ol>
    ),
  },
  {
    title: "CV and letters from your own facts",
    body: "Drafts use only facts you have confirmed, shaped to each programme’s rules. Nothing is invented, and you approve every document.",
    mock: (
      <div className="space-y-2 rounded-lg bg-surface p-3 shadow-sm">
        <p className="text-caption01 text-foreground-subtle">Motivation letter · draft 2</p>
        <p className="leading-5 text-foreground-secondary">
          &ldquo;My final-year project on <mark className="rounded bg-brand-soft px-0.5 text-brand-text">demand forecasting</mark> led me to
          Northgate&rsquo;s data science programme&hellip;&rdquo;
        </p>
        <div className="flex gap-2 pt-1">
          <Chip tone="ok">Fact confirmed</Chip>
          <Chip>Source: your CV</Chip>
        </div>
      </div>
    ),
  },
  {
    title: "Supervised autofill",
    body: "Our browser extension fills the university portal in your own tab. You watch every field, approve sensitive ones, and press submit.",
    mock: (
      <div className="space-y-2">
        {[
          ["Full name", "Filled"],
          ["Date of birth", "Filled"],
        ].map(([l, s]) => (
          <div key={l} className="flex items-center justify-between rounded-lg bg-surface px-3 py-2 shadow-sm">
            <span>{l}</span>
            <Chip tone="ok">{s}</Chip>
          </div>
        ))}
        <div className="flex items-center justify-between rounded-lg border border-warning/50 bg-warning-soft px-3 py-2">
          <span className="text-warning">Passport number</span>
          <span className="rounded-full bg-warning px-2.5 py-0.5 text-caption02 font-medium text-background">Approve</span>
        </div>
      </div>
    ),
  },
];

export function Features() {
  return (
    <section id="features" className="scroll-mt-20 py-24">
      <div className="mx-auto max-w-6xl px-5">
        <h2 className="mx-auto max-w-2xl text-center text-heading01 font-extrabold">
          Everything you need to build a stronger application
        </h2>
        <ul className="mt-14 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => (
            <li key={f.title} className="flex flex-col rounded-2xl border border-border bg-surface p-5">
              <div className={mockBox} aria-hidden>{f.mock}</div>
              <h3 className="mt-5 text-heading02 font-semibold">{f.title}</h3>
              <p className="mt-2 text-body02 text-foreground-secondary">{f.body}</p>
            </li>
          ))}
        </ul>
        <p className="mt-6 text-center text-caption01 text-foreground-subtle">Previews show sample data.</p>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
type V = "yes" | "part" | "no";
const rows: { label: string; v: [V, V, V, V] }[] = [
  { label: "Programmes and scholarships matched together, with net cost", v: ["yes", "part", "part", "part"] },
  { label: "Every requirement linked to the official page it came from", v: ["yes", "no", "part", "no"] },
  { label: "Documents built only from facts you confirmed", v: ["yes", "no", "yes", "part"] },
  { label: "Checks the university is a recognised body", v: ["yes", "no", "part", "no"] },
  { label: "Deadlines and funding cycles tracked per application", v: ["yes", "no", "yes", "part"] },
  { label: "Fills portal forms in your own browser; you press submit", v: ["yes", "no", "part", "no"] },
  { label: "Watches your inbox for university replies (read-only)", v: ["yes", "no", "part", "no"] },
  { label: "Hands off to a human when a fact or step is missing", v: ["yes", "no", "yes", "part"] },
  { label: "Deletes your data on request", v: ["yes", "part", "part", "part"] },
  { label: "Affordable for one student", v: ["yes", "yes", "no", "part"] },
];
const sym = {
  yes: { icon: "M4 10.5 8 14.5 16 5.5", cls: "text-brand-text", text: "Yes" },
  part: { icon: "M5 10h10", cls: "text-foreground-subtle", text: "Partly" },
  no: { icon: "M6 6l8 8M14 6l-8 8", cls: "text-foreground-subtle/60", text: "No" },
} as const;

export function Compare() {
  const cols = ["Elmify", "General AI chatbots", "Consultancies", "Other AI admissions tools"];
  return (
    <section id="compare" className="scroll-mt-20 bg-background-secondary py-24">
      <div className="mx-auto max-w-5xl px-5">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-heading01 font-extrabold">One tool to do it all</h2>
          <p className="mt-4 text-body01 text-foreground-secondary">
            Private consultants charge thousands. Elmify gives you the same structure for a fraction of the price.
          </p>
        </div>
        <div className="mt-12 relative overflow-x-auto rounded-2xl border border-border bg-surface">
          <table className="w-full min-w-[720px] border-collapse text-left text-body02">
            <caption className="sr-only">How Elmify compares with general AI chatbots, consultancies and other AI admissions tools</caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="sticky left-0 bg-surface p-4 font-normal text-foreground-subtle">What you need</th>
                {cols.map((c, i) => (
                  <th key={c} scope="col" className={`p-4 text-center font-semibold ${i === 0 ? "bg-brand-soft text-brand-text" : ""}`}>
                    {i === 0 ? <Wordmark className="mx-auto h-5" /> : c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className="border-b border-border last:border-0">
                  <th scope="row" className="sticky left-0 bg-surface p-4 font-normal text-foreground-secondary">{r.label}</th>
                  {r.v.map((v, i) => (
                    <td key={i} className={`p-4 text-center ${i === 0 ? "bg-brand-soft/60" : ""}`}>
                      <svg viewBox="0 0 20 20" className={`mx-auto size-5 ${sym[v].cls}`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                        <path d={sym[v].icon} />
                      </svg>
                      <span className="sr-only">{sym[v].text}</span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mx-auto mt-5 max-w-3xl text-center text-caption01 text-foreground-subtle">
          Competitor columns describe typical offerings and will vary by provider. The Elmify column describes the product as
          designed; features arrive in stages.
        </p>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
const principles = [
  ["No paid placements", "We rank programmes by fit and verified funding. Universities cannot pay to appear higher."],
  ["A source for every claim", "Requirements and deadlines link back to the official page they came from."],
  ["You press submit", "Elmify types into your own tab and never sends an application for you."],
  ["Your data, your call", "Ask us to delete your data and we will, with a clear timeline."],
];

export function Principles() {
  return (
    <section className="py-24">
      <div className="mx-auto max-w-6xl px-5">
        <h2 className="max-w-xl text-heading01 font-extrabold">Built so you can trust every step</h2>
        <dl className="mt-12 grid gap-x-12 gap-y-10 md:grid-cols-2">
          {principles.map(([t, b]) => (
            <div key={t} className="flex gap-4">
              <span className="mt-2 size-2.5 shrink-0 bg-brand" aria-hidden />
              <div>
                <dt className="text-heading02 font-semibold">{t}</dt>
                <dd className="mt-1.5 text-body01 text-foreground-secondary">{b}</dd>
              </div>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
export function Closing() {
  return (
    <section id="start" className="scroll-mt-20 px-5 pb-24">
      <div className="mx-auto flex max-w-6xl flex-col items-center rounded-3xl border border-transparent bg-[#0b0716] px-6 dark:border-border-strong dark:bg-[#150d2b] py-20 text-center text-[#f5f3ff]">
        <Mark className="size-14" tile={false} />
        <h2 className="mt-8 max-w-2xl text-heading01 font-extrabold">Ready to find a funded master&rsquo;s?</h2>
        <p className="mt-4 max-w-xl text-body01 text-[#b9b1d3]">
          Join the early-access list and be first in when we open to students.
        </p>
        <div className="mt-8">
          <Button href="mailto:hello@elmify.com?subject=Early%20access">Get early access</Button>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
export function Footer() {
  const cols = [
    ["Product", ["Dashboard", "Features", "Compare"]],
    ["Company", ["About", "Contact"]],
    ["Legal", ["Terms", "Privacy"]],
  ] as const;
  return (
    <footer className="border-t border-border py-14">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div>
          <Wordmark className="h-6" />
          <p className="mt-4 max-w-xs text-body02 text-foreground-secondary">Plan, fund and apply, all in one place.</p>
        </div>
        {cols.map(([h, items]) => (
          <div key={h}>
            <p className="text-body02 font-semibold">{h}</p>
            <ul className="mt-3 space-y-2 text-body02 text-foreground-secondary">
              {items.map((i) => (
                <li key={i}>
                  <a href={h === "Product" ? `#${i.toLowerCase()}` : "#"} className="hover:text-foreground">{i}</a>
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
