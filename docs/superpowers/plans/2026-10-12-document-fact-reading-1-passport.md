# Document fact reading, plan 1 of 3: vocabulary, passport reading, facts and dashboard

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A student's uploaded passport or ID card is read in the background into facts. Values the
strip's check digits prove become facts with no press. Doubtful ones wait on the dashboard, where
any value can be corrected. Portals are filled from them through `verified_values`.

**Architecture:**
- New fact keys: IDENTITY gains person keys, and a new ID_DOCUMENT category holds the document's
  own keys.
- A pure strip parser (`mrz.py`) and a pure proof step (`id_reading.py`) turn Azure's
  `prebuilt-idDocument` answer into `ReadValue`s.
- A worker pipeline (`document_reading.py`) records each read on a tenant `DocumentReading` row.
- A fact writer (`fact_writer.py`) applies the precedence rules to the `VerifiedFact` ledger.
- The dashboard shows "Your details" and "Details to check".
- Plan 2 adds diplomas and certificates on the same pipeline. Plan 3 adds the co-pilot's one-tap
  offer.

**Tech Stack:** Django 6, Postgres (FORCE RLS), Pydantic, Azure Document Intelligence REST
(`2024-11-30`), Babel (already installed), pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-document-fact-reading-design.md`. §§1–8 and §10 apply
to this plan, except §5.3 (plan 2) and §7.2–7.5 (plan 3).

## Global Constraints

- Run everything from the worktree `/home/orkhan/Desktop/fact-reading`, with `git -C` for git.
  Tests: `POSTGRES_DB=elmify_fact_reading uv run pytest -q`.
- Lint is `uv run ruff check .` — never `ruff format`. Types: `uv run mypy apps config`.
  Migrations: `uv run python manage.py makemigrations --check --dry-run` must report no changes
  after each task. Never hand-edit an applied migration.
- No language model ever sees a passport or an ID card (spec D6). Nothing in this plan calls
  OpenAI, Anthropic or any reader pair.
- `FACT_READING_ENABLED` ships off (env, default off). Azure also stays behind the existing
  `TRANSCRIPT_AZURE_ENABLED` gate, which keeps its name.
- Shared Azure page ceiling: `TRANSCRIPT_TENANT_DAILY_AZURE_PAGES`, reused, now counting both readers.
- Page cap: `FACT_READING_PAGE_CAPS = {"PASSPORT": 4, "DIPLOMA": 4, "LANGUAGE_CERTIFICATE": 2}`.
  Confidence threshold: `FACT_READING_CONFIDENCE = 0.95`. Per-student limit:
  `FACT_READING_HOURLY = 20`, rate-limit bucket `fact-reading`.
- A proven fact: `source_tier=AUTHORITATIVE_DOCUMENT`, `source_ref="document:<DocumentVersion id>"`,
  `confirmed_by` = the student, `confirmed_at` = now. Audit event `fact.read_from_document` with
  `actor_kind="AGENT"` and `actor=None`.
- A doubtful fact is the same row with `confirmed_by`/`confirmed_at` NULL.
- `PROTECTED_KEYS = {"identity.given_names", "identity.surname", "identity.citizenship",
  "identity.date_of_birth"}`. A difference on one of these never silently supersedes; it becomes a
  detail to check.
- `why` codes, closed: `check_digit`, `strip_agrees`, `confident`, `low_confidence`, `no_strip`,
  `strip_disagrees`, `no_citizenship`, `unknown_country`, `owner_mismatch`, `student_entry_differs`,
  `document_differs`.
- `failure` codes, closed: `unreadable`, `not_an_id_document`, `no_data_page`, `unsupported_file`,
  `document_unavailable`, `erasure_requested`, `reader_unavailable`.
- Dashboard strings are English (spec §3).
- Error and log messages carry codes and ids only, never a document value.

## Review Focus

1. **A strip with a valid composite digit but an OCR slip in a non-covered position** (sex,
   nationality). These positions have no check digit, so the value must be proven only by agreeing
   with the printed page. Owner: Task 4.
2. **A student whose CV states a date of birth that differs from the passport.** The passport value
   must arrive as a detail to check, never replace the CV's confirmed value, and never reach a
   portal unconfirmed. Owner: Task 6.
3. **Two valid passports, or only an expired one.** A portal must get the chosen or latest-expiring
   valid passport, and nothing from an expired one. Owner: Task 6 (`verified_values`).
4. **A redelivered scan event or a resume sweep racing the worker on the same document.** It must
   not read twice, bill twice, or write duplicate facts. Owner: Task 7.
5. **A student with passport identity rows but no confirmed CV name.** CV generation must still
   refuse for "no identity", and gap questions must still find the full-name row. Owner: Task 1.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/documents/models.py` (modify) | `VerifiedFact.Category.ID_DOCUMENT`, the `DocumentReading` model |
| `apps/documents/migrations/0028_id_document_category.py` (generated) | category CHECK update |
| `apps/documents/migrations/0029_document_reading.py` (generated) | `DocumentReading` table |
| `apps/documents/migrations/0030_document_reading_tenant_guards.py` (hand-written RunSQL) | RLS and composite FKs |
| `apps/documents/verification.py` (modify) | new payload keys; ID_DOCUMENT keys outside `_SPECS`; `generatable_facts` drops ID_DOCUMENT |
| `apps/documents/mrz.py` (create) | strip parsing, check digits, ICAO country to English name, transliteration forms |
| `apps/documents/azure_layout.py` (modify) | shared analyze loop; `analyze_id_document` with its response models |
| `apps/documents/id_reading.py` (create) | `ReadValue`; proof rules from an Azure ID result |
| `apps/documents/fact_writer.py` (create) | writing a reading's values into the ledger; `correct_fact` |
| `apps/documents/audit.py` (modify) | `record_event(..., actor_kind=)` |
| `apps/documents/document_reading.py` (create) | the worker pipeline: claim, read, delay, fail, write; shared ceiling |
| `apps/documents/document_queue.py`, `document_worker.py` (modify) | `read_document` action and dispatch |
| `apps/documents/transcript_pages.py` (modify) | ceiling counts document readings too |
| `apps/documents/management/commands/resume_transcript_readings.py` (modify) | also resumes readings |
| `apps/documents/fact_labels.py` (create) | display labels for fact keys and document kinds |
| `apps/documents/views.py`, `urls.py`, `templates/student/_documents.html` (modify) | the dashboard |
| `apps/portals/profile.py` (modify) | ID_DOCUMENT selection in `verified_values` |
| `apps/portals/fact_reading.py` (modify) | the hook queues unread passports |
| `apps/portals/bench_students.py` (modify) | sample values for every new learnable key |
| `apps/documents/generation.py`, `api.py`, `gaps.py` (modify) | identity checks look for the full-name row |
| `apps/audit/redaction.py`, `apps/audit/deletion.py` (modify) | erasure of `DocumentReading` |
| `apps/documents/templatetags/cv_countries.py` (modify) | `XK:Kosovo` |
| `config/settings/base.py` (modify) | the four settings above |

---

### Task 1: Vocabulary, and the identity consumers that assume one full-name row

**Files:**
- Modify: `apps/documents/models.py` (Category, the CHECK constraint, the IDENTITY comment)
- Create (generated): `apps/documents/migrations/0028_id_document_category.py`
- Modify: `apps/documents/verification.py`
- Modify: `apps/documents/generation.py:326`, `apps/documents/api.py:417`, `apps/documents/gaps.py:580`
- Modify: `apps/portals/bench_students.py`
- Test: `tests/documents/test_fact_vocabulary.py` (create)

**Interfaces:**
- Produces: `VerifiedFact.Category.ID_DOCUMENT == "ID_DOCUMENT"`;
  `verification.ID_DOCUMENT_KEYS: tuple[str, ...]`; `payload_keys("ID_DOCUMENT")` returns it;
  `payload_keys("IDENTITY")` includes `date_of_birth`, `sex`, `citizenship`, `given_names`,
  `surname`, `place_of_birth`; `verification.has_full_name(qs) -> QuerySet` (a filter helper).

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_fact_vocabulary.py
"""Spec 2026-10-12 §4: the keys a passport read writes, and the consumers that
must keep finding the full-name row among more IDENTITY rows."""

import pytest
from django.utils import timezone

from apps.documents.models import VerifiedFact
from apps.documents.verification import ID_DOCUMENT_KEYS, generatable_facts, payload_keys
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_identity_carries_the_passport_person_keys():
    keys = payload_keys(VerifiedFact.Category.IDENTITY)
    for key in ("date_of_birth", "sex", "citizenship", "given_names", "surname", "place_of_birth"):
        assert key in keys


def test_id_document_has_its_own_keys():
    assert ID_DOCUMENT_KEYS == (
        "document_type", "number", "issuing_country", "issue_date", "expiry_date",
        "issuing_authority",
    )
    assert payload_keys(VerifiedFact.Category.ID_DOCUMENT) == ID_DOCUMENT_KEYS


def test_every_new_key_is_learnable():
    from apps.portals.profile import LEARNABLE_FIELDS

    assert "identity.date_of_birth" in LEARNABLE_FIELDS
    assert "identity.citizenship" in LEARNABLE_FIELDS
    assert "id_document.number" in LEARNABLE_FIELDS
    assert "id_document.expiry_date" in LEARNABLE_FIELDS


def _fact(student, category, payload, confirmed=True):
    return VerifiedFact.objects.create(
        student=student, category=category, payload=payload,
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref="document:test", confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None, created_by=student,
    )


