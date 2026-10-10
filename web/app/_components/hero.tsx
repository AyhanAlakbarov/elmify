import Image from "next/image";
import { Button } from "./button";
import { appLinks } from "./app-links";
import home from "../../public/screens/home.png";

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="mx-auto max-w-4xl px-5 pb-14 pt-20 text-center md:pt-28">
        <p className="hero-line hidden items-center gap-2 rounded-full sm:inline-flex border border-border px-3.5 py-1 text-body02 text-foreground-secondary">
          <span className="size-1.5 bg-brand" aria-hidden />
          For master&rsquo;s applicants in Central and South Asia
        </p>
        <h1 className="hero-line mt-7 text-hero01 font-extrabold text-foreground [animation-delay:80ms]">
          Find a funded master&rsquo;s. Apply with a plan
          <span className="hero-stop" aria-hidden />
        </h1>
        <p className="hero-line mx-auto mt-7 max-w-2xl text-body01 text-foreground-secondary [animation-delay:250ms]">
          Elmify shows you programmes together with the scholarships that pay for them, then keeps every deadline,
          document and answer in one place until you press submit.
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

      <div className="mx-auto max-w-6xl px-5">
        <div className="shot-in rounded-[28px] bg-brand-soft p-3 sm:p-5 md:p-7">
          <Image
            src={home}
            alt="The Elmify home screen: four steps, application numbers, what needs attention and upcoming deadlines"
            className="w-full rounded-2xl border border-border shadow-[0_24px_60px_-28px_rgba(11,7,22,0.35)]"
            sizes="(min-width: 1152px) 1100px, 100vw"
            fetchPriority="high"
            loading="eager"
          />
        </div>
        <p className="mt-3 text-center text-caption01 text-foreground-subtle">The real student dashboard, shown with a sample student.</p>
      </div>
    </section>
  );
}
