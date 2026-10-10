# The recommendation spine: catalog rows and a profile become a pack

**Status:** approved by the owner 2026-09-19 (whole spine, one student end to end; a
standalone award is its own application with its own deadline). **Amended the same day** to be
Layer 5 of `2026-09-19-coverage-driven-funding-engine-design.md`: the pool query becomes cell
selection (§5.1) and award identity follows that design's §6.3.

Builds on: `2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md` §3 (the
holder axis, built on `claude/reader-holder-axis`), `2026-09-13-institution-programme-funding-search-design.md`
(the reader), and `phased requirements.md` P1-6 / P1-7 (the pool, the pack, the gates).

## 1. Why this exists

Both halves of the engine are built and they are not joined. Measured by reading the code
on 2026-09-19, not inferred:

- **The evaluator has no production caller.** `evaluate`, `rank_candidates` and `build_pack`
  (`apps/funding/pack.py`, `apps/funding/evaluation.py`) are reached from tests only.
- **The one live path that creates a pack is a fixture skeleton.** `apps/research/services.py::handle_research_message`
  fetches the placeholder `https://official.example.test/program.json`, refuses a fixture
  that is not `eligible`, writes one `RecommendationCandidate` with `eligible=True`
  hard-coded, and applies a single evidence-confidence check. It never calls a hard gate.
- **Nothing student-facing reads the reader's catalog.** Every reference to
  `FundingOpportunity` outside migrations is a writer, the review command, the recall
  command, or the seeder. The whole funding-discovery output has no consumer.
- **Three unjoined representations of "an option" exist:** `FundingOpportunity` (shared
  catalog, what the reader writes), `CandidateFacts` (pure schema, what the evaluator
  scores), `RecommendationCandidate` (tenant row, what the live pack stores — a
  `program_name` string with no foreign key to either).

So the engine can find money and can score options, and no student can receive one.

## 2. Scope

One student, end to end: pool query → facts → gates → pack, replacing the fixture path.
Programmes and standalone awards both, awards as their own applications.

**Two words used precisely throughout.** The **pool** is every candidate the run considered,
each with its outcome and its reasons — including the ones it will not recommend, which P1-7
requires to stay "visible with the reason". The **pack** is the recommended subset. "Pool
only" below means: the student sees it, with its flag, and it is not in the pack.

**Not in scope, deliberately:** `FundingCycleVerification` and the crawl/Wayback/search
ladder (funder spec §3.5.2 — needs the vendor fetch client, which is on another branch);
Wikidata-backed condition parsing; any UI change; the counsellor resolution queue
(component C of the funder spec).

## 3. Two gaps upstream of this work

Both were found while designing it, and both cap what the spine can deliver. They are
recorded here rather than silently worked around.

### 3.1 The typed eligibility table has no writer

`funding.BenefitRule` holds the conditions that close a route to a student who meets every
academic bar: `WORK_EXPERIENCE`, `AGE_CAP`, `MEANS_TEST`, `AFFILIATION`, `LANGUAGE`,
`GUARANTOR`, plus `RETURN_SERVICE` as a disclosure. The model is documented in detail and
**no code creates a row.** `_unmet_conditions`, `closed_route_reasons` and
`unevaluable_condition_reasons` — the eligibility logic this spine reuses — therefore run on
data nothing produces.

Consequence accepted for now: the spine reads whatever `BenefitRule` rows exist (none today,
hand-curated ones later) and behaves correctly with zero. It does not invent conditions.

### 3.2 The reader records the shape of a nationality rule, not its content

`LineVerdict` and `FundingOpportunity` carry `nationality_shape`
(`OPEN / COUNTRY_LIST / BLOC / BILATERAL_PAIR / UNSTATED`) and `internationals_included`.
Neither carries **which** countries. The funder spec §3.1 lists "eligibility keys"
(`CITIZENSHIP / RESIDENCE / DESCENT / REGION / AFFINITY / OPEN / NEED / …`) as an "existing
vocabulary, now written by the reader on every row"; that vocabulary appears nowhere in the
code, and no task in the holder-axis plan implemented it.

Consequence, and this is the load-bearing one: for a reader-written award restricted to a
country list, the spine can prove neither eligibility nor ineligibility for a given student.
Such an award is `POSSIBLY_ELIGIBLE_REVIEW` with the award's own sentence as the reason. That
is correct — `OPEN` and `UNSTATED` shapes still decide — but it means a pool built only from
reader rows is heavy on review items until the reader records the content. **Recording it is
the next piece of work after this one**, and it belongs in the judge, not here: a translation
layer that guessed a country list from a quote would be inventing eligibility.

