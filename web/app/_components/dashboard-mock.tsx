/* A sample dashboard drawn in HTML. Names and figures are placeholders until the real
   product exists; replace this component with a screenshot when it does. */

const nav = ["Mission", "Programmes", "Funding", "Documents", "Calendar", "Inbox"];

const tasks = [
  { t: "Confirm your transcript details", tag: "Needs you", tone: "warn" },
  { t: "Review motivation letter draft 2", tag: "Docs verified", tone: "ok" },
  { t: "Fill Northgate application, page 2 of 4", tag: "Ready to fill", tone: "brand" },
] as const;

const apps = [
  { name: "Northgate University", prog: "M.Sc. Data Science", net: "€0", funded: 100, due: "Jan 15", step: 3 },
  { name: "Rhein-Main University", prog: "M.Sc. Computer Science", net: "€2,400", funded: 72, due: "Feb 01", step: 2 },
  { name: "Baltic Institute of Technology", prog: "M.Sc. AI Systems", net: "€5,100", funded: 40, due: "Mar 10", step: 1 },
];

const tone = {
  warn: "bg-warning-soft text-warning",
  ok: "bg-success-soft text-success",
  brand: "bg-brand-soft text-brand-text",
} as const;

export function DashboardMock() {
  return (
    <div className="overflow-hidden rounded-2xl border border-border-strong bg-surface shadow-[0_30px_80px_-30px_rgba(76,29,149,0.35)]">
      {/* window bar */}
      <div className="flex items-center gap-2 border-b border-border bg-background-secondary px-4 py-3">
        <span className="size-2.5 rounded-full bg-border-strong" />
        <span className="size-2.5 rounded-full bg-border-strong" />
        <span className="size-2.5 rounded-full bg-border-strong" />
        <span className="mx-auto rounded-md bg-surface px-3 py-0.5 text-caption01 text-foreground-subtle">
          app.elmify.com/mission
        </span>
        <span className="w-10" />
      </div>

      <div className="grid text-left md:grid-cols-[188px_1fr]">
        {/* sidebar */}
        <aside className="hidden border-r border-border bg-background-secondary p-3 md:block">
          <ul className="space-y-0.5 text-body02">
            {nav.map((n, i) => (
              <li
                key={n}
                className={`rounded-lg px-3 py-1.5 ${i === 0 ? "bg-surface font-medium text-foreground shadow-sm" : "text-foreground-secondary"}`}
              >
                {n}
              </li>
            ))}
          </ul>
          <div className="mt-6 rounded-lg border border-border bg-surface p-3">
            <p className="text-caption01 text-foreground-subtle">Next deadline</p>
            <p className="tabular mt-1 text-heading03 font-semibold">Jan 15</p>
            <p className="text-caption01 text-foreground-secondary">Northgate University</p>
          </div>
        </aside>

        {/* main */}
        <div className="space-y-5 p-5 md:p-6">
          <div className="flex items-end justify-between">
            <div>
              <p className="text-heading02 font-semibold">Good morning, Aysel</p>
              <p className="text-body02 text-foreground-secondary">3 applications in progress, 1 needs you today.</p>
            </div>
            <span className="rounded-full bg-brand-soft px-3 py-1 text-caption01 font-medium text-brand-text">Sample data</span>
          </div>

          <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
            {/* applications */}
            <div className="space-y-3">
              {apps.map((a) => (
                <div key={a.name} className="rounded-xl border border-border p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-body02 font-medium">{a.name}</p>
                      <p className="text-caption01 text-foreground-subtle">{a.prog} · due {a.due}</p>
                    </div>
                    <div className="text-right">
                      <p className="tabular font-mono text-heading03 font-medium">{a.net}</p>
                      <p className="text-caption02 text-foreground-subtle">net cost / yr</p>
                    </div>
                  </div>
                  <div className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-background-secondary" role="img" aria-label={`${a.funded}% of cost covered by funding`}>
                    <span className="bg-brand" style={{ width: `${a.funded}%` }} />
                  </div>
                  <div className="mt-2 flex items-center justify-between text-caption01 text-foreground-subtle">
                    <span className="tabular">{a.funded}% covered by funding</span>
                    <span>Step {a.step} of 4</span>
                  </div>
                </div>
              ))}
            </div>

            {/* today + roadmap */}
            <div className="space-y-4">
              <div className="rounded-xl border border-border p-4">
                <p className="mb-3 text-body02 font-medium">Today</p>
                <ul className="space-y-2.5">
                  {tasks.map((t) => (
                    <li key={t.t} className="flex items-start justify-between gap-3 text-body02">
                      <span className="text-foreground-secondary">{t.t}</span>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-caption02 font-medium ${tone[t.tone]}`}>{t.tag}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-xl border border-border p-4">
                <p className="mb-3 text-body02 font-medium">Roadmap</p>
                <ol className="relative space-y-3 border-l border-border-strong pl-4">
                  {[
                    ["Nov", "Documents confirmed"],
                    ["Dec", "Letters approved"],
                    ["Jan", "Submit Northgate"],
                  ].map(([m, label], i) => (
                    <li key={m} className="relative text-body02">
                      <span className={`absolute -left-[21px] top-1.5 size-2 ${i === 0 ? "bg-brand" : "bg-border-strong"}`} />
                      <span className="tabular mr-2 font-mono text-caption01 text-foreground-subtle">{m}</span>
                      <span className="text-foreground-secondary">{label}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
