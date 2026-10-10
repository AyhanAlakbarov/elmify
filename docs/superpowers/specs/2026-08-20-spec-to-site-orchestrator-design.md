# spec-to-site-orchestrator — Design

**Date:** 2026-08-20
**Status:** Approved design, not yet implemented
**Type:** Reusable agent skill (portable across projects)

## Problem

A dozen design, animation, asset, and QA skills are installed, plus the Higgsfield
MCP and spec-kit's SDD pipeline. Nothing decides *which* fires *when*. The result
is skill collision — multiple skills claiming design authority simultaneously — and
aesthetic decisions made early that are silently lost by the time components are
built.

This skill is the conductor. It owns no phases of its own; it declares which skills
fire at each spec-kit phase, behind which approval gate, and how decisions made
early are mechanically enforced later.

## Non-goals

- **Not a replacement for spec-kit.** All spec/plan/task mechanics stay in spec-kit.
- **Not a state machine.** spec-kit's `spec.md` / `plan.md` / `tasks.md` already
  carry pipeline state across sessions. A parallel state file would duplicate and
  eventually contradict it.
- **Not executable code.** The job — invoke the right skill at the right moment — is
  instructions, not software. No scripts, no orchestration runtime.
- **Not a design researcher.** Reference selection is the human's job. The pipeline
  *asks* for references at `plan` and consumes what it is given; it does not go find
  them. If the human supplies none, it proceeds on `ui-ux-pro-max` tokens alone and
  says so explicitly, so the resulting direction is understood to be unreferenced.

## Identity

| Field | Value |
|---|---|
| Name | `spec-to-site-orchestrator` |
| Home | `~/claude-skills/skills/` (version-controlled, portable) |
| Install | Global, so it is available in every project |
| Structure | Single `SKILL.md`; split into reference files only if it exceeds ~400 lines |

**Description (the trigger — load-bearing, since Claude Code selects skills by
description match):**

> Use when building a website or web app from a brief, idea file, or product
> description — greenfield builds, full redesigns, or adding a major new surface.

The name encodes input → output → role, deliberately delineating this from any
future SEO or web-data-extraction pipeline.

## Architecture: thin conductor over spec-kit

```
constitution → specify → [clarify] → plan → ASSETS → tasks → implement → QA → refine
                                              ▲                            │
                                              └──────── loop ──────────────┘
```

`ASSETS`, `QA`, and `refine` are the only phases this skill adds. Everything else
is spec-kit's, unmodified.

### Phase routing table

| Phase | Skills that fire | Gate |
|---|---|---|
| `speckit-constitution` | `ui-ux-pro-max` (a11y + spacing floor), `design-taste-frontend` (anti-slop bans) → written as project principles | — |
| `speckit-specify` | `copywriting` (**macro-copy only**: H1/H2, value props, SEO narrative, content structure), structure and user journeys | ✋ approve |
| `speckit-clarify` | *(optional)* de-risk ambiguity before planning | — |
| `speckit-plan` | **Stack detection** → skill profile. **Prompt the human for reference URLs**, then references + `ui-ux-pro-max` tokens → `DESIGN.md`. Token materialization (Layer 1). Asset manifest derived. | ✋ approve |
| **ASSETS** | Higgsfield MCP: manifest → batch generate → land in repo | ✋ approve manifest **before credits are spent** |
| `speckit-tasks` | Decompose; annotate tasks with non-tokenizable design constraints (Layer 2) | ✋ approve |
| `speckit-analyze` | *(optional)* cross-artifact consistency check before building | — |
| `speckit-implement` | **Candidates**, loaded just-in-time per task (see below): `design-taste-frontend` (guardrails), `emil-design-eng` + `animate` (motion decisions), `gsap-*` (implementation), `shadcn`/`react-bits` (components), `copywriting` + `frontend-design` (**micro-copy**) | — |
| **QA** | `impeccable /audit`, `web-design-guidelines`, `react-scan` *(React only)*, `playwright` MCP | all must clear |
| **refine** | `impeccable /polish`, `/critique` → loop back to `implement` or `QA` | — |

## Stack adaptation

The skill carries **no** knowledge of individual stacks. It reads the stack from
spec-kit's `plan.md` (which already binds it) and cross-checks against
`package.json` / `manage.py` / `pyproject.toml`. It then routes on two axes only:

| Concern | React | Server-rendered |
|---|---|---|
| Components | `shadcn` + `react-bits` | hand-authored |
| Animation | `gsap-react` + `emil-design-eng` | `gsap-core` |
| Perf QA | `react-scan` | Lighthouse via `playwright` |
| Framework rules | `vercel-react-best-practices` | — |

Stack-agnostic skills always fire: `ui-ux-pro-max`, `design-taste-frontend`,
`impeccable`, `web-design-guidelines`, `copywriting`, `frontend-design`.
`ui-ux-pro-max` receives the stack *name* and performs its own 22-stack lookup
internally — that is why this skill does not need stack knowledge of its own.

**Degradation:** a skill that is not installed is skipped with an explicit note,
never a hard failure. Required for portability to projects that lack some of these.

## Copywriting: the macro/micro split

Scoping all copy to `specify` fails predictably: unmapped UI states surface during
implementation and get filled with generic placeholders ("Submit", "Error occurred").

- **Macro-copy at `specify`** — H1/H2, value propositions, SEO narrative, content
  structure. Locked early because *layout wraps around content*, not the reverse.
  Owner: `copywriting`.
