import { Button } from "./button";
import { COPY, type HeroMatch, type Locale, localizedAppLinks } from "./i18n";

/** A ring that fills to the match's chance once, on load. */
function ChanceRing({ value, label, delay }: { value: number; label: string; delay: number }) {
  const r = 20;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative grid size-14 shrink-0 place-items-center">
      <svg viewBox="0 0 48 48" className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx="24" cy="24" r={r} fill="none" stroke="var(--brand-soft)" strokeWidth="5" />
        <circle
          cx="24"
          cy="24"
          r={r}
          fill="none"
          stroke="var(--brand)"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={c}
          className="ring-fill"
          style={
            {
              "--ring-to": c * (1 - value / 100),
              "--ring-from": c,
              animationDelay: `${delay}ms`,
            } as React.CSSProperties
          }
        />
      </svg>
      <span className="text-caption01 font-bold tabular-nums text-foreground">
        {value}%
        <span className="sr-only"> {label}</span>
      </span>
    </div>
  );
}

function MatchRow({ m, i, chanceLabel }: { m: HeroMatch; i: number; chanceLabel: string }) {
  const delay = 700 + i * 260;
  return (
    <li
      className="match-in flex items-center gap-4 rounded-2xl border border-border bg-surface p-3.5 pr-4 shadow-[0_10px_30px_-18px_rgba(15,23,42,0.35)]"
      style={{ animationDelay: `${delay}ms` }}
    >
      <ChanceRing value={m.chance} label={chanceLabel} delay={delay + 150} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-body02 font-semibold text-foreground">{m.programme}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-caption01 text-foreground-subtle">
          {m.country}
          <span className="rounded-full bg-success-soft px-2 py-0.5 font-semibold text-success">
            {m.funding}
          </span>
        </p>
      </div>
    </li>
  );
}

export function Hero({ locale = "en" }: { locale?: Locale }) {
  const copy = COPY[locale].hero;
  const app = localizedAppLinks(locale);

  return (
    <section className="hero-bg overflow-hidden border-b border-border">
      <div className="mx-auto grid max-w-6xl items-center gap-14 px-5 pb-20 pt-14 md:pt-24 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:gap-12">
        <div className="max-w-xl">
          <h1 className="hero-line text-hero01 font-bold text-foreground">
            {copy.h1}
            <span className="hero-stop" aria-hidden />
          </h1>
          <p className="hero-line mt-6 max-w-[30rem] text-[1.25rem] leading-relaxed text-foreground-secondary [animation-delay:200ms]">
            {copy.body}
          </p>
          <div className="hero-line mt-9 flex flex-wrap items-center gap-3 [animation-delay:350ms]">
            <Button href={app.signup} size="lg">
              {copy.ctaPrimary}
            </Button>
            <Button href={app.login} variant="secondary" size="lg">
              {copy.ctaSecondary}
            </Button>
          </div>
        </div>

        <figure className="relative mx-auto w-full max-w-md" aria-label={copy.shotAlt}>
          <span className="absolute -top-3 right-4 z-10 rounded-full border border-border bg-surface px-2.5 py-0.5 text-caption01 font-semibold text-foreground-subtle">
            {copy.example}
          </span>
          <div className="shot-in rounded-3xl border border-border bg-background-secondary/80 p-5 backdrop-blur">
            <div className="flex items-center gap-3 rounded-2xl bg-foreground p-4 text-background">
              <span className="grid size-10 shrink-0 place-items-center rounded-full bg-brand text-body02 font-bold">
                {copy.profileName.charAt(0)}
              </span>
              <div className="min-w-0">
                <p className="text-body02 font-semibold">{copy.profileName}</p>
                <p className="mt-1 flex flex-wrap gap-1.5">
                  {copy.profileFacts.map((f) => (
                    <span key={f} className="rounded-full bg-white/10 px-2 py-0.5 text-caption01">
                      {f}
                    </span>
                  ))}
                </p>
              </div>
            </div>

            <div className="flow-dots my-3 flex flex-col items-center gap-1.5" aria-hidden>
              <span />
              <span />
              <span />
            </div>

            <p className="mb-2.5 px-1 text-caption01 font-semibold text-foreground-secondary">
              {copy.matchesLabel}
            </p>
            <ul className="grid gap-2.5">
              {copy.matches.map((m, i) => (
                <MatchRow key={m.programme} m={m} i={i} chanceLabel={copy.chanceLabel} />
              ))}
            </ul>
          </div>
        </figure>
      </div>
    </section>
  );
}
