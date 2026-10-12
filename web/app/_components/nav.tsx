import Link from "next/link";
import { Button } from "./button";
import { Wordmark } from "./logo";
import { appLinks } from "./app-links";

const links = [
  { href: "#how", label: "How it works" },
  { href: "#product", label: "Product" },
  { href: "#agencies", label: "For agencies" },
  { href: "#faq", label: "FAQ" },
];

export function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/80 bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-5">
        <Link href="/" aria-label="Elmify home" className="text-foreground">
          <Wordmark className="h-7" />
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-8 md:flex">
          {links.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="text-body02 text-foreground-secondary transition-colors duration-200 hover:text-foreground"
            >
              {l.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-4">
          <a
            href={appLinks.login}
            className="text-body02 font-medium text-foreground transition-colors duration-200 hover:text-brand-text"
          >
            Log in
          </a>
          <Button href={appLinks.signup}>Sign up free</Button>
        </div>
      </div>
    </header>
  );
}
