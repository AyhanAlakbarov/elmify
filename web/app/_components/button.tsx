import Link from "next/link";

type Props = {
  href: string;
  variant?: "primary" | "secondary";
  size?: "md" | "lg";
  children: React.ReactNode;
  className?: string;
};

export function Button({ href, variant = "primary", size = "md", children, className = "" }: Props) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-full font-medium transition-colors duration-150";
  const sizes = size === "lg" ? "h-12 px-7 text-body01" : "h-10 px-5 text-body02";
  const looks =
    variant === "primary"
      ? "bg-brand text-on-brand hover:bg-brand-strong"
      : "border border-border-strong text-foreground hover:bg-background-secondary";
  return (
    <Link href={href} className={[base, sizes, looks, className].join(" ")}>
      {children}
    </Link>
  );
}
