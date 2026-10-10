# Skill tailoring: matching a student's evidence to a programme's own page

Date: 2026-08-27
Status: design approved in conversation; implementation not started.

## 1. The problem

Repository intake produces a skills list nobody would want on a CV. Two
observed defects, both real, and one of them is the reason for the redesign:

* **Project-specific junk under "Core competencies".** `extraction.py` asks
  the model an open question -- name the methods this work performs -- and open
  generation produces names that mean nothing off this project (`15-atom slab
  model`). Commit `0aa80c2` already attacked this by refining the prompt; the
  defect survived, because prompt wording cannot make open generation closed.
* **Names that are not packages under "Libraries and frameworks".**
  `signals.py` runs eight import regexes over every non-Python source file.
  The Julia/MATLAB rule `^\s*(?:using|import)\s+([A-Za-z][\w]*)` fires on
  English comments, so a line reading `using leave-one-out cross validation`
  yields the package `leave`.

Underneath both: the three headings are defined by **where a name came from**,
not **what the name is**, and nothing checks a name against its heading.

Two further defects found while reading, fixed here because they are the same
class:

* `facts.py:_MAX_LIBRARY_SKILLS` truncates `sorted(libraries)[:15]`. The set is
  built at `intake.py:296` with no counts, so the cut is alphabetical: `ase`
  survives and `torch` does not, while the comment claims "the head of the list
  is the story".
* `write_library_skill_facts` documents that an import need not resolve
  (`copasi_parser`, `cdr`) and has no way to tell.

And the framing question that gates all of it: **are these skills useful for a
programme?** Today, no -- nothing reads them. No code in `generation.py` or
`profile_bridge.py` consumes `Category.SKILL`. The pool is written and goes
nowhere, which is why this is the right moment to define the consumer.

## 2. Decisions

| # | Decision |
|---|---|
| D1 | The skills pool exists to be **tailored** against a target programme, not to be printed as-is. |
| D2 | The programme's requirements come from **the agent fetching and reading the programme's own page**, not from the student pasting text and not from a hand-entered field. |
| D3 | Tailoring does four things: pick and order, flag gaps, propose the programme's wording, and rank which projects appear. |
| D4 | **Precision over recall.** Both junk classes are minimised at all cost; a missing true skill is cheaper than a false one. |
| D5 | Approach C -- an **open internal pool, a closed printed list**. The pool may be noisy; what reaches paper is gated by the programme's vocabulary. |
| D6 | Skills the programme never mentions still print, **below** the matched ones, ordered by evidence -- but only mechanically derived ones (see 5.1). |
| D7 | A model is used **only where the answer is not already machine-readable**. |
| D8 | The branch divergence is reconciled **before** any of this lands. |

## 3. Where the programme's wants come from

A new claim class, `ACADEMIC_PROFILE`, on the existing pipeline. No new
fetching and no new storage model:

    OfficialSource(source_type=PROGRAM)
      -> OfficialSourceSnapshot   (S3 copy, sha256, retrieved_at)
      -> OfficialEvidenceClaim    (claim_class=ACADEMIC_PROFILE)
      -> ProgramEvidenceClaim     -> Program

One claim per **wanted competency**. The claim row carries lineage --
snapshot, `last_checked_at`, and the freshness window that comes with its
class -- and its text is the page's own sentence.

A second row, `ProgramCompetency(program, evidence_claim, term, requirement)`,
is the queryable projection: `term` as the page words it and `requirement` in
`{REQUIRED, DESIRED}`. This is a new table rather than a naming convention
inside `OfficialEvidenceClaim.claim`, because the alternative is parsing
structure out of a free-text field on every read -- an implicit schema with
nothing enforcing it. The claim keeps lineage; the projection keeps the query.

The excerpt is not decoration -- it is what makes a bogus match visible in
section 6.

`Program` carries no academic content today (`apps/funding/models.py:335`:
name, campus, city, teaching languages, duration, CV-format rules), and
`ExtractedClaims` (`apps/research/extraction.py:39`) extracts money, deadlines,
languages and required documents. Neither knows what a programme is *about*.
This claim class is the missing half of the match.

### 3.1 Branch constraint

`OfficialEvidenceClaim.claim_class` does not exist on `master`. It was added on
`claude/phase-5-automated-discovery-requirements` (commit `4b26c5e`) with six
values -- IDENTITY, STRUCTURE, ELIGIBILITY, TUITION, FUNDING, DEADLINE -- plus
per-class freshness windows. `ACADEMIC_PROFILE` is a seventh value on a field
that exists only there, and that branch is 53/37 diverged from `origin/master`.

