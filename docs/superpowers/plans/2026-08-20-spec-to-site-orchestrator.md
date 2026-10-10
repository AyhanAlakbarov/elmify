# spec-to-site-orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable agent skill that conducts spec-kit's phases and routes design, asset, and QA skills to the right moment, so aesthetic decisions made at planning time are mechanically enforced at build time.

**Architecture:** A single `SKILL.md` of instructions — no executable orchestration. The skill owns no pipeline phases; spec-kit keeps all spec/plan/task mechanics and state. A stdlib-only Python validator guards the one failure mode that has already bitten this setup twice: a routing table naming skills that were renamed or deleted.

**Tech Stack:** Markdown (the skill), Python 3.12 stdlib (the validator). No dependencies, no test framework, no build step.

**Spec:** `docs/superpowers/specs/2026-08-20-spec-to-site-orchestrator-design.md`

## Global Constraints

- Skill home: `~/claude-skills/skills/spec-to-site-orchestrator/` — version-controlled, portable.
- `SKILL.md` must stay **under 400 lines**. Split into `references/*.md` only if it crosses that.
- The skill is **instructions, not code**. Code blocks inside it are templates the pipeline emits later; they are never executed by the skill itself.
- The skill **owns no phases**. Every spec/plan/task mechanic defers to spec-kit.
- **Degradation:** a skill that is not installed is skipped at runtime with an explicit note, never a hard failure.
- **JIT loading:** the routing table lists *candidates*, not a load list. Resolve capability → skill → load, per task.
- Skill names must match installed reality exactly: `design-taste-frontend` (not `taste-skill`), `emil-design-eng`, `impeccable`, `ui-ux-pro-max`, `web-design-guidelines`, `frontend-design`, `copywriting`, `animate`, `pick-ui-library`, `vercel-react-best-practices`, `gsap-core`, `gsap-react`, `gsap-scrolltrigger`, `playwright-cli`.
- Retired, must NOT appear as routed skills: `refero-design`, `design-discovery`, `taste-skill`.

---

### Task 1: Validator and skill skeleton

