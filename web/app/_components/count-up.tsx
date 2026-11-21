"use client";

import { useEffect, useRef } from "react";

const format = (n: number, suffix: string) => `${n.toLocaleString("en-US")}${suffix}`;

/** Counts from 0 to `value` once, when the number scrolls into view. The server
 *  renders the final number, so no-JS readers, crawlers and reduced motion see it. */
export function CountUp({ value, suffix = "" }: { value: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || value === 0) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    el.textContent = format(0, suffix);
    let frame = 0;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        observer.disconnect();
        const start = performance.now();
        const tick = (now: number) => {
          const t = Math.min(1, (now - start) / 1200);
          el.textContent = format(Math.round(value * (1 - Math.pow(1 - t, 3))), suffix);
          if (t < 1) frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
      },
      { threshold: 0.4 },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      el.textContent = format(value, suffix);
    };
  }, [value, suffix]);

  return (
    <span ref={ref} className="tabular-nums">
      {format(value, suffix)}
    </span>
  );
}