def test_generation_never_sees_an_id_document(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _fact(membership_a, VerifiedFact.Category.ID_DOCUMENT, {"number": "C01X00T47"})
        assert not generatable_facts(membership_a).filter(
            category=VerifiedFact.Category.ID_DOCUMENT
        ).exists()


def test_a_passport_identity_row_is_not_a_cv_identity(agency_a, membership_a):
    """CV generation refuses a student with no confirmed full name, even when a
    passport read wrote their date of birth."""
    from apps.documents.generation import IdentityNotConfirmed, generate_cv

    with tenant_scope(agency_a.id):
        _fact(membership_a, VerifiedFact.Category.IDENTITY, {"date_of_birth": "1999-04-12"})
        with pytest.raises(IdentityNotConfirmed):
            generate_cv(student=membership_a)


def test_missing_contact_reads_the_full_name_row(agency_a, membership_a):
    from apps.documents.gaps import missing_contact

    with tenant_scope(agency_a.id):
        name = _fact(membership_a, VerifiedFact.Category.IDENTITY, {"full_name": "Ana Lee"})
        _fact(membership_a, VerifiedFact.Category.IDENTITY, {"date_of_birth": "1999-04-12"})
        questions = missing_contact(membership_a)
    assert questions and all(q.fact_id == name.id for q in questions)
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_fact_vocabulary.py`
Expected: FAIL (ImportError on `ID_DOCUMENT_KEYS`).

- [ ] **Step 3: Add the category.** In `apps/documents/models.py`:
  - Add to `VerifiedFact.Category`, after TIMELINE:
    ```python
        #: One identity document the student holds -- a passport, an ID card or a
        #: residence permit (spec 2026-10-12 §4.2). A row per document, keyed by
        #: source_ref "document:<DocumentVersion id>", because a dual national
        #: holds two and a renewal leaves the old one behind. Never reaches
        #: generation (verification.generatable_facts drops it).
        ID_DOCUMENT = "ID_DOCUMENT"
    ```
  - Add `"ID_DOCUMENT"` to the `verifiedfact_category_valid` CHECK tuple.
  - Change the IDENTITY comment's "Payload is {"full_name": ...} and nothing else" to:
    "A CV's row carries full_name and its contact keys; a passport read writes one row per person
    key (date_of_birth, citizenship, ...), so a reader looking for the name filters on
    `full_name` (verification.has_full_name)."
  - Then run `uv run python manage.py makemigrations documents --name id_document_category`.

- [ ] **Step 4: Add the keys.** In `apps/documents/verification.py`:
  - In the `personal_information` tuple of the `_PAYLOAD_KEYS` comprehension (the one starting
    `"phone", "linkedin_url"`), append after `"linkedin_handle",`:
    ```python
            # Spec 2026-10-12 §4.1: a passport read writes these, one row per key.
            # date_of_birth, sex and citizenship are CVContent.personal_information
            # fields with no source until now; given_names, surname and
            # place_of_birth exist only here. Carried, never compared: a CV's
            # date of birth may be partial ("1999-04"), and comparing it with a
            # full date reads CONFLICTING over precision.
            "date_of_birth",
            "sex",
            "citizenship",
            "given_names",
            "surname",
            "place_of_birth",
    ```
  - Below the comprehension, add:
    ```python
    #: Spec 2026-10-12 §4.2. No CVContent field carries an identity document, so
    #: ID_DOCUMENT has no _CategorySpec (verify_against_facts iterates _SPECS over
    #: CVContent fields); its keys are registered here for payload_keys and the
    #: co-pilot's LEARNABLE_FIELDS.
    ID_DOCUMENT_KEYS: tuple[str, ...] = (
        "document_type",
        "number",
        "issuing_country",
        "issue_date",
        "expiry_date",
        "issuing_authority",
    )
    _PAYLOAD_KEYS[VerifiedFact.Category.ID_DOCUMENT] = ID_DOCUMENT_KEYS


    def has_full_name(facts: QuerySet[VerifiedFact]) -> QuerySet[VerifiedFact]:
        """IDENTITY rows that name the person. A passport read writes IDENTITY rows
        holding one key each (a date of birth, a citizenship), so "an IDENTITY fact
        exists" no longer means "we know their name"."""
        return facts.filter(category=VerifiedFact.Category.IDENTITY, payload__has_key="full_name")
    ```
  - In `generatable_facts`, change the return to
    `return unsuperseded_facts(student).filter(confirmed_by__isnull=False).exclude(category=VerifiedFact.Category.ID_DOCUMENT)`,
    and add to its docstring: "ID_DOCUMENT never: a passport number has no place in a CV or a
    letter, and generation sends this list to a model (spec 2026-10-12 D6)."

- [ ] **Step 5: Point the three consumers at the full-name row.**
  - `apps/documents/generation.py:326`: replace
    `generatable_facts(student).filter(category=VerifiedFact.Category.IDENTITY).exists()` with
    `has_full_name(generatable_facts(student)).exists()`, importing `has_full_name` from
    `.verification`.
  - `apps/documents/api.py:417`: the same replacement.
  - `apps/documents/gaps.py:580`: replace
    `unsuperseded_facts(student).filter(category=VerifiedFact.Category.IDENTITY).last()` with
    `has_full_name(unsuperseded_facts(student)).last()`.

- [ ] **Step 6: Give the bench samples every new key.**
  `tests/portals/test_bench_runner.py::test_the_samples_hold_every_key_a_map_can_ask_for_and_nothing_else`
  requires a sample value for every learnable key. In `apps/portals/bench_students.py`:
  - extend `_identity` with
    ```python
            "identity.date_of_birth": "1998-03-14",
            "identity.sex": "F",
            "identity.citizenship": "Azerbaijan",
            "identity.given_names": "NƏRMIN",
            "identity.surname": "BENCH-ƏLIYEVA",
            "identity.place_of_birth": "BAKU",
    ```
  - add a module constant
    ```python
    _ID_DOCUMENT = {
        "id_document.document_type": "passport",
        "id_document.number": "C01X00T47",
        "id_document.issuing_country": "Azerbaijan",
        "id_document.issue_date": "2021-05-20",
        "id_document.expiry_date": "2031-05-19",
        "id_document.issuing_authority": "MINISTRY OF INTERNAL AFFAIRS",
    }
    ```
    and merge `**_ID_DOCUMENT,` into the sample that already merges `**_identity(...)`.

- [ ] **Step 7: Run the new tests and the suites they touch**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents tests/portals`
Expected: PASS.
- A test asserting an exact IDENTITY payload dict, for example in ingestion or the profile
  bridge, now sees the new keys with `None` values. Update that expectation to include them: the
  payload is built by `fact_payload` from `payload_keys`, by design.
- `uv run python manage.py makemigrations --check --dry-run` must report "No changes detected".

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add -A apps/documents apps/portals/bench_students.py tests/documents/test_fact_vocabulary.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(documents): identity and ID-document fact keys; identity checks look for the full-name row"
```

---

### Task 2: The machine-readable strip

**Files:**
- Create: `apps/documents/mrz.py`
- Modify: `apps/documents/templatetags/cv_countries.py` (add `XK:Kosovo` to `_PAIRS`, in alphabetical order after `WS:Samoa`)
- Test: `tests/documents/test_mrz.py`

**Interfaces:**
- Produces:
  - `check_digit(field: str) -> str`;
  - `Strip` (frozen dataclass) with `format`, `document_code`, `issuing_state`, `surname`,
    `given_names`, `number: str | None`, `nationality`, `birth: str | None`, `sex`,
    `expiry: str | None`, `composite_ok: bool`;
  - `parse(raw: str) -> Strip | None`; `country_name_for(code: str) -> str | None`;
  - `NO_CITIZENSHIP: frozenset[str]`;
  - `printed_agrees(yymmdd: str, printed: date) -> bool`;
  - `date_from_strip(yymmdd: str, *, birth: bool, today: date) -> date | None`;
  - `names_agree(printed: str, strip_name: str) -> bool`; `fold_tokens(text: str) -> set[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_mrz.py
"""ICAO Doc 9303 specimens (Part 4, TD3; Part 5, TD1) and the failure cases."""

from datetime import date

from apps.documents import mrz

TD3 = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
)
TD1 = (
    "I<UTOD231458907<<<<<<<<<<<<<<<\n"
    "7408122F1204159UTO<<<<<<<<<<<6\n"
    "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"
)


def test_check_digits_of_the_specimens():
    assert mrz.check_digit("L898902C3") == "6"
    assert mrz.check_digit("740812") == "2"
    assert mrz.check_digit("120415") == "9"
    assert mrz.check_digit("D23145890") == "7"


def test_the_td3_specimen_parses_and_every_digit_holds():
    strip = mrz.parse(TD3)
    assert strip is not None and strip.format == "TD3" and strip.composite_ok
    assert (strip.surname, strip.given_names) == ("ERIKSSON", "ANNA MARIA")
    assert (strip.number, strip.birth, strip.expiry, strip.sex) == (
        "L898902C3", "740812", "120415", "F",
    )
    assert strip.nationality == "UTO" and strip.issuing_state == "UTO"


def test_the_td1_specimen_parses_and_every_digit_holds():
    strip = mrz.parse(TD1)
    assert strip is not None and strip.format == "TD1" and strip.composite_ok
    assert (strip.number, strip.birth, strip.expiry) == ("D23145890", "740812", "120415")
    assert (strip.surname, strip.given_names) == ("ERIKSSON", "ANNA MARIA")


def test_one_changed_digit_fails_its_own_check_and_the_composite():
    broken = TD3.replace("L898902C36", "L898903C36")
    strip = mrz.parse(broken)
    assert strip is not None and strip.number is None and not strip.composite_ok


def test_spaces_and_lowercase_from_ocr_are_tolerated_but_a_wrong_length_is_not():
    assert mrz.parse(TD3.lower().replace("<<<<", "< < < < ")) is not None
    assert mrz.parse(TD3[:-1]) is None
    assert mrz.parse("not a strip") is None


def test_a_document_number_continued_in_optional_data_is_not_proven():
    # A TD1 number longer than 9 characters puts "<" in the check position.
    long_number = TD1.replace("D231458907", "D23145890<", 1)
    strip = mrz.parse(long_number)
    assert strip is not None and strip.number is None


def test_dates_agree_with_the_printed_page_and_resolve_their_century():
    assert mrz.printed_agrees("740812", date(1974, 8, 12))
    assert not mrz.printed_agrees("740812", date(1974, 8, 13))
    today = date(2026, 10, 12)
    assert mrz.date_from_strip("740812", birth=True, today=today) == date(1974, 8, 12)
    assert mrz.date_from_strip("051231", birth=True, today=today) == date(2005, 12, 31)
    assert mrz.date_from_strip("310519", birth=False, today=today) == date(2031, 5, 19)
    assert mrz.date_from_strip("991399", birth=True, today=today) is None


def test_icao_codes_become_english_country_names():
    assert mrz.country_name_for("AZE") == "Azerbaijan"
    assert mrz.country_name_for("D<<") == "Germany"
    assert mrz.country_name_for("GBN") == "United Kingdom"
    assert mrz.country_name_for("UNK") == "Kosovo"
    assert mrz.country_name_for("UTO") is None  # the specimens' fictional state
    assert "XXA" in mrz.NO_CITIZENSHIP and "XXB" in mrz.NO_CITIZENSHIP


def test_printed_names_agree_with_their_strip_forms():
    assert mrz.names_agree("ƏLİYEV", "ALIYEV")
    assert mrz.names_agree("ƏLİYEV", "ELIYEV")
    assert mrz.names_agree("MÜLLER", "MUELLER") and mrz.names_agree("MÜLLER", "MULLER")
    assert mrz.names_agree("ŞAHİN", "SAHIN")
    assert mrz.names_agree("GROß", "GROSS")
    assert mrz.names_agree("ANNA MARIA LOUISE", "ANNA MARIA LOU")  # truncated strip
    assert not mrz.names_agree("ANNA", "ANNE")
    assert not mrz.names_agree("ANNA", "")


def test_fold_tokens_match_across_spellings():
    # Each letter's first strip form: Ə -> A, Ü -> UE, Ğ -> G. Both sides of a
    # comparison fold the same way, so the spelling chosen does not matter.
    assert mrz.fold_tokens("Məmmədova-Ağayeva Gülnarə") == {"MAMMADOVA", "AGAYEVA", "GUELNARA"}
```

- [ ] **Step 2: Run to see them fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_mrz.py`
Expected: FAIL (`ModuleNotFoundError: apps.documents.mrz`).

- [ ] **Step 3: Write `apps/documents/mrz.py`**

```python
"""The machine-readable strip of a passport (TD3) or an ID card (TD1).

ICAO Doc 9303 Parts 3-5. Standard library plus the country names this repo already
carries: about thirty lines of rules, not worth a dependency. The strip proves a
value only through its own check digit (spec 2026-10-12 §5.2): the document number,
the date of birth and the expiry each have one, and a composite digit covers them
together. Sex and nationality sit outside every digit, so they are proven only by
agreeing with the printed page -- never by the strip alone.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from babel.core import get_global

from .templatetags.cv_countries import country_name

_WEIGHTS = (7, 3, 1)
_STRIP_CHARS = re.compile(r"^[A-Z0-9<]+$")

#: ICAO codes ISO 3166 does not carry (Doc 9303 Part 3, 5): Germany's one-letter
#: code, the five British nationality classes, and the UN's code for Kosovo.
_ICAO_ONLY = {"D": "DE", "GBD": "GB", "GBN": "GB", "GBO": "GB", "GBP": "GB", "GBS": "GB",
              "UNK": "XK"}
#: Stateless (XXA), refugee (XXB, XXC) and unspecified (XXX): the field names no
#: citizenship, so nothing is ever proven from it.
NO_CITIZENSHIP = frozenset({"XXA", "XXB", "XXC", "XXX"})

#: Letters whose strip form differs between issuers, each with every form an
#: issuer uses (Doc 9303 Part 3, 6, plus national practice). Anything else is
#: folded by Unicode decomposition. Entries come from specimens and the consented
#: set (spec §9), never from guesswork.
_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    "Ə": ("A", "E"),
    "Ä": ("AE", "A"),
    "Ö": ("OE", "O"),
    "Ü": ("UE", "U"),
    "Å": ("AA", "A"),
    "Æ": ("AE",),
    "Ø": ("OE", "O"),
    "ß": ("SS",),
    "Ð": ("D",),
    "Þ": ("TH",),
    "Ł": ("L",),
}
_MAX_FORMS = 64


def check_digit(field: str) -> str:
    """The 7-3-1 weighted check digit of a strip field (Doc 9303 Part 3, 4.9)."""
    total = 0
    for index, char in enumerate(field):
        if char.isdigit():
            value = int(char)
        elif "A" <= char <= "Z":
            value = ord(char) - 55
        elif char == "<":
            value = 0
        else:
            raise ValueError("not a strip character")
        total += value * _WEIGHTS[index % 3]
    return str(total % 10)


@dataclass(frozen=True)
class Strip:
    format: str
    document_code: str
    issuing_state: str
    surname: str
    given_names: str
    #: None when the field's own check digit fails (or is "<", a continued number).
    number: str | None
    nationality: str
    birth: str | None
    sex: str
    expiry: str | None
    composite_ok: bool


def _checked(field: str, digit: str) -> str | None:
    return field if digit != "<" and check_digit(field) == digit else None


def _names(field: str) -> tuple[str, str]:
    surname, _, given = field.partition("<<")
    return " ".join(surname.split("<")).strip(), " ".join(given.split("<")).strip()


def parse(raw: str) -> Strip | None:
    """A strip from OCR text, or None when it is not one. Spaces and case are an
    OCR's; a wrong line length or a stray character is not a strip."""
    lines = [line.replace(" ", "").upper() for line in raw.splitlines() if line.strip()]
    if not all(_STRIP_CHARS.match(line) for line in lines):
        return None
    if len(lines) == 2 and all(len(line) == 44 for line in lines):
        return _td3(*lines)
    if len(lines) == 3 and all(len(line) == 30 for line in lines):
        return _td1(*lines)
    return None


def _td3(first: str, second: str) -> Strip:
    surname, given = _names(first[5:44])
    composite = second[0:10] + second[13:20] + second[21:43]
    return Strip(
        format="TD3",
        document_code=first[0:2].replace("<", ""),
        issuing_state=first[2:5],
        surname=surname,
        given_names=given,
        number=(_checked(second[0:9], second[9]) or "").replace("<", "") or None,
        nationality=second[10:13],
        birth=_checked(second[13:19], second[19]),
        sex=second[20],
        expiry=_checked(second[21:27], second[27]),
        composite_ok=check_digit(composite) == second[43],
    )


def _td1(first: str, second: str, third: str) -> Strip:
    surname, given = _names(third)
    composite = first[5:30] + second[0:7] + second[8:15] + second[18:29]
    return Strip(
        format="TD1",
        document_code=first[0:2].replace("<", ""),
        issuing_state=first[2:5],
        surname=surname,
        given_names=given,
        # ponytail: a number longer than 9 characters continues in the optional
        # field with "<" in the check position; it stays unproven rather than
        # parsed. Add the continuation rule if a real document needs it.
        number=(_checked(first[5:14], first[14]) or "").replace("<", "") or None,
        nationality=second[15:18],
        birth=_checked(second[0:6], second[6]),
        sex=second[7],
        expiry=_checked(second[8:14], second[14]),
        composite_ok=check_digit(composite) == second[29],
    )


def printed_agrees(yymmdd: str, printed: date) -> bool:
    return printed.strftime("%y%m%d") == yymmdd


def date_from_strip(yymmdd: str, *, birth: bool, today: date) -> date | None:
    """The strip's date with its century resolved: a birth date is never in the
    future; an expiry is in this century. Used only for a doubtful value, when no
    printed date exists to agree with."""
    try:
        year, month, day = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
        resolved = date(2000 + year, month, day)
    except ValueError:
        return None
    if birth and resolved > today:
        resolved = resolved.replace(year=resolved.year - 100)
    return resolved


def country_name_for(code: str) -> str | None:
    """English country name for an ICAO code, or None for anything ISO does not name."""
    code = code.replace("<", "").upper()
    if code in NO_CITIZENSHIP:
        return None
    alpha2 = _ICAO_ONLY.get(code)
    if alpha2 is None:
        aliases = get_global("territory_aliases").get(code) or []
        alpha2 = aliases[0] if len(aliases) == 1 else None
    if alpha2 is None:
        return None
    name = country_name(alpha2)
    return name if name != alpha2 else None


def _letter_options(char: str) -> tuple[str, ...]:
    if char in _ALTERNATIVES:
        return _ALTERNATIVES[char]
    base = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c))
    return (base,) if len(base) == 1 and "A" <= base <= "Z" else (" ",)


def _forms(printed: str) -> list[str]:
    options = [_letter_options(char) for char in printed.upper()]
    combos = itertools.islice(itertools.product(*options), _MAX_FORMS)
    return [" ".join("".join(combo).split()) for combo in combos]


def names_agree(printed: str, strip_name: str) -> bool:
    """The printed name, in some issuer's strip spelling, starts with the strip's
    name: the strip truncates long names, so a prefix is agreement."""
    wanted = " ".join(strip_name.upper().split())
    return bool(wanted) and any(form.startswith(wanted) for form in _forms(printed))


def fold_tokens(text: str) -> set[str]:
    """Name words in one fixed spelling (each letter's first strip form), for
    comparing a CV's name with a passport's."""
    return set(_forms(text)[0].split()) if text.strip() else set()
```

- [ ] **Step 4: Add Kosovo.** In `apps/documents/templatetags/cv_countries.py` `_PAIRS`, change the
  line `WF:Wallis and Futuna;WS:Samoa;YE:Yemen;YT:Mayotte;ZA:South Africa;ZM:Zambia;ZW:Zimbabwe`
  to `WF:Wallis and Futuna;WS:Samoa;XK:Kosovo;YE:Yemen;YT:Mayotte;ZA:South Africa;ZM:Zambia;ZW:Zimbabwe`.

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_mrz.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add apps/documents/mrz.py apps/documents/templatetags/cv_countries.py tests/documents/test_mrz.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(documents): parse and check a passport's machine-readable strip"
```

---

### Task 3: Azure's ID-document model

**Files:**
- Modify: `apps/documents/azure_layout.py`
- Test: `tests/documents/test_azure_id_document.py` (create)

**Interfaces:**
- Consumes: the existing `analyze_layout` loop and its injectable `start`/`poll`/`sleep`.
- Produces:
  - `AzureField` (`type`, `content`, `confidence`, `valueString`, `valueDate`,
    `valueCountryRegion`, `spans`, `valueObject: dict[str, AzureField]`), with
    `AzureField.text() -> str`;
  - `AzureIdDocument` (`docType`, `confidence`, `fields: dict[str, AzureField]`);
  - `AzureIdResult` (`content`, `pages: tuple[AzurePage, ...]`, `documents`);
  - `analyze_id_document(content: bytes, *, pages: str, start=..., poll=..., sleep=...) -> AzureIdResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_azure_id_document.py
import pytest

from apps.documents import azure_layout
from apps.documents.ocr_errors import OcrUnavailable

RESULT = {
    "content": "PASSPORT ...",
    "pages": [{"pageNumber": 1, "width": 8.5, "height": 11, "unit": "inch",
               "words": [{"content": "BAKU", "confidence": 0.99,
                          "span": {"offset": 0, "length": 4}}]}],
    "documents": [{
        "docType": "idDocument.passport", "confidence": 0.99,
        "fields": {
            "PlaceOfBirth": {"type": "string", "valueString": "BAKU", "content": "BAKU",
                             "confidence": 0.98, "spans": [{"offset": 0, "length": 4}]},
            "MachineReadableZone": {"type": "object", "content": "P<AZE...", "confidence": 0.99,
                                    "valueObject": {"Sex": {"type": "string",
                                                            "valueString": "F"}}},
        },
    }],
}


@pytest.fixture
def configured(settings):
    settings.AZURE_DI_ENDPOINT = "https://di.example.com"
    settings.AZURE_DI_KEY = "key"


def test_an_id_document_is_read_with_the_id_model(configured):
    started = {}

    def start(url, *, payload, headers):
        started["url"] = url
        return "https://di.example.com/op/1"

    result = azure_layout.analyze_id_document(
        b"%PDF-1.7", pages="1-4", start=start,
        poll=lambda *a, **k: {"status": "succeeded", "analyzeResult": RESULT},
        sleep=lambda s: None,
    )
    assert "prebuilt-idDocument:analyze" in started["url"] and "pages=1-4" in started["url"]
    passport = result.documents[0]
    assert passport.docType == "idDocument.passport"
    assert passport.fields["PlaceOfBirth"].text() == "BAKU"
    assert passport.fields["MachineReadableZone"].valueObject["Sex"].text() == "F"


def test_an_unconfigured_reader_is_unavailable(settings):
    settings.AZURE_DI_ENDPOINT = ""
    with pytest.raises(OcrUnavailable):
        azure_layout.analyze_id_document(b"x", pages="1-4")


def test_the_layout_reader_still_reads_layout(configured):
    started = {}

    def start(url, *, payload, headers):
        started["url"] = url
        return "op"

    azure_layout.analyze_layout(
        b"x", start=start, poll=lambda *a, **k: {"status": "succeeded",
                                                  "analyzeResult": {"content": ""}},
        sleep=lambda s: None,
    )
    assert "prebuilt-layout:analyze" in started["url"]
```

- [ ] **Step 2: Run to see it fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_azure_id_document.py`
Expected: FAIL (`AttributeError: ... analyze_id_document`).

- [ ] **Step 3: Refactor the loop and add the model.** In `apps/documents/azure_layout.py`:
  - Rename the body of `analyze_layout` into
    `_analyze(model: str, content: bytes, *, pages, locale, start, poll, sleep) -> dict[str, object]`.
    It builds the URL with
    `f".../documentintelligence/documentModels/{model}:analyze?{urlencode(query)}"` and returns
    the raw `analyzeResult` dict. It keeps every `except` branch and message exactly. The one
    exception: the pydantic `ValidationError` branch moves to the callers, because `_analyze` no
    longer validates.
  - `analyze_layout` keeps its signature and becomes:
    ```python
        try:
            return AzureLayout.model_validate(
                _analyze("prebuilt-layout", content, pages=pages, locale=locale,
                         start=start, poll=poll, sleep=sleep)
            )
        except ValidationError as error:
            raise OcrUnavailable("Azure answered outside the layout schema") from error
    ```
  - Add the models and the new entry point:
    ```python
    class AzureField(BaseModel):
        """One field of a prebuilt model's document (2024-11-30 schema)."""

        model_config = _IGNORE
        type: str = ""
        content: str = ""
        confidence: float = 0.0
        valueString: str | None = None
        valueDate: str | None = None
        valueCountryRegion: str | None = None
        spans: tuple[AzureSpan, ...] = ()
        valueObject: dict[str, AzureField] = {}

        def text(self) -> str:
            """The typed value when Azure gave one, else the printed content."""
            return (self.valueString or self.valueDate or self.valueCountryRegion
                    or self.content or "").strip()


    AzureField.model_rebuild()


    class AzureIdDocument(BaseModel):
        model_config = _IGNORE
        docType: str
        confidence: float = 0.0
        fields: dict[str, AzureField] = {}


    class AzureIdResult(BaseModel):
        model_config = _IGNORE
        content: str = ""
        pages: tuple[AzurePage, ...] = ()
        documents: tuple[AzureIdDocument, ...] = ()


    def analyze_id_document(
        content: bytes,
        *,
        pages: str,
        start: Callable[..., str] = start_json_operation,
        poll: Callable[..., dict[str, object]] = fetch_json_api,
        sleep: Callable[[float], None] = time.sleep,
    ) -> AzureIdResult:
        """prebuilt-idDocument (spec 2026-10-12 §5.2): a passport, ID card or residence
        permit, the printed page and the strip. `pages` caps what is analysed and billed."""
        try:
            return AzureIdResult.model_validate(
                _analyze("prebuilt-idDocument", content, pages=pages, locale=None,
                         start=start, poll=poll, sleep=sleep)
            )
        except ValidationError as error:
            raise OcrUnavailable("Azure answered outside the ID document schema") from error
    ```
  - Update the module docstring's first line to "Azure Document Intelligence: prebuilt-layout for
    scanned pages and photos, prebuilt-idDocument for passports and ID cards."

- [ ] **Step 4: Run the new and the existing Azure tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_azure_id_document.py tests/documents/test_azure_layout.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add apps/documents/azure_layout.py tests/documents/test_azure_id_document.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(documents): Azure's ID-document model behind the same guarded loop"
```

---

### Task 4: The proof rules

**Files:**
- Create: `apps/documents/id_reading.py`
- Create: `tests/documents/id_fixtures.py` (a builder for Azure ID results with real check digits)
- Test: `tests/documents/test_id_reading.py`

**Interfaces:**
- Consumes: `mrz.*` (Task 2); `AzureIdResult`, `AzureField` (Task 3).
- Produces:
  - `ReadValue(key: str, value: str, snippet: str, proven: bool, why: str)`, a frozen
    dataclass, with `as_dict()` and `ReadValue.from_dict(d)`;
  - `class NotRead(Exception)` with `.code` (`not_an_id_document` or `no_data_page`);
  - `read_id(result: AzureIdResult, *, known_names: list[str], threshold: float, today: date) -> list[ReadValue]`.

- [ ] **Step 1: Write the fixture builder**

```python
# tests/documents/id_fixtures.py
"""Azure prebuilt-idDocument answers with a strip whose check digits are real."""

from apps.documents.azure_layout import AzureIdResult
from apps.documents.mrz import check_digit


def td3(*, surname="ALIYEVA", given="NARMIN", number="C01X00T47", nationality="AZE",
        birth="980314", sex="F", expiry="310519", personal="", issuing="AZE") -> str:
    names = f"{surname}<<{given.replace(' ', '<')}"
    first = f"P<{issuing}{names}".ljust(44, "<")[:44]
    number_field = number.ljust(9, "<")
    personal_field = personal.ljust(14, "<")
    second = (
        f"{number_field}{check_digit(number_field)}{nationality}{birth}{check_digit(birth)}"
        f"{sex}{expiry}{check_digit(expiry)}{personal_field}{check_digit(personal_field)}"
    )
    composite = second[0:10] + second[13:20] + second[21:43]
    return f"{first}\n{second}{check_digit(composite)}"


def field(value, *, kind="string", confidence=0.99, offset=0):
    key = {"string": "valueString", "date": "valueDate", "countryRegion": "valueCountryRegion"}[kind]
    return {"type": kind, key: value, "content": value, "confidence": confidence,
            "spans": [{"offset": offset, "length": len(value)}]}


def result(fields: dict, *, doc_type="idDocument.passport", word_confidence=0.99,
           strip: str | None = None) -> AzureIdResult:
    """`fields` maps Azure field names to field() dicts; words are generated so
    every field's span is covered at `word_confidence`."""
    words, text, offset = [], [], 0
    built = {}
    for name, spec in fields.items():
        content = spec["content"]
        spec = {**spec, "spans": [{"offset": offset, "length": len(content)}]}
        words.append({"content": content, "confidence": word_confidence,
                      "span": {"offset": offset, "length": len(content)}})
        text.append(content)
        offset += len(content) + 1
        built[name] = spec
    if strip is not None:
        built["MachineReadableZone"] = {"type": "object", "content": strip, "confidence": 0.99}
    return AzureIdResult.model_validate({
        "content": " ".join(text),
        "pages": [{"pageNumber": 1, "width": 1, "height": 1, "unit": "inch", "words": words}],
        "documents": [{"docType": doc_type, "confidence": 0.99, "fields": built}],
    })


def passport(**overrides):
    """A clean passport whose printed page agrees with its strip."""
    printed = {
        "LastName": field("ƏLIYEVA"), "FirstName": field("NƏRMIN"),
        "DocumentNumber": field("C01X00T47"), "DateOfBirth": field("1998-03-14", kind="date"),
        "DateOfExpiration": field("2031-05-19", kind="date"),
        "DateOfIssue": field("2021-05-20", kind="date"), "Sex": field("F"),
        "Nationality": field("AZE", kind="countryRegion"),
        "CountryRegion": field("AZE", kind="countryRegion"),
        "PlaceOfBirth": field("BAKU"), "IssuingAuthority": field("MIA"),
    }
    strip_args = overrides.pop("strip_args", {})
    printed.update(overrides.pop("fields", {}))
    return result(printed, strip=td3(**strip_args), **overrides)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/documents/test_id_reading.py
"""Spec 2026-10-12 §5.2: what a passport read proves, one test per rule."""

from datetime import date

import pytest

from apps.documents.id_reading import NotRead, read_id
from tests.documents.id_fixtures import field, passport, result

TODAY = date(2026, 10, 12)


def _read(azure, known_names=()):
    values = read_id(azure, known_names=list(known_names), threshold=0.95, today=TODAY)
    return {v.key: v for v in values}


def test_a_clean_passport_proves_its_strip_values_and_its_confident_page_values():
    got = _read(passport())
    for key in ("id_document.number", "identity.date_of_birth", "id_document.expiry_date"):
        assert got[key].proven and got[key].why == "check_digit"
    assert got["identity.date_of_birth"].value == "1998-03-14"
    assert got["identity.sex"].proven and got["identity.sex"].why == "strip_agrees"
    assert got["identity.citizenship"].value == "Azerbaijan" and got["identity.citizenship"].proven
    assert got["identity.surname"].value == "ƏLIYEVA" and got["identity.surname"].proven
    assert got["identity.place_of_birth"].proven and got["identity.place_of_birth"].why == "confident"
    assert got["id_document.document_type"].value == "passport"
    assert got["id_document.issuing_country"].value == "Azerbaijan"


def test_a_page_disagreeing_with_the_strip_is_doubtful():
    got = _read(passport(fields={"DateOfBirth": field("1998-03-15", kind="date")}))
    assert not got["identity.date_of_birth"].proven
    assert got["identity.date_of_birth"].why == "strip_disagrees"
    assert got["identity.date_of_birth"].value == "1998-03-15"  # the printed form is shown


def test_sex_is_never_proven_by_the_strip_alone():
    """No check digit covers it: an OCR slip in the strip's sex position leaves the
    composite valid, so only agreement with the page proves it."""
    got = _read(passport(fields={"Sex": field("M")}))
    assert not got["identity.sex"].proven and got["identity.sex"].why == "strip_disagrees"


def test_a_broken_composite_proves_nothing_from_the_strip():
    azure = passport()
    strip = azure.documents[0].fields["MachineReadableZone"]
    broken = strip.content[:-1] + ("1" if strip.content[-1] != "1" else "2")
    azure.documents[0].fields["MachineReadableZone"] = strip.model_copy(update={"content": broken})
    got = _read(azure)
    assert not any(v.proven for k, v in got.items() if k in (
        "id_document.number", "identity.date_of_birth", "identity.sex", "identity.surname"))


def test_no_strip_leaves_strip_values_doubtful():
    azure = result({"LastName": field("ALIYEVA"), "DateOfBirth": field("1998-03-14", kind="date")})
    got = _read(azure)
    assert not got["identity.date_of_birth"].proven
    assert got["identity.date_of_birth"].why == "no_strip"


def test_a_low_confidence_place_of_birth_is_doubtful():
    azure = passport(fields={"PlaceOfBirth": field("BAKU", confidence=0.80)})
    got = _read(azure)
    assert not got["identity.place_of_birth"].proven
    assert got["identity.place_of_birth"].why == "low_confidence"


def test_low_word_confidence_makes_a_confident_field_doubtful():
    got = _read(passport(word_confidence=0.6))
    assert not got["identity.place_of_birth"].proven


def test_a_stateless_document_never_proves_a_citizenship():
    got = _read(passport(strip_args={"nationality": "XXA"},
                         fields={"Nationality": field("XXA", kind="countryRegion")}))
    assert not got["identity.citizenship"].proven
    assert got["identity.citizenship"].why == "no_citizenship"


def test_someone_elses_passport_proves_nothing():
    got = _read(passport(), known_names=["Rauf Hüseynov"])
    assert not any(v.proven for v in got.values())
    assert {v.why for v in got.values()} == {"owner_mismatch"}


def test_the_students_own_passport_matches_across_spellings():
    got = _read(passport(), known_names=["Nərmin Əliyeva"])
    assert got["id_document.number"].proven


def test_not_an_id_document_and_no_data_page():
    with pytest.raises(NotRead) as wrong:
        read_id(result({}, doc_type="invoice"), known_names=[], threshold=0.95, today=TODAY)
    assert wrong.value.code == "not_an_id_document"
    empty = result({}).model_copy(update={"documents": ()})
    with pytest.raises(NotRead) as none:
        read_id(empty, known_names=[], threshold=0.95, today=TODAY)
    assert none.value.code == "no_data_page"
```

- [ ] **Step 3: Run to see them fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_id_reading.py`
Expected: FAIL (`ModuleNotFoundError: apps.documents.id_reading`).

- [ ] **Step 4: Write `apps/documents/id_reading.py`**

```python
"""What a passport or ID card read proves (spec 2026-10-12 §5.2). Pure: an Azure
prebuilt-idDocument answer in, values with their proof out. No model reads a
passport; the proof is the strip's own check digits and agreement between the
strip and the printed page, or Azure's confidence where the strip is silent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date

from . import mrz
from .azure_layout import AzureField, AzureIdResult

ID_TYPES = {
    "idDocument.passport": "passport",
    "idDocument.nationalIdentityCard": "national_id",
    "idDocument.residencePermit": "residence_permit",
}
_SNIPPET = 200


@dataclass(frozen=True)
class ReadValue:
    key: str
    value: str
    snippet: str
    proven: bool
    why: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ReadValue:
        return cls(key=str(data["key"]), value=str(data["value"]), snippet=str(data["snippet"]),
                   proven=bool(data["proven"]), why=str(data["why"]))


class NotRead(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _confident(field: AzureField, result: AzureIdResult, threshold: float) -> bool:
    if field.confidence < threshold:
        return False
    spans = [(span.offset, span.offset + span.length) for span in field.spans]
    words = [word for page in result.pages for word in page.words
             if any(start <= word.span.offset < end for start, end in spans)]
    return bool(words) and all(word.confidence >= threshold for word in words)


def _iso(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def read_id(
    result: AzureIdResult, *, known_names: list[str], threshold: float, today: date
) -> list[ReadValue]:
    document = next((d for d in result.documents if d.docType in ID_TYPES), None)
    if document is None:
        raise NotRead("not_an_id_document" if result.documents else "no_data_page")
    fields = document.fields
    zone = fields.get("MachineReadableZone")
    strip = mrz.parse(zone.content) if zone is not None else None
    sound = strip is not None and strip.composite_ok
    values: list[ReadValue] = []

    def printed(name: str) -> AzureField | None:
        found = fields.get(name)
        return found if found is not None and found.text() else None

    def add(key: str, value: str, snippet: str, proven: bool, why: str) -> None:
        if value:
            values.append(ReadValue(key, value, snippet[:_SNIPPET], proven, why))

    def strip_why(agrees: bool) -> str:
        if strip is None:
            return "no_strip"
        return "check_digit" if sound and agrees else "strip_disagrees"

    # Values a check digit covers: proven by the digit AND the printed page.
    number = printed("DocumentNumber")
    if number is not None:
        text = number.text().replace(" ", "")
        agrees = sound and strip is not None and strip.number == text
        add("id_document.number", text, number.content, agrees, strip_why(agrees))
    for key, name, attr, birth in (
        ("identity.date_of_birth", "DateOfBirth", "birth", True),
        ("id_document.expiry_date", "DateOfExpiration", "expiry", False),
    ):
        page = printed(name)
        yymmdd = getattr(strip, attr) if strip is not None else None
        on_page = _iso(page.text()) if page is not None else None
        if on_page is not None:
            agrees = sound and yymmdd is not None and mrz.printed_agrees(yymmdd, on_page)
            add(key, on_page.isoformat(), page.content if page else "", agrees, strip_why(agrees))
        elif yymmdd is not None:
            from_strip = mrz.date_from_strip(yymmdd, birth=birth, today=today)
            if from_strip is not None:
                add(key, from_strip.isoformat(), zone.content if zone else "", False, "no_strip")

    # Values outside every digit: proven only by the strip and the page agreeing.
    sex = printed("Sex")
    if sex is not None:
        page_sex = sex.text()[:1].upper()
        strip_sex = (strip.sex if strip is not None else "").replace("<", "X")
        agrees = sound and page_sex == strip_sex
        add("identity.sex", page_sex, sex.content, agrees,
            "strip_agrees" if agrees else ("no_strip" if strip is None else "strip_disagrees"))
    for key, name, attr in (
        ("identity.citizenship", "Nationality", "nationality"),
        ("id_document.issuing_country", "CountryRegion", "issuing_state"),
    ):
        page = printed(name)
        if page is None:
            continue
        code = page.text().upper()
        name_text = mrz.country_name_for(code)
        if code in mrz.NO_CITIZENSHIP or (strip is not None and getattr(strip, attr) in mrz.NO_CITIZENSHIP):
            add(key, code, page.content, False, "no_citizenship")
            continue
        if name_text is None:
            add(key, code, page.content, False, "unknown_country")
            continue
        strip_name = mrz.country_name_for(getattr(strip, attr)) if strip is not None else None
        agrees = sound and strip_name == name_text
        add(key, name_text, page.content, agrees,
            "strip_agrees" if agrees else ("no_strip" if strip is None else "strip_disagrees"))
    for key, name, attr in (
        ("identity.surname", "LastName", "surname"),
        ("identity.given_names", "FirstName", "given_names"),
    ):
        page = printed(name)
        if page is None:
            continue
        agrees = sound and strip is not None and mrz.names_agree(page.text(), getattr(strip, attr))
        add(key, page.text(), page.content, agrees,
            "strip_agrees" if agrees else ("no_strip" if strip is None else "strip_disagrees"))
    document_type = ID_TYPES[document.docType]
    strip_type = {"TD3": "passport"}.get(strip.format, "card") if strip is not None else ""
    type_agrees = sound and (strip_type == document_type
                             or (strip_type == "card" and document_type != "passport"))
    add("id_document.document_type", document_type, document.docType, type_agrees,
        "strip_agrees" if type_agrees else ("no_strip" if strip is None else "strip_disagrees"))

    # Values the strip does not carry: proven only by Azure's confidence.
    for key, name in (
        ("identity.place_of_birth", "PlaceOfBirth"),
        ("id_document.issue_date", "DateOfIssue"),
        ("id_document.issuing_authority", "IssuingAuthority"),
    ):
        page = printed(name)
        if page is None:
            continue
        value = page.text()
        if key.endswith("_date"):
            parsed = _iso(value)
            if parsed is None:
                continue
            value = parsed.isoformat()
        confident = _confident(page, result, threshold)
        add(key, value, page.content, confident, "confident" if confident else "low_confidence")

    if known_names and not _owner_matches(values, known_names):
        values = [replace(v, proven=False, why="owner_mismatch") for v in values]
    return values


def _owner_matches(values: list[ReadValue], known_names: list[str]) -> bool:
    """Spec §5.2.4: the read surname shares a word with a name we already hold for
    the student. A parent's passport uploaded under PASSPORT fails this."""
    surname = next((v.value for v in values if v.key == "identity.surname"), "")
    tokens = mrz.fold_tokens(surname)
    if not tokens:
        return True  # nothing to compare; the strip rules stand alone
    return any(tokens & mrz.fold_tokens(name) for name in known_names)
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_id_reading.py tests/documents/test_mrz.py`
Expected: PASS.
- If `test_a_broken_composite_proves_nothing_from_the_strip` flips the last digit into another
  valid composite, change the replacement character until `mrz.parse(...).composite_ok` is
  False. The test is about a broken composite.

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add apps/documents/id_reading.py tests/documents/id_fixtures.py tests/documents/test_id_reading.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(documents): what a passport read proves -- strip digits, page agreement, confidence, owner"
```

---

### Task 5: The reading record, and erasure

**Files:**
- Modify: `apps/documents/models.py` (add `DocumentReading` after `TranscriptReading`)
- Create (generated): `apps/documents/migrations/0029_document_reading.py`
- Create: `apps/documents/migrations/0030_document_reading_tenant_guards.py`
- Modify: `apps/audit/redaction.py` (REDACT entry and allow-list), `apps/audit/deletion.py`
- Test: `tests/documents/test_document_reading_model.py`

**Interfaces:**
- Produces: `DocumentReading`:
  - fields: `student`, `document`, `kind`, `state` (`State.QUEUED/READING/DELAYED/READ/FAILED`),
    `failure`, `attempts`, `next_attempt_at`, `reader_version`, `file_sha256`, `azure_pages`,
    `values` (a list of `ReadValue.as_dict()`), `facts_written`, `primary_chosen_at`,
    `updated_at`, `created_at`;
  - unique `(document, reader_version)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_document_reading_model.py
import pytest
from django.db import IntegrityError, transaction

from apps.concierge.documents import register
from apps.documents.models import DocumentReading
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _reading(agency, membership, **fields):
    document = register(agency.id, membership.id, kind="PASSPORT")
    with tenant_scope(agency.id):
        return DocumentReading.objects.create(
            student=membership, document=document, kind="PASSPORT", reader_version="id-1",
            **fields,
        )


def test_one_reading_per_document_and_reader_version(agency_a, membership_a):
    reading = _reading(agency_a, membership_a)
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        DocumentReading.objects.create(
            student=membership_a, document=reading.document, kind="PASSPORT",
            reader_version="id-1",
        )


def test_a_tenant_never_sees_another_tenants_reading(rls_enforced_orm, agency_a, agency_b,
                                                     membership_a):
    _reading(agency_a, membership_a, values=[{"key": "identity.surname"}])
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert not DocumentReading.objects.exists()


def test_erasure_deletes_the_readings(agency_a, membership_a, monkeypatch):
    """Mirrors tests/portals/test_answers.py::test_erasure_deletes_the_students_answers.
    The test role is BYPASSRLS, so this proves the delete exists, not its RLS placement."""
    from django.utils import timezone

    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)
    _reading(agency_a, membership_a, values=[{"key": "identity.surname", "value": "ALIYEVA"}])
    with tenant_scope(agency_a.id):
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
        for state in ("RETENTION_REVIEW", "APPROVED", "EXECUTED"):
            advance_deletion(request, state)
        assert not DocumentReading.objects.filter(student=membership_a).exists()
