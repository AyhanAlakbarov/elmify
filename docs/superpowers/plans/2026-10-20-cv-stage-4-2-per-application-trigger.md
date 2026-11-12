# CV Stage 4.2: per-application trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adding a programme or a separately-applied scholarship to "my applications" makes that application's own CV in the background. The CV is written with the application's saved requirement list, belongs to that application alone, and reaches only that application's kit. Every predictable failure becomes a visible state, never a dead letter.

**Architecture:** The kit-capture job (`document_worker._capture`) already runs on every add. After it captures the kit, it queues one `generate` job carrying the `application_id`. The generate job does five things:
- builds the list through a new worker-side module, `apps/documents/application_list.py`, which loads the programme, the card's scholarship, any same-application scholarships, the letter shape for the captured cycle and the track;
- calls `generate_cv` as today;
- saves the list, its digest and the destination on the new `DocumentDraft` fields;
- turns missing identity or email into `Application.cv_status`;
- re-queues itself with an SQS delivery delay when a limiter's window is full.

Render and the kit then read the draft's own saved list and its application link. They no longer use live rules or a "programme or none" filter.

**Tech Stack:** Python 3.14, Django 5.2, pydantic 2.13, Postgres with RLS, SQS (boto3), pytest + pytest-django, ruff (lint only), mypy.

**Spec:** `docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md` (branch `claude/cv-engine-quality-design`, amended 2026-10-20 at `1f398178` and corrected in the commit carrying this plan). This plan covers §6.2, §6.3's ids, states and track, §6.5's deadline copy, §6.10's "the draft records its scholarship", §6.12's digest and render-from-list, and §6.13's limiter items. The step table in §2 is the scope, row 4.2.

## Global Constraints

- **Task 0 first.** Bring `claude/cv-engine-quality-design` up to date with `master`, then branch: `git -C /home/orkhan/Desktop/cv-engine-design worktree add /home/orkhan/Desktop/cv-stage-4-2 -b claude/cv-stage-4-2-trigger claude/cv-engine-quality-design`. `W=/home/orkhan/Desktop/cv-stage-4-2`. Every git command uses `git -C $W`; the shell's cwd resets to the `master` checkout, and a hook blocks commits whose cwd is on `master`.
- Lint is `uv run ruff check .` only. Never run `ruff format`.
- Types: `uv run mypy apps config`. Tests: `uv run pytest -q tests/documents tests/portals tests/funding tests/audit tests/mailbox` (each checkout gets its own test database).
- Migrations: one per app this step touches (`documents`, `portals`), numbered after `master`'s latest once Task 0 has merged it. `uv run python manage.py makemigrations --check --dry-run` prints "No changes detected" after each migration task. Never hand-edit `uv.lock` or an applied migration.
- **Every new column on a student-reachable model is classified** in `apps/audit/redaction.py` (`REDACT` or `KEEP`). `tests/audit/test_redaction_classification.py::test_every_reachable_field_is_classified_exactly_once` fails otherwise. FKs are not classified.
- **Page text is data.** `Requirement.sentence` and `source_url` are display-only. Nothing in this step puts them into a prompt; the writer still receives only `include` field names (`generation.py`), until step 4.4.
- **The web tier holds no grant on catalogue tables** (`runtime_web`). Anything the web tier reads about a CV (status, destination, list) lives on tenant rows: `DocumentDraft` and `Application`. The catalogue (`Program`, `FundingOpportunity`, `CatalogRule`, `ApplicationPrompt`, `FundingCycleVerification`) is read only in the worker.
- **`DocumentWorkMessage` is `extra="forbid"`.** This step adds no field to it. `application_id` already exists and is what the new generate job carries. A field added anyway means a worker-first deploy (`scripts/deploy.sh`).
- **SQS standard-queue delivery delay is at most 900 seconds** per message. A longer wait is several hops, and each hop is a new message, so a hop never counts toward `maxReceiveCount: 3`.
- Force mapping, merge and the Europass gate are step 4.1's and unchanged: `BINDING` → strict, `ADVISORY_*` → soft. The step 4.1 test `test_a_derived_rule_cannot_unlock_the_europass_pii_egress` and the bool-only `required_wins`/`forbid_wins` hardening (`94183860`) must still pass.
- Commit with an explicit pathspec, never `git add -A`/`.`. Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never push to `master`. The PR targets `claude/cv-engine-quality-design` and is opened only on the owner's instruction. CI does not run (billing); the gates above are the evidence.
- Line numbers below are from `claude/cv-engine-quality-design` at `1f398178`, before Task 0's merge. Task 0 shifts `document_worker.py`, `document_queue.py` and `packets.py`; re-find by the quoted text.

## Out of this step (named so nobody builds them here)

- **The page read** is step 4.2b, with its own plan (spec §6.2): the fetcher plus model keys on one task, the gated queue, `Program` read status and the short wait. This step writes CVs from the rules already stored.
- **Model calls outside the long transaction** (§6.13, second bullet). It moves to step 4.4, which rewrites `generate_cv` around the list anyway. `generate_cv` mixes reads and model calls, and reads need `tenant_transaction` for the RLS setting (`.claude/rules/row-level-security.md`, failure mode 1), so a split here would be a second rewrite.
- **Questions, the answers table, the seven-day wait** (4.3); **writing to the list** (4.4); **"use my own CV", filenames, one needs line per destination** (4.6); **hand-edit marker** (4.10).

## Review Focus

Most likely to bite first. Each one's test is named in its task.