Therefore: reconcile first, build on the merged base (D8). Otherwise this work
inherits the divergence and two large merges land at once.

### 3.2 Freshness

`ACADEMIC_PROFILE` gets its own window, much longer than the deadline windows.
What a programme teaches changes between prospectuses; its deadline changes
every cycle. Reusing the deadline clock would re-fetch every programme page
many times for no change.

## 4. The skill pool

### 4.1 What an entry carries

`SkillEntry(name, category)` -- a word and a heading -- is too thin. It cannot
be ranked (D6's tail needs an order) and it cannot be justified (a proposed
match has nothing to show). So each entry carries its evidence:

| kind | evidence stored |
|---|---|
| `language` | the host's byte count |
| `library` | the manifest that declares it, and the number of files importing it |
| `technique` | the excerpt from the repository's own text that named it |

**Storage.** `kind` (`language` / `library` / `technique`) and `evidence`
(a short human-readable justification: `"imported by 7 files"`, `"12431
bytes"`, or the naming excerpt) become optional fields on `SkillEntry`,
listed in `_PAYLOAD_KEYS` and **excluded from the verifier's compared detail**
-- the precedent set by `volume`/`issue`/`pages` on `PublicationEntry`. The CV
renderer reads `name` and `category` and ignores the rest, so nothing new
prints. This avoids a second table on the student's side for data the ledger
already models. (`ProgramCompetency` in section 3 is the programme's side and
has no ledger to reuse.)

**The three headings stop carrying meaning.** "Languages and tools" /
"Libraries and frameworks" / "Core competencies" become a rendering choice.
What matching reads is `kind`, which is set by how the name was derived.

### 4.2 Where libraries come from (D7 applied)

| input | machine-readable? | mechanism |
|---|---|---|
| languages | yes -- GitHub byte counts | no model |
| Python libraries | yes -- `ast.parse` | no model |
| other languages' libraries | yes -- the manifest | no model |
| techniques | no -- a judgment about prose | model |

The eight import regexes in `signals.py` are **deleted, not fixed**. Other
languages declare dependencies in structured files -- `package.json`,
`Cargo.toml`, `go.mod`, `pom.xml`, R's `DESCRIPTION` -- which parse exactly as
JSON or TOML. A name in a manifest provably resolves, which also answers the
`copasi_parser` problem. `leave` becomes impossible rather than unlikely, and
roughly forty lines disappear.

Python keeps `ast` and keeps ignoring `requirements.txt`: the existing
reasoning is sound *for pip freeze*. `signals.py`'s docstring generalised that
into "never trust a declared dependency file", which is wrong --
`package.json`'s `dependencies` is hand-written, not a freeze. The docstring is
corrected as part of this work.

A language whose manifest is absent contributes no libraries. Nothing is
guessed.

**Why not ask the model, given it already receives 24k chars of repository
text?** Because the failure modes are not comparable. A regex fails loudly:
`leave` is obviously junk. A model fails plausibly: `scikit-optimize` in a
repository that never used it looks entirely correct and neither the student
nor the counsellor would catch it. Under D4, the plausible failure is worse.

### 4.3 Ranking

Libraries rank by the number of files importing them, not alphabetically. The
existing cut keeps `ase` over `torch`; this one does not.

## 5. The match

New module `apps/documents/tailoring.py`, shaped like the evidence package:
pure functions plus exactly one model call, with DB writes kept out.

**Exact matches never reach the model.** A pool entry whose name equals a
programme term, case-folded, is matched by string comparison. Only the
remainder -- `density functional theory` against `electronic-structure
methods` -- is a judgment.

**The model chooses between two closed lists; it never writes names.** Input is
the pool (id, kind, evidence) and the programme's wanted competencies (id,
excerpt), both labelled DATA per the `extraction.py` pattern, schema-
constrained with `extra="forbid"`, `max_output_tokens` capped, `store=False`.
Output is pairs of ids. It cannot invent a skill because the only emittable
values are ids of rows that already exist. This is the structural difference
from "name the methods in this repository", which produced `15-atom slab
model`.

Every match carries two citations -- what in his code backs it, what on the
page asked for it -- so a wrong match is visible rather than merely wrong.

Rate-limited through `apps/ratelimit.py`'s `rate_limited()`, per CLAUDE.md's
rule that no LLM-calling path ships without a cost circuit-breaker.

### 5.1 The gating rule

Printed order:

1. matched entries, page-*required* before page-*desired*;
2. the unmatched tail -- **mechanical entries only**.