```

`rls_enforced_orm` is defined in `tests/portals/test_rls_spine.py`. Check how other modules reach
it (`grep -rn "rls_enforced_orm" tests | head`). If it is not in a conftest that `tests/documents`
sees, import it into this test module the way those modules do.

- [ ] **Step 2: Run to see them fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_document_reading_model.py`
Expected: FAIL (ImportError on `DocumentReading`).

- [ ] **Step 3: Add the model** in `apps/documents/models.py`, after `TranscriptReading`:

```python
class DocumentReading(TenantScopedModel):
    """One read of one passport, ID card, diploma or certificate (spec 2026-10-12 §6.1).

    `values` holds what was read and how it was proven -- the normalised value, the
    printed snippet it came from (at most 200 characters) and a closed `why` code --
    never Azure's raw answer or a model's. One row per (document, reader_version):
    a new reader version re-reads, the same one never does.
    """

    class State(models.TextChoices):
        QUEUED = "QUEUED"
        READING = "READING"
        DELAYED = "DELAYED"
        READ = "READ"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    document = models.ForeignKey(
        "concierge.DocumentVersion", on_delete=models.PROTECT, related_name="readings"
    )
    kind = models.CharField(max_length=30)
    state = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED)
    failure = models.CharField(max_length=30, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    reader_version = models.CharField(max_length=20)
    file_sha256 = models.CharField(max_length=64, blank=True)
    azure_pages = models.PositiveSmallIntegerField(default=0)
    values = models.JSONField(default=list)
    facts_written = models.BooleanField(default=False)
    #: The student chose this ID document for portals (spec §4.2); latest wins.
    primary_chosen_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="documentreading_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("document", "reader_version"), name="documentreading_once_per_version"
            ),
        ]
```