- **Micro-copy at `implement`** — button labels, empty states, error toasts,
  tooltips, loading text. Cannot be enumerated in a static spec. Owners:
  `copywriting` (conversion) + `frontend-design` (interface voice, cross-flow
  consistency).

`frontend-design`'s "More on writing in design" section is the micro-copy authority:
active voice, a control naming exactly what it does ("Save changes", not "Submit"),
an action keeping its name across a whole flow, errors that explain the fix rather
than apologize, empty states as invitations to act. Assigning it this role also
resolves its former redundancy as a competing design authority.

## The three-layer memory model

The problem: aesthetic decisions made at `plan` must still govern at `implement`,
possibly in a different session, under context pressure. A markdown file alone is
advisory and loses to context pressure. Three layers, strongest first.

### Layer 1 — materialize tokens into code

`DESIGN.md` decisions compile into CSS custom properties and the `@theme` block that
shadcn already generates. A value living only in markdown is a suggestion; a value
living in `var(--primary)` is load-bearing — components reference it and therefore
cannot drift from it.

**Visual tokens:** color (with roles, not just hexes), typography scale, spacing,
radius.

**Motion tokens (equally governed):** the kinetic identity is part of the design
contract, not an implementation detail. Core easings and durations are defined in
`DESIGN.md` and compiled to CSS custom properties:

```css
:root {
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-exit:   cubic-bezier(0.4, 0, 1, 1);
  --duration-fast: 150ms;
  --duration-base: 300ms;
}
```

**GSAP bridge.** GSAP cannot consume CSS custom properties natively — its eases are
registered strings (`power2.out`) or `CustomEase` instances, and its durations are
seconds, while CSS uses `cubic-bezier()` and milliseconds. One source, two consumers:
a small `motion.ts` reads the custom properties once at startup via
`getComputedStyle(document.documentElement)`, converts ms → s, registers the
cubic-beziers as `CustomEase` instances, and exports GSAP-ready values.

**Rule:** GSAP calls and React animation hooks reference the exported tokens. Numeric
durations and string easings are never hardcoded in component logic.

### Layer 2 — annotate tasks with what cannot be tokenized

Layout concepts, the signature element, motion *character* (as distinct from its
numeric values), and anti-references have no CSS variable to live in. These are
written directly into the relevant `tasks.md` entries at the `tasks` phase, so each
task carries its own constraints and `implement` never needs the whole ledger in
context.

### Layer 3 — audit catches the leak

`impeccable /audit` at the QA gate flags values that bypassed tokenization — both
hardcoded hex codes **and hardcoded animation timings**. This is the backstop for
drift that escaped Layers 1 and 2, and it is what makes the interface's physical
character as strictly governed as its visual character.

`DESIGN.md` remains the human-readable source of truth and the place decisions get
argued. Layers 1–2 are its machine-enforced projections; Layer 3 is the detector
watching for divergence.

## Just-in-time library inspection

The routing table names *candidate* skills per phase. It is not a load list. At
`implement`, loading every candidate upfront would burn the context window on
material the current task does not need — 165 `react-bits` components, eight
`gsap-*` skills, and `impeccable`'s 34 reference files, most of them irrelevant to
any single component.

**Rule:** resolve capability → skill → load, per task, at the moment of need.

- Read the task's Layer 2 annotations first; they name the capability required.
- Load **only** the matching skill. A scroll animation loads `gsap-scrolltrigger`,
  not the whole `gsap-*` family. A polish pass reads `impeccable`'s `polish.md`,
  not its full reference set.
- Look up component and library APIs at point of use — the `context7` MCP for live
  library docs, the `shadcn` registry for a specific component — rather than
  pre-loading catalogs.
- `pick-ui-library` fires when a library choice is actually open, not preemptively.

This is why the routing table lists candidates rather than sequences: the task
decides what loads, and unloaded skills cost nothing.

## Artifacts

### `DESIGN.md` (project root)

Replaces what `refero-design` formerly owned. Written at `plan`, amended during
`refine`.

- **Direction** — reference URLs the human picked, and why each
- **Tokens** — visual and motion, values *and roles*
- **Signature** — the one element the site is remembered by
- **Anti-references** — what to avoid, explicitly
- **Decisions log** — dated entries: what changed and why

### `assets/manifest.json`

Derived at the ASSETS phase, shown in full before any credits are spent.

Per entry: surface (hero, testimonial, og-image, texture), kind (image/video/3d),
prompt, model, count. On approval, batch generation runs via
`generate_image_batch` / `generate_video_batch` + `jobs_wait`; resulting ids and
local paths are written back into the same file.

## QA gate

A build is not done until all four clear:

| Check | Passing means |
|---|---|
| `impeccable /audit` | Findings addressed or explicitly waived (incl. hardcoded colors and timings) |
| `web-design-guidelines` | WIG compliance |
| `react-scan` *(React only)* | No flagged unnecessary re-renders |
| `playwright` MCP | Renders clean, no console errors, responsive at mobile + desktop, keyboard focus visible |

## Failure handling

- **Failed gate** → stop and report. Never silently proceed.
- **Failed Higgsfield job** → retry once, then continue with the asset marked `TODO`
  in the manifest rather than blocking the entire build.
- **Missing skill** → skip with an explicit note.
- **Stack mismatch** (detected stack disagrees with `plan.md`) → stop and report;
  do not guess which is authoritative.

## Deferred

- Reference files (`references/*.md`) — only if `SKILL.md` exceeds ~400 lines.
- Unattended long-run support (a resumable state file) — only if the pipeline is
  ever run walk-away rather than attended.
- Non-React, non-server-rendered profiles (native, e-mail) — add when a real project
  needs one.
