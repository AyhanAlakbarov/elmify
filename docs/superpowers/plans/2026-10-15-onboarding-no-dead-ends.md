# Onboarding without dead ends — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every student can finish onboarding: no raw JSON boxes, no waiting on the transcript reading, a draft that survives a change of device, and a transcript that can actually be uploaded from the documents page.

**Architecture:** The five JSON answers become Django `MultiValueField`s whose `compress()` produces exactly the JSON the profile schema already validates, so `_canonical_value`, `StudentProfileSnapshot` and every stored profile stay unchanged. A reading that finishes after the student typed their degree is offered on the review page. The draft moves from the login session to one tenant-scoped row per student.

**Tech Stack:** Django forms (`MultiValueField`, `MultiWidget`), Pydantic profile schemas, Postgres RLS, pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-onboarding-and-transcript-friction-design.md` §1–§2 (variants 1, 2, 8).

## Global Constraints

- Lint only: `uv run ruff check .`; never `ruff format`.
- Types: `uv run mypy apps config`.
- Tests: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts tests/tenancy tests/audit`.
- Django: `uv run python manage.py check`; `uv run python manage.py makemigrations --check --dry-run` after the one new migration.
- The stored profile shape does not change: every new field compresses to the JSON the schema already accepts. A profile written before this plan validates after it.
- A new tenant table follows `.claude/rules/row-level-security.md`: `ENABLE` + `FORCE ROW LEVEL SECURITY`, the `tenant_isolation` policy, and a composite `(tenant_id, student_id)` guard to `tenancy_membership`, as `documents/0026_transcript_pages_tenant_guards.py` does. Its personal-data column is listed in `apps/audit/redaction.py` `REDACT`, every other column in `KEEP`.
- Screens are Aykhan's: plain HTML, a `SHOULD BE DONE BY AYKHAN` comment where layout matters.
- Commit with an explicit pathspec; never `git add -A`.

## Review Focus

1. **A profile saved before this plan** (JSON answers) must still read back into the draft and the review page: the canonical form is unchanged. Test in Task 1.
2. **A blank optional money answer** (`budget_stretch`) stays `None`, and `0` still means none (`lanes spec §7.7`). Test in Task 1.
3. **A reading offered late replaces only the degree answer**, never the rest of the draft, and the student can decline it. Test in Task 3.
4. **Two tenants, one student id shape:** the draft row is invisible across tenants (RLS) and erased with the student. Test in Task 4.
5. **A tampered or stale stored draft** (an answer key no longer asked, a non-canonical value) is dropped, never crashes the page, as the session version does today. Test in Task 4.

---

### Task 1: Money answers as amount + currency

**Files:**
- Modify: `apps/accounts/forms.py` (`_JSON_VALUES`, `question_field`, new `MoneyField`, `MoneyWidget`)
- Modify: `templates/student/_consultation_step.html` only if the widget needs a wrapper (it should not)
- Test: `tests/accounts/test_budget_stretch.py` (its `isinstance(field, forms.JSONField)` assertion changes), new `tests/accounts/test_structured_answers.py`

**Interfaces:**
- Produces: `MoneyField(required: bool)` — a `forms.MultiValueField` of (`DecimalField(min_value=0, max_digits=14, decimal_places=2)`, `ChoiceField(choices=sorted ISO_4217_CODES)`); `compress([amount, currency]) -> {"amount": "<decimal str>", "currency": "XXX"} | None` (None when the amount is blank). `question_field("application_budget" | "self_funding_capacity" | "budget_stretch")` returns it.

- [ ] **Step 1: Write the failing tests**

`tests/accounts/test_structured_answers.py`:

```python
from apps.accounts.forms import ConsultationQuestionForm, MoneyField, question_field


def _post(key, **values):
    form = ConsultationQuestionForm(key=key, field=question_field(key), data=values)
    assert form.is_valid(), form.errors
    return form.cleaned_data["value"]


def test_budget_questions_are_money_fields_not_json_boxes():
    for key in ("application_budget", "self_funding_capacity", "budget_stretch"):
        assert isinstance(question_field(key), MoneyField)


def test_a_money_answer_compresses_to_the_stored_shape():
    assert _post("application_budget", value_0="300", value_1="EUR") == {
        "amount": "300.00", "currency": "EUR",
    }


def test_a_blank_stretch_is_none_and_zero_is_none():
    assert _post("budget_stretch", value_0="", value_1="EUR") is None
    assert _post("budget_stretch", value_0="0", value_1="EUR") is None


def test_a_required_budget_refuses_a_blank_amount():
    form = ConsultationQuestionForm(
        key="application_budget", field=question_field("application_budget"),
        data={"value_0": "", "value_1": "EUR"},
    )
    assert not form.is_valid()


def test_an_unknown_currency_is_refused():
    form = ConsultationQuestionForm(
        key="application_budget", field=question_field("application_budget"),
        data={"value_0": "10", "value_1": "ZZZ"},
    )
    assert not form.is_valid()


def test_a_stored_money_answer_shows_back_in_both_inputs():
    field = question_field("application_budget")
    assert field.widget.decompress({"amount": "300.00", "currency": "EUR"}) == ["300.00", "EUR"]
```

In `tests/accounts/test_budget_stretch.py`, change the `isinstance(field, forms.JSONField)` assertion to `isinstance(field, MoneyField)` (import it from `apps.accounts.forms`).

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts/test_structured_answers.py tests/accounts/test_budget_stretch.py`
Expected: FAIL — `ImportError: cannot import name 'MoneyField'`.

- [ ] **Step 3: Implement**

In `apps/accounts/forms.py`:

```python
from apps.reference_data import ISO_4217_CODES

_MONEY_VALUES = {"application_budget", "self_funding_capacity", "budget_stretch"}


class MoneyWidget(forms.MultiWidget):
    def __init__(self) -> None:
        super().__init__(
            (
                forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
                forms.Select(choices=[(code, code) for code in sorted(ISO_4217_CODES)]),
            )
        )

    def decompress(self, value: object) -> list[object]:
        if isinstance(value, dict):
            return [value.get("amount"), value.get("currency")]
        return [None, None]


class MoneyField(forms.MultiValueField):
    """An amount and its currency, compressed to the profile's `Money` shape.
    SHOULD BE DONE BY AYKHAN: the currency select's default and layout."""

    widget = MoneyWidget

    def __init__(self, *, required: bool) -> None:
        super().__init__(
            fields=(
                forms.DecimalField(min_value=0, max_digits=14, decimal_places=2, required=False),
                forms.ChoiceField(
                    choices=[(code, code) for code in sorted(ISO_4217_CODES)], required=False
                ),
            ),
            require_all_fields=False,
            required=required,
        )

    def compress(self, data_list: list[object]) -> dict[str, str] | None:
        if not data_list or data_list[0] in (None, ""):
            return None
        return {"amount": str(data_list[0]), "currency": str(data_list[1])}
```

Remove the three money keys from `_JSON_VALUES`, and in `question_field` add before the `_JSON_VALUES` branch:

```python
    if key in _MONEY_VALUES:
        return MoneyField(required=key not in _OPTIONAL_VALUES)
```

`_canonical_value`'s `key in _JSON_VALUES and value in (None, "")` branch handled blank money; add the money keys to it: change the condition to `key in (_JSON_VALUES | _MONEY_VALUES) and value in (None, "")`. A required `MoneyField` with a blank amount compresses to `None`; `MultiValueField(required=True)` refuses an all-empty input before that, so `self_funding_capacity` and `application_budget` stay required exactly as today.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts`
Expected: PASS. A test elsewhere posting `value='{"amount": ...}'` for a money question now posts `value_0` / `value_1`; update it, never the assertion about the stored value.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(onboarding): budget answers are an amount and a currency, not a JSON box" -- apps/accounts/forms.py tests/accounts/test_structured_answers.py tests/accounts/test_budget_stretch.py
```

---

### Task 2: The degree and language evidence as short forms

**Files:**
- Modify: `apps/accounts/forms.py` (new `AcademicRecordField`, `LanguageEvidenceField`; `_JSON_VALUES` becomes empty and is deleted)
- Test: `tests/accounts/test_structured_answers.py`, `tests/accounts/test_prefill.py` (`test_without_a_reading_the_academic_record_is_asked` posts the new fields)

**Interfaces:**
- Produces:
  - `AcademicRecordField()` — `MultiValueField` of `institution`, `country_code` (2 letters), `qualification`, `field`, `grade`, `grading_scale` (all required) and `completed_on`, `expected_completion` (optional dates); `compress -> [{"institution", "country_code", "qualification", "field", "grade", "grading_scale", "completed_on", "expected_completion", "courses": []}]`. Courses are never typed.
  - `LanguageEvidenceField()` — three optional rows of (`language`, `level`, `evidence_type` ∈ ATTESTED/TEST/DEGREE/OTHER, `available_by` date); `compress -> [ {row}, ... ]`, blank rows skipped, `[]` when all blank.

- [ ] **Step 1: Write the failing tests**

Append to `tests/accounts/test_structured_answers.py`:

```python
from apps.accounts.forms import AcademicRecordField, LanguageEvidenceField