Run `uv run python manage.py makemigrations documents --name document_reading`.

- [ ] **Step 4: Write the guards migration** `apps/documents/migrations/0030_document_reading_tenant_guards.py`:

```python
from django.db import migrations

RLS_SQL = """
ALTER TABLE documents_documentreading ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_documentreading FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_documentreading
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE documents_documentreading
    ADD CONSTRAINT documentreading_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_documentreading
    ADD CONSTRAINT documentreading_document_tenant_fk
    FOREIGN KEY (tenant_id, document_id)
    REFERENCES concierge_documentversion (tenant_id, id);
"""

REVERSE_SQL = """
ALTER TABLE documents_documentreading DROP CONSTRAINT documentreading_student_tenant_fk;
ALTER TABLE documents_documentreading DROP CONSTRAINT documentreading_document_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_documentreading;
ALTER TABLE documents_documentreading DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0029_document_reading"),
        ("concierge", "0014_studentcycle_tenant_guards"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
```

- [ ] **Step 5: Cover erasure.**
  - In `apps/audit/redaction.py`, add to `REDACT` after the `portals.PortalAnswer` entry:
    ```python
        # What a passport, diploma or certificate read says about the student.
        # Deleted outright by advance_deletion; redacted first as well, as
        # PortalAnswer is.
        "documents.DocumentReading": RedactSpec("student_id", ("values", "file_sha256")),
    ```
  - In the allow-list, after `"documents.TranscriptUpload": (...)`, add:
    ```python
        "documents.DocumentReading": (
            "kind", "state", "failure", "attempts", "next_attempt_at", "reader_version",
            "azure_pages", "facts_written", "primary_chosen_at", "updated_at", "created_at",
        ),
    ```
  - In `apps/audit/deletion.py`, directly after the
    `PortalAnswer.objects.filter(student_id=request.student_id).delete()` line, add:
    ```python
                # A document read's values (spec 2026-10-12 §8): about the person,
                # inside this block for the FORCE RLS reason PortalAnswer is.
                DocumentReading.objects.filter(student_id=request.student_id).delete()
    ```
    and import `DocumentReading` from `apps.documents.models`.
  - The `DocumentVersion` rows the readings point at are redacted, never deleted, so the PROTECT
    FK holds: readings go first, inside the same transaction.

- [ ] **Step 6: Run the model tests and the redaction coverage tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_document_reading_model.py tests/audit`
Expected: PASS. `tests/audit/test_redaction_classification.py` fails if any field of the new model
is in neither table; add it to the table it belongs in.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add -A apps/documents apps/audit tests/documents/test_document_reading_model.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(documents): DocumentReading, tenant-guarded and erased with the student"
```

---

### Task 6: Writing the facts, correcting them, and serving the right ID document

**Files:**
- Create: `apps/documents/fact_writer.py`
- Modify: `apps/documents/audit.py` (`actor_kind`)
- Modify: `apps/portals/profile.py` (`verified_values`)
- Test: `tests/documents/test_fact_writer.py`, `tests/portals/test_profile_id_documents.py`

