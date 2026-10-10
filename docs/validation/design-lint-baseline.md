# DESIGN.md §11 lint — baseline audit (pre-implementation)

Date: 2026-08-18. Static review of every file in `templates/` plus
`static/css/app.css`, against the DESIGN.md §11 mechanical checklist, taken **before**
the token block lands so later stages measure against a recorded floor. No code was
changed in this audit.

Overall verdict: the templates are a foundation, not a cleanup job. Semantic headings,
`{% empty %}` fallbacks on every list, `role="alert"` on wizard errors, a real skip
link, `.visually-hidden`, and `:focus-visible` outlines already exist. Most §11 items
"pass" only because nothing is styled yet (no radii, no motion, no viewport-height
CSS); those are marked *trivial* below and become real checks at Stage 2+.

## Checklist matrix

| §11 item | Status | Notes |
|---|---|---|
| Contrast (text/CTA/form vs surface) | PASS (trivial) | Browser defaults + `#1d4ed8` on white (6.70:1). Re-check at Stage 2 |
| CTA label wrap at desktop | PASS | Longest label "Approve exact version" — fine unstyled |
| Nav one line, ≤ 80px | PASS (trivial) | One role link + legal footer; re-check when header is styled |
| Viewport stability (`100dvh`, never `h-screen`) | PASS (trivial) | No viewport-height CSS exists |
| Reduced motion honored | PASS (trivial) | No motion exists; becomes real with first GSAP use |
| Empty states exist | PARTIAL | Present on every list, but bare text ("No roadmap items yet.") — no invitation to act, no §10 empty-state treatment |
| Loading states / skeletons | **FAIL** | `student/_pack.html` polls (`hx-trigger="every 5s"`) with no loading indication; no `hx-indicator` anywhere; skeletons absent |
| Error states | PARTIAL | Wizard: `role="alert"` ✓. Login: `form.as_p` defaults. Counselor forms (`mark done`, `resolve`): no error rendering path at all — server-side failures are invisible |
| Explicit mobile collapse | PASS (trivial) | Everything is single-column by default; must be declared once layouts exist |
| One accent, page-wide | PASS | Only `--brand-primary` in use |
| One radius system | PASS (trivial) | No radii exist |
| No `window.addEventListener('scroll')` | PASS | No custom JS; HTMX only |
| No placeholder-as-label | **FAIL** | `student/_pack.html`: `<input name="program_name" placeholder="Named program">` has no label |
| Copy self-audit | **FAIL** | `student/_consultation_step.html` renders `{{ question.key }}` as the visible label — machine keys (e.g. `target_field`) shown as UI copy |
| No placeholder people/data | PARTIAL | No Jane Doe/Acme. But counselor/owner dashboards display raw UUIDs as "Student: {{ id }}" — unreadable as real data |

## Defects to fix (not merely "unstyled") — statuses as of Stage 5

1. **Placeholder-as-label** — ~~`student/_pack.html` named-program input~~ **FIXED**
   (visible label, placeholder removed).
2. **Machine keys as labels** — ~~`_consultation_step.html` `question.key`~~ **FIXED**
   (`ProfileQuestion.label` + `QUESTION_LABELS`; missing entry fails at import).
3. **Inert live region** — **FIXED** in Stage 2 (`static/js/app.js`; polling swaps
   deliberately silent).
4. **No loading indication** — **PARTIAL**: `htmx-indicator` caption on the polling
   section; skeletons deferred until the recommendation list gets its real styling.
5. **Counselor form error paths** — **FIXED**: validation failures re-render the page
   with `role="alert"` and preserved input, keeping the 400/403 status contracts.

Signature-token wiring (from the visual pass): `--shadow-pop` now consumed by button
styling, `--brand-tint` by the §8 approval badge. `--shadow-pop-lg` remains reserved
for the marketing surface's primary CTA (§7) — unconsumed until that surface exists.

## DESIGN.md §8 contract gaps (statuses as of Stage 6)