1. **Drafts made before this step vanish from kits.** They have `application = NULL` and `requirements = NULL`. The kit must keep serving a legacy draft by its programme, as today, and must not serve a post-4.2 draft whose application was removed (`application = NULL`, `requirements` set). Tests: Task 6 `test_a_legacy_programme_cv_still_reaches_its_kit`, `test_a_removed_applications_cv_never_reaches_a_new_card`.
2. **A redelivered capture job makes a second CV.** SQS delivers at least once, and `add_application` re-queues capture for a card with an empty kit. Each extra generate job costs a model call. The capture job queues `generate` only when `cv_status` is blank. The generate job skips an application that already has a non-superseded draft with the same list digest. Tests: Task 7 `test_capture_twice_queues_one_cv`; Task 4 `test_a_repeat_job_with_the_same_list_makes_no_second_draft`.
3. **A deferred job is lost or loops into the dead-letter queue.** If re-enqueueing raises, the original message must not be deleted, so SQS redelivers it. A job still limited after its delay defers again rather than raising. Tests: Task 8 `test_a_failed_defer_leaves_the_message_for_redelivery`, `test_a_still_limited_job_defers_again`.
4. **An award card's CV is dropped, or carries no scholarship.** For an award card, `Application.program_id` holds a `FundingOpportunity` id. Today `_generate` looks it up as a `Program`, finds none and drops the job. The draft must record `funding_opportunity` and leave `programme = NULL`. Tests: Task 4 `test_an_award_cards_cv_records_its_scholarship`; Task 6 `test_a_scholarship_cv_never_reaches_another_applications_kit`.
5. **One approval makes every older approved CV servable.** Approving never supersedes older approved drafts, so the kit lists every version. The kit serves only the newest approved CV per application. Test: Task 6 `test_only_the_newest_approved_cv_of_an_application_is_served`.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `apps/documents/requirement_list.py` | Modify | `Requirement.id`; `state` removed; sentence stored once; `RequirementList.digest()`; `build_requirements(..., together=...)` |
| `apps/documents/application_list.py` | Create | Worker-side: the inputs of one application's list (programme, scholarship, same-application scholarships, letter shape, track) and the destination label |
| `apps/documents/models.py` | Modify | `DocumentDraft.application`, `requirements`, `requirement_states`, `requirements_digest`, `destination_label`, `is_general` |
| `apps/documents/drafts.py` | Modify | `create_draft` accepts the new fields |
| `apps/documents/document_worker.py` | Modify | `_generate` builds and saves the list, handles award cards, maps failures to `cv_status`, defers on limits; `_capture` queues the CV |
| `apps/documents/cv_jobs.py` | Create | `queue_application_cv`, `resume_waiting_cvs`, `defer` |
| `apps/documents/render.py`, `europass_render.py` | Modify | Rules from the saved list when there is one |
| `apps/documents/api.py` | Modify | `generate` stops spending the CV limit and links the student's application |
| `apps/documents/revisions.py` | Modify | Quick edit carries the new fields |
| `apps/documents/confirmation.py`, `apps/mailbox/views.py` | Modify | Resume waiting CVs when identity is confirmed or the email granted |
| `apps/portals/models.py` | Modify | `Application.cv_status`, `cv_resumes_at` |
| `apps/portals/packets.py` | Modify | `_kit_documents` serves the application's newest approved CV |
| `apps/portals/award_deadline.py` | Create | The award card's deadline from stored cycle evidence |
| `apps/queue.py`, `apps/documents/document_queue.py` | Modify | `delay_seconds` on enqueue |
| `apps/ratelimit.py` | Modify | `seconds_until_reset` |
| `apps/audit/redaction.py` | Modify | Classify the new columns |
| `apps/documents/management/commands/queue_application_cvs.py` | Create (Task 11, conditional) | Backfill |

---

### Task 0: Bring the design branch up to date with master, then branch

`claude/cv-engine-quality-design` is 381 commits behind `origin/master` (merge base `397085a2`). `master` rewrote `document_queue.py`'s `action` literal and added an on-commit send, gained `read_document`/`refresh_evidence` branches in `document_worker.handle_document_work`, and added documents migrations 0028–0036. This step edits all three, so it starts from them.

- [ ] **Step 1:** In `/home/orkhan/Desktop/cv-engine-design`, check that `git status --short` is empty, then `git fetch origin && git merge origin/master`. On a conflict, keep both sides' behaviour. Master has not touched `derive.py`, `rule_sinks.py`, `constraints.py`, `render.py` or `grammar*.py` since the merge base, so conflicts are expected in docs, `packets.py`, `document_worker.py` and `document_queue.py` only. A document conflict keeps the measured claims of each side (`~/.config/ai_rules/rules/workflows.md`, "Plan execution").
- [ ] **Step 2:** Gates on the merge: `uv run ruff check .`, `uv run mypy apps config`, `uv run python manage.py makemigrations --check --dry-run` ("No changes detected"), `uv run pytest -q`. Expected: all pass, apart from the 2 known OCR failures master carries. If any other test fails, compare it on `origin/master` with `git worktree add --detach /tmp/claude-1000/m42 origin/master` plus one test run. A failure that also happens there is master's; anything else is the merge's.
- [ ] **Step 3:** Commit the merge, push `claude/cv-engine-quality-design` (owner approved pushing this branch, 2026-10-20), and create the worktree from Global Constraints.

### Task 1: Lasting item ids, states off the item, one stored sentence, the digest

**Files:**
- Modify: `apps/documents/requirement_list.py` (`Requirement` :89-123, `RequirementList` :126-156)
- Test: `tests/documents/test_requirement_list.py`

**Interfaces:**
- Produces:
  - `Requirement.id: str` (16 hex characters; filled by `RequirementList`, never by callers);
  - `RequirementList.digest() -> str` (64 hex characters);
  - `RequirementList.by_id() -> dict[str, Requirement]`.
- Removes `Requirement.state`; `ItemState` stays as the type of the values in `DocumentDraft.requirement_states`.

- [ ] **Step 1: Write the failing tests**

```python
def test_item_ids_are_the_same_across_two_builds():
    a, b = _two_builds_of_the_same_programme()
    assert [i.id for i in a.items] == [i.id for i in b.items]
    assert all(len(i.id) == 16 for i in a.items)

def test_true_duplicates_get_distinct_ids():
    built = RequirementList(items=(_written("Send a CV"), _written("Send a CV")))
    assert len({i.id for i in built.items}) == 2

def test_a_reread_that_changes_only_rule_ids_and_order_keeps_ids_and_digest():
    before = _list_from(rules=[_rule("PAGE-3", "max_pages", 2), _rule("PAGE-7", "photo_allowed", False)])
    after = _list_from(rules=[_rule("PAGE-9", "photo_allowed", False), _rule("PAGE-1", "max_pages", 2)])
    assert {i.key: i.id for i in before.items} == {i.key: i.id for i in after.items}
    assert before.digest() == after.digest()

def test_the_digest_changes_when_a_value_changes():
    assert _list_from(rules=[_rule("PAGE-3", "max_pages", 2)]).digest() != \
           _list_from(rules=[_rule("PAGE-3", "max_pages", 3)]).digest()

def test_the_digest_ignores_sentences_and_contributors():
    a = _list_from(rules=[_rule("PAGE-3", "max_pages", 2, text="Two pages max.")])
    b = _list_from(rules=[_rule("PAGE-3", "max_pages", 2, text="CV: at most 2 pages")])
    assert a.digest() == b.digest()

def test_a_ruled_items_sentence_is_dumped_once_and_read_back():
    built = _list_from(rules=[_rule("PAGE-3", "max_pages", 2, text="Two pages max.")])
    dumped = built.model_dump(mode="json")
    assert "sentence" not in dumped["items"][0]
    assert RequirementList.model_validate(dumped).items[0].sentence == "Two pages max."

def test_an_item_has_no_state_field():
    assert "state" not in Requirement.model_fields
```