**Interfaces:**
- Consumes: `ReadValue` (Task 4), `DocumentReading` (Task 5), `ID_DOCUMENT_KEYS` (Task 1).
- Produces:
  - `PROTECTED_KEYS: frozenset[str]`;
  - `write_facts(reading: DocumentReading) -> None`, called inside a tenant transaction;
  - `correct_fact(*, student: Membership, fact_id: UUID, key: str, value: str) -> VerifiedFact`,
    which raises `FactNotFound` (from `confirmation`) or `ValueError("invalid_value")`;
  - `record_event(*, actor, event, object_id, actor_kind="")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_fact_writer.py
"""Spec 2026-10-12 §6.2: precedence, one test per rule."""

import pytest
from django.utils import timezone

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents.fact_writer import correct_fact, write_facts
from apps.documents.id_reading import ReadValue
from apps.documents.models import DocumentReading, VerifiedFact
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _read(agency, student, values, kind="PASSPORT"):
    document = register(agency.id, student.id, kind=kind)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        reading = DocumentReading.objects.create(
            student=student, document=document, kind=kind, reader_version="id-1",
            state="READ", values=[v.as_dict() for v in values],
        )
        write_facts(reading)
        reading.refresh_from_db()
    return reading


def _v(key, value, proven=True, why="check_digit"):
    return ReadValue(key, value, value, proven, why)


def _current(student, category, key):
    return [f for f in VerifiedFact.objects.filter(student=student, category=category,
                                                   superseded_by__isnull=True)
            if key in f.payload]


def test_a_proven_value_is_a_confirmed_fact_the_machine_wrote(agency_a, membership_a):
    reading = _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    with tenant_scope(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "date_of_birth")
        assert fact.confirmed_at is not None and fact.confirmed_by == membership_a
        assert fact.source_ref == f"document:{reading.document_id}"
        event = AuditEvent.objects.get(object_id=fact.id)
        assert (event.event, event.actor_id, event.actor_kind) == (
            "fact.read_from_document", None, "AGENT")
    assert reading.facts_written


def test_a_doubtful_value_waits_unconfirmed(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", False, "low_confidence")])
    with tenant_scope(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "place_of_birth")
        assert fact.confirmed_at is None


def test_the_students_own_entry_wins(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        own = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"date_of_birth": "1998-03-15"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", confirmed_by=membership_a,
            confirmed_at=timezone.now(), created_by=membership_a,
        )
    reading = _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    with tenant_scope(agency_a.id):
        rows = _current(membership_a, "IDENTITY", "date_of_birth")
        assert own in rows
        read = next(f for f in rows if f.id != own.id)
        assert read.confirmed_at is None
    assert reading.values[0]["why"] == "student_entry_differs"


def test_an_agreeing_read_writes_nothing(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    with tenant_scope(agency_a.id):
        assert len(_current(membership_a, "IDENTITY", "date_of_birth")) == 1


def test_a_renewal_with_a_new_surname_becomes_a_detail_to_check(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.surname", "ALIYEVA")])
    _read(agency_a, membership_a, [_v("identity.surname", "HUSEYNOVA")])
    with tenant_scope(agency_a.id):
        rows = _current(membership_a, "IDENTITY", "surname")
        confirmed = [f.payload["surname"] for f in rows if f.confirmed_at]
        waiting = [f.payload["surname"] for f in rows if not f.confirmed_at]
    assert confirmed == ["ALIYEVA"] and waiting == ["HUSEYNOVA"]


def test_a_newer_proven_unprotected_value_supersedes_an_older_read(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKI", why="confident")])
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKU", why="confident")])
    with tenant_scope(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "place_of_birth")
        assert fact.payload["place_of_birth"] == "BAKU" and fact.supersedes is not None


def test_an_id_document_is_one_row_with_its_doubtful_keys_beside_it(agency_a, membership_a):
    reading = _read(agency_a, membership_a, [
        _v("id_document.number", "C01X00T47"),
        _v("id_document.expiry_date", "2031-05-19"),
        _v("id_document.issue_date", "2021-05-20", False, "low_confidence"),
    ])
    ref = f"document:{reading.document_id}"
    with tenant_scope(agency_a.id):
        rows = list(VerifiedFact.objects.filter(student=membership_a, category="ID_DOCUMENT",
                                                source_ref=ref))
        confirmed = [f for f in rows if f.confirmed_at]
        assert len(confirmed) == 1
        assert confirmed[0].payload == {"number": "C01X00T47", "expiry_date": "2031-05-19"}
        assert [f.payload for f in rows if not f.confirmed_at] == [{"issue_date": "2021-05-20"}]
        document = DocumentVersion.objects.get(id=reading.document_id)
        assert str(document.expires_on) == "2031-05-19"


def test_a_typed_expiry_is_never_overwritten(agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentVersion.objects.filter(id=document.id).update(expires_on="2030-01-01")
        reading = DocumentReading.objects.create(
            student=membership_a, document=document, kind="PASSPORT", reader_version="id-1",
            state="READ", values=[_v("id_document.expiry_date", "2031-05-19").as_dict()],
        )
        write_facts(reading)
        assert str(DocumentVersion.objects.get(id=document.id).expires_on) == "2030-01-01"


def test_a_correction_supersedes_with_the_students_own_entry(agency_a, membership_a):
    _read(agency_a, membership_a, [_v("identity.place_of_birth", "BAKI", False, "low_confidence")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "place_of_birth")
        new = correct_fact(student=membership_a, fact_id=fact.id, key="place_of_birth",
                           value="Baku")
        assert new.supersedes_id == fact.id and new.source_tier == "STUDENT_STATEMENT"
        assert new.confirmed_by == membership_a and new.payload == {"place_of_birth": "Baku"}


def test_a_correction_refuses_a_bad_date_and_someone_elses_fact(agency_a, membership_a,
                                                                membership_b):
    from apps.documents.confirmation import FactNotFound

    _read(agency_a, membership_a, [_v("identity.date_of_birth", "1998-03-14")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (fact,) = _current(membership_a, "IDENTITY", "date_of_birth")
        with pytest.raises(ValueError):
            correct_fact(student=membership_a, fact_id=fact.id, key="date_of_birth",
                         value="14/03/1998")
        with pytest.raises(FactNotFound):
            correct_fact(student=membership_b, fact_id=fact.id, key="date_of_birth",
                         value="1998-03-14")
```

```python
# tests/portals/test_profile_id_documents.py
"""Spec 2026-10-12 §4.2: which ID document a portal gets."""

import pytest
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.models import DocumentReading, VerifiedFact
from apps.portals.profile import verified_values
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _document(agency, student, payload):
    document = register(agency.id, student.id, kind="PASSPORT")
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        VerifiedFact.objects.create(
            student=student, category="ID_DOCUMENT", payload=payload,
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
            confirmed_by=student, confirmed_at=timezone.now(), created_by=student,
        )
        DocumentReading.objects.create(student=student, document=document, kind="PASSPORT",
                                       reader_version="id-1", state="READ")
    return document


def _values(agency, student):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return verified_values(student)


def test_the_valid_passport_with_the_latest_expiry_is_served(agency_a, membership_a):
    _document(agency_a, membership_a, {"document_type": "passport", "number": "OLD",
                                       "expiry_date": "2027-01-01"})
    _document(agency_a, membership_a, {"document_type": "passport", "number": "NEW",
                                       "expiry_date": "2031-01-01"})
    _document(agency_a, membership_a, {"document_type": "national_id", "number": "CARD",
                                       "expiry_date": "2035-01-01"})
    assert _values(agency_a, membership_a)["id_document.number"] == "NEW"


def test_an_expired_document_is_never_served(agency_a, membership_a):
    _document(agency_a, membership_a, {"document_type": "passport", "number": "GONE",
                                       "expiry_date": "2020-01-01"})
    assert "id_document.number" not in _values(agency_a, membership_a)


def test_the_students_choice_wins(agency_a, membership_a):
    chosen = _document(agency_a, membership_a, {"document_type": "passport", "number": "MINE",
                                                "expiry_date": "2028-01-01"})
    _document(agency_a, membership_a, {"document_type": "passport", "number": "OTHER",
                                       "expiry_date": "2031-01-01"})
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.filter(document=chosen).update(primary_chosen_at=timezone.now())
    assert _values(agency_a, membership_a)["id_document.number"] == "MINE"


def test_doubtful_keys_of_a_document_are_not_served(agency_a, membership_a):
    document = _document(agency_a, membership_a, {"document_type": "passport", "number": "N1",
                                                  "expiry_date": "2031-01-01"})
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a, category="ID_DOCUMENT", payload={"issue_date": "2021-01-01"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
            created_by=membership_a,
        )
    assert "id_document.issue_date" not in _values(agency_a, membership_a)
```

- [ ] **Step 2: Run to see them fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_fact_writer.py tests/portals/test_profile_id_documents.py`
Expected: FAIL (ImportError on `fact_writer`).

- [ ] **Step 3: `record_event` gains `actor_kind`.** In `apps/documents/audit.py`, change the
  signature to
  `def record_event(*, actor: Membership | None, event: str, object_id: UUID, actor_kind: str = "") -> AuditEvent | None:`
  and the create call to
  `AuditEvent.objects.create(actor=actor, actor_kind=actor_kind, event=event, object_id=object_id)`.
  Add to the docstring: "`actor_kind="AGENT"` with `actor=None` is a machine write no person made
  (a passport read, spec 2026-10-12 §6.2)."

- [ ] **Step 4: Write `apps/documents/fact_writer.py`**

```python
"""A reading's values into the fact ledger (spec 2026-10-12 §6.2), and the
student's own correction of one. Called inside the caller's tenant transaction.

Precedence per key: the student's own entry, then the newest proven read, then an
older one. A read never overwrites a student entry and never silently changes a
name, a citizenship or a date of birth: those differences wait as a detail to
check. A proven value is confirmed by no click -- the audit trail says AGENT --
while `confirmed_by` names the student whose own document it is, the precedent
evidence/facts.write_publication_fact set."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from django.utils import timezone

from apps.concierge.models import DocumentVersion
from apps.tenancy.models import Membership

from .audit import record_event
from .confirmation import FactNotFound
from .hygiene import normalize_text
from .id_reading import ReadValue
from .models import DocumentReading, VerifiedFact
from .verification import payload_keys, unsuperseded_facts

PROTECTED_KEYS = frozenset(
    {"identity.given_names", "identity.surname", "identity.citizenship", "identity.date_of_birth"}
)
_SEXES = frozenset({"M", "F", "X"})
_MAX_VALUE = 200


def _split(key: str) -> tuple[str, str]:
    prefix, _, field = key.partition(".")
    return prefix.upper(), field


def _same(a: object, b: object) -> bool:
    return normalize_text(str(a)).casefold() == normalize_text(str(b)).casefold()


def _tips(student: Membership, category: str, field: str) -> list[VerifiedFact]:
    return [f for f in unsuperseded_facts(student).filter(category=category,
                                                          payload__has_key=field)]


def write_facts(reading: DocumentReading) -> None:
    student = reading.student
    ref = f"document:{reading.document_id}"
    values = [ReadValue.from_dict(v) for v in reading.values]
    written: list[ReadValue] = []
    for value in values:
        if value.key.startswith("id_document."):
            written.append(value)
        else:
            written.append(_write_person_value(student, ref, value))
    _write_id_document(student, ref, [v for v in written if v.key.startswith("id_document.")])
    reading.values = [v.as_dict() for v in written]
    reading.facts_written = True
    reading.save(update_fields=["values", "facts_written", "updated_at"])


def _write_person_value(student: Membership, ref: str, value: ReadValue) -> ReadValue:
    category, field = _split(value.key)
    tips = _tips(student, category, field)
    confirmed = [f for f in tips if f.confirmed_at is not None]
    current = confirmed[-1] if confirmed else None
    if current is not None and _same(current.payload[field], value.value):
        return value
    if any(f.confirmed_at is None and _same(f.payload[field], value.value) for f in tips):
        return value  # the same doubtful value already waits
    proven, why = value.proven, value.why
    if current is not None and proven:
        if current.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT:
            proven, why = False, "student_entry_differs"
        elif value.key in PROTECTED_KEYS:
            proven, why = False, "document_differs"
    supersedes = (
        current
        if proven and current is not None and len(current.payload) == 1
        and current.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
        else None
    )
    fact = _create(student, category, {field: value.value}, ref, proven, supersedes)
    if proven:
        record_event(actor=None, actor_kind="AGENT", event="fact.read_from_document",
                     object_id=fact.id)
    return ReadValue(value.key, value.value, value.snippet, proven, why)


def _write_id_document(student: Membership, ref: str, values: list[ReadValue]) -> None:
    if not values:
        return
    category = VerifiedFact.Category.ID_DOCUMENT
    proven = {_split(v.key)[1]: v.value for v in values if v.proven}
    existing = (
        unsuperseded_facts(student)
        .filter(category=category, source_ref=ref, confirmed_at__isnull=False)
        .last()
    )
    if proven and (existing is None or existing.payload != proven):
        fact = _create(student, category, proven, ref, True, existing)
        record_event(actor=None, actor_kind="AGENT", event="fact.read_from_document",
                     object_id=fact.id)
        expiry = proven.get("expiry_date")
        if expiry:
            DocumentVersion.objects.filter(
                id=ref.removeprefix("document:"), expires_on__isnull=True
            ).update(expires_on=expiry)
    waiting = unsuperseded_facts(student).filter(category=category, source_ref=ref,
                                                 confirmed_at__isnull=True)
    for value in values:
        if value.proven:
            continue
        field = _split(value.key)[1]
        if any(f.payload.get(field) == value.value for f in waiting):
            continue
        _create(student, category, {field: value.value}, ref, False, None)


def _create(student, category, payload, ref, proven, supersedes) -> VerifiedFact:
    now = timezone.now()
    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref=ref,
        confirmed_by=student if proven else None,
        confirmed_at=now if proven else None,
        supersedes=supersedes,
        created_by=student,
    )


def _valid(field: str, value: str) -> str:
    value = " ".join(value.split())
    if not value or len(value) > _MAX_VALUE:
        raise ValueError("invalid_value")
    if field.endswith("date") or field == "date_of_birth":
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise ValueError("invalid_value") from None
    if field == "sex":
        if value.upper() not in _SEXES:
            raise ValueError("invalid_value")
        return value.upper()
    return value


def correct_fact(*, student: Membership, fact_id: UUID, key: str, value: str) -> VerifiedFact:
    """The student's own value for one key of a document-read fact: a superseding
    STUDENT_STATEMENT row, confirmed by them, keeping the document's source_ref so
    an ID document's keys stay together."""
    fact = (
        unsuperseded_facts(student)
        .filter(id=fact_id, source_ref__startswith="document:")
        .first()
    )
    if fact is None or key not in fact.payload or key not in payload_keys(fact.category):
        raise FactNotFound("not a document-read fact of this student")
    payload = {**fact.payload, key: _valid(key, value)}
    corrected = VerifiedFact.objects.create(
        student=student,
        category=fact.category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref=fact.source_ref,
        confirmed_by=student,
        confirmed_at=timezone.now(),
        supersedes=fact,
        created_by=student,
    )
    record_event(actor=student, event="fact.corrected", object_id=corrected.id)
    return corrected
