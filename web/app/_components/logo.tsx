import { WORDMARK } from "./logo-paths";

/** The "elmıfy" wordmark. Letters follow the text colour; the square dot is the
 *  brand indigo and drops in on load, hopping again on hover. */
export function Wordmark({ className = "h-7" }: { className?: string }) {
  const { viewBox, d, dot } = WORDMARK;
  return (
    <svg viewBox={viewBox} role="img" aria-label="Elmify" className={`elm-logo w-auto ${className}`}>
      <path d={d} fill="currentColor" />
      <rect className="elm-dot fill-brand" x={dot.x} y={dot.y} width={dot.size} height={dot.size} />
    </svg>
  );
}