`_two_builds_of_the_same_programme`, `_list_from`, `_rule` and `_written` are local helpers over `build_requirements` and `Requirement`, in the style of this file's existing helpers.

- [ ] **Step 2: Run** `uv run pytest -q tests/documents/test_requirement_list.py`. Expected: the new tests fail (`id`, `digest`, the `state` field).
- [ ] **Step 3: Implement**
  - **The id.** `id` is computed in a `RequirementList` `model_validator(mode="after")`, never accepted from callers. It is the first 16 hex characters of `sha256` over `json.dumps([document, key, origin, source_url, value, n], sort_keys=True, default=str)`, where `n` counts earlier items with the same five-tuple. `source_url` is the item's own field (for a ruled item, `rule.source_url` when the field is blank). `rule.rule_id` is never part of the id, because it carries the sentence's position on the page.
  - **`digest()`.** `sha256` over `json.dumps(sorted([document, key, value, force, origin, conflict] for each item), sort_keys=True, default=str)`.
  - **One stored sentence.** A `model_serializer(mode="wrap")` drops `sentence` when it equals `rule.rule_text`. A `model_validator(mode="before")` refills it from `rule["rule_text"]` when absent.
  - Remove `state`. Grep for `.state` and `state=` on `Requirement` across `apps/` and `tests/`, and fix each use.
- [ ] **Step 4: Run** the file, then `uv run pytest -q tests/documents/test_catalog_rules.py tests/documents/test_render.py`. Expected: PASS. `cv_rules()` output is unchanged.
- [ ] **Step 5: Commit** `refactor(cv): lasting requirement ids, digest of what changes the CV, states off the item`.

### Task 2: Same-application scholarships in the list

**Files:**
- Modify: `apps/documents/requirement_list.py` (`build_requirements` :717, `_format_item`)
- Test: `tests/documents/test_requirement_list.py`, `tests/documents/test_catalog_rules.py`

**Interfaces:**
- Produces: `build_requirements(program, opportunity=None, *, together: Sequence[Any] = (), catalog=..., track=..., style_rules=..., letter_shape=..., document_language=..., competencies=...) -> RequirementList`. The other parameters are unchanged.

- [ ] **Step 1: Write the failing tests** (the database ones in `test_catalog_rules.py`, which already seeds `CatalogRule` rows):

```python
def test_a_together_awards_funder_rule_reaches_the_programmes_list(db, program_factory):
    programme = program_factory()
    emjm = _award(route="JOINT_SELECTION", cv_format_requirement="europass_required")
    _funder_rule(emjm, "R-900", "max_pages", 3, enforcement="BINDING")
    built = build_requirements(programme, together=[emjm], catalog=CatalogRule.objects.order_by("rule_id"))
    item = next(i for i in built.items if i.key == "max_pages")
    assert (item.value, item.origin, item.force) == (3, "scholarship", "strict")

def test_a_together_award_brings_its_format_when_the_card_has_none(db, program_factory):
    built = build_requirements(program_factory(), together=[_award(cv_format_requirement="europass_required")])
    fmt = next(i for i in built.items if i.key == "cv_format")
    assert (fmt.value, fmt.origin) == ("europass_required", "scholarship")

def test_a_together_award_adds_no_non_funder_catalog_rule_twice(db, program_factory):
    programme = program_factory()
    alone = build_requirements(programme, catalog=CatalogRule.objects.order_by("rule_id"))
    joined = build_requirements(programme, together=[_award()], catalog=CatalogRule.objects.order_by("rule_id"))
    assert [i.id for i in alone.items] == [i.id for i in joined.items]
```

- [ ] **Step 2: Run.** Expected: FAIL (`together` is not a parameter).
- [ ] **Step 3: Implement.**
  - For each award in `together`, `build_requirements` adds `_catalog_contributions` restricted to rows whose `scope_kind == "FUNDER"` (so UNIVERSAL, TRACK, COUNTRY and INSTITUTION rows are not added twice).
  - `_format_item` takes the first non-empty `cv_format_requirement` among `(opportunity, *together)` before the programme's own. Its order is unchanged: funder, then programme.
- [ ] **Step 4: Run** both files. Expected: PASS.
- [ ] **Step 5: Commit** `feat(cv): scholarships applied for in the programme's own application join its list`.

### Task 3: The draft and the application carry the CV's facts

**Files:**
- Modify: `apps/documents/models.py` (`DocumentDraft` :121-233), `apps/documents/drafts.py` (`create_draft` :25-60), `apps/portals/models.py` (`Application` :337-522), `apps/audit/redaction.py` (REDACT :102, KEEP :276-286, plus the `portals.Application` KEEP entry)
- Create: one migration in each of `apps/documents/migrations/` and `apps/portals/migrations/`
- Test: `tests/documents/test_document_draft.py`, `tests/portals/test_application.py`, `tests/audit/test_redaction_classification.py` (existing tripwire, no edit)

**Interfaces:**
- Produces, on `DocumentDraft`:
  - `application = FK("portals.Application", null=True, blank=True, on_delete=SET_NULL, related_name="cv_drafts")`;
  - `requirements = JSONField(null=True, blank=True)` (null: made before step 4.2);
  - `requirement_states = JSONField(default=dict, blank=True)` (`{item id: {"state": ItemState, "reason": str}}`);
  - `requirements_digest = CharField(max_length=64, blank=True, default="")`;
  - `destination_label = CharField(max_length=300, blank=True, default="")`;
  - `is_general = BooleanField(default=False)`.