```

- [ ] **Step 5: `verified_values` picks one ID document.** In `apps/portals/profile.py`:
  - In the `for fact in facts:` loop, skip `ID_DOCUMENT` rows:
    `if fact.category == VerifiedFact.Category.ID_DOCUMENT: continue`.
  - Before `return values`, add `values.update(_id_document_values(student, facts))`.
  - Define:
    ```python
    def _id_document_values(student: Membership, facts: list[VerifiedFact]) -> dict[str, str]:
        """Spec 2026-10-12 §4.2: one document's keys, never a mix of two. The student's
        chosen one if it is valid, else the valid passport with the latest expiry, else
        the valid document of any type with the latest expiry. An expired document is
        never served: the portal box stays a hint."""
        from apps.documents.models import DocumentReading

        documents: dict[str, dict[str, str]] = {}
        for fact in facts:
            if fact.category == VerifiedFact.Category.ID_DOCUMENT:
                for key, value in fact.payload.items():
                    if isinstance(value, str) and value.strip():
                        documents.setdefault(fact.source_ref, {})[key] = value
        today = timezone.localdate().isoformat()
        valid = {ref: doc for ref, doc in documents.items() if doc.get("expiry_date", "") >= today}
        if not valid:
            return {}
        chosen = (
            DocumentReading.objects.filter(student=student, primary_chosen_at__isnull=False)
            .order_by("-primary_chosen_at")
            .values_list("document_id", flat=True)
            .first()
        )
        if chosen is not None and f"document:{chosen}" in valid:
            picked = valid[f"document:{chosen}"]
        else:
            passports = [d for d in valid.values() if d.get("document_type") == "passport"]
            picked = max(passports or list(valid.values()), key=lambda d: d.get("expiry_date", ""))
        return {f"id_document.{key}": value for key, value in picked.items()}
    ```
    Import `timezone` from `django.utils`. This replaces the generic loop's last-row-wins for
    ID_DOCUMENT only.

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_fact_writer.py tests/portals/test_profile_id_documents.py tests/portals tests/documents/test_confirmation.py tests/documents/test_audit_events.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add apps/documents/fact_writer.py apps/documents/audit.py apps/portals/profile.py tests/documents/test_fact_writer.py tests/portals/test_profile_id_documents.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(documents): a reading's values into the ledger, the student's correction, one ID document per portal"
```

---

### Task 7: The reading pipeline

**Files:**
- Create: `apps/documents/document_reading.py`
- Modify: `config/settings/base.py`, `apps/documents/document_queue.py`, `apps/documents/document_worker.py`,
  `apps/documents/transcript_pages.py` (`_check_ceiling`),
  `apps/documents/management/commands/resume_transcript_readings.py`
- Test: `tests/documents/test_document_reading.py`

**Interfaces:**
- Consumes: `analyze_id_document` (Task 3), `read_id`, `NotRead` (Task 4), `DocumentReading`
  (Task 5), `write_facts` (Task 6).
- Produces:
  - `READER_VERSION = {"PASSPORT": "id-1"}`, `READ_KINDS = frozenset(READER_VERSION)` (plan 2
    adds kinds);
  - `enabled() -> bool`;
  - `queue_reading(tenant_id: UUID, document_id: UUID) -> bool` (True when a QUEUED row was
    created);
  - `process_document(tenant_id, document_id, *, store=None, analyze=analyze_id_document) -> None`;
  - `delay(tenant_id, reading_id, *, reason: str) -> None`; `azure_pages_today() -> int` (called
    inside a tenant transaction);
  - a `DocumentWorkMessage` action `"read_document"` with field `document_id: UUID | None`.

- [ ] **Step 1: Add the settings** to `config/settings/base.py`, after `TRANSCRIPT_STUCK_AFTER_MINUTES`:

```python
#: Spec 2026-10-12: read a passport, ID card, diploma or certificate into facts.
#: Off until the launch gates in spec §9 are met; Azure also needs
#: TRANSCRIPT_AZURE_ENABLED, which now gates both readers.
FACT_READING_ENABLED = os.getenv("FACT_READING_ENABLED", "") == "1"
#: Pages sent to Azure per document, from the first: billing stops here.
FACT_READING_PAGE_CAPS = {"PASSPORT": 4, "DIPLOMA": 4, "LANGUAGE_CERTIFICATE": 2}
#: A value Azure reads with no strip to check it is proven only at or above this,
#: for the field and for every word in it (spec §5.2.3).
FACT_READING_CONFIDENCE = 0.95
#: Readings per student per hour; our own re-reads never count.
FACT_READING_HOURLY = 20
```

Also add `FACT_READING_ENABLED`'s comment line to the `TRANSCRIPT_TENANT_DAILY_AZURE_PAGES`
comment: "Counts both readers' Azure pages: transcripts and document fact reading."

- [ ] **Step 2: Write the failing tests**

```python
# tests/documents/test_document_reading.py
"""Spec 2026-10-12 §5.1, §6.1, §6.4: the worker path for a passport."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents import document_reading
from apps.documents.models import DocumentReading, VerifiedFact
from apps.documents.ocr_errors import OcrUnavailable
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.documents.id_fixtures import passport

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _on(settings):
    settings.FACT_READING_ENABLED = True
    settings.TRANSCRIPT_AZURE_ENABLED = True


class _Store:
    def __init__(self, body=b"%PDF-1.7 passport"):
        self.body = body

    def get(self, key):
        return self.body


def _passport_upload(agency, student):
    document = register(agency.id, student.id, kind="PASSPORT")
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        DocumentVersion.objects.filter(id=document.id).update(
            state="AVAILABLE", promoted_key=f"tenants/{agency.id}/x", content_type="application/pdf"
        )
    return document


def _run(agency, document, analyze, store=None):
    document_reading.process_document(agency.id, document.id, store=store or _Store(),
                                      analyze=analyze)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return DocumentReading.objects.get(document_id=document.id)


def test_a_passport_is_read_once_into_facts(agency_a, membership_a):
    document = _passport_upload(agency_a, membership_a)
    calls = []

    def analyze(content, *, pages):
        calls.append(pages)
        return passport()

    reading = _run(agency_a, document, analyze)
    assert reading.state == "READ" and reading.facts_written and calls == ["1-4"]
    assert reading.azure_pages == 1
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.filter(student=membership_a, category="ID_DOCUMENT").exists()
    _run(agency_a, document, analyze)  # a redelivery
    assert calls == ["1-4"]


def test_the_same_file_uploaded_again_is_never_read_again(agency_a, membership_a):
    calls = []

    def analyze(content, *, pages):
        calls.append(pages)
        return passport()

    _run(agency_a, _passport_upload(agency_a, membership_a), analyze)
    second = _run(agency_a, _passport_upload(agency_a, membership_a), analyze)
    assert len(calls) == 1 and second.state == "READ" and second.values


def test_azure_down_delays_and_the_sweep_retries(agency_a, membership_a):
    document = _passport_upload(agency_a, membership_a)

    def down(content, *, pages):
        raise OcrUnavailable("down")

    reading = _run(agency_a, document, down)
    assert reading.state == "DELAYED" and reading.attempts == 1
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.filter(id=reading.id).update(
            next_attempt_at=timezone.now() - timedelta(minutes=1)
        )
    seen = []
    document_reading_process = document_reading.process_document

    def spy(tenant_id, document_id, **kwargs):
        seen.append(document_id)

    document_reading.process_document = spy
    try:
        call_command("resume_transcript_readings", stdout=StringIO())
    finally:
        document_reading.process_document = document_reading_process
    assert seen == [document.id]


def test_known_names_are_whole_names_never_a_bare_surname(agency_a, membership_a):
    """Spec §5.2.4 as ruled during the build: a one-word value reads as a given name,
    so an earlier passport's surname alone must never be a known name."""
    from django.utils import timezone

    first = _passport_upload(agency_a, membership_a)
    membership_a.user.first_name, membership_a.user.last_name = "Nərmin", "Əliyeva"
    membership_a.user.save()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        for key, value in (("given_names", "NƏRMIN"), ("surname", "ƏLIYEVA")):
            VerifiedFact.objects.create(
                student=membership_a, category="IDENTITY", payload={key: value},
                source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{first.id}",
                confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a,
            )
        second = _passport_upload(agency_a, membership_a)
        reading = DocumentReading.objects.create(
            student=membership_a, document=second, kind="PASSPORT", reader_version="id-1",
        )
        names = document_reading._known_names(reading)
    assert "Nərmin Əliyeva" in names and "NƏRMIN ƏLIYEVA" in names
    assert "ƏLIYEVA" not in names


def test_not_an_id_document_fails_with_its_code(agency_a, membership_a):
    from tests.documents.id_fixtures import result

    reading = _run(agency_a, _passport_upload(agency_a, membership_a),
                   lambda content, *, pages: result({}, doc_type="invoice"))
    assert (reading.state, reading.failure) == ("FAILED", "not_an_id_document")


def test_the_shared_ceiling_delays_without_calling_azure(agency_a, membership_a, settings):
    settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES = 2
    calls = []

    def analyze(content, *, pages):
        calls.append(pages)
        return passport()

    reading = _run(agency_a, _passport_upload(agency_a, membership_a), analyze)
    assert reading.state == "DELAYED" and calls == []


def test_off_means_nothing_is_read_or_queued(agency_a, membership_a, settings):
    settings.FACT_READING_ENABLED = False
    document = _passport_upload(agency_a, membership_a)
    assert not document_reading.queue_reading(agency_a.id, document.id)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert not DocumentReading.objects.exists()


def test_a_clean_scan_of_a_passport_reaches_the_reader(agency_a, membership_a, monkeypatch):
    from apps.documents import document_worker
    from apps.documents.document_queue import ScanResultEvent

    reached = []
    monkeypatch.setattr(document_reading, "process_document",
                        lambda tenant_id, document_id, **k: reached.append(document_id))
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    document_worker.handle_scan_result(ScanResultEvent(
        object_key=document.object_key, scan_result="NO_THREATS_FOUND",
        bucket_name="evidence", version_id="v1"))
    assert reached == [document.id]
```

The conftest autouse fixture `_uploads_pass_the_upload_check` already stubs
`_check_and_promote`, so the scan test reaches the dispatch. The ceiling test works because the
check counts the **cap** (4 pages that may be billed) against what is left (2).

- [ ] **Step 3: Write `apps/documents/document_reading.py`**

```python
"""Reading a student's own document into facts, on the document worker (spec
2026-10-12 §5, §6). Every slow step -- the file download, Azure -- runs outside a
transaction; each write is a short one under the tenant's RLS scope, the pattern
transcript_pages set. A reading is one row per (document, reader version): a
redelivered scan event, the resume sweep and the co-pilot's hook all land on the
same row, and the lease in _claim keeps two of them from reading it at once."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.concierge.documents import DocumentUnavailable, ReadableObjectStore, open_document
from apps.concierge.models import DocumentVersion
from apps.ratelimit import rate_limited
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.middleware import deletion_lock_target

from .azure_layout import AzureIdResult, analyze_id_document
from .fact_writer import write_facts
from .id_reading import NotRead, ReadValue, read_id
from .models import DocumentReading, TranscriptPage, VerifiedFact
from .ocr_errors import OcrUnavailable
from .verification import unsuperseded_facts

logger = logging.getLogger(__name__)

State = DocumentReading.State
READER_VERSION = {"PASSPORT": "id-1"}
READ_KINDS = frozenset(READER_VERSION)
MAX_UPLOAD_BYTES = 10_000_000
MAX_ATTEMPTS = 12
_FIRST_DELAY = timedelta(minutes=5)
_LONGEST_DELAY = timedelta(hours=6)
_LEASE = timedelta(minutes=10)


class _Failed(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Wait(Exception):
    """Not now: the ceiling, the student's hourly limit. Retried by the sweep."""


def enabled() -> bool:
    return settings.FACT_READING_ENABLED and settings.TRANSCRIPT_AZURE_ENABLED


def azure_pages_today() -> int:
    """Azure pages this tenant was billed today, by either reader. Inside a tenant
    transaction: both tables are FORCE RLS."""
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    transcripts = TranscriptPage.objects.filter(source="azure", created_at__gte=midnight).count()
    documents = DocumentReading.objects.filter(updated_at__gte=midnight).aggregate(
        pages=Sum("azure_pages")
    )["pages"] or 0
    return transcripts + documents


def queue_reading(tenant_id: UUID, document_id: UUID) -> bool:
    """The QUEUED row for an AVAILABLE upload of a kind we read. True when this
    call created it. Idempotent: the unique (document, reader_version) is the lock."""
    if not enabled():
        return False
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        document = DocumentVersion.objects.filter(
            id=document_id, state="AVAILABLE", kind__in=READ_KINDS
        ).first()
        if document is None:
            return False
        _, created = DocumentReading.objects.get_or_create(
            document=document,
            reader_version=READER_VERSION[document.kind],
            defaults={"student_id": document.student_id, "kind": document.kind},
        )
        return created


def process_document(
    tenant_id: UUID,
    document_id: UUID,
    *,
    store: ReadableObjectStore | None = None,
    analyze: Callable[..., AzureIdResult] = analyze_id_document,
) -> None:
    if not enabled():
        return
    queue_reading(tenant_id, document_id)
    claimed = _claim(tenant_id, document_id)
    if claimed is None:
        return
    reading, document = claimed
    try:
        values, digest, pages = _read(tenant_id, reading, document, store=store, analyze=analyze)
    except _Failed as failed:
        _fail(tenant_id, reading.id, failed.code)
        return
    except DocumentUnavailable:
        _fail(tenant_id, reading.id, "document_unavailable")
        return
    except (_Wait, OcrUnavailable, ClientError, BotoCoreError) as error:
        delay(tenant_id, reading.id, reason=type(error).__name__)
        return
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        locked = DocumentReading.objects.select_for_update().select_related("student").get(
            id=reading.id
        )
        if locked.state == State.READ:
            return
        locked.values = [v.as_dict() for v in values]
        locked.file_sha256, locked.azure_pages = digest, pages
        locked.state, locked.failure, locked.next_attempt_at = State.READ, "", None
        locked.save(update_fields=["values", "file_sha256", "azure_pages", "state", "failure",
                                   "next_attempt_at", "updated_at"])
        write_facts(locked)


def _claim(tenant_id: UUID, document_id: UUID) -> tuple[DocumentReading, DocumentVersion] | None:
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        reading = (
            DocumentReading.objects.select_for_update(of=("self",))
            .select_related("student", "document")
            .filter(document_id=document_id)
            .order_by("-created_at")
            .first()
        )
        if reading is None or reading.state in (State.READ, State.FAILED):
            return None
        student = reading.student
        if not student.active or deletion_lock_target(student) is not None:
            reading.state, reading.failure = State.FAILED, "erasure_requested"
            reading.save(update_fields=["state", "failure", "updated_at"])
            return None
        now = timezone.now()
        if reading.next_attempt_at is not None and reading.next_attempt_at > now:
            return None
        reading.state, reading.next_attempt_at = State.READING, now + _LEASE
        reading.save(update_fields=["state", "next_attempt_at", "updated_at"])
        return reading, reading.document


def _read(
    tenant_id: UUID,
    reading: DocumentReading,
    document: DocumentVersion,
    *,
    store: ReadableObjectStore | None,
    analyze: Callable[..., AzureIdResult],
) -> tuple[list[ReadValue], str, int]:
    content = open_document(document, store=store)
    if len(content) > MAX_UPLOAD_BYTES:
        raise _Failed("unsupported_file")
    digest = hashlib.sha256(content).hexdigest()
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        twin = (
            DocumentReading.objects.filter(
                student_id=reading.student_id, file_sha256=digest, state=State.READ,
                reader_version=reading.reader_version,
            )
            .exclude(id=reading.id)
            .first()
        )
        if twin is not None:  # the same bytes again: nothing read, nothing billed
            return [ReadValue.from_dict(v) for v in twin.values], digest, 0
        cap = settings.FACT_READING_PAGE_CAPS[reading.kind]
        if azure_pages_today() + cap > settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES:
            raise _Wait()
        known_names = _known_names(reading)
    if rate_limited("fact-reading", reading.student_id, limit=settings.FACT_READING_HOURLY,
                    window_seconds=3600):
        raise _Wait()
    result = analyze(content, pages=f"1-{cap}")
    try:
        values = read_id(result, known_names=known_names,
                         threshold=settings.FACT_READING_CONFIDENCE, today=timezone.localdate())
    except NotRead as not_read:
        raise _Failed(not_read.code) from None
    return values, digest, len(result.pages)


def _known_names(reading: DocumentReading) -> list[str]:
    """Whole names we already hold for the student, to catch someone else's passport
    (spec §5.2.4): the account holder's own name, the CV's full name, and each earlier
    document's given names and surname joined. Never a bare surname -- the ownership
    check reads a one-word value as a given name, so ["ŞAHIN"] would vouch for any
    ŞAHIN. Never this document's own. Called inside a tenant transaction."""
    student = reading.student
    names = [student.user.get_full_name()]
    ref = f"document:{reading.document_id}"
    parts: dict[str, dict[str, str]] = {}
    for fact in unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.IDENTITY, confirmed_at__isnull=False
    ).exclude(source_ref=ref):
        full = fact.payload.get("full_name")
        if isinstance(full, str) and full.strip():
            names.append(full)
        if fact.source_ref.startswith("document:"):
            for key in ("given_names", "surname"):
                value = fact.payload.get(key)
                if isinstance(value, str) and value.strip():
                    parts.setdefault(fact.source_ref, {})[key] = value
    for document in parts.values():
        if document.get("given_names") and document.get("surname"):
            names.append(f"{document['given_names']} {document['surname']}")
    return [name for name in names if name.strip()]


def delay(tenant_id: UUID, reading_id: UUID, *, reason: str) -> None:
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        reading = DocumentReading.objects.select_for_update().filter(id=reading_id).first()
        if reading is None or reading.state in (State.READ, State.FAILED):
            return
        reading.attempts += 1
        if reading.attempts >= MAX_ATTEMPTS:
            reading.state, reading.failure, reading.next_attempt_at = (
                State.FAILED, "reader_unavailable", None)
        else:
            reading.state = State.DELAYED
            reading.next_attempt_at = timezone.now() + min(
                _FIRST_DELAY * 2 ** (reading.attempts - 1), _LONGEST_DELAY
            )
        reading.save(update_fields=["state", "failure", "attempts", "next_attempt_at",
                                    "updated_at"])
    logger.warning("DocumentReadingDelayed reading=%s attempts=%s reason=%s",
                   reading_id, reading.attempts, reason)


def _fail(tenant_id: UUID, reading_id: UUID, code: str) -> None:
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        DocumentReading.objects.filter(id=reading_id).update(
            state=State.FAILED, failure=code, next_attempt_at=None, updated_at=timezone.now()
        )
    logger.warning("DocumentReadingFailed reading=%s failure=%s", reading_id, code)
```

