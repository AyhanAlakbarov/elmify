/**
 * Display-only marks beside each portal field. The layer is a closed shadow
 * root (the page cannot reach into it, and its CSS cannot reach in), the host
 * ignores pointer events, and every string goes in as textContent. It carries
 * labels only: never a student value, never an identifier. If the page keeps
 * removing the host the layer gives up and the panel is the only place a field
 * is shown (FieldView.placed = false).
 */
import type { FieldRecord } from "./state.js";

declare const __ELMIFY_TEST__: boolean;

export interface MarkLabels {
  filled: string; check: string; yourTurn: string; changed: string; portalError: string;
  why: (key: string) => string; next: string | null;
}

const MAX_REATTACH = 5;
let host: HTMLElement | null = null;
let root: ShadowRoot | null = null;
let reattached = 0;
let observer: MutationObserver | null = null;
let lastLabels: MarkLabels | null = null;
let onChange: (() => void) | null = null;
let focusedKey: string | null = null;

interface Item { record: FieldRecord; nodes: HTMLElement[]; off: (() => void) | null }
const drawn = new Map<string, Item>();

function tagName(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return "x-" + Array.from(bytes, (b) => ((b % 26) + 10).toString(36)).join("");
}

const STYLE = `
:host { all: initial !important; position: fixed !important; inset: 0 !important;
        pointer-events: none !important; z-index: 2147483647 !important; }
.mark, .tag, .chip { all: initial; position: fixed; display: flex; align-items: center; gap: 4px;
        font: 12px/1.3 system-ui, sans-serif; padding: 2px 6px; border-radius: 10px;
        pointer-events: none; white-space: nowrap; }
.filled { background: #e8f5ec; color: #145a2a; } .check { background: #fff4e0; color: #7a4a00; }
.your_turn, .portal_error { background: #fdecec; color: #8a1c1c; } .changed { background: #eef0f3; color: #3a3f47; }
.tag { background: #1f2937; color: #fff; }
.chip { background: #1d3a8a; color: #fff; font-weight: 600; }
.outline { all: initial; position: fixed; pointer-events: none; border-radius: 4px; box-sizing: border-box; }
.outline.check { border: 2px solid #e0a020; } .outline.your_turn, .outline.portal_error { border: 2px solid #d04040; }
`;

function ensureHost(): ShadowRoot | null {
  if (host?.isConnected && root) return root;
  if (reattached >= MAX_REATTACH) {
    observer?.disconnect(); // the page keeps fighting: give up, the panel carries it
    return null;
  }
  if (host) reattached += 1;
  host = document.createElement(tagName());
  if (__ELMIFY_TEST__) host.setAttribute("data-elmify-marks", "");
  host.setAttribute("aria-hidden", "true");
  for (const [k, v] of [["pointer-events", "none"], ["position", "fixed"], ["display", "block"], ["inset", "0"], ["z-index", "2147483647"]])
    host.style.setProperty(k!, v!, "important");
  root = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = STYLE;
  root.append(style);
  document.documentElement.append(host);
  observer?.disconnect();
  observer = new MutationObserver(() => { if (!host?.isConnected) redraw(); });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  return root;
}

// Scroll and resize move the fields under fixed-position marks. The listeners
// exist only while marks are drawn (a page we never marked gets no layer), and
// a burst of events costs one redraw per frame.
const SCROLL = { passive: true, capture: true } as const;
let frame = 0;
function schedule(): void {
  if (frame || drawn.size === 0) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    redraw();
  });
}
function followScroll(on: boolean): void {
  if (on) {
    addEventListener("scroll", schedule, SCROLL);
    addEventListener("resize", schedule, { passive: true });
    return;
  }
  removeEventListener("scroll", schedule, SCROLL);
  removeEventListener("resize", schedule);
  cancelAnimationFrame(frame);
  frame = 0;
}

export function drawMarks(records: Map<string, FieldRecord>, labels: MarkLabels, changed?: () => void): void {
  followScroll(true);
  lastLabels = labels;
  if (changed) onChange = changed;
  for (const item of drawn.values()) item.off?.();
  drawn.clear();
  for (const [key, record] of records) {
    const item: Item = { record, nodes: [], off: null };
    const el = record.element;
    if (el) {
      const focus = () => { focusedKey = key; redraw(); };
      const blur = () => { if (focusedKey === key) { focusedKey = null; redraw(); } };
      el.addEventListener("focusin", focus);
      el.addEventListener("focusout", blur);
      item.off = () => { el.removeEventListener("focusin", focus); el.removeEventListener("focusout", blur); };
    }
    drawn.set(key, item);
  }
  redraw(true);
}

