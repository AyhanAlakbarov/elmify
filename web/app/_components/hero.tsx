import Image from "next/image";
import { Button } from "./button";
import { appLinks } from "./app-links";
import home from "../../public/screens/home.png";

export function Hero() {
  return (
    <section className="overflow-hidden border-b border-border">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-5 pb-16 pt-14 md:pt-20 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-10 lg:pb-20">
        <div className="max-w-2xl">
          <h1 className="hero-line text-hero01 font-bold text-foreground">
            Get into a funded master&rsquo;s abroad
            <span className="hero-stop" aria-hidden />
          </h1>
          <p className="hero-line mt-6 max-w-[34rem] text-body01 text-foreground-secondary [animation-delay:200ms]">
            Elmify&rsquo;s AI reads official university and scholarship pages, matches programmes to your profile and
            prepares your documents. You stay in charge.
          </p>
          <div className="hero-line mt-9 flex flex-wrap items-center gap-3 [animation-delay:350ms]">
            <Button href={appLinks.signup} size="lg">
              Sign up free
            </Button>
            <Button href="#how" variant="secondary" size="lg">
              See how it works
            </Button>
          </div>
        </div>

        <figure className="shot-in relative lg:-mr-24 xl:-mr-40">
          <Image
            src={home}
            alt="The Elmify home screen: the student's progress, next actions and upcoming deadlines"
            className="w-full rounded-2xl border border-border shadow-[0_30px_70px_-30px_rgba(15,23,42,0.35)]"
            sizes="(min-width: 1024px) 720px, 100vw"
            fetchPriority="high"
            loading="eager"
          />
          <figcaption className="mt-3 text-caption01 text-foreground-subtle">
            The student dashboard, shown with a sample student.
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