### 3.3 Money that requires a place somewhere else

A research institute's thesis stipend (Max Planck, CNRS) and a French CIFRE contract both pay
a student who is **enrolled at a partner university**. The award is conditional on an
admission, and nothing in the model can express that: `route` describes selection
(`INSTITUTION_NOMINATES`, `JOINT_SELECTION`), not an enrolment prerequisite, and a holder
award carries no link to the institutions that would satisfy one.

Two consequences, both real once such an award is in the catalog: it would be offered to a
student with no place at a qualifying institution — money they cannot take — and §5.4's rule
that an award is its own application is wrong for it, because it is only worth applying to
alongside a specific programme application.

Out of scope here, and the reason is the same as §3.2: closing it needs the reader to record
*which* institutions the condition names, and a translation layer that guessed them would be
inventing eligibility. Evidence and the full claim-by-claim review of the proposal that
surfaced it: `docs/research/2026-09-19-dual-seed-review.md`.

### 3.4 Award identity collapses multi-award funders (corrected upstream)

The holder-axis plan keyed an award on `(holder domain, kind)`, so a ministry's or an agency's
dozens of schemes of one kind become one row. The engine design §6.3 corrects the key to
`(organisation, page, heading, kind)`; the pool and the pack here take award identity from the
catalog row and need no change when it lands, but any count of "awards found" before that
correction undercounts the large funders.

## 4. The structural decision

Awards and programmes are different things and are not forced into one bundle.
`CandidateFacts` has ~15 programme-only required fields (`location_key`, `city`,
`duration_months`, `teaching_languages`, `cost_components`) that a foundation's scholarship
has none of, and six of the nine hard gates read them.

**Two fact types, one shared condition engine.**

- `CandidateFacts` — a programme and the money attached to it. Unchanged, so the existing
  gates and their tests are untouched.
- `AwardCandidateFacts` — one standalone award: its catalog row, its holder, its benefits,
  its conditions, its deadline per condition, its intake evidence. No programme.
- The condition logic (`_unmet_conditions`, `unevaluable_condition_reasons`,
  `open_routes`, `closed_route_reasons`, `_return_service_disclosures`) is already written
  against *conditions and benefits*, not against programmes. It moves to a module both types
  import, with no behaviour change.

Rejected: making `program_id` optional on `CandidateFacts` (every programme gate would need
an `if` for a candidate that has no programme, and a gate that silently skips is the failure
mode this repo treats as worse than a crash); and a generic `Applicable` protocol with gates
declaring which fields they need (same silent-skip risk, more machinery).

## 5. The spine, five parts

### 5.1 The pool query — `apps/funding/pool.py`

**Cell selection**, not a field-and-country filter (engine design §3, §8). The profile selects
its cells — every holder type × the hosts it has not excluded × its `nationality` and
`country_of_residence` × its level — and the pool is the served awards and catalog programmes
in those cells, plus the cells' coverage so the pack can say which are thin. Bounded by an
explicit limit, ordered deterministically, and it never reads a row whose `served` is false —
the serve gate is the catalog's promise and the pool does not second-guess it.

Until Layer 0 exists, the interim query is `target_field` + `excluded_countries` +
`intended_intake` over programmes and served `HOLDER` awards; it is replaced, not extended.

A student's *preference* is a pool filter; a student's *non-negotiable* is a hard gate. The
two must not be conflated: filtering the pool by a preferred country hides funding the
student would have taken, and `allowed_countries` is already used by a hard gate, so the
pool applies only `excluded_countries` and the field.

### 5.2 Two translators — `apps/funding/facts.py`

`program_facts(program, profile_intake)` → `CandidateFacts`, and
`award_facts(opportunity)` → `AwardCandidateFacts`. Pure functions over rows already
fetched; no I/O inside them.

What each maps, and what it refuses to invent:

| target field | source | when absent |
|---|---|---|
| benefits | `FundingBenefit` rows, with `repayable_share` | no benefit → no coverage, never a zero-cost assumption |
| applicant conditions | `BenefitRule` rows of kind `APPLICANT_CONDITION` | none → no condition, never a guessed bar (§3.1) |
| return service | `BenefitRule` rows of kind `RETURN_SERVICE` | none → no disclosure |
| nationality restriction | `nationality_shape` + `country_code` | `COUNTRY_LIST` / `BLOC` / `BILATERAL_PAIR` with no list → an undecidable condition carrying the award's quote (§3.2) |
| evidence confidence | the row's `agreement` and the lead's strength | `UNAGREED` → `LOW` |
| deadline(s) | `FundingOpportunity` + the judge's `deadlines` | none → the intake gate decides, never a fabricated date |

