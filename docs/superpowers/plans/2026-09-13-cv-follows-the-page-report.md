# The CV follows the page — execution report

Plan: `2026-09-13-cv-follows-the-page.md`. Spec: `../specs/2026-09-13-format-decision-guarantee-design.md`.
Branch `claude/program-page-reader`, base `7d79d86`, head `2249fe4`. Executed 2026-09-13/14, subagent-driven:
one implementer and one reviewer per task, a whole-branch review, one fix wave, a ponytail pass, a
security review. Not pushed beyond `7d79d86`; no PR — that decision is the owner's.

## What shipped

Every CV requirement a programme page states now lands in one of five outcomes — switch the template,
check a rule, apply a typed directive, ask the student for the missing fact, or show the counsellor the
quote — and the system acts only when three model readings agree on the *action*; anything less abstains
to the no-egress default with the sentence visible. The keyword modality rule and its regex guards are
deleted. `docs/research/cv-format-eval.csv` (48 sentences) is a live gate pinned to the configured model.

20 files, +2,046 / −735 (ours; the owner's parallel commits `421b5d2`, `80333fd`, `233d041`, `66b7d25`,
`8d20998` are docs and excluded from every number here).

| commit | what |
|---|---|
| `3fcd8ea` | `UNDECIDED`, `cv_directives`, `unreadable`, keys `undecided`/`unapplied`, `_MULTI_KEYS` |
| `a770803` | `ReadResult.page_text`/`.snapshot`; two-sided unreadable floor |
| `a671590` | `candidates()` — code over the whole page, two recall paths |
| `6afe204`, `a981182` | closed question: `FormatVerdict`, `Directive`, three phrasings, `_judge` |
| `3905b4b` | `outcomes()`/`decide()` — act on unanimity, abstain visibly |
| `077f220`, `e173d71` | `derive_page_rules`; `read_and_derive` rewired; keyword rule deleted; list markers stripped |
| `cdf08a4` | directives reach render (`order`/`emphasise`) and generation (`include`) |
| `a99bddb` | `programme_required` gap questions |
| `cab5248`, `8cba359`, `830af0d` | the gate: corpus, harness, third-party rule, split caps |
| `e6783ad` | `CLAUDE.md` + spec status |
| `d7d119e` | whole-branch review fixes (1 Critical, 7 Important) + `order(cv)` |
| `4aea8e1` | ponytail cuts (−23 lines) |
| `2249fe4` | security fix: votes counted per sample |

## Gates at head

- `POSTGRES_DB=tehsil_master uv run pytest -q` → **2439 passed, 45 skipped, 16 deselected**
- `uv run ruff check .` clean · `uv run mypy apps config` clean (291 files) · `uv run bandit -c pyproject.toml -r apps config` 0 findings

Live gate (`test_the_eval_corpus_has_no_wrong_action_and_few_abstentions`, `gpt-5.6-luna`), every run:

| run | correct | wrong | format rows undecided | advisory rows undecided |
|---|---|---|---|---|
| pre-rulings | 39/48 | (harness judged the wrong field) | — | — |
| round 1 | 43/48 | 0 | 0/34 | 5/14 |
| round 2 | 43/48 | 0 | 0/34 | 5/14 |
| round 3 | 44/48 | 0 | 0/34 | 4/14 |
| fix wave | 45/48 | 0 | 0/34 | 3/14 |
| security fix | 46/48 | 0 | 0/34 | 2/14 |

The PII decision (format rows) was decided and correct in every run. Advisory abstentions churn among
the tabular-form / order / emphasise sentences; the gate caps them at ceil(30%).

## What the reviews caught that the plan had wrong

1. **Critical (whole-branch review):** `outcomes()` accepted a "Europass required" verdict on a line
   that never contains the word — three agreeing readings of "The CV must follow the EU standard
   tabular form" wrote `europass_required`. The plan's test for this used an out-of-range index and
   proved nothing. Fixed: such a verdict is `other_template` (surfaced, no egress). `d7d119e`.
2. **Security review:** format/directive votes were a flat list across samples; one reading emitting
   the same verdict three times while the others stayed silent passed as unanimous. Fixed: one vote
   per sample, a repeat is dissent. `2249fe4`.
3. `candidates()` kept `readable_text`'s `- ` list marker in `rule_text` and the dedup key (Task 6).
4. Headings were never judged; a page whose only Europass mention is a heading derived "says nothing"
   (final review; overturned a Task-3 ruling).
5. The prompt defined `preferred` and `not_required` so that "you may use Europass" fit both; the gold
   set was inconsistent the same way (Task 9).
