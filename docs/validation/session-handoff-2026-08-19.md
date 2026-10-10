# Session handoff — 2026-08-19 (design-system implementation, remote session)

For the next session (local Claude Code) picking up this work. Read
`DESIGN.md` (locked contract), `CLAUDE.md` §"Design authority", and
`docs/validation/design-lint-baseline.md` (stage-by-stage state) first —
this note only carries what those don't.

## Branch / commit state

- **master**: PR #1 (design contract + tokens + badges) and PR #2 (form
  contract + htmx 4xx fix + inline student error paths) merged.
- **`claude/tehsil-agent-design-authority-501p0l`**: restarted from master
  after PR #2, carrying the layout-composition pass (scaffold, §7 panels,
  flow column, §10 empty-state slots) and this note. Its PR merges to master.
- Suite baseline: 594 passed, 2 skipped on Postgres. CI = ruff check, mypy,
  bandit, pip-audit, `manage.py check`, `makemigrations --check`, pytest —
  run ALL of these locally before pushing; pytest alone is not enough (a
  ruff-only failure cost PR #2 a red CI round).

## Open item being taken over locally: remaining bare-4xx endpoints

Context: `base.html`'s `htmx-config` meta makes 400/403/422/429 responses
swap (pinned by `tests/acceptance/test_htmx_config.py` — do not remove).
Under `hx-boost` this means an endpoint that returns a bare-text 4xx body now
swaps that raw string in as the page. The form-contract work fixed all
student/counselor form endpoints and MFA; still returning bare text:

- `apps/concierge/views.py::admin_support_grant` — 403 "an active support
  grant is required". `admin/support_grant.html` currently requires
  `active_grant` to render, so the fix needs a denied-state branch of that
  page (or a dedicated denied template), keeping the 403.
- `apps/tenancy/middleware.py` — 400 "unknown tenant host", 403 "tenant
  membership required", 403 str(error) from the staff-MFA gate. Middleware
  runs before any view context exists; these need a minimal standalone error
  template rather than the page re-render pattern.
- `apps/accounts/views.py` — 403 "tenant membership required" and three
  wizard-sequencing 400s ("consultation is ready for confirmation",
  "consultation is incomplete", "unexpected consultation question"). The
  wizard posts explicitly via htmx (`hx-target="#consultation"`,
  `hx-swap="outerHTML"`), so a bare-text 400 replaces the wizard section with
  the raw string. Fix = re-render the step/review state with the message via
  the established error context, keeping the 400.

Pattern to follow (established, reviewed, merged): views pass `error` /
`error_form` / `error_field` and re-render their page with the caller's
status; templates route through `components/_form_errors.html` (form-level)
and `components/_field.html`'s error slot (field-level), always included with
`only`. Reference implementations: `_render_error` in
`apps/funding/views.py`, `_message_error` in `apps/concierge/views.py`,
`_review_page` error plumbing, and the MFA branch in
`apps/tenancy/views.py::mfa_setup`. Error copy precedent: short sentences,
sentence case, numbers from code constants ("A program name is required.",
"Too many requests. Try again shortly."); service-layer messages render
verbatim.

## Other open items (not being taken over — tracked, don't lose)

- **Helper-text slots deliberately empty** pending product copy (list in the
  baseline doc's Stage 9 section): named-program purpose, student message
  expectations, approval Reason, resolve Rationale, mark-done Result. Only
  code-derived facts are filled today (150/4000-char limits, https:// rule).
- **`--shadow-pop-lg` unconsumed** — reserved for the marketing surface's
  primary CTA (§7). Nothing consumes it yet by design.
- **Marketing surface not started.** DESIGN.md §10's provisional markers were
  resolved 2026-08-19 (see §10 and ledger D7): the character-illustration
  allowance is dropped (no mascot anywhere); emoji-glyph stickers, the
  ribbon/blob shape, and the §9 reveals are affirmed — recorded as a
  weak-evidence decision (one reference + taste), revisable after real users
  see the marketing surface. The §10 *ban* side is locked. Product empty
  states carry `<!-- illustration: {subject}, 96x96, palette-bound -->`
  placeholder comments; assets may now be generated per §10's source rule
  (no characters).
- **`registration/login.html` unreachable** — no auth URLs are wired
  (`django.contrib.auth.urls` not included), so `@login_required` redirects
  to a 404ing `/accounts/login/`. The template itself is already migrated to
  the §8 field partials.
- **Skeleton loaders / §7 print pass (report + dossier) / audit-timeline
  styling** — deferred, see baseline doc.

## Tooling notes for local sessions

- Tests need Postgres (`config/settings/test.py` inherits the Postgres
  config; defaults user/password/db `tehsil` on 127.0.0.1:5432).
- Visual QA loop used throughout: `tests/acceptance/test_swap_render.py`
  with `SWAP_RENDER_OUT=<dir>` dumps the student pack page under the three
  §3 hexes; serve the dir with a `static` symlink to the repo's `static/`
  and screenshot (playwright-cli). Same dump-serve-screenshot pattern works
  for any page via a throwaway test that drives `slice_driver`.
- All §11 lint numbers (contrast pairs, 65px header, 375px no-overflow) are
  recorded per-stage in the baseline doc; re-run the checklist after each
  visual stage.
