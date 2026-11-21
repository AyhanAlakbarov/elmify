import Link from "next/link";

type Props = {
  href: string;
  variant?: "primary" | "secondary";
  size?: "md" | "lg";
  children: React.ReactNode;
  className?: string;
  /** Opens in a new tab (a page outside Elmify, such as the booking calendar). */
  external?: boolean;
};

/** Indigo is the main action; the secondary button is an outline in the same ink. */
export function Button({
  href,
  variant = "primary",
  size = "md",
  children,
  className = "",
  external = false,
}: Props) {
  const base = [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full font-semibold",
    "transition-[background-color,border-color,color,transform] duration-200 active:scale-[0.98]",
  ].join(" ");
  const sizes =
    size === "lg"
      ? "h-12 px-6 text-body01"
      : "h-9 px-3.5 text-caption01 sm:h-10 sm:px-5 sm:text-body02";
  const looks = {
    primary: "bg-brand text-on-brand hover:bg-brand-strong",
    secondary: "border border-border-strong bg-surface text-foreground hover:border-foreground",
  }[variant];
  const classes = [base, sizes, looks, className].join(" ");
  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={classes}>
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={classes}>
      {children}
    </Link>
  );
}