- Produces: `create_draft(*, student, kind, content, facts=(), programme=None, funding_opportunity=None, application=None, requirements: RequirementList | None = None, destination_label="", is_general=False, render_variant="", actor=None) -> DocumentDraft`. It stores `requirements.model_dump(mode="json")` and `requirements.digest()`.
- Produces, on `Application`:
  - `cv_status = CharField(max_length=20, blank=True, default="", choices=CVStatus)`, where `class CVStatus(TextChoices)` has `QUEUED`, `WAITING_IDENTITY`, `WAITING_EMAIL`, `NO_CV`, `MADE`;
  - `cv_resumes_at = DateTimeField(null=True, blank=True)`.
  - A `CheckConstraint` named `portal_app_cv_status_valid` (pattern: the fee_state check).

- [ ] **Step 1: Write the failing tests**

```python
def test_create_draft_saves_the_list_its_digest_and_destination(db, membership_a, program_factory):
    built = build_requirements(program_factory())
    with tenant_scope(membership_a.tenant_id):
        draft = create_draft(student=membership_a, kind="CV", content=_content(),
                             requirements=built, destination_label="MSc Data Science, TU Delft")
    assert RequirementList.model_validate(draft.requirements) == built
    assert draft.requirements_digest == built.digest()
    assert draft.requirement_states == {}

def test_a_draft_made_without_a_list_stores_null(db, membership_a):
    with tenant_scope(membership_a.tenant_id):
        assert create_draft(student=membership_a, kind="CV", content=_content()).requirements is None

def test_removing_an_application_with_a_cv_attached_succeeds(db, membership_a):
    app, draft = _application_with_cv(membership_a)
    remove_application(app, actor=membership_a)
    draft.refresh_from_db()
    assert draft.application_id is None and draft.requirements is not None

def test_a_cv_status_outside_the_choices_is_refused(db, membership_a):
    with pytest.raises(IntegrityError):
        Application.objects.create(tenant=membership_a.tenant, student=membership_a,
                                   program_id=uuid4(), cv_status="BOGUS")
```

`test_removing_...` goes in `tests/portals/test_applications.py`; the others go in the files above.

- [ ] **Step 2: Run them.** Expected: FAIL (unknown fields).
- [ ] **Step 3: Implement the fields and migrations,** then classify the new columns in `redaction.py`:
  - `DocumentDraft`: `requirement_states` goes to REDACT beside `content`, because states can name student entries (spec §10). `requirements`, `requirements_digest`, `destination_label` and `is_general` go to KEEP.
  - `Application`: `cv_status` and `cv_resumes_at` go to KEEP.
- [ ] **Step 4: Run** the tests, the redaction tripwires and `makemigrations --check --dry-run`. Expected: PASS, "No changes detected".
- [ ] **Step 5: Commit** `feat(cv): drafts record their application, list and destination; applications record their CV status`.

### Task 4: The generate job builds and saves the application's list

**Files:**
- Create: `apps/documents/application_list.py`
- Modify: `apps/documents/document_worker.py` (`_generate` :370-441; docstring :373-392)
- Test: `tests/documents/test_application_list.py` (new), `tests/documents/test_document_worker.py`

**Interfaces:**
- Consumes: `build_requirements(..., together=...)` (Task 2), `create_draft(...)` (Task 3).
- Produces in `application_list.py` (worker-only; reads the catalogue):
  - `@dataclass(frozen=True) class ListInputs: programme: Program | None; opportunity: FundingOpportunity | None; together: tuple[FundingOpportunity, ...]; destination_label: str`;
  - `def inputs_for(application: Application | None, programme_id: UUID | None) -> ListInputs | None`. It returns `None` when the id names neither a `Program` nor a `FundingOpportunity`, which is the existing drop.
  - `def track_for(programme: Program | None, student: Membership) -> str`: `programme.academic_track` when set; else `"research"` when the student has a generatable `VerifiedFact` of category `RESEARCH`; else `"taught"`.
  - `def build_for(inputs: ListInputs, student: Membership, application: Application | None) -> RequirementList`.
  - `TOGETHER_ROUTES = frozenset({"CONSIDERED_WITH_ADMISSION", "JOINT_SELECTION"})`.

`inputs_for`:
- **Award card** (`application.candidate` not None and `candidate.opportunity_id` not None): `opportunity = candidate.opportunity`, `programme = None`.
- **Programme card or a plain programme id:** `programme = Program` by id. `opportunity` is the `FundingOpportunity` behind a separate card linked to this one through `ApplicationLink`, when there is exactly one, else `None`. `together = FundingOpportunity.objects.filter(Q(program=programme) | Q(programs=programme), route__in=TOGETHER_ROUTES).distinct().order_by("id")`.
- `destination_label` is the programme's `name` (with its institution's name after a comma when it has one), else the opportunity's `name`.

`build_for` calls `build_requirements` with:
- `catalog=CatalogRule.objects.order_by("rule_id")`;
- `track=track_for(...)`;
- `style_rules=render._UNIVERSAL_RULES`;
- `letter_shape=shape_from_prompt(prompt)`, where `prompt` is the `ApplicationPrompt` for `(programme, application.kit_letter_cycle)`. It is `None` when there is no programme, no cycle or no prompt, and so is `document_language`;
- `competencies` = the programme's COMPETENCY `ProgramStatement` texts, as `generation._tailor` reads them.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_award_cards_cv_records_its_scholarship(db, ...):
    card = _award_card(opportunity=_award(name="DAAD EPOS"))
    _run_generate(application=card)
    draft = DocumentDraft.objects.get(application=card)
    assert draft.programme_id is None and draft.funding_opportunity_id == card.candidate.opportunity_id
    assert draft.destination_label == "DAAD EPOS"

def test_a_programme_cards_cv_saves_its_list_and_digest(db, ...):
    card = _programme_card()
    _run_generate(application=card)
    draft = DocumentDraft.objects.get(application=card)
    assert draft.requirements is not None and len(draft.requirements_digest) == 64
    assert draft.is_general is False

def test_a_generate_without_application_or_programme_is_the_general_cv(db, ...):
    _run_generate(application=None, programme_id=None)
    assert DocumentDraft.objects.get().is_general is True

def test_a_repeat_job_with_the_same_list_makes_no_second_draft(db, ...):
    card = _programme_card()
    _run_generate(application=card); _run_generate(application=card)
    assert DocumentDraft.objects.filter(application=card).count() == 1

def test_the_track_comes_from_research_facts_when_the_programme_states_none(db, membership_a):
    _confirmed_fact(membership_a, category="RESEARCH")
    assert track_for(program_factory(academic_track=""), membership_a) == "research"

