# Handoff — marketing site build via spec-to-site-orchestrator

Written 2026-08-20 for a fresh session. Everything below is verified, not assumed.

## What to do

Build the **marketing/landing site only** (not the product UI). Audience 18–25; it must
read dynamic and fresh. The `spec-to-site-orchestrator` skill is installed globally and
should trigger on a request like "build the landing site from idea_v2.md" — if it does
not fire, invoke it by name rather than working around it.

## Brief sources

- `idea_v2.md` — **authoritative** product source. §1 "Product and audience" is the part
  that matters for marketing copy.
- `phased requirements.md` — §2 product-wide rules, §3.3 technical requirements.
- One line worth knowing: idea_v2.md:19 says only *"The product should be a well-designed
  website."* There is no existing brand or visual direction to inherit. The pipeline will
  ask for reference URLs at `plan`; it never researches them itself.

## Product one-liner (derived, verify before using in copy)

A paid agentic platform that finds fully funded master's scholarships worldwide, checks
eligibility against the student's real profile, and runs the applications end to end.
Master's applicants only. Interface in English. Sold direct to students and white-labeled
to education agencies.

## Stack — already scaffolded, do not re-scaffold

`frontend/` holds Vite + React 19 + TypeScript + Tailwind v4 + shadcn/ui (Base UI, Nova
preset). Also installed: `react-bits` (registry verified, one component pulled),
`react-scan` (dev-only, gated behind `import.meta.env.DEV`), `shadergradient` + R3F/three,
`lenis`, GSAP.

The shadcn Nova/neutral preset currently in `frontend/src/index.css` is a **placeholder**,
not a design decision. Layer 1 token materialization at `plan` should replace it.

## Pipeline state

- `.specify/` is initialized; the `speckit-*` skills are installed.
- `.specify/memory/constitution.md` is **still the untouched spec-kit template** with
  `[PRINCIPLE_1_NAME]` placeholders. The `constitution` phase writes it — that is the
  first real step.
- No `spec.md` / `plan.md` / `tasks.md` exist yet. Nothing has been built.

Constitution inputs already located, so you need not hunt for them:
- a11y + spacing floor: `~/.claude/skills/ui-ux-pro-max/references/pro-rules.md`
  (§Layout & Spacing at line 49, §Accessibility at line 106)
- anti-slop bans: `~/.claude/skills/design-taste-frontend/SKILL.md` §4.7 line 234
  (hero discipline, eyebrow restraint max 1 per 3 sections, zigzag cap, split-header ban,
  layout-repetition ban), §9.G line 685 (em-dash ban)

## Higgsfield — verified live 2026-08-20

Connected, **Plus plan, 1000 credits**. All eight tool names in the skill resolve.

The asset phase was corrected against the real schemas (commit `0356a33`). Two gates, not
one: the manifest approval, **and** the `unlim_choice` question the server returns when
`use_unlim` is omitted. Put that second question to the human; never answer it for them.
Batches cap at 12 items.

## Uncommitted state in this repo

`phased requirements.md` has a 2-line uncommitted amendment (lines 312, 323) recording the
HTMX → React stack reversal with rationale. Commit it or keep it; it is deliberate, not
stray. All §2 security rules were verified untouched by that edit.

## Related work not yet merged

`~/claude-skills` on branch `feat/spec-to-site-orchestrator`, 10 commits, unmerged. That is
the orchestrator skill itself. The globally installed copy is a **detached copy** — editing
the repo does not update the live skill without re-running
`npx skills add . --skill spec-to-site-orchestrator -g -y`.

## Known constraints that bind the build

- `phased requirements.md:268` prohibits tenant-provided CSS, JavaScript and HTML. It binds
  harder under React than it did server-rendered. `brand_primary_color` remains the only
  tenant-variable value.
- Platform interface stays in English (idea_v2.md:11).
- No refund, cancellation, or outcome guarantee may be promised in copy
  (idea_v2.md:74) — this constrains marketing claims directly.
- Do not claim guaranteed funding or outcomes anywhere in copy; §2 forbids inferring
  guaranteed funding, and that discipline extends to marketing language.