def test_the_degree_is_a_short_form_and_compresses_to_one_record():
    assert isinstance(question_field("academic_history"), AcademicRecordField)
    value = _post(
        "academic_history",
        value_0="Baku State University", value_1="AZ", value_2="BSc", value_3="Chemistry",
        value_4="85", value_5="0-100", value_6="2025-06-30", value_7="",
    )
    assert value == [{
        "institution": "Baku State University", "country_code": "AZ", "qualification": "BSc",
        "field": "Chemistry", "grade": "85", "grading_scale": "0-100",
        "completed_on": "2025-06-30", "expected_completion": None, "courses": [],
    }]


def test_a_degree_missing_its_university_is_refused():
    form = ConsultationQuestionForm(
        key="academic_history", field=question_field("academic_history"),
        data={"value_0": "", "value_1": "AZ", "value_2": "BSc", "value_3": "Chemistry",
              "value_4": "85", "value_5": "0-100"},
    )
    assert not form.is_valid()


def test_language_evidence_skips_blank_rows():
    assert isinstance(question_field("language_evidence"), LanguageEvidenceField)
    value = _post(
        "language_evidence",
        value_0="English", value_1="C1", value_2="TEST", value_3="2026-01-15",
        **{f"value_{i}": "" for i in range(4, 12)},
    )
    assert value == [{"language": "English", "level": "C1", "evidence_type": "TEST",
                      "available_by": "2026-01-15"}]
    assert _post("language_evidence", **{f"value_{i}": "" for i in range(12)}) == []
```

(The exact dict key order and date rendering follow `_canonical_value`'s round trip through the schema; if the canonical form drops `None` dates or the empty course list, match the canonical form — the assertion is about what the profile stores, so compare against `_canonical_value(key, <dict above>)` if they differ.)

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts/test_structured_answers.py -k "degree or language"`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
_EVIDENCE_TYPES = ("ATTESTED", "TEST", "DEGREE", "OTHER")
_LANGUAGE_ROWS = 3  # ponytail: three rows; more than three tested languages is rare, add a row then


class AcademicRecordField(forms.MultiValueField):
    """The latest degree, typed when no transcript reading is ready. Courses come
    only from a reading. SHOULD BE DONE BY AYKHAN: labels and layout per input."""

    def __init__(self) -> None:
        text = dict(required=True)
        fields = (
            forms.CharField(max_length=200, **text),   # institution
            forms.CharField(min_length=2, max_length=2, **text),  # country_code
            forms.CharField(max_length=100, **text),   # qualification
            forms.CharField(max_length=200, **text),   # field
            forms.CharField(max_length=50, **text),    # grade
            forms.CharField(max_length=100, **text),   # grading_scale
            forms.DateField(required=False),           # completed_on
            forms.DateField(required=False),           # expected_completion
        )
        widgets = [forms.TextInput() for _ in range(6)] + [
            forms.DateInput(attrs={"type": "date"}), forms.DateInput(attrs={"type": "date"})
        ]
        super().__init__(
            fields=fields, widget=forms.MultiWidget(widgets), require_all_fields=False
        )

    def compress(self, data_list: list[object]) -> list[dict[str, object]] | None:
        if not data_list:
            return None
        names = ("institution", "country_code", "qualification", "field", "grade",
                 "grading_scale", "completed_on", "expected_completion")
        record = dict(zip(names, data_list, strict=True))
        record["country_code"] = str(record["country_code"]).upper()
        for key in ("completed_on", "expected_completion"):
            record[key] = record[key].isoformat() if record[key] else None
        return [{**record, "courses": []}]


