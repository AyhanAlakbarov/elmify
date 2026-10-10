import Link from "next/link";
import { Button } from "./button";
import { ThemeToggle } from "./theme-toggle";
import { Wordmark } from "./logo";

const links = [
  { href: "#dashboard", label: "Dashboard" },
  { href: "#features", label: "Features" },
  { href: "#compare", label: "Compare" },
];

export function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
        <Link href="/" aria-label="Elmify home" className="text-foreground">
          <Wordmark className="h-6" />
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-8 md:flex">
          {links.map((l) => (
            <a key={l.href} href={l.href} className="text-body02 text-foreground-secondary transition-colors hover:text-foreground">
              {l.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <Button href="#start">Get early access</Button>
        </div>
      </div>
    </header>
  );
}