function textFor(state: string, labels: MarkLabels): [string, string] | null {
  switch (state) {
    case "filled": case "already": return ["filled", "✓ " + labels.filled];
    case "mismatch": return ["check", "! " + labels.check];
    case "your_turn": return ["your_turn", "✎ " + labels.yourTurn];
    case "portal_error": return ["portal_error", "! " + labels.portalError];
    case "changed_by_you": return ["changed", "✎ " + labels.changed];
    default: return null; // "elsewhere": nothing on this page
  }
}

function put(shadow: ShadowRoot, item: Item, cls: string, text: string | null): HTMLElement {
  const node = document.createElement("div");
  node.className = cls;
  if (text !== null) node.textContent = text;
  shadow.append(node);
  item.nodes.push(node);
  return node;
}

type Side = "right" | "left";
const GAP = 6;

/** Beside the field, never over the page: right of it if the viewport has room,
 *  else left of it, else nowhere (the node goes and the panel carries it).
 *  Clamping into the viewport used to lay it over the portal's own text. */
function beside(item: Item, node: HTMLElement, box: DOMRect, top: number, only?: Side): Side | null {
  const width = node.getBoundingClientRect().width;
  const room = document.documentElement.clientWidth;
  const right = box.right + GAP;
  const left = box.left - GAP - width;
  const side = only ?? (right + width <= room ? "right" : left >= 0 ? "left" : null);
  const x = side === "right" ? right : left;
  if (side === null || x < 0 || x + width > room) {
    node.remove();
    item.nodes = item.nodes.filter((n) => n !== node);
    return null;
  }
  node.style.left = `${x}px`;
  node.style.top = `${top}px`;
  return side;
}

function redraw(quiet = false): void {
  const shadow = ensureHost();
  const before = Array.from(drawn.values(), (i) => i.record.view.placed).join();
  for (const item of drawn.values()) { for (const n of item.nodes) n.remove(); item.nodes = []; item.record.view.placed = false; }
  if (shadow && lastLabels) {
    let chipDone = lastLabels.next === null;
    for (const [key, item] of drawn) {
      const el = item.record.element;
      const text = textFor(item.record.view.state, lastLabels);
      if (!el || !text || !el.isConnected) continue;
      const box = el.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      const top = box.top + Math.max(0, (box.height - 18) / 2);
      const side = beside(item, put(shadow, item, `mark ${text[0]}`, text[1]), box, top);
      if (!side) continue; // no room on either side: the panel carries this field
      if (text[0] === "check" || text[0] === "your_turn" || text[0] === "portal_error") {
        const o = put(shadow, item, `outline ${text[0]}`, null);
        o.style.left = `${box.left}px`;
        o.style.top = `${box.top}px`;
        o.style.width = `${box.width}px`;
        o.style.height = `${box.height}px`;
      }
      if (focusedKey === key && text[0] === "filled") {
        beside(item, put(shadow, item, "tag", lastLabels.why(key)), box, top + 22, side);
      }
      const held = item.record.view.state === "mismatch" && item.record.view.reason === "held_other";
      if (!chipDone && (text[0] === "your_turn" || text[0] === "portal_error" || held)) {
        beside(item, put(shadow, item, "chip", lastLabels.next), box, top + 22, side);
        chipDone = true;
      }
      item.record.view.placed = true;
    }
  }
  const after = Array.from(drawn.values(), (i) => i.record.view.placed).join();
  if (!quiet && before !== after) onChange?.();
}

export function clearMarks(): void {
  followScroll(false);
  observer?.disconnect();
  for (const item of drawn.values()) item.off?.();
  host?.remove();
  host = null; root = null; reattached = 0; drawn.clear(); focusedKey = null;
}

function markNode(item: Item): HTMLElement | undefined {
  return item.nodes.find((n) => n.classList.contains("mark"));
}

/** Test hooks: the page cannot read a closed root, so these read our own bookkeeping. */
export function marksForTest(): { key: string; state: string; placed: boolean; rect: { x: number; y: number; w: number; h: number } }[] {
  return Array.from(drawn, ([key, item]) => {
    const r = markNode(item)?.getBoundingClientRect();
    return { key, state: item.record.view.state, placed: item.record.view.placed,
             rect: { x: r?.x ?? 0, y: r?.y ?? 0, w: r?.width ?? 0, h: r?.height ?? 0 } };
  });
}
export function marksTextForTest(): string {
  return Array.from(drawn.values(), (i) => i.nodes.map((n) => n.textContent ?? "").join("\n")).join("\n");
}