def test_an_unknown_id_is_still_dropped_with_a_warning(db, caplog, ...):
    _run_generate(application=None, programme_id=uuid4())
    assert "DocumentGenerateUnknownProgramme" in caplog.text and not DocumentDraft.objects.exists()
```

`_run_generate` builds a `DocumentWorkMessage(action="generate", kind="CV", ..., application_id=..., programme_id=...)` and calls `document_worker._generate`, with `generate_cv` monkeypatched to return a fixed `GenerationResult`, as the file's existing generate tests do.

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** `_generate`:
  1. loads `application` when `message.application_id` is set, and returns with a log line if the row is gone;
  2. gets `inputs_for(...)`, keeping the unknown-id and BLOCKED-verdict drops (the verdict applies only when there is a programme);
  3. calls `build_for`;
  4. returns without generating when `application` has a non-superseded draft with the same `requirements_digest`;
  5. calls `generate_cv(student=..., programme=inputs.programme)` as today;
  6. calls `create_draft(..., programme=inputs.programme, funding_opportunity=inputs.opportunity, application=application, requirements=built, destination_label=inputs.destination_label, is_general=application is None and inputs.programme is None and inputs.opportunity is None)`;
  7. sets `application.cv_status = MADE`.

  Update the docstring: the predictable failures are now handled here (Task 7), not only at the endpoint.
- [ ] **Step 4: Run** both test files. Expected: PASS.
- [ ] **Step 5: Commit** `feat(cv): the generate job builds, saves and digests the application's requirement list`.

### Task 5: Render from the saved list

**Files:**
- Modify: `apps/documents/render.py` (`render_draft` :1263-1302), `apps/documents/europass_render.py` (:118-123)
- Test: `tests/documents/test_render.py`, `tests/documents/test_europass_render.py`

**Interfaces:**
- Produces: `def draft_rules(draft: DocumentDraft, content: CVContent) -> tuple[ConstraintRule, ...]` in `render.py`. It returns `RequirementList.model_validate(draft.requirements).cv_rules()` when `draft.requirements is not None` (an empty list gives `()`), and `resolve_rules(draft.programme, draft.funding_opportunity, content=content)` when it is `None` (a legacy draft).

- [ ] **Step 1: Write the failing tests**

```python
def test_render_draft_uses_the_saved_list_not_the_live_rules(db, monkeypatch, ...):
    draft = _approved_draft(requirements=_list_with(max_pages=1))
    monkeypatch.setattr(render, "resolve_rules", _explode)
    assert ("max_pages", 1) in {(r.key, r.value) for r in draft_rules(draft, _content())}

def test_a_saved_list_with_no_rules_never_falls_back_to_live(db, monkeypatch, ...):
    draft = _approved_draft(requirements=RequirementList())
    monkeypatch.setattr(render, "resolve_rules", _explode)
    render_draft(draft=draft)

def test_a_legacy_draft_still_resolves_live(db, ...):
    draft = _approved_draft(requirements=None)
    assert draft_rules(draft, _content()) == resolve_rules(draft.programme, draft.funding_opportunity, content=_content())

def test_the_europass_cache_key_hashes_the_saved_lists_rules(db, ...):
    a = _approved_europass_draft(requirements=_list_with(prohibited=["hyperlinks"]))
    b = _approved_europass_draft(requirements=_list_with())
    assert _cache_key(a) != _cache_key(b)
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `render_draft`: `if not constraints: constraints = draft_rules(draft, content)`. The "empty constraints means resolve live" branch is gone for list-bearing drafts.
  - `europass_render.render_and_store` uses `draft_rules`.
  - Directives stay `directives_from_program(draft.programme)` until step 4.4, which switches them to the list (step 4.1 plan, "What later steps consume").
- [ ] **Step 4: Run** `tests/documents/test_render.py tests/documents/test_europass_render.py tests/documents/test_europass_worker.py`. Expected: PASS, with `test_a_derived_rule_cannot_unlock_the_europass_pii_egress` unchanged.
- [ ] **Step 5: Commit** `feat(cv): render checks a draft against its own saved list`.

### Task 6: The kit serves the application's own newest approved CV

**Files:**
- Modify: `apps/portals/packets.py` (`_kit_documents` :461-531, the query at :488-495)
- Test: `tests/portals/test_kit.py`

**Interfaces:**
- Produces: `def kit_cv_drafts(application: Application) -> list[DocumentDraft]`, in `packets.py`, used by `_kit_documents`. It returns at most one draft per destination:
  - the newest approved, rendered CV with `application=application`;
  - else the newest approved general CV (`is_general=True`);
  - else, for legacy drafts (`application IS NULL AND requirements IS NULL`), the newest approved draft with `programme_id == application.program_id`, else the newest legacy draft with `programme`, `funding_opportunity` and `application` all null.

  "Newest" means highest `version`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_scholarship_cv_never_reaches_another_applications_kit(db, ...):
    award_card, programme_card = _award_card(), _programme_card()
    _approved_cv(application=award_card, funding_opportunity=award_card.candidate.opportunity)
    assert _kit_cv_ids(programme_card) == []

def test_an_award_card_gets_its_own_cv(db, ...):
    card = _award_card(); cv = _approved_cv(application=card)
    assert _kit_cv_ids(card) == [cv.id]

def test_only_the_newest_approved_cv_of_an_application_is_served(db, ...):
    card = _programme_card(); _approved_cv(application=card); newer = _approved_cv(application=card)
    assert _kit_cv_ids(card) == [newer.id]

def test_a_legacy_programme_cv_still_reaches_its_kit(db, ...):
    card = _programme_card(); legacy = _approved_cv(programme_id=card.program_id, requirements=None)
    assert _kit_cv_ids(card) == [legacy.id]

def test_a_removed_applications_cv_never_reaches_a_new_card(db, ...):
    old = _programme_card(); _approved_cv(application=old); remove_application(old, actor=old.student)
    new = _programme_card(program_id=old.program_id)
    assert _kit_cv_ids(new) == []

def test_a_re_applicants_new_card_does_not_get_last_years_cv(db, ...):
    last_year = _programme_card(); _approved_cv(application=last_year)
    this_year = _programme_card(program_id=last_year.program_id, candidate=_new_candidate())
    assert _kit_cv_ids(this_year) == []
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `kit_cv_drafts` and use it in `_kit_documents` instead of the `Q(programme_id=...) | Q(programme__isnull=True)` query. Prepared-document rows and the bundle logic are unchanged. `mint_packet`'s "approved draft removes CV uploads" stays (§6.15 changes it in 4.6).
- [ ] **Step 4: Run** `tests/portals/test_kit.py tests/portals/test_kit_view.py tests/portals/test_packet.py`. Expected: PASS. An existing test that relied on every approved version being listed is changed on purpose; name it in the commit body.
- [ ] **Step 5: Commit** `fix(kit): each application gets only its own newest approved CV`.

### Task 7: Adding an application queues its CV; failures become states

**Files:**
- Create: `apps/documents/cv_jobs.py`
- Modify: `apps/documents/document_worker.py` (`_capture` :302-325, `_generate`), `apps/documents/confirmation.py` (`confirm_facts` :37), `apps/mailbox/views.py` (:207, after `membership.application_email = grant.address`)
- Test: `tests/documents/test_cv_jobs.py` (new), `tests/documents/test_document_worker.py`, `tests/documents/test_confirmation.py`, `tests/mailbox/test_views.py` (or the file covering the grant view)

**Interfaces:**
- Produces in `cv_jobs.py`:
  - `def queue_application_cv(application: Application, *, delay_seconds: int = 0) -> None`. It enqueues `DocumentWorkMessage(action="generate", kind="CV", tenant_id, student_id, application_id=application.id, programme_id=application.program_id)` on commit, and sets `cv_status=QUEUED`.
  - `def resume_waiting_cvs(student: Membership) -> int`. It calls `queue_application_cv` for each of the student's applications whose `cv_status` is `WAITING_IDENTITY` or `WAITING_EMAIL`, and returns the count.
- Consumes: `Application.CVStatus` (Task 3), `inputs_for`/`build_for` (Task 4).

The CV is skipped (`cv_status = NO_CV`, no model call) when the built list's `cv_format` item has value `structured_fields_only` (spec §6.2, corrected 2026-10-20).

- [ ] **Step 1: Write the failing tests**

```python
def test_capture_queues_the_applications_cv(db, captured_queue, ...):
    card = _programme_card(); _run_capture(card)
    assert [(m.action, m.application_id) for m in captured_queue] == [("generate", card.id)]
    card.refresh_from_db(); assert card.cv_status == "QUEUED"

