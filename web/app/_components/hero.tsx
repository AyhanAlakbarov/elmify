import { Button } from "./button";
import { appLinks } from "./app-links";

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="dot-grid absolute inset-0 -z-10" aria-hidden />
      <span
        aria-hidden
        className="dot-pulse absolute left-[12%] top-[38%] -z-10 size-2.5 bg-brand"
      />
      <span
        aria-hidden
        className="dot-pulse absolute right-[14%] top-[62%] -z-10 size-2 bg-brand [animation-delay:3.4s]"
      />
      <div className="mx-auto max-w-4xl px-5 pb-20 pt-24 text-center md:pt-32">
        <h1 className="hero-line text-hero01 font-extrabold text-foreground">
          Find a funded master&rsquo;s. Apply with confidence
          <span className="hero-stop" aria-hidden />
        </h1>
        <p className="hero-line mx-auto mt-7 max-w-2xl text-body01 text-foreground-secondary [animation-delay:250ms]">
          Elmify matches you with master&rsquo;s programmes and the scholarships that pay for them, tracks every
          deadline, and fills in your applications while you stay in control.
        </p>
        <div className="hero-line mt-10 flex flex-wrap items-center justify-center gap-3 [animation-delay:400ms]">
          <Button href={appLinks.signup} size="lg">
            Create your free account
          </Button>
          <Button href={appLinks.demo} variant="secondary" size="lg">
            Book a demo
          </Button>
        </div>
      </div>
    </section>
  );
}