### 5.3 Gates

Programme gates: today's `HARD_GATES`, unchanged.

Award gates, a separate short list, each with its own sentence:

1. conditions the student demonstrably fails (shared engine),
2. `cycle_validity` on the award's evidence,
3. the selected deadline is still reachable relative to `intended_intake`,
4. evidence confidence is not `LOW` — an award whose readings never agreed is excluded with
   that reason, not flagged; `UNAGREED` is a fact about our reading, and showing a student
   money on evidence we distrust is the one thing the serve rule exists to prevent.

The profile carries `intended_intake` as a date and `cycle_validity` takes the intake as the
page writes it, so the gate passes `str(profile.intended_intake.year)` and also passes
`intake_starts_on=profile.intended_intake` — the real start date, which is exactly the
override that function documents for an intake that does not begin in September.

**`cycle_validity` is wired on step-0 evidence only** — what the reader stored on the row
(`offered`, `applies_to`, `stated_on`, `deadline`/`deadlines`, `suspended_for`,
`suspension_quote`). Without the ladder there is no call history, so `UPCOMING` is
unreachable and most awards return `UNVERIFIED`.

**Therefore the gate hides an award only when the evidence says it is shut** — a dated
negation (`SUSPENDED`), an `ENDED` record, or a passed deadline (`CLOSED_FOR_INTAKE`). An
`UNVERIFIED` award enters the pool carrying "we could not confirm this is open for your
intake" and never the recommended pack. This is deliberately weaker than funder spec §3.5's
"only `OPEN` and `UPCOMING` are shown", and tightens to it automatically when the ladder
lands: the same function, more evidence. Gating hard today would empty the pack for want of
a crawler, which is a worse failure than a flagged option.

### 5.4 The pack

`build_pack` gains a second list. Programme applications keep today's shape, ordering and
budget arithmetic. Award applications are their own entries, each with its own deadline and
the sentence it rests on.

**An award's money is not counted as coverage against any programme's cost.** Owner decision
2026-09-19: it is an application, not a discount. Counting money not yet won would understate
the gap by exactly the amount at risk, which is the mistake `repayable_share` exists to
prevent in the other direction.

Ordering between the two lists follows the existing rule: an award whose decision lands
before a university fee deadline is `SCHOLARSHIP_FIRST` for that programme.

### 5.5 The entry point

`handle_research_message` keeps its message-driven seam and its `select_for_update` on the
run, and its body becomes: pool → facts → evaluate → `build_pack` → write
`RecommendationCandidate` rows (now with a foreign key to the catalog row they came from)
→ publish. The placeholder fetch and the `OfficialFixture` path go.

A `POSSIBLY_ELIGIBLE_REVIEW` outcome opens a `ConsultantResearchTask` and the option appears
in the pool flagged, with its reasons. Publication is still un-gated by counsellor review
(§38): the task is work for a human, not a hold on the student's pack.

## 6. Failure paths

| failure | behaviour |
|---|---|
| pool returns nothing | the run records why (field, countries, intake) and publishes an empty pack with that sentence — never a silent empty list |
| a catalog row cannot be translated | the row is skipped, counted, and named in the run's degraded list; one bad row never fails a pack |
| every candidate is excluded | the pack publishes with the excluded list and its reasons, which is P1-7's "visible with the reason" |
| `cycle_validity` cannot decide | `UNVERIFIED`, pool-only, flagged |
| an undecidable condition | `POSSIBLY_ELIGIBLE_REVIEW`, pool-only, flagged, consultant task opened |

## 7. Testing

- `facts.py`: table-driven, one row per mapped field, including every "when absent" case
  above. A translator that invents a value is the defect these catch.
- award gates: one test per gate, plus a suspended award (hidden), an unverified award
  (pool, flagged, not packed) and an award whose deadline has passed.
- the spine end to end: one student, one programme row, one holder award, a fake rate table
  → a pack with one programme application and one award application. This is the test that
  fails today for every reason in §1.
- no new live-API test: the spine makes no model call.

## 8. What this does not prove

That the options are *good*. The reader's own gate (2026-09-19 measurement) shows awards on
funder pages coming back `UNAGREED` on `route` and `money_form`, which makes their evidence
confidence `LOW` and keeps them out of the pack. The spine makes the path exist; the funder
spec's component C and the `route`/`money_form` decision are what fill it.