def test_capture_twice_queues_one_cv(db, captured_queue, ...):
    card = _programme_card(); _run_capture(card); _run_capture(card)
    assert sum(m.action == "generate" for m in captured_queue) == 1

def test_missing_identity_becomes_a_waiting_state_not_a_dead_letter(db, ...):
    card = _programme_card(identity_confirmed=False)
    _run_generate(application=card)
    card.refresh_from_db(); assert card.cv_status == "WAITING_IDENTITY"

def test_missing_email_becomes_a_waiting_state(db, ...):
    card = _programme_card(application_email="")
    _run_generate(application=card)
    card.refresh_from_db(); assert card.cv_status == "WAITING_EMAIL"

def test_confirming_identity_resumes_every_waiting_cv(db, captured_queue, ...):
    a, b = _programme_card(cv_status="WAITING_IDENTITY"), _programme_card(cv_status="WAITING_IDENTITY")
    confirm_facts(student=a.student, fact_ids=[_identity_fact(a.student).id], actor=a.student)
    assert {m.application_id for m in captured_queue} == {a.id, b.id}

def test_a_use_our_form_programme_gets_no_cv(db, ...):
    card = _programme_card(cv_format_requirement="structured_fields_only")
    _run_generate(application=card)
    card.refresh_from_db()
    assert card.cv_status == "NO_CV" and not DocumentDraft.objects.filter(application=card).exists()

def test_a_job_for_a_removed_application_is_dropped(db, ...):
    card = _programme_card(); message = _generate_message(card); card.delete()
    document_worker._generate(message)
    assert not DocumentDraft.objects.exists()
```

The grant-view test asserts that `resume_waiting_cvs` is called once the address is saved, with the queue monkeypatched as `tests/portals/test_applications.py::captured` does.

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **`_capture`:** after `capture_requirements` and `_prepare`, call `queue_application_cv(application)` when `application.cv_status == ""`.
  - **`_generate`:** catch `IdentityNotConfirmed` and `ApplicationEmailMissing` around `generate_cv`. The tenant transaction rolls back, so record `WAITING_IDENTITY`/`WAITING_EMAIL` in a fresh `tenant_transaction` and return normally, which deletes the message.
  - **`confirm_facts`:** call `resume_waiting_cvs(student)` when an IDENTITY fact is among those confirmed.
  - **The mailbox grant view:** call it after saving the address.
  - Both callers run in the web tier and only enqueue.
- [ ] **Step 4: Run** the four test files. Expected: PASS.
- [ ] **Step 5: Commit** `feat(cv): adding an application queues its CV; missing identity or email waits instead of failing`.

### Task 8: Limits counted once, and every limit queues and resumes

**Files:**
- Modify: `apps/queue.py` (`enqueue`), `apps/documents/document_queue.py` (`enqueue_document_work` :142-145), `apps/ratelimit.py`, `apps/documents/api.py` (`generate` :403-439), `apps/documents/document_worker.py` (`_generate`), `apps/documents/cv_jobs.py`, `apps/documents/management/commands/run_document_worker.py` (:58-76 comment and catch)
- Test: `tests/test_queue.py` (or the file covering `apps/queue.py`), `tests/test_ratelimit.py`, `tests/documents/test_cv_jobs.py`, `tests/documents/test_api.py`, `tests/documents/test_run_document_worker.py`

**Interfaces:**
- Produces:
  - `enqueue(message, *, client=None, queue_url, group_id=None, delay_seconds: int = 0)`. `DelaySeconds` is sent only when greater than 0. A value outside 0–900 raises `ValueError`.
  - `enqueue_document_work(message, *, client=None, queue_url, delay_seconds: int = 0)`.
  - `def seconds_until_reset(window_seconds: int) -> int` in `ratelimit.py`: `window_seconds - int(time.time()) % window_seconds`, using the module's `time` (tests freeze it).
  - `def defer(message: DocumentWorkMessage, *, window_seconds: int, application: Application | None) -> None` in `cv_jobs.py`. It re-enqueues `message` with `delay_seconds=min(900, seconds_until_reset(window_seconds))`. When `application` is set, it also records `cv_status=QUEUED` and `cv_resumes_at = now + that delay`.

- [ ] **Step 1: Write the failing tests**

```python
def test_one_api_request_and_its_job_spend_one_cv_generation(db, client_logged_in_as_student, ...):
    client_logged_in_as_student.post("/api/documents/generate", {...})
    _run_queued_generate()
    assert cache.get(_cv_bucket_key(student)) == 1