Languages and manifest libraries may print unmatched, because a byte count and
a `package.json` line vouch for them. **Model-read techniques print only when
matched.** `15-atom slab model` may sit in the pool indefinitely and never
reach paper, because no admissions page asks for it. This single rule is what
makes D4 structural rather than aspirational.

## 6. Gaps, wording, project ranking

All three ride on the same match; none costs another model call.

**Gaps** are the programme-side leftovers: a competency the page asked for that
nothing in the pool matched. Consultation only, never the CV. The output names
its own basis -- "against the 3 repositories and 2 publications on file" --
because a gap list computed over one repository would otherwise read as a
deficiency rather than as missing input.

**Programme wording** applies only to an already-matched pair. Where the names
differ, the page's phrasing is offered as an alternative label, with the
student's original beside it and the justifying excerpt. Written
`confirmed_by=None`; printed only after he confirms. Two structural limits keep
this from becoming fabrication: it can only relabel, never add, because it
rides on a match; and a match requires evidence on his side. The additional
rule -- do not widen; `DFT` -> `computational materials science` is a bigger
claim, not a synonym -- is given to the model and is not machine-checkable,
which is precisely why the human confirm is the gate.

**Project ranking** is the same match counted per repository: a project scores
by how many of the programme's *required* competencies its own skills matched.
Ordering needs no new machinery -- `entry_selection.select_best_entries`
already takes `limit` and `key` and keeps ties in input order. This matters
when the page limit bites (`R-023` caps a taught-track CV at two pages):
something is cut on a principle rather than by accident.

## 7. Failure behaviour

Tailoring degrades; it never blocks. No programme page, a refusal, or a schema
violation all collapse to "no matches", and the CV renders the mechanical list
in evidence order -- today's behaviour minus the junk. This follows
`extraction.py:propose_description`, which already collapses refusal, empty and
invalid into `None` for the same reason, and accepts the same known cost: a
systematic refusal is indistinguishable from "this programme page said
nothing".

## 8. Testing

Almost everything here is a pure function over text, which is what keeps the
existing package testable without a database. The new code keeps that shape.

* **Pinned regressions.** A C file whose comment reads `using leave-one-out
  cross validation` yields zero libraries. A repository importing thirty
  packages keeps the most-imported, not the alphabetically first.
* **The gating invariant, pinned on its own.** No `technique`-kind entry
  appears in rendered output unless it is part of a matched pair.
* **Manifest parsers.** One fixture per format plus a malformed one; a
  repository with no manifest asserts zero libraries.
* **The model call**, against a stubbed `ResponsesAPI`: an id outside the
  closed sets is rejected; a refusal degrades to "no matches" rather than
  raising; both inputs are labelled DATA.
* **One live end-to-end run** against a real repository and a real programme
  page stays opt-in and out of CI -- live runs cost money.

Run as `POSTGRES_DB=tehsil_<worktree> uv run pytest -q`; the shared
`test_tehsil` database wedges across parallel sessions and the symptom looks
like an unrelated regression.

## 9. Out of scope

* A global controlled vocabulary of skills. Matching is per-application.
* Any effect on `apps/funding` scoring -- skills do not change which programmes
  he is shown.
* Auto-confirmation of anything a model produced. Unchanged: interpretive
  claims stay `confirmed_by=None`.
* The same match applied to the motivation-letter engine, obvious as that
  extension is.

## 10. Shipping order

0. Reconcile `master` with `origin/master`.
1. **Pool fixes** -- delete the regexes, parse manifests, rank by import count,
   store evidence. Lands and is worth having with no tailoring at all.
2. **`ACADEMIC_PROFILE`** claim class and programme-page extraction.
3. **The match**, then gaps, wording and project ranking on top of it.

Each step is independently landable and independently useful.

## 11. Risks

* **The divergence is the schedule risk**, not the design risk: 53 local-only
  and 37 remote-only commits, and PR #26 landed on `origin/master` while this
  line of work stayed local.
* **`ACADEMIC_PROFILE` extraction quality is unmeasured.** No programme page
  has been run through it. Step 2 should be validated against a handful of real
  pages before step 3 is built on top of it.
* **Manifest coverage is untested against real student repositories.** If his
  work is overwhelmingly Python, deleting the regexes costs nothing; for a
  JavaScript or R student the manifest path carries all the weight.
* **The evidence package is still wired to nothing.** `ingest_evidence` has no
  caller outside tests, so none of this reaches a student until that is
  connected -- which is a separate piece of work this spec does not cover.
