import { MARK, WORDMARK } from "./logo-paths";

/** "elmify" wordmark. Letters follow the text colour; the square dot is the brand purple
 *  (lighter on dark backgrounds) and animates on load and on hover. */
export function Wordmark({ className = "h-7" }: { className?: string }) {
  const { viewBox, d, dot } = WORDMARK;
  return (
    <svg
      viewBox={viewBox}
      role="img"
      aria-label="Elmify"
      className={`elm-logo w-auto ${className}`}
    >
      <path d={d} fill="currentColor" />
      <rect
        className="elm-dot fill-brand dark:fill-brand-text"
        x={dot.x}
        y={dot.y}
        width={dot.size}
        height={dot.size}
      />
    </svg>
  );
}

/** The "e." app mark. `tile` draws the rounded square behind it. */
export function Mark({ className = "size-8", tile = true }: { className?: string; tile?: boolean }) {
  const { viewBox, d, dot } = MARK;
  return (
    <svg viewBox={viewBox} role="img" aria-label="Elmify" className={`elm-logo ${className}`}>
      {tile && <rect width="1024" height="1024" rx="232" className="fill-foreground" />}
      <path d={d} className={tile ? "fill-background" : "fill-current"} />
      <rect
        className={`elm-dot ${tile ? "fill-[#a78bfa]" : "fill-brand dark:fill-brand-text"}`}
        x={dot.x}
        y={dot.y}
        width={dot.size}
        height={dot.size}
      />
    </svg>
  );
}