**Files:**
- Create: `~/claude-skills/skills/spec-to-site-orchestrator/SKILL.md`
- Create: `~/claude-skills/skills/spec-to-site-orchestrator/validate.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `validate.py` runnable as `python3 validate.py`, exiting `0` on pass and `1` on failure. `SKILL.md` containing a `<!-- validator:skills -->` … `<!-- /validator:skills -->` block that every later task appends routed skill names to. Later tasks add sections to `SKILL.md` and re-run this validator unchanged.

- [ ] **Step 1: Write the failing validator**

Create `~/claude-skills/skills/spec-to-site-orchestrator/validate.py`:

```python
#!/usr/bin/env python3
"""Validate SKILL.md structure and that every routed skill actually exists.

Run from this directory:  python3 validate.py
Exits 0 on pass, 1 on failure.

Guards the failure mode that has already occurred twice in this setup:
a routing table naming a skill that was since renamed or deleted.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
SKILL = HERE / "SKILL.md"
MAX_LINES = 400
RETIRED = {"refero-design", "design-discovery", "taste-skill"}
SEARCH_ROOTS = [
    Path.home() / ".claude" / "skills",
    Path.cwd() / ".claude" / "skills",
]


def frontmatter(text: str) -> dict[str, str]:
    """Parse the leading --- fenced YAML-ish block into a flat dict."""
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def routed_skills(text: str) -> list[str]:
    """Extract skill names from the validator:skills block."""
    match = re.search(
        r"<!-- validator:skills -->(.*?)<!-- /validator:skills -->", text, re.DOTALL
    )
    if not match:
        return []
    return re.findall(r"^\s*-\s+([a-z0-9][a-z0-9-]*)\s*$", match.group(1), re.MULTILINE)


def is_installed(name: str) -> bool:
    """A skill is installed if a directory of that name sits directly in a skill root."""
    return any((root / name).is_dir() for root in SEARCH_ROOTS)


def main() -> int:
    if not SKILL.exists():
        print(f"FAIL: {SKILL} does not exist")
        return 1

    text = SKILL.read_text()
    errors = []

    meta = frontmatter(text)
    if meta.get("name") != "spec-to-site-orchestrator":
        errors.append(f"frontmatter name must be spec-to-site-orchestrator, got {meta.get('name')!r}")
    description = meta.get("description", "")
    if len(description) < 40:
        errors.append("frontmatter description missing or too short to trigger on")
    if "Use when" not in description:
        errors.append("description must state an observable trigger starting 'Use when'")

    line_count = len(text.splitlines())
    if line_count > MAX_LINES:
        errors.append(f"SKILL.md is {line_count} lines, limit is {MAX_LINES}")

    skills = routed_skills(text)
    if not skills:
        errors.append("no validator:skills block found, or it is empty")
    for name in skills:
        if name in RETIRED:
            errors.append(f"{name} is retired and must not be routed")
        elif not is_installed(name):
            errors.append(f"routed skill {name!r} is not installed anywhere")

    for message in errors:
        print(f"FAIL: {message}")
    if errors:
        return 1
    print(f"PASS: {line_count} lines, {len(skills)} routed skills, all installed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/claude-skills/skills/spec-to-site-orchestrator && python3 validate.py
```

Expected: `FAIL: .../SKILL.md does not exist`, exit code 1.

- [ ] **Step 3: Write the minimal SKILL.md to pass**

Create `~/claude-skills/skills/spec-to-site-orchestrator/SKILL.md`:

```markdown
---
name: spec-to-site-orchestrator
description: Use when building a website or web app from a brief, idea file, or product description — greenfield builds, full redesigns, or adding a major new surface. Conducts spec-kit's phases and routes design, asset, and QA skills to each one.
---

# Spec to Site Orchestrator

Conducts a website build from brief to shipped interface. Routes the right design,
asset, and QA skill to each spec-kit phase, and makes aesthetic decisions made at
planning time survive until build time.

## What this skill does not do

- **It owns no phases.** spec-kit keeps all spec/plan/task mechanics and pipeline
  state. This skill declares what fires where; it does not re-implement planning.
- **It is not a state machine.** `spec.md` / `plan.md` / `tasks.md` already carry
  state across sessions. Do not create a parallel state file.
- **It is not a design researcher.** Reference selection is the human's job. Ask for
  references at `plan`; never go hunting for them. If the human supplies none,
  proceed on `ui-ux-pro-max` tokens alone and say so explicitly, so the direction is
  understood to be unreferenced.
- **It is not code.** Code blocks below are templates to emit into the target
  project. Nothing here executes.

## Pipeline

```
constitution → specify → [clarify] → plan → ASSETS → tasks → [analyze] → implement → QA → refine
                                              ▲                                        │
                                              └──────────────── loop ──────────────────┘
```

`ASSETS`, `QA`, and `refine` are the only phases this skill adds. The rest are
spec-kit's, unmodified.

## Routed skills

Every skill this pipeline may invoke. Validated against installed reality by
`validate.py`.

<!-- validator:skills -->
- ui-ux-pro-max
- design-taste-frontend
- emil-design-eng
- impeccable
- web-design-guidelines
- frontend-design
- copywriting
- animate
- pick-ui-library
- vercel-react-best-practices
- gsap-core
- gsap-react
- gsap-scrolltrigger
- playwright-cli
<!-- /validator:skills -->
```

- [ ] **Step 4: Run the validator to verify it passes**

```bash
cd ~/claude-skills/skills/spec-to-site-orchestrator && python3 validate.py
```

Expected: `PASS: <n> lines, 14 routed skills, all installed`, exit code 0.

- [ ] **Step 5: Verify the retired-skill guard actually works**

Temporarily add `- refero-design` inside the `validator:skills` block, re-run, and confirm it reports `FAIL: refero-design is retired and must not be routed`. Then remove that line and confirm PASS again. This proves the guard is live rather than dead code.

- [ ] **Step 6: Commit**

```bash
cd ~/claude-skills
git add skills/spec-to-site-orchestrator/
git commit -m "feat: skill skeleton and reference validator for spec-to-site-orchestrator"
```

---

### Task 2: Phase routing table and stack detection

**Files:**
- Modify: `~/claude-skills/skills/spec-to-site-orchestrator/SKILL.md` (append after the Routed skills section)

**Interfaces:**
- Consumes: `SKILL.md` and `validate.py` from Task 1; the `validator:skills` list is already complete and must not change.
- Produces: a `## Phase routing` section and a `## Stack detection` section. Task 3's JIT rule refers to the routing table as "candidates"; Task 4's Layer 2 refers to the `tasks` row's annotation step.

- [ ] **Step 1: Append the routing and stack-detection sections**

```markdown
## Phase routing

Each row lists which skills *may* fire at that phase. This is a candidate list, not
a load list — see Just-in-time loading below.

| Phase | Candidate skills | Gate |
|---|---|---|
| `speckit-constitution` | `ui-ux-pro-max` (a11y and spacing floor), `design-taste-frontend` (anti-slop bans) → written as project principles | — |
| `speckit-specify` | `copywriting` (**macro-copy only**), structure and user journeys | approve |
| `speckit-clarify` | *(optional)* de-risk ambiguity before planning | — |
| `speckit-plan` | **Stack detection** → profile. Ask the human for reference URLs, then references + `ui-ux-pro-max` tokens → `DESIGN.md`. Materialize tokens (Layer 1). Derive asset manifest. | approve |
| **ASSETS** | Higgsfield MCP: manifest → batch generate → land in repo | approve manifest **before credits are spent** |
| `speckit-tasks` | Decompose; annotate tasks with non-tokenizable constraints (Layer 2) | approve |
| `speckit-analyze` | *(optional)* cross-artifact consistency check | — |
| `speckit-implement` | Per task, JIT: `design-taste-frontend`, `emil-design-eng`, `animate`, `gsap-*`, `shadcn`/`react-bits`, `copywriting` + `frontend-design` (micro-copy) | — |
| **QA** | `impeccable`, `web-design-guidelines`, `react-scan` *(React only)*, `playwright` MCP | all must clear |
| **refine** | `impeccable` polish and critique → loop back | — |

## Stack detection

Carry no per-stack knowledge. Read the stack from spec-kit's `plan.md`, which
already binds it, and cross-check against what is on disk:

| Evidence | Stack |
|---|---|
| `package.json` with `react` dependency | React |
| `package.json` with `next` dependency | React (Next) |
| `manage.py` + `pyproject.toml` | Django, server-rendered |
| `composer.json` | Laravel, server-rendered |
| `Gemfile` | Rails, server-rendered |

If detected stack and `plan.md` disagree, **stop and report**. Do not guess which is
authoritative.

Route on two axes only:

| Concern | React | Server-rendered |
|---|---|---|
| Components | `shadcn` + `react-bits` | hand-authored |
| Animation | `gsap-react` + `emil-design-eng` | `gsap-core` |
| Perf QA | `react-scan` | Lighthouse via `playwright` |
| Framework rules | `vercel-react-best-practices` | — |

Everything else is stack-agnostic and always applies: `ui-ux-pro-max`,
`design-taste-frontend`, `impeccable`, `web-design-guidelines`, `copywriting`,
`frontend-design`. Hand `ui-ux-pro-max` the stack *name* and let it do its own
22-stack lookup internally — that is why this skill needs no stack knowledge.

**Degradation:** if a routed skill is not installed, skip it and say so explicitly in
the run. Never fail the pipeline over a missing skill.
```

- [ ] **Step 2: Run the validator**

```bash
cd ~/claude-skills/skills/spec-to-site-orchestrator && python3 validate.py
```

Expected: PASS, still 14 routed skills, line count still under 400.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-skills
git add skills/spec-to-site-orchestrator/SKILL.md
git commit -m "feat: phase routing table and two-axis stack detection"
```

---

### Task 3: Just-in-time loading rules

**Files:**
- Modify: `~/claude-skills/skills/spec-to-site-orchestrator/SKILL.md` (append)

**Interfaces:**
- Consumes: the `## Phase routing` table from Task 2, which this section reinterprets as candidates.
- Produces: a `## Just-in-time loading` section. Task 4's Layer 2 annotations are the input this rule reads to decide what to load.

- [ ] **Step 1: Append the JIT section**

```markdown
## Just-in-time loading

The routing table names candidates. It is not a load list. Loading every candidate
at `implement` burns context on material the current task does not need: 165
`react-bits` components, eight `gsap-*` skills, and `impeccable`'s 34 reference
files, nearly all irrelevant to any one component.

**Rule: resolve capability → skill → load, per task, at the moment of need.**

1. Read the task's Layer 2 annotations first. They name the capability required.
2. Load only the matching skill:
   - scroll-linked animation → `gsap-scrolltrigger`, not the whole `gsap-*` family
   - a polish pass → `impeccable`'s `polish.md`, not its full reference set
   - motion feel decisions → `emil-design-eng` or `animate`, only when the task animates
3. Look up library APIs at point of use — the `context7` MCP for live library docs,
   the `shadcn` registry for one specific component — rather than pre-loading catalogs.
4. `pick-ui-library` fires only when a library choice is genuinely open.

Unloaded skills cost nothing. A task that renders a static section should finish
without ever loading an animation skill.
```

- [ ] **Step 2: Run the validator**

```bash
cd ~/claude-skills/skills/spec-to-site-orchestrator && python3 validate.py
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-skills
git add skills/spec-to-site-orchestrator/SKILL.md
git commit -m "feat: just-in-time skill loading rules"
```

---

### Task 4: Three-layer design memory

**Files:**
- Modify: `~/claude-skills/skills/spec-to-site-orchestrator/SKILL.md` (append)

**Interfaces:**
- Consumes: the `plan` and `tasks` rows from Task 2's routing table; the JIT rule from Task 3 reads the Layer 2 annotations this section defines.
- Produces: a `## Design memory` section defining `DESIGN.md`, the token CSS template, the `motion.ts` bridge template, task annotation format, and the audit backstop. Task 7's QA gate asserts against the Layer 3 rule stated here.

- [ ] **Step 1: Append the design-memory section**

````markdown
## Design memory

Decisions made at `plan` must still govern at `implement`, possibly in a later
session under context pressure. A markdown file alone is advisory and loses to
context pressure. Three layers, strongest first.

### Layer 1 — materialize tokens into code

Compile `DESIGN.md` decisions into CSS custom properties. A value living only in
markdown is a suggestion; a value living in `var(--primary)` is load-bearing —
components reference it and cannot drift from it.

Visual tokens: color (with roles, not just hexes), type scale, spacing, radius.

**Motion tokens are governed exactly as strictly.** The kinetic identity is part of
the design contract, not an implementation detail:

```css
:root {
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-exit: cubic-bezier(0.4, 0, 1, 1);
  --duration-fast: 150ms;
  --duration-base: 300ms;
}
```

**GSAP bridge.** GSAP cannot read CSS custom properties natively — its eases are
registered strings or `CustomEase` instances and its durations are seconds, while
CSS uses `cubic-bezier()` and milliseconds. One source, two consumers. Emit this
into the target project (client-side only; it reads the DOM at module load):

```ts
// src/lib/motion.ts
import { gsap } from 'gsap'
import { CustomEase } from 'gsap/CustomEase'

gsap.registerPlugin(CustomEase)

const readVar = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim()

const toSeconds = (value: string) =>
  value.endsWith('ms') ? parseFloat(value) / 1000 : parseFloat(value)

function registerEase(name: string, cssVar: string): string {
  const points = readVar(cssVar).match(/-?[\d.]+/g)
  if (!points || points.length !== 4) {
    throw new Error(`${cssVar} is not a cubic-bezier: ${readVar(cssVar)}`)
  }
  const [x1, y1, x2, y2] = points
  CustomEase.create(name, `M0,0 C${x1},${y1} ${x2},${y2} 1,1`)
  return name
}

export const ease = {
  spring: registerEase('ease-spring', '--ease-spring'),
  exit: registerEase('ease-exit', '--ease-exit'),
}

export const duration = {
  fast: toSeconds(readVar('--duration-fast')),
  base: toSeconds(readVar('--duration-base')),
}
```

**Rule:** GSAP calls and animation hooks import from `motion.ts`. Numeric durations
and string easings are never hardcoded in component logic. CSS transitions use the
custom properties directly.

### Layer 2 — annotate tasks with what cannot be tokenized

Layout concepts, the signature element, motion *character* as distinct from its
numeric values, and anti-references have no CSS variable to live in. Write these
directly into the relevant `tasks.md` entries at the `tasks` phase, so each task
carries its own constraints and `implement` never needs the whole ledger in context.

Annotation format, appended to a task in `tasks.md`:

```markdown
**Design constraints:**
- Signature: asymmetric split hero, image bleeds past the right gutter
- Motion character: arrives settled, never bouncy — use `ease.exit`, not `ease.spring`
- Anti-reference: no centered three-card row
```

### Layer 3 — audit catches the leak

At the QA gate, `impeccable`'s audit flags values that bypassed tokenization — both
hardcoded hex codes **and hardcoded animation timings**. This is the backstop for
drift that escaped Layers 1 and 2, and it is what keeps the interface's physical
character as strictly governed as its visual character.

`DESIGN.md` stays the human-readable source of truth and the place decisions get
argued. Layers 1 and 2 are its machine-enforced projections; Layer 3 watches for
divergence.

### `DESIGN.md` contents

Written at `plan`, amended during `refine`:

- **Direction** — the reference URLs the human picked, and why each
- **Tokens** — visual and motion, values *and roles*
- **Signature** — the one element the site is remembered by
- **Anti-references** — what to avoid, explicitly
- **Decisions log** — dated entries: what changed and why
````

- [ ] **Step 2: Run the validator**

```bash
cd ~/claude-skills/skills/spec-to-site-orchestrator && python3 validate.py
```

Expected: PASS. If line count now exceeds 400, split this section into `references/design-memory.md` and link to it from `SKILL.md`, then re-run.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-skills
git add skills/spec-to-site-orchestrator/
git commit -m "feat: three-layer design memory with motion tokens and GSAP bridge"
```

---

### Task 5: Macro/micro copy split

**Files:**
- Modify: `~/claude-skills/skills/spec-to-site-orchestrator/SKILL.md` (append)

**Interfaces:**
- Consumes: the `specify` and `implement` rows from Task 2's routing table.
- Produces: a `## Copy` section assigning `copywriting` to macro-copy and `copywriting` + `frontend-design` to micro-copy.

- [ ] **Step 1: Append the copy section**

```markdown
## Copy

Scoping all copy to `specify` fails predictably: unmapped UI states surface during
implementation and get filled with generic placeholders — "Submit", "Error occurred".
Split it.

**Macro-copy at `specify`** — H1/H2, value propositions, SEO narrative, content
structure. Locked early because *layout wraps around content*, not the reverse.
Owner: `copywriting`.

**Micro-copy at `implement`** — button labels, empty states, error toasts, tooltips,
loading text. These cannot be enumerated in a static spec. Owners: `copywriting` for
conversion, `frontend-design` for interface voice and cross-flow consistency.

`frontend-design`'s "More on writing in design" section is the micro-copy authority:

- Active voice; a control names exactly what it does — "Save changes", not "Submit"
- An action keeps its name across the whole flow: a "Publish" button produces a
  "Published" toast
- Errors explain what happened and how to fix it; they never apologize and are never
  vague
- Empty states are invitations to act, not decoration
- Each element does one job — a label labels, an example demonstrates
```

- [ ] **Step 2: Run the validator**

```bash
cd ~/claude-skills/skills/spec-to-site-orchestrator && python3 validate.py
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-skills
git add skills/spec-to-site-orchestrator/SKILL.md
git commit -m "feat: macro/micro copy split with frontend-design as micro-copy owner"
```

---

### Task 6: Asset phase

**Files:**
- Modify: `~/claude-skills/skills/spec-to-site-orchestrator/SKILL.md` (append)

**Interfaces:**
- Consumes: the `ASSETS` row from Task 2's routing table.
- Produces: an `## Asset phase` section defining `assets/manifest.json` and the credit gate. Task 7's failure handling refers to the `TODO` status defined here.

- [ ] **Step 1: Append the asset section**

````markdown
## Asset phase

Runs between `plan` and `tasks`, so components are built against real assets rather
than placeholders. Designing layouts around gray boxes produces layouts that fit gray
boxes.

**1. Derive the manifest** from the spec and `DESIGN.md`. Write
`assets/manifest.json`:

```json
{
  "assets": [
    {
      "id": "hero-loop",
      "surface": "hero",
      "kind": "video",
      "prompt": "slow aerial drift over terraced hillside at dawn, muted teal grade",
      "model": "auto",
      "count": 1,
      "status": "pending"
    }
  ]
}
```

**2. Show the full manifest and stop.** This is the only cost checkpoint in the
pipeline. Higgsfield generation spends real credits — never generate before the
human has seen what and how much.

**3. On approval, batch generate.** Use `generate_image_batch` /
`generate_video_batch` with `jobs_wait`, not one call per asset. Call
`models_explore` with `action: 'recommend'` when `"model": "auto"` and the right
model is unclear.

**4. Write results back** into the same file: set `status` to `done`, add the
returned `generation_id` and the local path.

Higgsfield also covers: `generate_3d` for GLB meshes when the stack has a 3D
surface, `remove_background` for product cutouts, and `upscale_image` /
`upscale_video` for a final quality pass. Reach for these only when the manifest
calls for them.
````

- [ ] **Step 2: Run the validator**

```bash
cd ~/claude-skills/skills/spec-to-site-orchestrator && python3 validate.py
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-skills
git add skills/spec-to-site-orchestrator/SKILL.md
git commit -m "feat: Higgsfield asset phase with manifest cost gate"
```

---

### Task 7: QA gate and failure handling

**Files:**
- Modify: `~/claude-skills/skills/spec-to-site-orchestrator/SKILL.md` (append)

**Interfaces:**
- Consumes: the `QA` and `refine` rows from Task 2; the Layer 3 rule from Task 4; the manifest `status` field from Task 6.
- Produces: the final two sections of `SKILL.md`. After this task the skill is content-complete and Task 8 installs it.

- [ ] **Step 1: Append the QA and failure sections**

```markdown
## QA gate

A build is not done until all four clear. Run them after `implement`, before
declaring anything finished.

| Check | Passing means |
|---|---|
| `impeccable` audit | Findings addressed or explicitly waived — including hardcoded colors and hardcoded animation timings (Layer 3) |
| `web-design-guidelines` | Web Interface Guidelines compliance |
| `react-scan` *(React only)* | No flagged unnecessary re-renders |
| `playwright` MCP | Renders clean, no console errors, responsive at mobile and desktop, keyboard focus visible |

Report each result explicitly. Never claim a check passed without having run it.

## Failure handling

- **Failed gate** → stop and report. Never silently proceed.
- **Failed Higgsfield job** → retry once. If it fails again, set that asset's
  `status` to `"TODO"` in `assets/manifest.json` and continue the build rather than
  blocking it. Report which assets are outstanding.
- **Missing skill** → skip it with an explicit note. Never fail the pipeline over a
  skill that is not installed.
- **Stack mismatch** — detected stack disagrees with `plan.md` → stop and report. Do
  not guess which is authoritative.
```

- [ ] **Step 2: Run the validator**

```bash
cd ~/claude-skills/skills/spec-to-site-orchestrator && python3 validate.py
```

Expected: PASS, line count still under 400.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-skills
git add skills/spec-to-site-orchestrator/SKILL.md
git commit -m "feat: QA gate and failure handling rules"
```

---

### Task 8: Install globally and smoke test

**Files:**
- Modify: none (installation and verification only)

**Interfaces:**
- Consumes: the complete `SKILL.md` from Tasks 1–7.
- Produces: the skill installed and discoverable in a fresh session; a recorded smoke-test result.

- [ ] **Step 1: Install globally**

```bash
cd ~/claude-skills
npx --yes skills add . --skill spec-to-site-orchestrator -g -y
```

Expected: installation summary naming `spec-to-site-orchestrator`.

- [ ] **Step 2: Verify it is discoverable**

```bash
ls -l ~/.claude/skills/spec-to-site-orchestrator
```

Expected: the directory or symlink exists.

- [ ] **Step 3: Verify the trigger fires**

In a **new** Claude Code session, in any directory, type:

> I want to build a landing page from this brief.

Expected: the model announces it is using `spec-to-site-orchestrator`. If it does not fire, the `description` frontmatter is the cause — it is the only thing Claude Code matches on. Widen the observable triggers in it, re-run `validate.py`, and retry. Do not rename the skill to fix a trigger problem.

- [ ] **Step 4: Smoke test the routing, without building anything**

In that session, ask:

> Walk me through which skills you'd invoke at each phase for a React marketing site, without doing any work.

Expected: it names stack detection first, then routes React-side skills (`shadcn`/`react-bits`, `gsap-react`, `react-scan`) rather than server-rendered ones, treats the routing table as candidates rather than loading everything, and names the manifest approval as a cost gate. If it loads skills eagerly, the JIT section from Task 3 needs strengthening.

- [ ] **Step 5: Commit any fixes**

```bash
cd ~/claude-skills
git add skills/spec-to-site-orchestrator/
git commit -m "fix: adjust trigger description after smoke test"
```

Skip this step if Steps 3 and 4 passed without changes.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Identity (name, home, description trigger) | 1 |
| Non-goals (owns no phases, not a state machine, not a researcher, not code) | 1 |
| Pipeline diagram | 1 |
| Phase routing table | 2 |
| Stack adaptation (two axes) | 2 |
| Degradation on missing skill | 2 (stated), 7 (failure handling) |
| Just-in-time library inspection | 3 |
| Layer 1 — tokens, visual and motion, GSAP bridge | 4 |
| Layer 2 — task annotations | 4 |
| Layer 3 — audit backstop | 4 (defined), 7 (enforced at gate) |
| `DESIGN.md` contents | 4 |
| Macro/micro copy split | 5 |
| `assets/manifest.json` and credit gate | 6 |
| QA gate, four checks | 7 |
| Failure handling, four cases | 7 |
| Deferred items (reference files, state file, extra profiles) | Not implemented — correctly deferred per spec |

No gaps.

**Placeholder scan:** The only `TODO` and `TBD`-shaped strings are the literal
manifest `status` value `"TODO"` (Task 6, Task 7), which is intended content rather
than an unfinished instruction. No "add appropriate error handling", no "similar to
Task N", no undefined references.

**Type consistency:** `validate.py`'s `routed_skills()`, `frontmatter()`, and
`is_installed()` are defined once in Task 1 and re-run unchanged in Tasks 2–7. The
`<!-- validator:skills -->` marker is identical everywhere it appears. `ease.spring`
/ `ease.exit` / `duration.fast` / `duration.base` exported by `motion.ts` in Task 4
match the CSS custom property names `--ease-spring` / `--ease-exit` /
`--duration-fast` / `--duration-base` defined immediately above them, and the Layer 2
annotation example references `ease.exit` and `ease.spring` by those same names. The
manifest `status` field takes `pending` → `done` | `TODO` consistently across Tasks 6
and 7.

## Known risk

`validate.py`'s `is_installed()` checks that a directory of the given name sits
directly in a skill root. It does not confirm that directory contains a valid
`SKILL.md`. That is deliberate — the check exists to catch renamed and deleted
skills, which is the failure mode that has actually occurred here twice
(`taste-skill` → `design-taste-frontend`, and `refero-design`'s removal). Tightening
it to parse each referenced skill's own frontmatter is a reasonable later hardening
if the loose check ever passes something broken.

It also only looks one level deep in `~/.claude/skills` and `<project>/.claude/skills`.
Plugin-namespaced skills (`plugin:skill`) would not resolve — none of the 14 routed
skills are plugin-namespaced today, so this is correct now and would need widening
only if a plugin skill is ever routed.

**Verified during planning:** all 14 routed skills resolve, in 0.4ms total, and all
three retired names are confirmed absent from disk.