- Eligibility badge — **DONE** (Stage 4). Evidence rows — **DONE** (labeled link +
  domain/last-checked caption; print surfaces keep raw URLs). Money — **DONE**
  (tabular-nums, gap variant). Deadlines — **DONE** (absolute date + urgency badges,
  DONE items never urgent). Roadmap stage — **DONE per D14** (labeled stage+state
  pill; multi-node stepper deferred until per-application grouping). Approval state —
  **DONE** (Stage 5). Wizard progress — **DONE** ("Question n of m" + native progress
  bar; dynamic denominator documented). Notifications — **DONE** (card + left
  border). `&mdash;` sweep — **DONE** (middot is the meta separator vocabulary).
- Still open: audit-timeline entry styling (dossier is print-profile, deferred);
  report visual design (§7 print pass); skeleton loaders (waits on list styling);
  `registration/login.html` is not reachable (no auth URLs wired —
  `@login_required` redirects to a 404ing `/accounts/login/`), found during the
  Stage 9 form pass. Admin support-grant's bare-403 body — **FIXED Stage 12**.
- Forms — **DONE** (Stage 9): §8 structure via `components/_field.html`
  (label above input, helper slot, error below with icon in
  `--status-ineligible`) and `_form_errors.html` (non-field errors); all eight
  form surfaces migrated, `form.as_p` retired from the login template.
  Helper slots filled only with code-derived facts (150/4000-char limits,
  https:// requirement); slots needing product copy are listed below and left
  empty. Prerequisite fixes (Stage 9, behavioral): student-side endpoints
  re-render inline errors instead of bare 4xx text; base.html `htmx-config`
  makes 4xx re-renders actually swap under hx-boost (pinned by
  `tests/acceptance/test_htmx_config.py`); `_is_htmx` no longer mistakes
  boosted navigation for fragment requests.
- Helper copy pending (product decisions — slots exist, deliberately empty):
  named-program form (what "Check named program" does), student message form
  (who reads it / response expectations), approval Reason, resolve Rationale,
  mark-done Result.
- Money zero-gap correction (Stage 8): callers pass `gap=True` for every real
  figure, so a fully covered program rendered "0.00 EUR" in gap-red — §8 says
  covered amounts stay neutral. `components/_money.html` now applies
  `money--gap` only when `gap and amount > 0` (funding_gap is clamped
  non-negative); regression in `tests/funding/test_evidence_and_money.py`.
- Raw UUIDs as people — **FIXED** (Stage 7): counselor/owner dashboards render
  `Membership.display_name` (full name, username fallback); `data-student-id` attrs
  keep the machine ids.

## Student-pack swap-test result (Stage 8, rendered screenshots) — PASS

Method: `tests/acceptance/test_swap_render.py` builds a real published pack via
the slice driver and dumps the student recommendation page under `#0254a5`
(platform default) and both DESIGN.md §3 swap hexes (`#b45309`, `#1a7f37`);
each dump was screenshotted in Chromium at 1280×900 with the repo CSS and
self-hosted Manrope loaded.

Verdict against §3 ("if the component's meaning or hierarchy changes, it is
leaning on the accent"): **pass on all three hexes.**

- Structure is invariant: cream canvas, Deep Harbor headings, single-family
  Manrope, pill buttons with the flat-offset pop shadow (visibly re-tinted via
  `--brand-pop`), hairline input. Page hierarchy (title → program card → CTA)
  reads identically under every hex.
- Approval badge holds the §3 derived-token rule: `--surface-dark` text on
  `--brand-tint` stays legible on the amber and green tints (the banned
  white/primary-as-text pairs are not used).
- Semantic status is untouched by tenant variance: the Eligible badge keeps its
  fixed green tint + icon + label under all three primaries. Under `#1a7f37`
  the brand hue lands near the eligible green — acceptable because hue is never
  the sole carrier (icon + label + fill/shadow distinguish badge from button),
  which is exactly the rule the lock relies on.
- Links change hue but stay underlined, so affordance never rides on the accent.
- One §8 defect surfaced by the run (zero-gap red money) — fixed, see above.
  One gap noted for the form-styling pass (label-above-input), see above.

## Stage 11: page-scaffold and layout-composition pass

Date: 2026-08-19. Chromium-verified at 1280×900 and 375×720; header measures
65px (§11 ≤ 80); no horizontal scroll at 375.

- **Scaffold**: header band (hairline-separated cream, brand wordmark left,
  role nav right, one line) and footer share `main`'s centered 1200px measure
  via `.shell`; §6 base-7 vertical rhythm on h1/h2 and section gaps.
- **Raised panels** (§7): data lists and candidate articles sit on
  `.panel`/`.panel-list` — white, 12px radius, 28px padding, hairline row
  separation, no shadows (pop stays interactive-only per §6).
- **Flow column**: consultation wizard, sign-in, and MFA render in a centered
  560px `.wizard` measure — progress, prompt, and action read as one unit.
- **Empty states (§10, folded in)**: every empty list renders a designated
  `.empty-state` slot with an illustration placeholder comment
  (`<!-- illustration: {subject}, 96x96, palette-bound -->`). Illustrations
  were deliberately NOT generated: §10's allowance side is provisional and
  says re-confirm before any illustrated asset is generated. Two authored
  invitation lines pending user approval: "Items your counselor adds will
  appear here." (students; RoadmapItem is counselor-created) and "Students
  assigned to you will appear here." (counselors; assignment is owner-made).
- Swap-test note: the pass adds no brand-token consumers — every new surface
  uses platform-fixed cream/white/hairline/navy, so §3 invariance is by
  construction; button/link re-tinting was verified in Stage 10.

## Stage 12: bare-4xx denied-page pass

Date: 2026-08-19. Branch `claude/bare-4xx-denied-pages`, merged to master (PR #4).

- **Four bare-text 403s → `templates/403.html`**: `TenantMembershipMiddleware`'s
  membership and staff-MFA gates, `accounts.views.profile`'s membership check,
  and `admin_support_grant`'s missing-grant check (the Stage 10/11 "still open"
  item, now closed above) all raise Django's `PermissionDenied` instead of
  returning `HttpResponseForbidden(text)`. Django's `permission_denied` view
  renders `templates/403.html` with `{"exception": str(exception)}`, so each
  site's already-authored message surfaces verbatim — no new copy, no
  per-call-site error-context plumbing. Reuses `.wizard` and `.form-error`; no
  new CSS.
- **Two bare-text wizard 400s → re-render**: "consultation is incomplete" and
  "unexpected consultation question" (out-of-sequence posts — stale tab,
  double submit, replayed form) now re-render via a new
  `_render_current_state()` helper instead of returning bare text, keeping the
  400 status. Also fixed a latent bug the sequencing 400s shared:
  `_render_question`'s "consultation is ready for confirmation" branch was
  dead code (every caller already guards it) and is now the type-narrowing
  assert it always should have been.
- `security-review` and `ponytail:ponytail-review` both run against the diff:
  no findings, two comment-length shrinks applied (net −8 lines).
- **Deferred copy items — both CLOSED 2026-08-19:**
  - ~~The 400 `"unknown tenant host"` needs authored copy~~ **FIXED**:
    `HostTenantContextMiddleware` now raises `SuspiciousOperation`, which
    Django's `bad_request` view renders via the new `templates/400.html`.
    Unlike `403.html`, Django passes this view **no exception context**
    ("to not disclose any sensitive information"), so the body is static
    authored copy, approved: "This address isn't recognized. Check the
    link, or contact your counselor if you were sent here." The `<h1>`
    stays the unauthored RFC 9110 §15.5.1 reason phrase ("400 Bad
    Request") — only the body copy was approved this round, same
    still-pending-heading state `403.html` was in before this pass.
  - ~~`templates/403.html`'s `<h1>` reads the RFC reason phrase, not
    authored copy~~ **FIXED**: now "You don't have access to this page",
    approved.

Still open, unchanged: `registration/login.html` unreachable (no auth URLs
wired); skeleton loaders; report/dossier print pass; audit-timeline styling;
empty-state invitation-line copy approval (Stage 11); helper-copy slots
(Stage 9 list).

## Stage 10 re-run: §11 checklist + swap harness against the styled forms

Date: 2026-08-19. Chromium 1280×900 and 375×720 via the swap harness dumps.

§11 items that changed status:

| §11 item | Status | Notes |
|---|---|---|
| Error states | **PASS** (was PARTIAL/FAIL) | Every form surface renders §8 errors (below input, semantic red, icon) with preserved values and correct 4xx statuses; browser-verified that they actually display under hx-boost. Remaining exception: admin support-grant 403 (logged above) |
| Contrast | PASS (real now) | Field label 14px/500 Ink, helper 12px Slate (D13), error `--status-ineligible` on cream — all matrix-verified pairs |
| CTA label wrap | PASS (re-verified) | Longest labels ("Approve exact version", "Check named program") don't wrap at 1280 or 375 |
| Explicit mobile collapse | PASS (real now) | 375px: single column, `scrollWidth == innerWidth` (no horizontal scroll), fields fluid to 100% |
| One radius system | PASS (real now) | Pill buttons/badges, 10px inputs, 480px field measure — §6 mixed rule applied |
| No placeholder-as-label | PASS | None anywhere; `_field.html` structurally prevents it |
| Copy self-audit | PASS | All authored strings user-approved 2026-08-19; helper slots carry only code-derived facts |

Unchanged: empty states (bare text, §10 treatment pending), loading/skeletons
(deferred until list styling), reduced motion (no new motion; button `:active`
wrapped), no scroll listeners, one accent.

Swap test (styled forms, #0254a5 / #b45309 / #1a7f37): **PASS** — the field
system is hue-invariant by construction (hairline border, white surface, Ink
label, Slate helper, semantic-red error); only buttons, links, and the focus
ring re-tint. Zero-gap money stays neutral under every hex.

## Print-profile swap-test result (Stage 7, static analysis)

- `audit/dossier.html` carries **zero CSS** — hue-independent by construction; the
  swap test passes trivially and screenshots on either hex must be identical.
- `reports/consultation_report.html` injects the tenant `--brand-primary` but **no
  rule consumes it yet** — the hue currently changes nothing (a decorative no-op until
  the §7 print pass styles the report). Identical renders across hexes are the
  *expected* result there, not a bug. `--shadow-pop-lg` likewise remains reserved for
  the marketing CTA surface.

## Original build list (superseded by the statuses above)

- Eligibility renders as two-state boolean text at 4 call sites
  (`student/_candidate.html`, `student/_pack.html`, `counselor/review.html`,
  `reports/consultation_report.html`); §8 requires the three-state badge with
  icon + label. → Stage 4.
- Evidence rows print the raw `source_url` as anchor text (twice per candidate);
  §8 wants a labeled source link + last-checked caption.
- `&mdash;` used as inline layout punctuation (`_candidate.html`, `_pack.html`,
  `audit/dossier.html`, report header); replace with structural markup when styling.
- Money figures unstyled; no tabular-nums, no gap treatment (§8 money contract).
- Deadlines are raw datetimes; no urgency states (§8 deadline contract).
- Roadmap stages are text spans; §8 requires the labeled stepper.
- Approval state vocabulary is inconsistent: "Approved by counselor" /
  "Pending counselor re-approval" / "Published" — §8 defines `Approved v{n}` /
  `Awaiting approval` / `Approval invalidated`.
- Consultation wizard has no progress indicator (§8 roadmap-stage / flow pattern).
- Notifications are bare `<li>`s; §8 defines the card + left-border treatment.
- `audit/dossier.html` and `reports/consultation_report.html` are standalone
  documents (correct for the §7 report/print profile) — the report already injects
  `--brand-primary` ✓; the dossier carries no tenant identity and will need the §7
  print treatment.

Re-run this checklist after each stage; items marked *trivial* flip to real checks as
soon as the relevant CSS exists.