class LanguageEvidenceField(forms.MultiValueField):
    def __init__(self) -> None:
        row = (
            forms.CharField(max_length=100, required=False),
            forms.CharField(max_length=50, required=False),
            forms.ChoiceField(choices=[("", "")] + [(t, t) for t in _EVIDENCE_TYPES],
                              required=False),
            forms.DateField(required=False),
        )
        fields = tuple(f for _ in range(_LANGUAGE_ROWS) for f in row)
        widgets = [
            w for _ in range(_LANGUAGE_ROWS) for w in (
                forms.TextInput(), forms.TextInput(),
                forms.Select(choices=[("", "")] + [(t, t) for t in _EVIDENCE_TYPES]),
                forms.DateInput(attrs={"type": "date"}),
            )
        ]
        super().__init__(fields=fields, widget=forms.MultiWidget(widgets),
                         require_all_fields=False, required=False)

    def compress(self, data_list: list[object]) -> list[dict[str, object]]:
        rows = []
        for start in range(0, len(data_list or []), 4):
            language, level, kind, available = data_list[start:start + 4]
            if not language:
                continue
            rows.append({"language": language, "level": level, "evidence_type": kind,
                         "available_by": available.isoformat() if available else None})
        return rows
```

In `question_field`, return `AcademicRecordField()` for `academic_history` and `LanguageEvidenceField()` for `language_evidence`; delete `_JSON_VALUES` and its branch, and in `_canonical_value` keep the blank handling for `language_evidence` (`[]`) via the money/blank condition. A half-filled language row (language without level or date) is refused by the schema in `_canonical_value`, which already turns a `ValidationError` into a form error.

Each `MultiWidget` needs `decompress` for redisplay of a stored answer: add it the same way as `MoneyWidget` (a list record → its values in field order; for language evidence, up to three rows flattened).

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts`
Expected: PASS; `test_without_a_reading_the_academic_record_is_asked` posts `value_0`…`value_7`.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(onboarding): the degree and language evidence are short forms; no JSON box is left" -- apps/accounts/forms.py tests/accounts/test_structured_answers.py tests/accounts/test_prefill.py
```

---

### Task 3: A reading that finishes later is offered on the review page

**Files:**
- Modify: `apps/accounts/consultation.py` (extract `_reading_answer`, new `late_reading`, `use_reading`)
- Modify: `apps/accounts/views.py` (`_render_review` context; `profile` POST action `use_reading`)
- Modify: `templates/student/_consultation_step.html` (the offer)
- Test: `tests/accounts/test_prefill.py`

**Interfaces:**
- Produces:
  - `late_reading(draft: ConsultationDraft, *, membership: Membership) -> TranscriptReading | None` — the newest reading when the draft's degree was typed (`draft.reading_id is None`), the reading is not accepted, and it validates as an academic record; else `None`.
  - `use_reading(draft, reading) -> ConsultationDraft` — replaces `academic_history` with the reading's record, sets `reading_id` and `highlights`; nothing else in the draft changes.

- [ ] **Step 1: Write the failing tests**

In `tests/accounts/test_prefill.py` (reuse its existing reading/draft fixtures and helpers):

```python
def test_a_reading_that_finishes_after_typing_is_offered(agency_a, django_user_model):
    # draft with a typed degree (reading_id None), then a reading arrives
    ...
    assert late_reading(draft, membership=student) == reading


def test_using_a_late_reading_replaces_only_the_degree(agency_a, django_user_model):
    ...
    used = use_reading(draft, reading)
    assert used.answers["academic_history"] == [reading.record_as_answer]
    assert {k: v for k, v in used.answers.items() if k != "academic_history"} == {
        k: v for k, v in draft.answers.items() if k != "academic_history"
    }
    assert used.reading_id == reading.id