The twin check and the ceiling read must happen inside a tenant transaction (FORCE RLS);
`rate_limited` and Azure are outside. Note that `values` copied from a twin are re-checked by
`write_facts` against this student's current ledger, so a twin never bypasses precedence.

- [ ] **Step 4: Share the ceiling.** In `apps/documents/transcript_pages.py::_check_ceiling`,
  replace the `used = TranscriptPage.objects.filter(...).count()` line with
  `used = azure_pages_today()`, imported locally inside the function
  (`from .document_reading import azure_pages_today`) to avoid an import cycle. Keep the
  ponytail comment. Remove the now-unused `midnight` line if nothing else uses it.

- [ ] **Step 5: The queue action and the worker dispatch.**
  - `apps/documents/document_queue.py`: `action: Literal["generate", "render", "capture_requirements", "read_document"]`,
    and add `document_id: UUID | None = None` with the comment
    `#: read_document only: the DocumentVersion to read into facts (spec 2026-10-12 §7.1).`
  - `apps/documents/document_worker.py::handle_document_work`: add the branch
    ```python
        elif message.action == "read_document":
            if message.document_id is None:
                raise ValueError("read_document message carries no document_id")
            document_reading.process_document(message.tenant_id, message.document_id)
    ```
    before the final `else`.
  - In `handle_scan_result`, directly after
    `if document.state == "CHECKING" and not _check_and_promote(tenant_id, document): return`,
    add:
    ```python
        if document.kind in document_reading.READ_KINDS:
            # A passport (plan 2: a diploma, a certificate) is read into facts in
            # the background (spec 2026-10-12 §5); nothing else waits on it.
            document_reading.process_document(tenant_id, document.id)
            return
    ```
    Also update the comment "A passport, diploma, certificate or letter is stored for the student to
    attach (dashboard spec §6). Nothing reads its contents." to "A letter or other upload is stored
    for the student to attach (dashboard spec §6). Nothing reads its contents."
  - Import `document_reading` as a module (`from . import document_reading`), so the tests'
    monkeypatch reaches it.

- [ ] **Step 6: The resume sweep.** In `resume_transcript_readings.py`:
  - after the transcript loop inside `for agency in Agency.objects.all():`, add
    ```python
                for document_id, reading_id in _due_readings(agency.id):
                    try:
                        document_reading.process_document(agency.id, document_id)
                    except Exception as error:  # one reading must not strand the batch
                        logger.warning("DocumentReadingResumeFailed reading=%s error=%s",
                                       reading_id, type(error).__name__)
                        document_reading.delay(agency.id, reading_id, reason=type(error).__name__)
    ```
  - and define
    ```python
    def _due_readings(tenant_id: UUID) -> list[tuple[UUID, UUID]]:
        now = timezone.now()
        stuck = now - timedelta(minutes=settings.TRANSCRIPT_STUCK_AFTER_MINUTES)
        with tenant_scope(tenant_id), tenant_transaction(tenant_id):
            return list(
                DocumentReading.objects.filter(
                    Q(state="DELAYED", next_attempt_at__lte=now)
                    | Q(state="READING", updated_at__lt=stuck)
                    | Q(state="QUEUED", updated_at__lt=stuck)
                )
                .order_by("updated_at")
                .values_list("document_id", "id")[:_BATCH]
            )
    ```
  - Import `from apps.documents import document_reading` and `DocumentReading`. Extend the module
    docstring's first line to "Resume transcript readings and document fact readings that are
    waiting or were lost."
  - A QUEUED row the hook created (Task 8) is picked up here when no message reached the worker.

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_document_reading.py tests/documents/test_document_worker.py tests/documents/test_resume_transcript_readings.py tests/documents/test_document_queue.py`
Expected: PASS. Then run all of `tests/documents`.

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add -A apps/documents config/settings/base.py tests/documents/test_document_reading.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(documents): read an uploaded passport into facts on the document worker"
```

---

### Task 8: The co-pilot hook queues unread passports

**Files:**
- Modify: `apps/portals/fact_reading.py`
- Test: `tests/portals/test_fact_reading_hook.py`

**Interfaces:**
- Consumes: `document_reading.queue_reading`, `enabled`, `READ_KINDS` (Task 7);
  `DocumentWorkMessage(action="read_document")` (Task 7).
- Produces: `request_fact_reading(application, fields)` (signature unchanged) and
  `KIND_FOR_PREFIX: tuple[tuple[str, str], ...]`. Plan 2 extends the prefix table.

- [ ] **Step 1: Write the failing tests**

```python
# tests/portals/test_fact_reading_hook.py
"""Spec 2026-10-12 §7.1: a portal asking for a field queues the unread upload
that can supply it, and never raises into mint_packet."""

import pytest

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents.models import DocumentReading
from apps.portals import fact_reading
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _on(settings):
    settings.FACT_READING_ENABLED = True
    settings.TRANSCRIPT_AZURE_ENABLED = True


def _application(agency, student):
    return type("App", (), {"tenant_id": agency.id, "student_id": student.id,
                            "student": student, "id": None})()


def _available(agency, student, kind="PASSPORT"):
    document = register(agency.id, student.id, kind=kind)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        DocumentVersion.objects.filter(id=document.id).update(state="AVAILABLE")
    return document


def test_an_unread_passport_is_queued_once(agency_a, membership_a, monkeypatch):
    sent = []
    monkeypatch.setattr(fact_reading, "enqueue_document_work",
                        lambda message, **k: sent.append(message))
    document = _available(agency_a, membership_a)
    app = _application(agency_a, membership_a)
    fact_reading.request_fact_reading(app, ["identity.date_of_birth", "id_document.number"])
    fact_reading.request_fact_reading(app, ["identity.date_of_birth"])
    assert [m.document_id for m in sent] == [document.id]
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert DocumentReading.objects.get(document=document).state == "QUEUED"


def test_fields_no_document_supplies_queue_nothing(agency_a, membership_a, monkeypatch):
    sent = []
    monkeypatch.setattr(fact_reading, "enqueue_document_work",
                        lambda message, **k: sent.append(message))
    _available(agency_a, membership_a)
    fact_reading.request_fact_reading(_application(agency_a, membership_a), ["experience.title"])
    assert sent == []


def test_a_failure_never_reaches_the_packet(agency_a, membership_a, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(fact_reading, "enqueue_document_work", boom)
    _available(agency_a, membership_a)
    fact_reading.request_fact_reading(_application(agency_a, membership_a),
                                      ["identity.date_of_birth"])  # no raise
```

- [ ] **Step 2: Run to see them fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/portals/test_fact_reading_hook.py`
Expected: FAIL (`enqueue_document_work` not an attribute of `fact_reading`).

- [ ] **Step 3: Rewrite `apps/portals/fact_reading.py`**, keeping the module docstring's first
  paragraph and replacing "That reader is a separate plan. This hook is where it attaches..." with
  a description of what it does now:

```python
"""Facts a portal asked for that the student does not hold yet (owner, 2026-10-09).

A fact-less field is the student's to type -- the red "You fill this" box -- and
never blocks the application or calls a counsellor. Such fields fill themselves
once the student's own upload is read (spec 2026-10-12): the document worker reads
every passport when it is uploaded, and this hook catches the uploads made before
that existed. It only queues: it runs inside mint_packet, in the web process, and
never calls Azure, never raises and never blocks.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from django.conf import settings

from apps.concierge.models import DocumentVersion
from apps.documents import document_reading
from apps.documents.document_queue import DocumentWorkMessage, enqueue_document_work
from apps.documents.models import DocumentReading
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .models import Application

logger = logging.getLogger(__name__)

#: Which upload kind can supply a field (spec §7.1). Plan 2 adds the diploma and
#: the language certificate.
KIND_FOR_PREFIX: tuple[tuple[str, str], ...] = (
    ("identity.", "PASSPORT"),
    ("id_document.", "PASSPORT"),
)
_PER_PACKET = 5


def request_fact_reading(application: Application, fields: Sequence[str]) -> None:
    """Queue a reading of each unread upload that could supply one of `fields`."""
    try:
        _request(application, fields)
    except Exception as error:  # never into mint_packet
        logger.warning("FactReadingNotQueued application=%s error=%s",
                       application.id, type(error).__name__)


def _request(application: Application, fields: Sequence[str]) -> None:
    if not document_reading.enabled():
        return
    kinds = {kind for field in fields for prefix, kind in KIND_FOR_PREFIX
             if field.startswith(prefix)} & document_reading.READ_KINDS
    if not kinds:
        return
    with tenant_scope(application.tenant_id), tenant_transaction(application.tenant_id):
        unread = list(
            DocumentVersion.objects.filter(
                student_id=application.student_id, kind__in=kinds, state="AVAILABLE"
            )
            .exclude(id__in=DocumentReading.objects.values("document_id"))
            .values_list("id", "kind")[:_PER_PACKET]
        )
    for document_id, kind in unread:
        if document_reading.queue_reading(application.tenant_id, document_id):
            enqueue_document_work(
                DocumentWorkMessage(
                    action="read_document", kind=kind, tenant_id=application.tenant_id,
                    student_id=application.student_id, document_id=document_id,
                ),
                queue_url=settings.DOCUMENT_QUEUE_URL,
            )
```

`DocumentWorkMessage.kind` is `str` with no validation in the queue model. Confirm that by
reading the model; if a validator rejects non-draft kinds, add `"PASSPORT"` and the plan-2 kinds
to it.

- [ ] **Step 4: Run the hook tests and the packet tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/portals/test_fact_reading_hook.py tests/portals/test_packet.py`
Expected: PASS. `test_packet.py` monkeypatches `packets.request_fact_reading`, so its assertions
hold.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add apps/portals/fact_reading.py tests/portals/test_fact_reading_hook.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(portals): a portal asking for a passport field queues the unread passport"
```

---

### Task 9: The dashboard — "Your details", "Details to check", problems, the passport choice

**Files:**
- Create: `apps/documents/fact_labels.py`
- Modify: `apps/documents/views.py` (`page_context`, two POST views), `apps/documents/urls.py`,
  `templates/student/_documents.html`
- Test: `tests/documents/test_documents_page_details.py`

**Interfaces:**
- Consumes: `correct_fact` (Task 6), `DocumentReading` (Task 5), the existing
  `/api/documents/facts/confirm` (one id = "Use").
- Produces:
  - `FIELD_LABELS: dict[str, str]`, `KIND_LABELS: dict[str, str]`,
    `PROBLEM_TEXT: dict[str, str]`, `WHY_TEXT: dict[str, str]`;
  - views `correct_fact_view` (`student-fact-correct`) and `choose_id_document`
    (`student-id-document-primary`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_documents_page_details.py
"""Spec 2026-10-12 §3: what the dashboard shows after a passport read."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.models import DocumentReading, VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _fact(student, document, payload, confirmed=True, category="IDENTITY"):
    return VerifiedFact.objects.create(
        student=student, category=category, payload=payload,
        source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None, created_by=student,
    )


class _Page:
    """The student's own browser, as tests/documents/test_documents_page.py drives it."""

    def __init__(self, client, host):
        self.client, self.host = client, host

    def get(self, path):
        return self.client.get(path, HTTP_HOST=self.host)

    def post(self, path, data=None):
        return self.client.post(path, data or {}, HTTP_HOST=self.host)


@pytest.fixture
def page(client, domain_a, user_a, membership_a):
    client.force_login(user_a)
    return _Page(client, domain_a.host)


def test_details_and_details_to_check_are_shown_apart_from_cv_facts(page, agency_a,
                                                                     membership_a):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _fact(membership_a, document, {"date_of_birth": "1998-03-14"})
        doubtful = _fact(membership_a, document, {"place_of_birth": "BAKI"}, confirmed=False)
        DocumentReading.objects.create(
            student=membership_a, document=document, kind="PASSPORT", reader_version="id-1",
            state="READ", values=[{"key": "identity.place_of_birth", "value": "BAKI",
                                   "snippet": "PLACE OF BIRTH BAKI", "proven": False,
                                   "why": "low_confidence"}],
        )
    html = page.get(reverse("student-documents")).content.decode()
    assert "Your details" in html and "Date of birth" in html and "1998-03-14" in html
    assert "1 detail to check" in html and "PLACE OF BIRTH BAKI" in html
    assert str(doubtful.id) in html  # the Use button's body
    cv_section = html.split('id="facts"')[1].split("</section>")[0]
    assert "BAKI" not in cv_section  # never in the CV's confirm-all list


