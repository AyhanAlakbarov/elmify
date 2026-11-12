# Letter plan 1: correctness on today's letter code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four defects in the letter engine that exist today on `master`, before any story or research work builds on them.

**Architecture:** All changes sit in the deterministic letter checks (`apps/documents/letter_gates.py`), the generation entry (`apps/documents/letters.py`), approval (`apps/documents/letter_approval.py`) and the console command (`draft_letter.py`). One new idea is introduced: a gate violation may be **non-blocking** (a warning carried on the result), which the why-programme and no-facts cases need so that closing the made-up-link loophole does not block every letter while research fit is switched off.

**Tech Stack:** Python 3, Django, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-14-letter-story-and-research-fit-amendment-design.md` (§2, §5, §4.6, §7.3, §8.1, §14 plan 1).

## Plan refinements against the spec (bird's-eye review, 2026-10-14)

Found while reading the code; each keeps the spec's intent and is recorded in the spec in Task 5.

1. **Closing the loophole would block every letter today.** `is_letter_blocked` blocks on *any* gate violation, and with research fit off no letter has a verified programme input, so "only a verified input satisfies `WHY_PROGRAMME`" turns every letter into a blocked one. Hence the non-blocking violation (Task 3). The warning is carried on the result, **not** turned into a counsellor flag: flags hold a letter in `DRAFT` for a queue nobody reviews (owner, 2026-09-18), which would stop every letter auto-approving.
2. **`script_of` and character counting are one function today.** `letter_shape.counts_characters` is `script_of(...) is not None`, so adding Russian to `script_of` would make Russian letters character-counted and break every word cap. They are split (Task 2).
3. **Unicode sentence splitting without ICU.** A character class of the sentence terminals our letter languages use (Latin `.!?`, Arabic `؟`, Armenian `։`, CJK `。！？`) replaces `[.!?]\s+`; no new dependency. Known limit, written as a `ponytail:` comment: Greek writes its question mark as `;` (U+037E normalises to `;`), indistinguishable from a semicolon without the language, so Greek questions are not split.
4. **`script_of` skips two-script languages.** Serbian (Cyrillic and Latin) and Kazakh (Cyrillic, moving to Latin) are left out, because a correct Latin-script letter would fail the check.
5. **`DocumentDraft.cycle` moves to plan 3**, where pools first use it, and stores `ApplicationPrompt.cycle` verbatim (pools compare drafts with drafts; "2027" cannot be mapped to `YYYY-YYYY` unambiguously).
6. **The short no-facts letter length moves to plan 3** with thin profiles; plan 1 makes the no-facts letter generatable (warning, not block).

## Global Constraints

- Lint only: `uv run ruff check .` — never `ruff format`.
- Types: `uv run mypy apps config`.
- Tests: `POSTGRES_DB=elmify_letter_story_spec uv run pytest -q tests/documents` (per-worktree database).
- Django: `uv run python manage.py check` and `uv run python manage.py makemigrations --check --dry-run` (this plan adds no migration).
- No new dependency. No edit to an applied migration.
- Commit with an explicit pathspec (`git commit -- <paths>`); never `git add -A`.
- Untrusted text (letter prose, page sentences, gate `detail`) never enters model instructions; the retry note carries gate codes and known archetypes only (existing rule in `letters.py`).

## Review Focus

1. **A Russian letter that quotes English names** (programme, lab, software) must still pass the script check — the 50% ratio is over all non-space characters. Test in Task 2.
2. **Claim spans in a Japanese letter after hygiene** — `letter_render.hygienic_letter_content` re-anchors with `sentence_spans`; a CJK split change must not unanchor a correct claim. Test in Task 1.
3. **A research row with missing or malformed provenance** (no `program_id`, `provenance=None`) must be dropped, never crash generation. Test in Task 4.
4. **A retry triggered by a real blocking violation must not mention warnings** in its retry note, or the model is invited to invent a `SOURCED` claim. Test in Task 3.
5. **A zero-unit letter stays blocking** even though `GENERIC_PARAGRAPH` gains a warning form. Test in Task 3.

---

### Task 1: Sentence splitting for every letter script

**Files:**
- Modify: `apps/documents/letter_gates.py:44` (`_SENTENCE_SPLIT`) and `sentence_spans` (docstring only)
- Test: `tests/documents/test_letter_gates.py`

**Interfaces:**
- Produces: `sentence_spans(text: str) -> list[tuple[str, int, int]]` — unchanged signature, now splits CJK, Arabic and Armenian sentences. `_normalised_sentences` and `_unit_sentences` use `_SENTENCE_SPLIT` and inherit the change.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_letter_gates.py` (add `sentence_spans` to the import list at the top):

