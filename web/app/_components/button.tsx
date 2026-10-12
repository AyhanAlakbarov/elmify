import Link from "next/link";

type Props = {
  href: string;
  variant?: "primary" | "secondary";
  size?: "md" | "lg";
  children: React.ReactNode;
  className?: string;
};

/** Indigo is the main action; the secondary button is an outline in the same ink. */
export function Button({ href, variant = "primary", size = "md", children, className = "" }: Props) {
  const base = [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full font-semibold",
    "transition-[background-color,border-color,color,transform] duration-200 active:scale-[0.98]",
  ].join(" ");
  const sizes = size === "lg" ? "h-12 px-6 text-body01" : "h-10 px-5 text-body02";
  const looks = {
    primary: "bg-brand text-on-brand hover:bg-brand-strong",
    secondary: "border border-border-strong bg-surface text-foreground hover:border-foreground",
  }[variant];
  return (
    <Link href={href} className={[base, sizes, looks, className].join(" ")}>
      {children}
    </Link>
  );
}