def test_the_api_still_refuses_a_flood_of_requests(db, ...):
    responses = [_post_generate() for _ in range(21)]
    assert responses[-1].status_code == 429

def test_a_cv_limit_defers_the_job_instead_of_raising(db, captured_queue, ...):
    _fill_bucket("cv_generation", student, 10)
    _run_generate(application=card)
    assert captured_queue[-1].application_id == card.id and captured_queue.delays[-1] == 900
    card.refresh_from_db(); assert card.cv_status == "QUEUED" and card.cv_resumes_at is not None

def test_a_skill_match_limit_defers_the_job_too(db, captured_queue, monkeypatch, ...):
    monkeypatch.setattr(generation, "_tailor", _raise(SkillMatchRateLimited))
    _run_generate(application=card)
    assert captured_queue[-1].application_id == card.id

def test_a_still_limited_job_defers_again(db, captured_queue, ...):
    _fill_bucket("cv_generation", student, 10)
    _run_generate(application=card); _run_generate(application=card)
    assert sum(m.application_id == card.id for m in captured_queue) == 2

def test_a_failed_defer_leaves_the_message_for_redelivery(db, monkeypatch, ...):
    monkeypatch.setattr(cv_jobs, "enqueue_document_work", _raise(RuntimeError))
    _fill_bucket("cv_generation", student, 10)
    with pytest.raises(RuntimeError):
        _run_generate(application=card)

def test_delay_seconds_above_the_sqs_cap_is_refused():
    with pytest.raises(ValueError):
        enqueue(_message(), queue_url="q", client=_FakeSQS(), delay_seconds=901)

def test_seconds_until_reset_counts_down_to_the_window_edge(frozen_time_at_1_700_000_000):
    assert seconds_until_reset(3600) == 3600 - 1_700_000_000 % 3600
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **`api.generate`:** replace `generation_rate_limited(student.id)` with `pack_command_rate_limited(student.id)`, the existing per-student request limiter (20 a minute). It keeps the 429 for floods and spends no CV generation, so `generate_cv`'s own check is the one count per job (spec §6.13). It also passes `application_id` when the student owns an `Application` whose `program_id` equals `programme_id` (newest by `created_at`).
  - **`_generate`:** catch `GenerationRateLimited` (window `_CV_GENERATION_RATE_WINDOW_SECONDS`) and `SkillMatchRateLimited` (window 3600, `tailoring.py:280-282`) outside the tenant transaction, then call `defer`. If `defer` raises, the exception propagates, so the message is not deleted.
  - **`run_document_worker`:** drop `GenerationRateLimited` from the deferral catch; keep `IngestionRateLimited`. Update the 58–66 comment, which says the deferral ends in the dead-letter queue.
- [ ] **Step 4: Run** the five test files. Expected: PASS.
- [ ] **Step 5: Commit** `fix(cv): one CV generation per job, and a full limit queues the job instead of dead-lettering it`.

### Task 9: An award card gets its deadline from our stored reading

**Files:**
- Create: `apps/portals/award_deadline.py`
- Modify: `apps/documents/document_worker.py` (`_capture`)
- Test: `tests/portals/test_award_deadline.py` (new)

**Interfaces:**
- Produces: `def award_deadline(application: Application) -> datetime | None` (worker-only). Steps:
  1. return `None` unless the card is an award card (`candidate.opportunity_id` set);
  2. load the student's profile snapshot through `candidate.run.profile_version_id` (`StudentProfileVersion.snapshot` → `StudentProfileSnapshot`), giving `year = intended_intake.year`;
  3. load the `FundingCycleVerification` row for `(opportunity, year)`, returning `None` when there is none;
  4. `evidence = to_evidence(row.evidence, target_year=year, cadence=<the award's cadence, as research/cycle_verification._cadence reads it>, page_removed=row.page_removed, lapsed=row.projection_lapsed)`;
  5. `select_deadline(evidence, deadline_student(nationality, country_of_residence))`;
  6. return the date at 00:00 UTC.

  Midnight UTC sits at or before the end of that day anywhere, so every reminder rung fires early, never late. `deadline_timezone` stays blank.
- `_cadence` is made public as `cadence_of(opportunity)` in `research/cycle_verification.py`, keeping one implementation.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_award_card_gets_its_intakes_deadline(db, ...):
    card = _award_card(intake=date(2027, 9, 1), nationality="AZ")
    _cycle_row(card.candidate.opportunity, 2027, deadlines=[["2027-01-15", "15 January 2027", "ALL"]])
    assert award_deadline(card) == datetime(2027, 1, 15, tzinfo=UTC)

def test_a_deadline_for_other_applicants_only_is_not_used(db, ...):
    card = _award_card(intake=date(2027, 9, 1), nationality="AZ")
    _cycle_row(card.candidate.opportunity, 2027, deadlines=[["2026-11-30", "30 Nov (EU)", "EU"]])
    assert award_deadline(card) is None

def test_no_stored_cycle_row_means_no_deadline(db, ...):
    assert award_deadline(_award_card()) is None

def test_a_programme_card_has_no_stored_deadline_yet(db, ...):
    assert award_deadline(_programme_card()) is None

def test_capture_writes_the_deadline_only_when_the_card_has_none(db, ...):
    card = _award_card(deadline=datetime(2027, 2, 1, tzinfo=UTC)); _cycle_row(...)
    _run_capture(card); card.refresh_from_db()
    assert card.deadline == datetime(2027, 2, 1, tzinfo=UTC)