```python
# --- Plan 1, task 1: sentence splitting for every letter script ---


def test_latin_sentences_split_as_before():
    assert [s for s, _, _ in sentence_spans("I studied. I built! Why? Done.")] == [
        "I studied.", "I built!", "Why?", "Done.",
    ]


def test_a_version_number_is_not_a_sentence_end():
    assert [s for s, _, _ in sentence_spans("I used Python 3.11 daily. Then I left.")] == [
        "I used Python 3.11 daily.", "Then I left.",
    ]


def test_japanese_and_chinese_sentences_split_without_a_space():
    assert [s for s, _, _ in sentence_spans("研究をしました。次に進みます。")] == [
        "研究をしました。", "次に進みます。",
    ]
    assert [s for s, _, _ in sentence_spans("我学习了。你呢？好！")] == ["我学习了。", "你呢？", "好！"]


def test_arabic_question_mark_and_armenian_full_stop_end_sentences():
    assert len(sentence_spans("هل درست؟ نعم درست.")) == 2
    assert len(sentence_spans("Ես սովորել եմ։ Հետո աշխատել եմ։")) == 2


def test_spans_point_at_their_own_text_in_cjk():
    text = "研究をしました。次に進みます。"
    for sentence, start, end in sentence_spans(text):
        assert text[start:end] == sentence


def test_no_empty_trailing_sentence_after_a_final_cjk_stop():
    assert [s for s, _, _ in sentence_spans("研究をしました。")] == ["研究をしました。"]
```

And the hygiene case (Review Focus 2) in `tests/documents/test_letter_render.py`, next to the existing `hygienic_letter_content` tests:

```python
def test_hygiene_keeps_a_japanese_claim_anchored_to_its_sentence():
    text = "東京大学で研究しました。次に進みます。"
    first = "東京大学で研究しました。"
    claim = LetterClaim(
        text=first, span_start=0, span_end=len(first),
        kind=ClaimKind.FACTUAL, fact_id=uuid4(),
    )
    content = LetterContent(
        language="ja",
        units=(LetterUnit(archetype="WHY_FIELD", text=text, claims=(claim,)),),
    )
    cleaned = hygienic_letter_content(content)
    unit = cleaned.units[0]
    anchored = unit.claims[0]
    assert unit.text[anchored.span_start:anchored.span_end] == first
```

(Import `uuid4`, `LetterClaim`, `ClaimKind`, `LetterContent`, `LetterUnit` and `hygienic_letter_content` if the file does not already.)

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_letter_story_spec uv run pytest -q tests/documents/test_letter_gates.py -k "sentences or sentence_end or spans_point or trailing" tests/documents/test_letter_render.py -k japanese`
Expected: the CJK, Arabic and Armenian tests FAIL (one span each); the Latin tests PASS.

- [ ] **Step 3: Implement**

Replace line 44 of `apps/documents/letter_gates.py`:

```python
#: Where a sentence ends, for every script a letter is written in. Latin, Arabic
#: (؟) and Armenian (։) terminals end a sentence only before whitespace, so a
#: version number ("3.11") never splits; CJK full-width terminals take no space
#: after them and split before the next visible character, so a final one leaves
#: no empty trailing sentence. ponytail: Greek writes its question mark as ";"
#: (U+037E normalises to it), indistinguishable from a semicolon without the
#: letter's language, so Greek questions are not split; pass the language in
#: if a Greek letter ever needs it.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?؟։])\s+|(?<=[。！？])\s*(?=\S)")
```

Update the first line of `sentence_spans`'s docstring to: `Split ``text`` into sentences with their ``[start, end)`` offsets, for every letter script (see ``_SENTENCE_SPLIT``).`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_letter_story_spec uv run pytest -q tests/documents/test_letter_gates.py tests/documents/test_letter_render.py tests/documents/test_letters.py`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(letters): split sentences in Chinese, Japanese, Arabic and Armenian letters" -- apps/documents/letter_gates.py tests/documents/test_letter_gates.py tests/documents/test_letter_render.py
```

---

### Task 2: The script check for every letter script, separate from character counting

**Files:**
- Modify: `apps/documents/letter_gates.py:300-317` (`_HANGUL` … `script_of`)
- Modify: `apps/documents/letter_shape.py:354-361` (`counts_characters`)
- Test: `tests/documents/test_letter_gates.py`, `tests/documents/test_letter_shape.py`

**Interfaces:**
- Produces: `script_of(document_language: str) -> re.Pattern[str] | None` — now also Cyrillic (`ru`, `uk`, `be`, `bg`, `mk`), Greek (`el`), Arabic (`ar`), Armenian (`hy`), Georgian (`ka`). `CHARACTER_COUNTED_LANGUAGES: frozenset[str]` = `{"ko", "ja", "zh"}` in `letter_gates`. `letter_shape.counts_characters(document_language) -> bool` reads that set, not `script_of`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_letter_gates.py`:

```python
# --- Plan 1, task 2: script check for every letter script ---

import pytest  # noqa: E402  (keep with the module's other imports when moving it up)


def _letter(language, text):
    return LetterContent(
        language=language, units=(LetterUnit(archetype="WHY_FIELD", text=text, claims=()),)
    )


@pytest.mark.parametrize(
    ("language", "native"),
    [
        ("ru", "Я изучала машинное обучение в университете."),
        ("uk", "Я вивчала машинне навчання в університеті."),
        ("bg", "Учих машинно обучение в университета."),
        ("el", "Σπούδασα μηχανική μάθηση στο πανεπιστήμιο."),
        ("ar", "درست تعلم الآلة في الجامعة."),
        ("hy", "Ես սովորել եմ մեքենայական ուսուցում համալսարանում։"),
        ("ka", "მე ვსწავლობდი მანქანურ სწავლებას უნივერსიტეტში."),
    ],
)
def test_a_letter_in_its_own_script_passes_and_in_english_fails(language, native):
    assert check_language_mismatch(_letter(language, native), document_language=language) == ()
    english = _letter(language, "I studied machine learning at the university.")
    assert any(
        v.code == GateCode.LANGUAGE_MISMATCH
        for v in check_language_mismatch(english, document_language=language)
    )


def test_a_russian_letter_quoting_english_names_still_passes():
    text = (
        "Я работала с библиотекой PyTorch в лаборатории Robotics Lab и хочу продолжить "
        "исследования в области обучения с подкреплением в вашей программе."
    )
    assert check_language_mismatch(_letter("ru", text), document_language="ru") == ()


@pytest.mark.parametrize("language", ["sr", "kk", "az", "tr", "de"])
def test_two_script_and_latin_languages_have_no_script_check(language):
    assert script_of(language) is None
```

Add `script_of` to the import list. Append to `tests/documents/test_letter_shape.py`:

```python
@pytest.mark.parametrize("language", ["ru", "el", "ar", "hy", "ka", "en", "de"])
def test_only_cjk_counts_characters(language):
    assert counts_characters(language) is False


@pytest.mark.parametrize("language", ["ja", "ja-JP", "zh", "zh-Hans", "ko"])
def test_cjk_counts_characters(language):
    assert counts_characters(language) is True
```

(Import `pytest` and `counts_characters` from `apps.documents.letter_shape` if missing.)

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_letter_story_spec uv run pytest -q tests/documents/test_letter_gates.py -k "own_script or quoting or two_script" tests/documents/test_letter_shape.py -k counts_characters`
Expected: the "in English fails" half FAILS for all seven languages; `counts_characters` tests PASS (they pin today's behaviour before the split).

- [ ] **Step 3: Implement**

Replace `apps/documents/letter_gates.py` lines 301-317 with:

```python
_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_ARMENIAN = re.compile(r"[԰-֏]")
_GEORGIAN = re.compile(r"[Ⴀ-ჿ]")
#: Languages written in one non-Latin script. Serbian (Cyrillic and Latin) and
#: Kazakh (Cyrillic, moving to Latin) are deliberately absent: a correct letter
#: in either script must not fail the check.
_NON_LATIN_SCRIPTS = {
    "ko": _HANGUL, "ja": _KANA, "zh": _HAN,
    "ru": _CYRILLIC, "uk": _CYRILLIC, "be": _CYRILLIC, "bg": _CYRILLIC, "mk": _CYRILLIC,
    "el": _GREEK, "ar": _ARABIC, "hy": _ARMENIAN, "ka": _GEORGIAN,
}
#: Languages whose length is counted in characters, not words. A separate set
#: from the script table on purpose: `letter_shape.counts_characters` used to
#: read `script_of`, so every script added here would have switched that
#: language's word caps off.
CHARACTER_COUNTED_LANGUAGES = frozenset({"ko", "ja", "zh"})