def test_a_prefilled_draft_is_not_offered_its_own_reading_again(agency_a, django_user_model):
    ...
    assert late_reading(prefilled_draft, membership=student) is None


def test_the_review_page_offers_the_reading_and_the_student_may_decline(client, ...):
    # GET review shows "Your transcript has been read"; POST action=use_reading swaps it;
    # POST action=confirm without using it keeps the typed degree and leaves the reading unaccepted
```

Write the `...` setup with the file's existing helpers (`_reading(...)`, the draft builder); `reading.record_as_answer` is `_canonical_answer("academic_history", [reading.record])[0]`.

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts/test_prefill.py -k "late or offered or decline"`
Expected: FAIL — `ImportError: cannot import name 'late_reading'`.

- [ ] **Step 3: Implement**

In `consultation.py`, factor the body of `prefill_from_latest_reading` that builds `(history, highlights)` from a reading into `_reading_answer(reading) -> tuple[list[object], tuple[Highlight, ...]] | None` (None on `ValidationError`), and use it in both:

```python
def late_reading(
    draft: ConsultationDraft, *, membership: Membership
) -> TranscriptReading | None:
    """A reading that finished after the student typed their degree. Offered on
    the review page; never applied without the student choosing it."""
    if draft.reading_id is not None or "academic_history" not in draft.answers:
        return None
    reading = TranscriptReading.objects.filter(student=membership).order_by("-created_at").first()
    if reading is None or reading.accepted is not None or _reading_answer(reading) is None:
        return None
    return reading


def use_reading(draft: ConsultationDraft, reading: TranscriptReading) -> ConsultationDraft:
    answer = _reading_answer(reading)
    assert answer is not None  # late_reading checked it
    history, highlights = answer
    return replace(
        draft,
        answers={**draft.answers, "academic_history": history},
        reading_id=reading.id,
        highlights=highlights,
        correction_key=None,
    )
```

In `views.py`: `_render_review` adds `"late_reading": late_reading(draft, membership=...)` to the context (pass the membership in); in `profile`'s POST, before `confirm`, handle `action == "use_reading"`: re-check `late_reading`, apply `use_reading`, write the draft, re-render the review. In the template's review branch, above the answers:

```html
{% if late_reading %}
  <form method="post" action="{% url 'student-profile' %}">
    {% csrf_token %}<input type="hidden" name="action" value="use_reading">
    <p>Your transcript has been read. Use it instead of the degree you typed?</p>
    <button type="submit">Use my transcript</button>
  </form>
{% endif %}
```

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(onboarding): a transcript read after the student typed their degree is offered, never imposed" -- apps/accounts/consultation.py apps/accounts/views.py templates/student/_consultation_step.html tests/accounts/test_prefill.py
```

---

### Task 4: The draft is stored per student, not in the session

**Files:**
- Modify: `apps/accounts/models.py` (new `ConsultationDraftRecord`)
- Create: `apps/accounts/migrations/0007_consultation_draft_record.py` (model, then RLS + tenant guard `RunSQL`)
- Modify: `apps/accounts/consultation.py` (`read_draft`, `write_draft`, `clear_draft` take `tenant_id`/`membership_id` only; `session_key` deleted)
- Modify: `apps/accounts/views.py` (four call sites), `tests/accounts/test_consultation.py` (one)
- Modify: `apps/audit/redaction.py` (`REDACT` and `KEEP` entries)
- Test: new `tests/accounts/test_draft_record.py`

**Interfaces:**
- Produces: `ConsultationDraftRecord(TenantScopedModel)`: `id` UUID pk, `student` OneToOne `Membership` (`on_delete=PROTECT`, like `StudentProfileVersion`), `envelope` JSONField, `updated_at` auto_now. `read_draft(*, tenant_id, membership_id) -> ConsultationDraft`; `write_draft(draft) -> None`; `clear_draft(draft) -> None` — same validation as today; an invalid stored envelope is deleted and an empty draft returned.

- [ ] **Step 1: Write the failing tests**

`tests/accounts/test_draft_record.py`:

```python
import pytest

