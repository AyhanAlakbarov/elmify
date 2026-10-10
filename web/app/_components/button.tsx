import Link from "next/link";

type Props = {
  href: string;
  variant?: "primary" | "secondary" | "light";
  size?: "md" | "lg";
  children: React.ReactNode;
  className?: string;
};

/** Ink is the main action (the logo's black); purple shows on hover. */
export function Button({ href, variant = "primary", size = "md", children, className = "" }: Props) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-[background-color,border-color,color,transform] duration-150 active:scale-[0.97]";
  const sizes = size === "lg" ? "h-12 px-7 text-body01" : "h-10 px-5 text-body02";
  const looks = {
    primary: "bg-foreground text-background hover:bg-brand",
    secondary: "border border-border-strong bg-surface text-foreground hover:border-foreground",
    light: "bg-background text-foreground hover:bg-brand hover:text-on-brand",
  }[variant];
  return (
    <Link href={href} className={[base, sizes, looks, className].join(" ")}>
      {children}
    </Link>
  );
}