def test_a_failed_read_and_a_foreign_passport_say_so(page, agency_a, membership_a):
    failed = register(agency_a.id, membership_a.id, kind="PASSPORT")
    foreign = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.create(student=membership_a, document=failed, kind="PASSPORT",
                                       reader_version="id-1", state="FAILED",
                                       failure="unreadable")
        DocumentReading.objects.create(
            student=membership_a, document=foreign, kind="PASSPORT", reader_version="id-1",
            state="READ", values=[{"key": "identity.surname", "value": "X", "snippet": "X",
                                   "proven": False, "why": "owner_mismatch"}],
        )
    html = page.get(reverse("student-documents")).content.decode()
    assert "We couldn't read this — upload a clearer photo" in html
    assert "This passport doesn't look like yours" in html


def test_a_correction_posts_and_redirects(page, agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        fact = _fact(membership_a, document, {"place_of_birth": "BAKI"}, confirmed=False)
    response = page.post(reverse("student-fact-correct", args=[fact.id]),
                         {"key": "place_of_birth", "value": "Baku"})
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.get(supersedes=fact).payload == {"place_of_birth": "Baku"}


def test_the_passport_question_appears_only_for_two_valid_passports(page, agency_a,
                                                                    membership_a):
    first = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _fact(membership_a, first, {"document_type": "passport", "number": "A1",
                                    "expiry_date": "2031-01-01"}, category="ID_DOCUMENT")
    assert "Which passport should we use?" not in page.get(
        reverse("student-documents")).content.decode()
    second = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _fact(membership_a, second, {"document_type": "passport", "number": "B2",
                                     "expiry_date": "2032-01-01"}, category="ID_DOCUMENT")
        DocumentReading.objects.create(student=membership_a, document=second, kind="PASSPORT",
                                       reader_version="id-1", state="READ")
    html = page.get(reverse("student-documents")).content.decode()
    assert "Which passport should we use?" in html
    response = page.post(reverse("student-id-document-primary", args=[second.id]))
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        assert DocumentReading.objects.get(document=second).primary_chosen_at is not None
```

- [ ] **Step 2: Run to see them fail**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_documents_page_details.py`
Expected: FAIL (`NoReverseMatch: student-fact-correct`).

- [ ] **Step 3: Write `apps/documents/fact_labels.py`**

```python
"""Plain English for the dashboard (spec 2026-10-12 §3). Plan 2 adds the diploma
and certificate keys; the panel's four-language strings live in the extension."""

FIELD_LABELS: dict[str, str] = {
    "identity.given_names": "Given names",
    "identity.surname": "Surname",
    "identity.date_of_birth": "Date of birth",
    "identity.place_of_birth": "Place of birth",
    "identity.sex": "Sex",
    "identity.citizenship": "Citizenship",
    "id_document.document_type": "Document type",
    "id_document.number": "Document number",
    "id_document.issuing_country": "Issuing country",
    "id_document.issue_date": "Issue date",
    "id_document.expiry_date": "Expiry date",
    "id_document.issuing_authority": "Issuing authority",
}
KIND_LABELS: dict[str, str] = {"PASSPORT": "your passport"}
PROBLEM_TEXT: dict[str, str] = {
    "unreadable": "We couldn't read this — upload a clearer photo",
    "not_an_id_document": "This doesn't look like a passport or ID card — upload the photo page",
    "no_data_page": "We couldn't find the photo page — upload it on its own",
    "unsupported_file": "We couldn't read this file — upload a photo or a PDF",
    "reader_unavailable": "We couldn't read this yet — we'll keep trying",
    "owner_mismatch": "This passport doesn't look like yours",
}
WHY_TEXT: dict[str, str] = {
    "low_confidence": "The text was hard to read.",
    "strip_disagrees": "The printed page and the code strip disagree.",
    "no_strip": "We couldn't check it against the code strip.",
    "no_citizenship": "This document does not state a citizenship.",
    "unknown_country": "We didn't recognise this country.",
    "owner_mismatch": "The name doesn't match yours.",
    "student_entry_differs": "You entered a different value before.",
    "document_differs": "Your earlier document says something else.",
}
```

- [ ] **Step 4: Extend `page_context`** in `apps/documents/views.py`:
  - Change `facts = list(unsuperseded_facts(student).filter(confirmed_by__isnull=True))` to exclude
    document reads: `.exclude(source_ref__startswith="document:")`.
  - Before the `return`, build:
    ```python
        readings = list(DocumentReading.objects.filter(student=student).select_related("document"))
        snippets = {
            (f"document:{r.document_id}", v.get("key")): v
            for r in readings for v in (r.values or [])
        }
        read_facts = list(unsuperseded_facts(student).filter(source_ref__startswith="document:"))
        details, to_check = [], []
        for fact in read_facts:
            for key, value in fact.payload.items():
                full = f"{fact.category.lower()}.{key}"
                if full not in FIELD_LABELS or not isinstance(value, str):
                    continue
                read = snippets.get((fact.source_ref, full), {})
                row = {"label": FIELD_LABELS[full], "value": value, "key": key,
                       "fact_id": fact.id, "snippet": read.get("snippet", ""),
                       "why": WHY_TEXT.get(str(read.get("why", "")), ""),
                       "use_body": json.dumps({"fact_ids": [str(fact.id)]})}
                (details if fact.confirmed_at else to_check).append(row)
        problems = [
            {"document": r.document, "text": PROBLEM_TEXT.get(r.failure, PROBLEM_TEXT["unreadable"])}
            for r in readings if r.state == DocumentReading.State.FAILED
            and r.failure != "erasure_requested"
        ] + [
            {"document": r.document, "text": PROBLEM_TEXT["owner_mismatch"]}
            for r in readings if any(v.get("why") == "owner_mismatch" for v in (r.values or []))
        ]
        today = timezone.localdate().isoformat()
        passports = [
            {"document_id": fact.source_ref.removeprefix("document:"), **fact.payload}
            for fact in read_facts
            if fact.category == VerifiedFact.Category.ID_DOCUMENT and fact.confirmed_at
            and fact.payload.get("document_type") == "passport"
            and fact.payload.get("expiry_date", "") >= today
        ]
    ```
    and add to the returned dict: `"details": details`, `"to_check": to_check`,
    `"problems": problems`, `"passport_choices": passports if len(passports) >= 2 else []`.
    Imports: `DocumentReading`, `VerifiedFact`, `timezone`, and the three label dicts.
  - Add the two views:
    ```python
    @login_required
    @require_POST
    def correct_fact_view(request: HttpRequest, fact_id: UUID) -> HttpResponse:
        """The student's own value for one read detail (spec 2026-10-12 §3, D5)."""
        student = current_membership(request, Membership.Role.STUDENT)
        if rate_limited("api-confirm", student.id, limit=60, window_seconds=3600):
            return HttpResponse(status=429)
        try:
            with transaction.atomic():
                correct_fact(student=student, fact_id=fact_id,
                             key=str(request.POST.get("key", "")),
                             value=str(request.POST.get("value", "")))
        except FactNotFound:
            raise Http404 from None
        except ValueError:
            return HttpResponse("That value can't be saved.", status=400)
        return redirect(f"{reverse('student-documents')}#details")


    @login_required
    @require_POST
    def choose_id_document(request: HttpRequest, document_id: UUID) -> HttpResponse:
        """Which valid passport portals get (spec §4.2): only ever the student's own."""
        student = current_membership(request, Membership.Role.STUDENT)
        updated = DocumentReading.objects.filter(
            student=student, document_id=document_id, state=DocumentReading.State.READ
        ).update(primary_chosen_at=timezone.now())
        if not updated:
            raise Http404
        return redirect(f"{reverse('student-documents')}#details")
    ```
    New imports in `views.py`: `from django.db import transaction`, `from django.urls import reverse`,
    `from apps.ratelimit import rate_limited`, `from .confirmation import FactNotFound`,
    `from .fact_writer import correct_fact`, `from .models import DocumentReading, VerifiedFact`,
    `from django.utils import timezone`, and
    `from .fact_labels import FIELD_LABELS, PROBLEM_TEXT, WHY_TEXT`. Skip any that are already
    imported.
    Before writing them, read `document_expiry` in the same file. Mirror how it gets the tenant
    transaction for its write; if it relies on middleware for the RLS GUC, so do these. Reuse its
    imports for `current_membership`, `redirect` and `require_POST`.
  - `apps/documents/urls.py`: add
    ```python
        path("student/documents/facts/<uuid:fact_id>/correct/", views.correct_fact_view,
             name="student-fact-correct"),
        path("student/documents/id-documents/<uuid:document_id>/primary/",
             views.choose_id_document, name="student-id-document-primary"),
    ```

- [ ] **Step 5: The template.** In `templates/student/_documents.html`:
  - Change the "Facts read from your CV" heading's section to stay as it is. Its list now excludes
    document reads (Step 4).
  - Insert, before `<section aria-labelledby="facts-heading" id="facts">`:

```html
<section aria-labelledby="details-heading" id="details">
  <h2 id="details-heading">Your details</h2>
  {% for problem in problems %}
    <p role="status">{{ problem.document.get_kind_display }}: {{ problem.text }}</p>
  {% endfor %}
  {% if to_check %}
    <h3>{{ to_check|length }} detail{{ to_check|length|pluralize }} to check</h3>
    <ul>
      {% for row in to_check %}
        <li>
          {{ row.label }}: <strong>{{ row.value }}</strong>
          {% if row.snippet %}<span> — read from “{{ row.snippet }}”</span>{% endif %}
          {% if row.why %}<span> {{ row.why }}</span>{% endif %}
          {% if not counselor_view %}
            <button type="button" data-api-post="/api/documents/facts/confirm" data-body="{{ row.use_body }}">Use</button>
            <form method="post" action="{% url 'student-fact-correct' row.fact_id %}">
              {% csrf_token %}
              <input type="hidden" name="key" value="{{ row.key }}">
              <label for="correct-{{ row.fact_id }}-{{ row.key }}">Correct</label>
              <input id="correct-{{ row.fact_id }}-{{ row.key }}" name="value" value="{{ row.value }}">
              <button type="submit">Save</button>
            </form>
            <span role="status"></span>
          {% endif %}
        </li>
      {% endfor %}
    </ul>
  {% endif %}
  {% if passport_choices and not counselor_view %}
    <h3>Which passport should we use?</h3>
    {% for passport in passport_choices %}
      <form method="post" action="{% url 'student-id-document-primary' passport.document_id %}">
        {% csrf_token %}
        <button type="submit">{{ passport.number }}, expires {{ passport.expiry_date }}</button>
      </form>
    {% endfor %}
  {% endif %}
  {% if details %}
    <ul>
      {% for row in details %}
        <li>
          {{ row.label }}: {{ row.value }}
          {% if not counselor_view %}
            <form method="post" action="{% url 'student-fact-correct' row.fact_id %}">
              {% csrf_token %}
              <input type="hidden" name="key" value="{{ row.key }}">
              <label for="edit-{{ row.fact_id }}-{{ row.key }}">Edit</label>
              <input id="edit-{{ row.fact_id }}-{{ row.key }}" name="value" value="{{ row.value }}">
              <button type="submit">Save</button>
            </form>
          {% endif %}
        </li>
      {% endfor %}
    </ul>
  {% elif not to_check %}
    <p>Upload your passport and we'll fill in your details on every application.</p>
  {% endif %}
</section>
```

  The "1 detail to check" string in the test comes from `{{ to_check|length }} detail{{ ...|pluralize }} to check`.

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=elmify_fact_reading uv run pytest -q tests/documents/test_documents_page_details.py tests/documents/test_documents_page.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add apps/documents/fact_labels.py apps/documents/views.py apps/documents/urls.py templates/student/_documents.html tests/documents/test_documents_page_details.py
git -C /home/orkhan/Desktop/fact-reading commit -m "feat(documents): Your details, details to check, read problems and the passport choice on the dashboard"
```

---

### Task 10: Gates, and the record in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (Application automation section, after the "Built, 2026-09-17: pairing" paragraph)

- [ ] **Step 1: Add the record** to `CLAUDE.md`:

```markdown
**Built, 2026-10-12: reading a student's passport into facts** (`apps/documents/mrz.py`,
`id_reading.py`, `document_reading.py`, `fact_writer.py`; spec
`docs/superpowers/specs/2026-10-12-document-fact-reading-design.md`, plan 1 of 3). Three rules
bind anything built on it:

- **A proven value is a confirmed fact no person confirmed.** `confirmed_by` names the student
  whose document it is, and the audit event is `fact.read_from_document` with
  `actor_kind=AGENT`. "Proven" means the strip's own check digit and the printed page agree, or
  Azure's confidence where the strip is silent. It never means "genuine": nothing here checks
  authenticity, and no screen may call a value "verified" in that sense.
- **IDENTITY is no longer one row.** A passport read writes one IDENTITY row per key. Anything
  that needs the person's name filters with `verification.has_full_name`; never
  `filter(category=IDENTITY).last()`.
- **ID_DOCUMENT never reaches a model.** `generatable_facts` drops it, and no language model
  reads a passport at all (spec D6). Do not add an ID_DOCUMENT row to any prompt.
- `FACT_READING_ENABLED` ships off. The launch gates (spec §9: a consented set judged by the
  owner, zero wrong proven values) come before it is on for real students.
```

- [ ] **Step 2: The privacy notice is the owner's, not the code's.** Spec §8 adds one line to
  the privacy notice: uploaded identity documents and certificates are read by a machine to fill
  applications. The notices live in `apps/privacy/legal/privacy_notice_*.{az,en,ru}.md`. They are
  versioned legal documents, and changing one makes every student re-accept. Do **not** edit them.
  Put the proposed sentence in the PR body under "Owner action before FACT_READING_ENABLED":
  "Identity documents, diplomas and certificates you upload are read automatically to fill your
  applications; you can check and correct every value on your dashboard."

- [ ] **Step 3: Run every gate**

Run, from the worktree:
- `POSTGRES_DB=elmify_fact_reading uv run pytest -q`
- `uv run ruff check .`
- `uv run mypy apps config`
- `uv run bandit -c pyproject.toml -r apps config`
- `uv run python manage.py check`
- `uv run python manage.py makemigrations --check --dry-run`

Expected: all pass. Fix anything they find in the task that owns it.

- [ ] **Step 4: Commit**

```bash
git -C /home/orkhan/Desktop/fact-reading add CLAUDE.md
git -C /home/orkhan/Desktop/fact-reading commit -m "docs: the passport-reading rules in CLAUDE.md"
```