from apps.accounts.consultation import ConsultationDraft, clear_draft, read_draft, write_draft
from apps.accounts.models import ConsultationDraftRecord
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_a_draft_survives_a_new_session(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        draft = ConsultationDraft(agency_a.id, membership_a.id, {"target_field": "Chemistry"})
        write_draft(draft)
        assert read_draft(tenant_id=agency_a.id, membership_id=membership_a.id).answers == {
            "target_field": "Chemistry"
        }


def test_clear_draft_removes_the_row(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        draft = ConsultationDraft(agency_a.id, membership_a.id, {"target_field": "Chemistry"})
        write_draft(draft)
        clear_draft(draft)
        assert not ConsultationDraftRecord.objects.filter(student=membership_a).exists()


def test_a_stale_stored_draft_is_dropped_not_fatal(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        ConsultationDraftRecord.objects.create(
            student=membership_a,
            envelope={"tenant_id": str(agency_a.id), "membership_id": str(membership_a.id),
                      "answers": {"no_longer_asked": 1}},
        )
        assert read_draft(tenant_id=agency_a.id, membership_id=membership_a.id).answers == {}
        assert not ConsultationDraftRecord.objects.filter(student=membership_a).exists()


def test_another_tenant_cannot_see_the_draft(rls_enforced_orm, agency_a, agency_b, membership_a):
    with tenant_scope(agency_a.id):
        write_draft(ConsultationDraft(agency_a.id, membership_a.id, {"target_field": "x"}))
    with tenant_scope(agency_b.id):
        assert not ConsultationDraftRecord.objects.exists()


def test_erasure_blanks_the_draft():
    from apps.audit.redaction import REDACT
    assert REDACT["accounts.ConsultationDraftRecord"].fields == ("envelope",)
```

Use the fixture names `tests/conftest.py` actually provides for two agencies and a membership (`agency_a`, `agency_b`, `membership_a` exist per the repo's tests; adjust if a name differs). `rls_enforced_orm` is the fixture `.claude/rules/row-level-security.md` names for RLS assertions.

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts/test_draft_record.py`
Expected: FAIL — `ImportError: cannot import name 'ConsultationDraftRecord'`.

- [ ] **Step 3: Implement**

`apps/accounts/models.py`:

```python
class ConsultationDraftRecord(TenantScopedModel):
    """The onboarding questionnaire in progress, one per student. Stored here,
    not in the login session, so a student who signs in on another device keeps
    their answers (onboarding friction spec, variant 8)."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.OneToOneField(Membership, on_delete=models.PROTECT)
    envelope = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "id"), name="consultationdraftrecord_tenant_id_uniq"
            )
        ]
```

Run `uv run python manage.py makemigrations accounts --name consultation_draft_record`, then append to that migration a `RunSQL` with the RLS block and guard, copied from `documents/0026_transcript_pages_tenant_guards.py`:

```sql
ALTER TABLE accounts_consultationdraftrecord ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts_consultationdraftrecord FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON accounts_consultationdraftrecord
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE accounts_consultationdraftrecord
    ADD CONSTRAINT consultationdraftrecord_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id) REFERENCES tenancy_membership (tenant_id, id);
```

with its reverse (drop constraint, drop policy, disable RLS), and `("tenancy", "0002_rls")` in its dependencies.

`consultation.py`: `read_draft(*, tenant_id, membership_id)` reads `ConsultationDraftRecord.objects.filter(student_id=membership_id).first()`, validates `record.envelope` with the existing checks, and on failure deletes the row (instead of `session.pop`). `write_draft(draft)` builds the same envelope and does `update_or_create(student_id=draft.membership_id, defaults={"envelope": envelope})`. `clear_draft(draft)` deletes the row. Delete `session_key`.

`views.py`: drop `request.session` from the four calls.

`apps/audit/redaction.py`: add `"accounts.ConsultationDraftRecord": RedactSpec("student_id", ("envelope",))` to `REDACT` and `"accounts.ConsultationDraftRecord": ("updated_at",)` to `KEEP`.

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts tests/tenancy tests/audit`
Expected: PASS, including the repo's own every-tenant-table-has-RLS and erasure-completeness tests.

- [ ] **Step 5: Commit**

```bash
git add apps/accounts/migrations/0007_consultation_draft_record.py tests/accounts/test_draft_record.py
git commit -m "feat(onboarding): the questionnaire draft is kept per student, so a new device does not start over" -- apps/accounts/models.py apps/accounts/migrations/0007_consultation_draft_record.py apps/accounts/consultation.py apps/accounts/views.py apps/audit/redaction.py tests/accounts/test_draft_record.py tests/accounts/test_consultation.py
```

---

### Task 5: A transcript can be uploaded from the documents page

Found while writing this plan: `static/dashboard/documents.js` sends `kind`, `mode` and `replaces`
only, and `transcript_pages._transcript_upload` refuses any transcript without `role`
(`ORIGINAL` / `TRANSLATION`) with 400 `invalid_role`. The plain-HTML documents page therefore cannot
upload a transcript at all.

**Files:**
- Modify: `templates/student/_documents.html` (a role fieldset, and a language select for an original)
- Modify: `static/dashboard/documents.js` (send `role`, and `language` when chosen, for `TRANSCRIPT`)
- Test: `tests/documents/test_api.py` (the request the page now builds is accepted), a template test in the
  file that already renders the documents page (`grep -rn "_documents.html\|student-documents" tests`)

**Interfaces:**
- Consumes: `TranscriptUpload.Role` (`ORIGINAL`, `TRANSLATION`), `transcript_pages._LANGUAGES`
  (`az`, `tr`, `ru`); a language is allowed only with `ORIGINAL`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_documents_page_offers_original_or_translation_for_a_transcript(client, ...):
    html = client.get(reverse("student-documents")).content.decode()
    assert 'name="role" value="ORIGINAL"' in html
    assert 'name="role" value="TRANSLATION"' in html


def test_the_request_the_page_builds_for_a_transcript_is_accepted(client, paid_cycle, ...):
    response = client.post(
        "/api/documents/uploads",
        data={"kind": "TRANSCRIPT", "mode": "ADD", "role": "ORIGINAL", "language": "az"},
        content_type="application/json",
    )
    assert response.status_code == 201
```

(Reuse the paid-cycle and student-client fixtures `tests/documents/test_api.py` already uses for its
transcript cases.)

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_api.py -k "documents_page or page_builds"`
Expected: the template test FAILS (no role inputs); the API test passes already and pins the contract.

- [ ] **Step 3: Implement**

In `_documents.html`, inside the upload form after the kind select:

```html
{# documents.js shows this only when the chosen kind is TRANSCRIPT. SHOULD BE DONE BY AYKHAN: layout. #}
<fieldset data-transcript-role hidden>
  <legend>Is this the original transcript or a translation?</legend>
  <p><label><input type="radio" name="role" value="ORIGINAL" checked> Original</label>
     <select name="language"><option value="">Language…</option>
       <option value="az">Azerbaijani</option><option value="tr">Turkish</option>
       <option value="ru">Russian</option></select></p>
  <p><label><input type="radio" name="role" value="TRANSLATION"> Certified translation</label></p>
</fieldset>
```

In `documents.js`, where `showModes()` toggles the mode fieldset on kind change, also toggle
`[data-transcript-role]` for `kind === "TRANSCRIPT"`; in the submit handler, for a transcript add
`body.role` from the checked role radio and, when the role is `ORIGINAL` and a language is chosen,
`body.language`. Add `invalid_role: "Say whether this is the original or a translation."` to `REFUSALS`.

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_api.py tests/dashboard`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(documents): the documents page can upload a transcript (it never sent original or translation)" -- templates/student/_documents.html static/dashboard/documents.js tests/documents/test_api.py
```

---

### Task 6: Every gate

- [ ] **Step 1: Run**

```bash
uv run ruff check .
uv run mypy apps config
POSTGRES_DB=elmify_letter_plan_2 uv run python manage.py check
POSTGRES_DB=elmify_letter_plan_2 uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q
```

Expected: all clean; record the pytest summary line.