def _primary_subtag(document_language: str) -> str:
    return document_language.lower().split("-")[0]


def script_of(document_language: str) -> re.Pattern[str] | None:
    """The script a language is written in, or None for a Latin-script one.

    The PRIMARY SUBTAG only: `document_language` holds up to ten characters,
    so "ja-JP" and "zh-Hans" are storable.
    """
    return _NON_LATIN_SCRIPTS.get(_primary_subtag(document_language))
```

Replace `apps/documents/letter_shape.py`'s `counts_characters` body (keep its signature), and change its import from `script_of` to `CHARACTER_COUNTED_LANGUAGES`:

```python
def counts_characters(document_language: str) -> bool:
    """Whether this language's length is counted in characters (CJK), not words.

    Read from `letter_gates.CHARACTER_COUNTED_LANGUAGES`, the primary subtag
    only, so "ja-JP" and "zh-Hans" count characters like "ja" and "zh".
    """
    return document_language.lower().split("-")[0] in CHARACTER_COUNTED_LANGUAGES
```

Run `grep -n "script_of" apps/documents/letter_shape.py` afterwards: if `script_of` is no longer used there, remove it from the import.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_letter_story_spec uv run pytest -q tests/documents/test_letter_gates.py tests/documents/test_letter_shape.py tests/documents/test_letters.py tests/documents/test_letter_terms.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(letters): check the script of Cyrillic, Greek, Arabic, Armenian and Georgian letters" -- apps/documents/letter_gates.py apps/documents/letter_shape.py tests/documents/test_letter_gates.py tests/documents/test_letter_shape.py
```

---

### Task 3: Non-blocking violations, the why-programme gate and the no-facts letter

**Files:**
- Modify: `apps/documents/letter_gates.py` (`LetterGateViolation`, `check_generic_paragraph`, `run_letter_gates`)
- Modify: `apps/documents/letters.py` (`is_letter_blocked`, `_evaluate`, retry note in `generate_letter`)
- Modify: `apps/documents/management/commands/draft_letter.py` (`_report`)
- Test: `tests/documents/test_letter_gates.py`, `tests/documents/test_letters.py`

**Interfaces:**
- Produces:
  - `LetterGateViolation(code, detail, unit_archetype=None, blocking=True)` — new trailing field `blocking: bool = True`.
  - `check_generic_paragraph(content, *, programme_input_ids: frozenset[UUID] = frozenset(), has_facts: bool = True) -> tuple[LetterGateViolation, ...]`.
  - `run_letter_gates(..., programme_input_ids: frozenset[UUID] = frozenset(), has_facts: bool = True)` — passes both through.
  - `is_letter_blocked(...)` blocks only on `blocking` violations.
- Consumes (Task 4): `_evaluate` receives inputs already filtered to the programme.

Rules this task implements (spec §5, §4.6):
- `WHY_PROGRAMME` is satisfied only by a `SOURCED` claim whose `input_id` is in `programme_input_ids`. A URL-only `SOURCED` claim no longer counts.
- When `programme_input_ids` is empty (nothing verified for this programme — today, always), the missing claim is a **non-blocking** violation with detail `"WHY_PROGRAMME not specific to this programme: no verified programme fact"`.
- When `has_facts` is False, "no FACTUAL or SOURCED claim" is **non-blocking** with detail `"no confirmed facts: written from the programme and the plan only"`.
- A zero-unit letter stays blocking (unchanged code in `_evaluate`).
- The retry note lists blocking violations only.

- [ ] **Step 1: Write the failing tests**

In `tests/documents/test_letter_gates.py`, replace `test_why_programme_needs_a_sourced_claim_not_only_a_factual_one` with:

```python
def _why_programme(*claims):
    return LetterContent(
        language="en",
        units=(LetterUnit(archetype="WHY_PROGRAMME", text="my thesis leads me here.", claims=claims),),
    )


def _factual():
    return LetterClaim(
        text="my thesis", span_start=0, span_end=9, kind=ClaimKind.FACTUAL, fact_id=uuid4()
    )


def test_why_programme_needs_a_sourced_claim_not_only_a_factual_one():
    verified = uuid4()
    violations = check_generic_paragraph(
        _why_programme(_factual()), programme_input_ids=frozenset({verified})
    )
    assert any(v.code == GateCode.GENERIC_PARAGRAPH and v.blocking for v in violations)


def test_a_url_only_sourced_claim_no_longer_satisfies_why_programme():
    url_only = LetterClaim(
        text="my thesis", span_start=0, span_end=9, kind=ClaimKind.SOURCED,
        source_url="https://made-up.example/page",
    )
    violations = check_generic_paragraph(
        _why_programme(_factual(), url_only), programme_input_ids=frozenset({uuid4()})
    )
    assert any(v.code == GateCode.GENERIC_PARAGRAPH and v.blocking for v in violations)


def test_a_sourced_claim_citing_a_verified_input_satisfies_why_programme():
    verified = uuid4()
    cited = LetterClaim(
        text="my thesis", span_start=0, span_end=9, kind=ClaimKind.SOURCED,
        source_url="https://www.tum.de/robotics", input_id=verified,
    )
    assert check_generic_paragraph(
        _why_programme(_factual(), cited), programme_input_ids=frozenset({verified})
    ) == ()


def test_with_nothing_verified_why_programme_is_a_warning_not_a_block():
    violations = check_generic_paragraph(_why_programme(_factual()))
    assert violations and all(not v.blocking for v in violations)
    assert "not specific to this programme" in violations[0].detail


def test_a_letter_with_no_facts_is_a_warning_not_a_block():
    content = LetterContent(
        language="en",
        units=(LetterUnit(archetype="CAREER_GOALS", text="I want to build tools.", claims=()),),
    )
    violations = check_generic_paragraph(content, has_facts=False)
    assert violations and all(not v.blocking for v in violations)
    assert check_generic_paragraph(content, has_facts=True)[0].blocking
```

In `tests/documents/test_letters.py`:

```python
def test_is_letter_blocked_ignores_non_blocking_violations():
    warning = LetterGateViolation(GateCode.GENERIC_PARAGRAPH, "warning", "WHY_PROGRAMME", blocking=False)
    assert is_letter_blocked((), (warning,), immigration=False) is False


def test_a_warning_alone_does_not_spend_the_retry(agency_a, django_user_model):
    # _clean_content's WHY_PROGRAMME cites a URL only: with no verified
    # programme input that is a warning, so the letter is not retried.
    client = _mock_client(_clean_content())
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "warn1")
        result = generate_letter(
            student=student,
            prompt=_prompt_stub(ApplicationPrompt.Structure.CONTINUOUS_LETTER),
            facts={}, inputs={}, forbidden_institution_names=frozenset(), client=client,
        )
    assert result.retried is False
    assert client.responses.parse.call_count == 1
    assert result.gate_violations and all(not v.blocking for v in result.gate_violations)


def test_the_retry_note_never_mentions_a_warning(agency_a, django_user_model):
    # A real blocking violation (an uncovered number) forces the retry; the
    # WHY_PROGRAMME warning must not appear in the note.
    text = "I completed 120 ECTS credits."
    content = LetterContent(
        language="en",
        units=(LetterUnit(archetype="WHY_PROGRAMME", text=text, claims=()),),
    )
    client = _mock_client(content)
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "warn2")
        generate_letter(
            student=student,
            prompt=_prompt_stub(ApplicationPrompt.Structure.CONTINUOUS_LETTER),
            facts={}, inputs={}, forbidden_institution_names=frozenset(), client=client,
        )
    note = str(client.responses.parse.call_args_list[1].kwargs["input"][0]["content"])
    assert "UNDECLARED_ASSERTION" in note
    assert "GENERIC_PARAGRAPH" not in note
```