```

The `EvidenceEntry` shape for `_cycle_row` is copied from `tests/funding/test_cycle_evidence.py`'s fixtures. Read that file for the exact `deadlines` triple and the `condition` values `select_deadline` matches.

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `award_deadline`. `_capture` then sets `application.deadline` when it is `None` and `award_deadline(...)` returns a date.
- [ ] **Step 4: Run** the new file, plus `tests/portals/test_reminder_sweep.py`. Expected: PASS. The reminder sweep is unchanged; it now has a deadline to fire on.
- [ ] **Step 5: Commit** `feat(applications): an award card takes its deadline from our stored cycle reading`.

### Task 10: A counsellor quick edit keeps the new fields

**Files:**
- Modify: `apps/documents/revisions.py` (`counselor_quick_edit` :59-80)
- Test: `tests/documents/test_revisions.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_quick_edit_carries_application_scholarship_list_and_destination(db, ...):
    original = _draft(application=card, funding_opportunity=award, requirements=_list(),
                      destination_label="DAAD EPOS", render_variant="EUROPASS_API")
    edited = counselor_quick_edit(document=original, content=_content(), counselor=counselor)
    for field in ("application_id", "funding_opportunity_id", "requirements", "requirements_digest",
                  "destination_label", "is_general", "render_variant", "programme_id"):
        assert getattr(edited, field) == getattr(original, field), field
```

- [ ] **Step 2: Run.** Expected: FAIL on `application_id`.
- [ ] **Step 3: Implement.** Pass the fields through `create_draft`. `requirements` is passed as `RequirementList.model_validate(document.requirements)` when the original's list is not `None`.
- [ ] **Step 4: Run** `tests/documents/test_revisions.py`. Expected: PASS.
- [ ] **Step 5: Commit** `fix(cv): a counsellor quick edit keeps the draft's application, scholarship and list`.

### Task 11 (conditional): Backfill open applications

**Only if the owner confirms that real students already hold applications** (spec §6.2). If not, skip this task and say so in the PR.

**Files:**
- Create: `apps/documents/management/commands/queue_application_cvs.py`
- Test: `tests/documents/test_queue_application_cvs.py`

- [ ] **Step 1: Write the failing test.** `call_command("queue_application_cvs", "--tenant", str(agency.id))` queues one `generate` per application in state PREPARING or READY_TO_SUBMIT with `cv_status == ""`. A second run queues none. `--dry-run` prints the count and queues nothing.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** One `tenant_transaction` per tenant, calling `queue_application_cv` for each application. Limits apply through Task 8's defer, so a large backfill spreads itself over hours instead of failing.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cv): a one-off command queues CVs for applications made before step 4.2`.

### Task 12: Notes, ledger and the gates

**Files:**
- Modify: `apps/documents/requirement_list.py` docstring ("Saved on the draft by build step 4.2" now names the fields), `.claude/rules/cv-and-letters.md` only if a statement there is now false (read it first; edit with the owner's approval, per `rules/artifacts.md`)
- Create: `~/agent-workspace/elmify-runs/cv-stage-4-2/progress.md` (the build ledger, as step 4.1 kept)

- [ ] **Step 1:** Grep `apps/` and `.claude/rules/` for "programme__isnull", "general CV", "resolve_rules(draft" and "checked synchronously by the generate endpoint". Fix every comment that now describes old behaviour.
- [ ] **Step 2: Gates.** Run `uv run ruff check .`, `uv run mypy apps config`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, `uv run pytest -q`, `uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py`. Expected: clean; the full suite passes, apart from master's 2 known OCR failures.
- [ ] **Step 3: Commit** `docs(cv): notes match the per-application trigger`.

## What later steps consume

- **4.2b (page read):** when a read changes `Program.cv_constraints`, call `queue_application_cv(application)` for each open application of that programme. The generate job's digest check (Task 4) makes an unchanged list free.
- **4.3 (questions):**
  - `DocumentDraft.requirement_states[item.id]` holds `{"state": "waiting_for_you", "reason": ...}`;
  - questions key on `(fact, key)` across applications; `Application.cv_status` gains a `WAITING_ANSWERS` choice;
  - `RequirementList.by_id()`.
- **4.4 (writing):** `build_for` is the single place the list is made; the writer gets `RequirementList.for_document("cv")`. It moves model calls out of the transaction (named above).
- **4.6 (page):** `destination_label`, `Application.cv_status`/`cv_resumes_at` ("queued, starts at 14:20"), `kit_cv_drafts`.
- **4.10 (staying current):** `requirements_digest` is the comparison; a remake calls `queue_application_cv`.

## Self-review

- **Spec coverage, row 4.2 of §2:**
  - each CV linked to its application: Tasks 3, 4;
  - kit serves only its CV: Task 6;
  - render from the saved list: Task 5;
  - lasting ids, states apart, digest: Task 1;
  - track from facts: Task 4;
  - same-application scholarships: Tasks 2, 4;
  - failures as states: Task 7;
  - CV queued by the capture job: Task 7;
  - no CV for "use our form": Task 7;
  - scholarship on the draft: Task 4;
  - quick edit: Task 10;
  - award deadlines: Task 9;
  - rate limits: Task 8;
  - backfill: Task 11.
- **Moved out on purpose:** the page read (4.2b, spec §2); model calls out of the transaction (4.4, reason above); hand-edit marker (4.10).
- **§10 fields in this step:** `application` (SET_NULL), nullable `requirements`, `requirement_states` keyed by id, general marker, destination label. The hand-edit marker, read status, own-CV choice and signature belong to later steps. `render_variant` already pins the format, so no new format field is added.
- **Decided here, for review:**
  - **Same-application scholarships** come from the catalogue (`FundingOpportunity.program`/`programs` with routes `CONSIDERED_WITH_ADMISSION`/`JOINT_SELECTION`), not from the student's recommendation run. The rules apply to the one upload whether or not the student was matched to the award.
  - **The api limiter** reuses `pack_command_rate_limited` instead of a new bucket.
  - **The award deadline** is taken at 00:00 UTC.
  - **A programme card's `opportunity`** is the linked separate card's award only when there is exactly one; with several, each award card makes its own CV and the programme's list has no scholarship.
  - **Legacy drafts** are told apart by `requirements IS NULL`, not by a date.
- **Type consistency:**
  - `RequirementList.digest()` is 64 hex characters and `requirements_digest` is `max_length=64`.
  - `Requirement.id` is 16 hex characters, and `requirement_states` keys are those ids.
  - `queue_application_cv(application, *, delay_seconds=0)` is used in Tasks 7, 8 and 11.
  - `CVStatus` values are the same in Tasks 3, 7 and 8.
- **Proportion:** the tests carry the assertions; code bodies appear only for the id and digest formulas, which the tests do not determine.