6. A sentence about a *supervisor's* CV got its page cap attributed to the applicant in all three
   readings — the case the deleted regex guard covered. The prompt now states the rule; the gate pins it.
7. 48 lines × one directive verdict each exceeded the 40-entry schema cap, so complete answers were
   rejected as off-schema and looked like abstentions (Task 9).
8. Two disputes on one sentence produced two rules with one `rule_id`, and `resolve_rules` dropped one.

## Rulings made without you (each with what it costs if wrong)

- Unreadable floor is two-sided: < 1,500 chars AND ≥ 20,000 bytes — a shell under 20 KB reads as "says nothing"; none measured.
- Work in place on the branch, no worktree — none.
- Heading lines are judged as candidates (final ruling; the Task-3 ruling that skipped them is overturned) — a `#1 …` prose line is handled by `_HEADING_LINE`.
- A directive verdict of `none` is absence, not a vote — none lost.
- List markers stripped before `rule_text`/dedup — none.
- "Optional"/"may use" Europass → STANDARD; `preferred` = recommended/suggested/encouraged — a page that only *permits* Europass renders STANDARD (the safe direction).
- Gold relabels: `s4`, `s5` → standard; `goettingen-de` → unapplied; `emhrpp-a` → none; `d2` reworded to name the CV; `d4` → `cv=reverse_chronological` — the gate rows are partly synthetic and say so.
- Prompt completeness per dimension; list caps 40 → 100; output tokens 4,000 → 8,000 — cost per changed page up slightly.
- The gate asserts zero wrong actions; format-row abstentions ≤ 1; advisory-row abstentions ≤ ceil(30%) — the spec's "every sentence unanimous" is superseded; up to ~30% of advisory sentences may sit as counsellor-visible quotes rather than rules.
- One directive per sentence (spec amended) — a sentence naming two sections yields one.
- `order` gains the whole-CV target `cv`; `emphasise` does not.
- A `required`/`preferred` verdict on a non-europass line is `other_template` — a mandate phrased without the word is shown, not acted on.
- Abstention surfaces every unsettled sentence, not only europass lines.
- `_INCLUDE_TARGETS`/`_SECTIONS`/`_ORDER_TARGETS` live in `constraints.py`; `PageDirective` validates against them.
- Surfaced rule ids are `PAGE-<i>-<disputed item>`.
- Kept `gap_questions(student, programme=None)` despite the ponytail finding — it is the spec's named integration point for "ask".
- Security fix applied at filter confidence 6/10 — below the skill's reporting bar, on the PII path, cheap.

## Left for you

- **Push and PR** — the branch is 22 commits ahead of `origin` (yours included).
- **Quorum:** `decide()` accepts `_SAMPLES − 1` surviving readings. The security reviewer suggested requiring all three before any `EUROPASS` action. It is a spec decision; recorded, not done.
- **No production caller** reaches any of this; `gap_questions(programme=)` is called by nothing yet (`views.py`, `gap_intake.py` pass no programme). Wiring owes per-tenant rate limiting (`CLAUDE.md`).
- **The gate's blind spot** stands as written: a unanimous wrong answer never abstains. The second-model audit is in the spec's "Deliberately not built".
- Deferred minors (ledger): `apply_directives` silently ignores `order` on a non-dated section; `_DERIVE_MAX_OUTPUT_TOKENS` sized on the 48-line corpus; `"ects credits"` prompt wording; dead `disputed` on some `unjudged` outcomes.
- Union-of-three statement reads (`7d79d86`) stay; six model calls per changed page now run inside one transaction.

## Addendum, 2026-09-14 — majority rule for advisory outcomes (`300dc3f`)

Owner decision after reading the abstentions: catching every criterion and applying it on top of
STANDARD outranks the last bit of precision on *advisory* rules. Constraints and directives now act on
a majority of surviving readings (2 of 3); the Europass action still needs all three. First live run
under majority: 47/48, advisory abstentions 0/14 — and one wrong rule, the supervisor's two-page cap
attributed to the applicant by two readings. The third-party rule therefore went back into code as a
guard on the *outcome* (`Candidate.third_party`; such a sentence is shown as `undecided`/`third_party`,
never applied), not as a filter that would silence it. Second run: **48/48, 0 wrong, 0 abstentions on
both dimensions.** Cost recorded in the spec: a sentence capping both the applicant's and a host's CV
in one breath is shown, not derived; `reference` in ordinary prose ("include two references") is
shown, not applied; and the gate's blind spot is now "a wrong answer a majority agrees on".

Head `300dc3f`; full suite 2446 passed; ruff, mypy, bandit clean.