(Import `LetterGateViolation` and `GateCode` from `apps.documents.letter_gates` and `LetterContent`, `LetterUnit` if missing. `test_empty_units_letter_is_blocked_and_retried` already pins Review Focus 5 — leave it.)

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_letter_story_spec uv run pytest -q tests/documents/test_letter_gates.py -k "why_programme or url_only or no_facts or verified" tests/documents/test_letters.py -k "non_blocking or warning"`
Expected: FAIL (`unexpected keyword argument 'programme_input_ids'`, `'blocking'`).

- [ ] **Step 3: Implement**

`apps/documents/letter_gates.py` — add `from uuid import UUID` to the imports, then:

```python
@dataclass(frozen=True)
class LetterGateViolation:
    code: GateCode
    detail: str
    unit_archetype: str | None = None
    #: False for a warning: carried on the result for the student to see, never
    #: a reason to block, retry or hold the letter (spec 2026-10-14 §5, §4.6).
    blocking: bool = True
```

Replace `check_generic_paragraph`:

```python
_NOT_PROGRAMME_SPECIFIC = "not specific to this programme: no verified programme fact"
_NO_FACTS = "no confirmed facts: written from the programme and the plan only"


def check_generic_paragraph(
    content: LetterContent,
    *,
    programme_input_ids: frozenset[UUID] = frozenset(),
    has_facts: bool = True,
) -> tuple[LetterGateViolation, ...]:
    """Every body paragraph rests on a fact; WHY_PROGRAMME rests on a verified
    programme fact. Only a SOURCED claim citing one of `programme_input_ids`
    (research rows verified for THIS programme) satisfies WHY_PROGRAMME: a
    SOURCED claim carrying only a URL was a link the model could make up. When
    nothing is verified for the programme, or the student has no confirmed
    facts, the miss is a warning -- blocking it would block every such letter."""
    violations: list[LetterGateViolation] = []
    for unit in content.units:
        if unit.archetype in _EXEMPT_ARCHETYPES:
            continue
        kinds = {claim.kind.value for claim in unit.claims}
        if not kinds & {"FACTUAL", "SOURCED"}:
            violations.append(
                LetterGateViolation(
                    GateCode.GENERIC_PARAGRAPH,
                    "no FACTUAL or SOURCED claim" if has_facts else _NO_FACTS,
                    unit.archetype,
                    blocking=has_facts,
                )
            )
        elif unit.archetype in _SOURCED_REQUIRED_ARCHETYPES and not any(
            claim.kind == ClaimKind.SOURCED and claim.input_id in programme_input_ids
            for claim in unit.claims
        ):
            violations.append(
                LetterGateViolation(
                    GateCode.GENERIC_PARAGRAPH,
                    f"{unit.archetype} without a SOURCED claim citing a verified programme fact"
                    if programme_input_ids
                    else f"{unit.archetype} {_NOT_PROGRAMME_SPECIFIC}",
                    unit.archetype,
                    blocking=bool(programme_input_ids),
                )
            )
    return tuple(violations)
```

In `run_letter_gates`, add the two keyword parameters with the same defaults and change the call to `check_generic_paragraph(content, programme_input_ids=programme_input_ids, has_facts=has_facts)`.

`apps/documents/letters.py`:

```python
def is_letter_blocked(
    claim_verdicts: tuple[LetterClaimVerdict, ...],
    gate_violations: tuple[LetterGateViolation, ...],
    *,
    immigration: bool,
) -> bool:
    if any(violation.blocking for violation in gate_violations):
        return True
    ...  # verdict loop unchanged
```

In `_evaluate`, pass to `run_letter_gates`:

```python
        programme_input_ids=frozenset(
            input_id
            for input_id, entry in inputs.items()
            if entry.kind == NarrativeInput.Kind.RESEARCH_FIT and entry.provenance
        ),
        has_facts=bool(facts),
```

In `generate_letter`'s retry-note block, build `failed_gate_codes` from `(v for v in violations if v.blocking)` instead of `violations`.

`apps/documents/management/commands/draft_letter.py` `_report`: print each violation as

```python
            kind = "warning" if not violation.blocking else "blocking"
            self.stdout.write(f"    {violation.code} ({violation.unit_archetype}) [{kind}]")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_letter_story_spec uv run pytest -q tests/documents`
Expected: PASS. Existing tests that asserted `gate_violations == ()` for `_clean_content()` now see one non-blocking violation: change those assertions to `not any(v.blocking for v in result.gate_violations)`. Do not weaken any assertion about a blocking violation. A test that relied on `GENERIC_PARAGRAPH` blocking while passing `facts={}` now gets a warning instead (no facts): give it one confirmed fact so it still exercises the blocking path, rather than deleting the assertion.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(letters): a made-up link no longer satisfies why-this-programme; unverifiable cases warn instead of block" -- apps/documents/letter_gates.py apps/documents/letters.py apps/documents/management/commands/draft_letter.py tests/documents/test_letter_gates.py tests/documents/test_letters.py
```

