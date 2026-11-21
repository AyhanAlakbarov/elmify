import Link from "next/link";
import { LocaleHtmlShell } from "./_components/landing-page";

export default function NotFound() {
  return (
    <LocaleHtmlShell locale="en">
      <main id="main" className="mx-auto flex min-h-[70dvh] max-w-xl flex-col items-center justify-center px-5 text-center">
        <h1 className="text-heading01 font-bold">Page not found</h1>
        <p className="mt-3 text-body01 text-foreground-secondary">
          The page you are looking for does not exist.
        </p>
        <Link
          href="/"
          className="mt-6 inline-flex items-center rounded-full bg-brand px-5 py-2.5 text-body02 font-semibold text-on-brand"
        >
          Back to Elmify
        </Link>
      </main>
    </LocaleHtmlShell>
  );
}