(Add any other test file whose `== ()` assertion was changed in Step 4 to the pathspec.)

---

### Task 4: Research rows are filtered to the letter's programme

**Files:**
- Modify: `apps/documents/letters.py` (new `inputs_for_programme`; applied at the top of `generate_letter`)
- Modify: `apps/documents/letter_approval.py` (`mark_letter_ready` applies it before verification and the re-check)
- Test: `tests/documents/test_letters.py`, `tests/documents/test_letter_approval.py`

**Interfaces:**
- Produces: `inputs_for_programme(inputs: dict[UUID, NarrativeInput], programme_id: UUID) -> dict[UUID, NarrativeInput]` in `apps/documents/letters.py`. Keeps every non-`RESEARCH_FIT` input; keeps a `RESEARCH_FIT` input only when `provenance` is a dict whose `"program_id"` equals `str(programme_id)`; logs one WARNING naming the dropped input ids (ids only — never the sentence).
- Consumes: Task 3's `_evaluate` computes `programme_input_ids` from the inputs it is handed, so filtering first makes the gate programme-aware too.

- [ ] **Step 1: Write the failing tests**

In `tests/documents/test_letters.py`, change `_research_input` to take the programme and stamp it (existing callers pass the prompt's programme):

```python
def _research_input(entity="Chair of Robotics", *, program_id):
    sentence = f"The {entity} hosts master's theses on legged locomotion."
    return NarrativeInput(
        id=uuid4(),
        kind=NarrativeInput.Kind.RESEARCH_FIT,
        proposed_by=NarrativeInput.ProposedBy.ENGINE,
        text=sentence,
        provenance={
            "program_id": str(program_id),
            "sentence": sentence,
            "entity": entity,
            "source_url": "https://www.tum.de/robotics",
            "kind": "research_group",
            "page_digest": "d" * 64,
        },
    )
```

Update each existing caller to build the prompt first and pass `program_id=prompt.programme_id`. Then add:

```python
def test_another_programmes_research_never_reaches_the_letter(agency_a, django_user_model):
    prompt = _prompt_stub(ApplicationPrompt.Structure.CONTINUOUS_LETTER)
    other = _research_input("Chair of Elsewhere", program_id=uuid4())
    client = _mock_client(_clean_content())
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "rf-other")
        generate_letter(
            student=student, prompt=prompt, facts={}, inputs={other.id: other},
            forbidden_institution_names=frozenset(), client=client,
        )
    text = _prompt_text(client)
    assert "Chair of Elsewhere" not in text
    assert str(other.id) not in text


@pytest.mark.parametrize("provenance", [None, {}, {"program_id": None}, {"sentence": "x"}])
def test_a_research_row_with_broken_provenance_is_dropped_not_fatal(provenance):
    entry = NarrativeInput(
        id=uuid4(), kind=NarrativeInput.Kind.RESEARCH_FIT,
        proposed_by=NarrativeInput.ProposedBy.ENGINE, text="t", provenance=provenance,
    )
    plan = NarrativeInput(
        id=uuid4(), kind=NarrativeInput.Kind.RESEARCH_PLAN,
        proposed_by=NarrativeInput.ProposedBy.STUDENT, text="my plan",
    )
    kept = inputs_for_programme({entry.id: entry, plan.id: plan}, uuid4())
    assert list(kept) == [plan.id]


def test_a_sourced_claim_citing_another_programmes_row_is_unsupported(
    agency_a, django_user_model
):
    prompt = _prompt_stub(ApplicationPrompt.Structure.CONTINUOUS_LETTER)
    other = _research_input(program_id=uuid4())
    client = _mock_client(_content_with_sourced_claim(other))
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "rf-cite")
        result = generate_letter(
            student=student, prompt=prompt, facts={}, inputs={other.id: other},
            forbidden_institution_names=frozenset(), client=client,
        )
    assert any(v.verdict == Verdict.UNSUPPORTED for v in result.claim_verdicts)
```

(Import `inputs_for_programme`, `Verdict` and `pytest` if missing.) In `tests/documents/test_letter_approval.py`, add one test that calls `mark_letter_ready` with a content citing another programme's research row and asserts `ApprovalBlocked` is raised (follow the file's existing `mark_letter_ready` fixture pattern; the row's verdict is `UNSUPPORTED` once filtered).

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=elmify_letter_story_spec uv run pytest -q tests/documents/test_letters.py -k "research or provenance or another" tests/documents/test_letter_approval.py`
Expected: FAIL (`inputs_for_programme` not importable; other programme's entity reaches the prompt).

- [ ] **Step 3: Implement**

In `apps/documents/letters.py` (near `_research_payload`; `logger` exists in the module — if not, add `logger = logging.getLogger(__name__)`):

```python
def inputs_for_programme(
    inputs: dict[UUID, NarrativeInput], programme_id: UUID
) -> dict[UUID, NarrativeInput]:
    """The student's inputs this letter may use: every non-research input, and
    research rows verified for THIS programme only (spec 2026-10-14 §7.3). A
    research row without a readable `program_id` is dropped -- its programme is
    unknown, so citing it could name another university's lab."""
    kept: dict[UUID, NarrativeInput] = {}
    dropped: list[str] = []
    for input_id, entry in inputs.items():
        if entry.kind != NarrativeInput.Kind.RESEARCH_FIT:
            kept[input_id] = entry
            continue
        provenance = entry.provenance if isinstance(entry.provenance, dict) else {}
        if provenance.get("program_id") == str(programme_id):
            kept[input_id] = entry
        else:
            dropped.append(str(input_id))
    if dropped:
        logger.warning(
            "letter for programme %s: dropped %d research input(s) not verified for it: %s",
            programme_id, len(dropped), ", ".join(dropped),
        )
    return kept
```

First statement of `generate_letter`'s body (before the structure check is fine — it is pure): `inputs = inputs_for_programme(inputs, prompt.programme_id)`.

In `apps/documents/letter_approval.py` `mark_letter_ready`, before `verify_letter_claims`: `inputs = inputs_for_programme(inputs, prompt.programme_id)` (import it from `.letters`; `prompt.programme_id` exists on real `ApplicationPrompt` rows — if a test double lacks it, give the double the attribute rather than reading it with `getattr`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=elmify_letter_story_spec uv run pytest -q tests/documents`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(letters): a letter cites research verified for its own programme only" -- apps/documents/letters.py apps/documents/letter_approval.py tests/documents/test_letters.py tests/documents/test_letter_approval.py
```

---

### Task 5: Record the refinements in the spec, run every gate

**Files:**
- Modify: `docs/superpowers/specs/2026-10-14-letter-story-and-research-fit-amendment-design.md` (§8.1 first bullet, §14 items 1 and 3)

- [ ] **Step 1: Edit the spec**

- §8.1, first bullet: replace "sentence splitting by Unicode rules (ICU), replacing `_SENTENCE_SPLIT`" with "sentence splitting by the Unicode sentence terminals our letter languages use (Latin, Arabic `؟`, Armenian `։`, CJK `。！？`), replacing `_SENTENCE_SPLIT` without a new dependency; Greek `;` questions are a recorded limit".
- §8.1, second bullet: add "Serbian and Kazakh are left out: both are written in two scripts".
- §14 item 1: remove "`DocumentDraft.cycle`" and add "non-blocking (warning) gate violations".
- §14 item 3: add "`DocumentDraft.cycle` (stores `ApplicationPrompt.cycle` verbatim) and the short no-facts / thin-profile length".
- §4.4 first bullet: replace "(normalised to `YYYY-YYYY` … mapped to it)" with "(storing `ApplicationPrompt.cycle` verbatim; pools compare drafts with drafts)".

- [ ] **Step 2: Run every gate**

```bash
uv run ruff check .
uv run mypy apps config
POSTGRES_DB=elmify_letter_story_spec uv run pytest -q
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run bandit -c pyproject.toml -r apps config ocr/read_pages.py
```

Expected: all clean; record the pytest summary line.

- [ ] **Step 3: Commit**

```bash
git commit -m "docs(spec): plan 1 refinements -- warnings, script table, cycle moves to plan 3" -- docs/superpowers/specs/2026-10-14-letter-story-and-research-fit-amendment-design.md
```
