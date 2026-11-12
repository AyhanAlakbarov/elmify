# Dynamic Mid-Semester Score Progression & Anti-Account-Sharing Identity Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock every student account to its owner across document uploads, profile versions, and browser-extension portal forms while dynamically propagating mid-semester GPA, coursework, and language score improvements into live board card probabilities and newly unlocked **New for you** offers.

**Architecture:** We centralize transliteration-aware owner name and birth-date verification in `apps/documents/id_reading.py` and enforce it across passports, certificates, diplomas, transcripts, CVs, profile version creation (`apps/accounts/profile_versions.py`), and portal form overrides (`apps/portals/answers.py`), alerting the assigned counsellor on mismatch. On the progression side, we make `sync_facts_to_profile` monotonic on language scores, enqueue a `rebuild_pack` worker job when a profile's GPA, coursework, or language score improves, update `RecommendationCandidate` rows in place during `rebuild_pack` (refreshing active board cards), and surface newly unlocked or boosted programmes and scholarships in `apps/dashboard/new_for_you.py`.

**Tech Stack:** Python 3.12, Django 5, Pydantic v2, PostgreSQL with Row-Level Security (`runtime_web` / `runtime_engine`), `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-29-score-progression-and-identity-lock-design.md`

## Global Constraints

- `runtime_web` views and `apps/dashboard/new_for_you.py` must never query shared catalogue tables (`Program`, `FundingOpportunity`, `OutcomeCalibrationRecord`); all catalogue evaluation happens in `apps/research/services.py` (`runtime_engine`).
- Transliteration across Azerbaijani, Turkish, Russian, and English (`Əli` / `Ali`, `Məmmədov` / `Mammadov`) and patronymic tokens (`oğlu`, `qızı`) must be accepted via `apps/documents/mrz.py` (`same_given_name`, `same_name_token`).
- When `known_owner_names(student)` has no 2+ word name (e.g., an unnamed test fixture user before any `IDENTITY` fact is confirmed), document ownership checks do not false-reject unless a transcript explicitly names a conflicting person.
- Never downgrade an existing language score on `StudentProfileSnapshot` when an older or lower certificate/CEFR level is synced in `sync_facts_to_profile`.
- `rebuild_pack` (`version > 1`) must update existing `RecommendationCandidate` rows on the same `run` in place rather than inserting duplicate `(run, program)` or `(run, opportunity)` rows.

## Review Focus

- **Single-test-score vs bare-CEFR comparison in `sync_facts_to_profile`:** A student whose profile holds `"B2"` (or `"IELTS 6.0"`) and who confirms an `"IELTS 7.5"` certificate with `cefr_level=None` must end up with `level="IELTS 7.5"`, whereas syncing an older `"IELTS 6.0"` after `"IELTS 7.5"` must keep `"IELTS 7.5"`.
- **Azerbaijani/Turkish transliterated name on certificate or transcript:** A student registered as `"Nərmin Əliyeva"` uploading an English IELTS certificate or transcript printed `"ALIYEVA NARMIN"` (surname first, uppercase, ASCII transliterated) must pass ownership verification (`proven=True`).
- **Mid-semester GPA update on an in-progress degree vs swapping universities:** Updating `Baku State University` `BSc` from `grade="82"` to `grade="91"` (or setting `completed_on`) must succeed and trigger `rebuild_pack`, whereas replacing `Baku State University` with `ADA University` on an existing degree without `allow_identity_override=True` must raise `ProfileVersionRejected("academic_history_identity_mismatch")`.
- **In-place candidate update preserving `Application.candidate` FK:** When `rebuild_pack` runs for `version=2`, an active `Application` card linked to a `version=1` `RecommendationCandidate` must see its `card.chance_line` reflect the new `estimated_chance_pct` without creating a second `RecommendationCandidate` row for that programme.
- **Deduplicated counsellor notifications on repeated mismatch reads:** Re-running `write_facts` or `record_answers` on the same mismatched document or application must not spam duplicate open `Notification` rows for the counsellor.

---

### Task 1: Shared Owner Identity Helpers & Passport / Certificate / Diploma / CV Ownership Enforcement

**Files:**
- Modify: `apps/documents/id_reading.py:195-283`
- Modify: `apps/documents/document_reading.py:330-375`
- Modify: `apps/documents/text_reading.py:360-395`
- Modify: `apps/documents/fact_writer.py:113-140`
- Modify: `apps/documents/ingestion.py:511-600`
- Test: `tests/documents/test_id_reading.py`, `tests/documents/test_text_reading.py`, `tests/documents/test_ingestion.py`

**Interfaces:**
- Produces in `apps/documents/id_reading.py`:
  - `known_owner_names(student: Membership) -> list[str]`
  - `owner_birth_date(student: Membership) -> str | None`
  - `owner_matches_full_name(candidate_name: str, known_names: Iterable[str]) -> bool`
  - `owner_matches_document_text(text: str, known_names: Iterable[str]) -> bool`
  - `raise_identity_mismatch_alert(student: Membership, *, message: str, application: Application | None = None) -> None`
- Updates `apps/documents/text_reading.py`:
  - `prove(kind: str, quotes: Sequence[CertificateQuotes | DiplomaQuotes], layout: AzureLayout, visible: Sequence[str], floor: float, *, identifiers: Sequence[str] = ()) -> list[ReadValue]`

- [ ] **Step 1: Write the failing tests in `tests/documents/test_id_reading.py`, `tests/documents/test_text_reading.py`, and `tests/documents/test_ingestion.py`**

```python
# In tests/documents/test_id_reading.py:
def test_passport_with_mismatched_birth_date_marks_owner_mismatch():
    # Student profile has date_of_birth="2000-01-01", passport has "1998-03-14"
    got = _by_key(read_id(
        kind="PASSPORT", mrz_text=VALID_MRZ, quotes=[ agrees_quotes() ],
        layout=layout_for(VALID_MRZ), visible=(), floor=0.95,
        known_names=["Narmin Aliyeva"], known_birth_date="2000-01-01",
    ))
    assert got["identity.surname"].why == "owner_mismatch"
    assert not got["identity.surname"].proven

# In tests/documents/test_text_reading.py:
def test_certificate_missing_account_holder_name_marks_owner_mismatch():
    got = _by_key(prove(
        "LANGUAGE_CERTIFICATE", [cert(), cert()],
        layout(CERT + " Candidate Name: KAMRAN HASANOV"), (), 0.95,
        identifiers=["Narmin Aliyeva", "Nərmin Əliyeva"],
    ))
    assert all(not v.proven and v.why == "owner_mismatch" for v in got.values())

def test_certificate_with_transliterated_surname_first_matches_owner():
    got = _by_key(prove(
        "LANGUAGE_CERTIFICATE", [cert(), cert()],
        layout(CERT + " Candidate Name: ALIYEVA NARMIN"), (), 0.95,
        identifiers=["Nərmin Əliyeva"],
    ))
    assert got["language.test_score"].proven

# In tests/documents/test_ingestion.py:
def test_uploading_a_friends_cv_is_refused_with_owner_mismatch_and_alerts_counsellor(
    agency_a, django_user_model, counselor_membership, fake_store
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-friend")
        student.user.first_name, student.user.last_name = "Narmin", "Aliyeva"
        student.user.save()
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=student
        )
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        with pytest.raises(UnsupportedUpload, match="owner_mismatch"):
            ingest_uploaded_cv(
                document=document, student=student, client=_openai_client(), store=fake_store
            )
        assert VerifiedFact.objects.filter(student=student).count() == 0
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/pytest --reuse-db tests/documents/test_id_reading.py tests/documents/test_text_reading.py tests/documents/test_ingestion.py -k "owner_mismatch or transliterated_surname_first" -v`
Expected: FAIL (`TypeError` on unexpected keyword arguments `known_birth_date` / `identifiers` and did not raise `UnsupportedUpload`).

- [ ] **Step 3: Implement owner helpers in `apps/documents/id_reading.py` and wire them into `document_reading.py`, `text_reading.py`, `fact_writer.py`, and `ingestion.py`**

- In `apps/documents/id_reading.py`:
  - Add `known_owner_names(student: Membership) -> list[str]`, `owner_birth_date(student: Membership) -> str | None`, `owner_matches_full_name(candidate_name: str, known_names: Iterable[str]) -> bool`, `owner_matches_document_text(text: str, known_names: Iterable[str]) -> bool`, and `raise_identity_mismatch_alert(student: Membership, *, message: str, application: Application | None = None) -> None` (using `Notification.raise_card` on `RoadmapItem.Stage.DOCUMENTS` when an active `CounselorAssignment` exists and no unacknowledged notification with the same `message` exists for `student`).
  - Add optional `known_birth_date: str | None = None` to `read_id`: if `known_birth_date` is provided and `proven.get("identity.date_of_birth")` is present and not equal to `known_birth_date`, set `mismatch = True`.
- In `apps/documents/text_reading.py`:
  - Pass `identifiers=identifiers` into `prove(...)` from `read_text_document`. Inside `prove`, filter `identifiers` to person-name strings (no `@`, no digits, $\ge 2$ alphabetic tokens); if any exist and `not owner_matches_document_text(layout.content, name_identifiers)`, return `[ReadValue(v.key, v.value, v.snippet, False, "owner_mismatch") for v in out]`.
- In `apps/documents/fact_writer.py::write_facts`:
  - When `any(v.why == "owner_mismatch" for v in values)`, call `raise_identity_mismatch_alert(student, message=f"Uploaded document {reading.document_id} does not match the student's identity.")` before returning.
- In `apps/documents/ingestion.py::ingest_uploaded_cv`:
  - Check `known = [n for n in known_owner_names(student) if len(n.split()) >= 2]`. If `known` and `not owner_matches_full_name(extracted.personal_information.full_name, known)`, call `raise_identity_mismatch_alert` and raise `UnsupportedUpload("owner_mismatch")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest --reuse-db tests/documents/test_id_reading.py tests/documents/test_text_reading.py tests/documents/test_document_reading_text.py tests/documents/test_fact_writer.py tests/documents/test_ingestion.py -v`
Expected: PASS

---

### Task 2: Academic Transcript Ownership Verification

**Files:**
- Modify: `apps/documents/transcript.py:244-315`
- Modify: `apps/documents/transcript_pages.py:681-790`
- Modify: `apps/documents/transcript_check.py:440-485`
- Test: `tests/documents/test_transcript.py`, `tests/documents/test_transcript_pages.py`

**Interfaces:**
- Consumes: `known_owner_names`, `owner_matches_full_name`, `owner_matches_document_text`, `raise_identity_mismatch_alert` from `apps/documents/id_reading.py`.
- Produces in `apps/documents/transcript.py`:
  - `transcript_owner_matches(pages: tuple[OcrPage, ...], known_names: Iterable[str]) -> bool`

- [ ] **Step 1: Write the failing tests in `tests/documents/test_transcript.py` and `tests/documents/test_transcript_pages.py`**

```python
# In tests/documents/test_transcript.py:
def test_transcript_owner_matches_accepts_transliterated_owner_and_rejects_friend():
    page_owner = _page(COURSES, lines=("Tələbə: Əliyeva Nərmin Rauf qızı", "Bakı Dövlət Universiteti"))
    page_friend = _page(COURSES, lines=("Student Name: Kamran Hasanov", "Bakı Dövlət Universiteti"))
    assert transcript_owner_matches((page_owner,), ["Narmin Aliyeva"]) is True
    assert transcript_owner_matches((page_friend,), ["Narmin Aliyeva"]) is False

# In tests/documents/test_transcript_pages.py:
def test_assembling_a_friends_transcript_refuses_upload_and_alerts_counsellor(
    agency_a, membership_a, counselor_membership, paid_cycle_a
):
    membership_a.user.first_name, membership_a.user.last_name = "Narmin", "Aliyeva"
    membership_a.user.save()
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    [upload] = _read_all(
        agency_a, membership_a, paid_cycle_a,
        ({}, (PageRead(1, page=_page(lines=("Student Name: Kamran Hasanov",))),)),
    )
    with patch("apps.documents.transcript_pages.read_from_pages") as read:
        assemble(agency_a.id, upload.id)
    read.assert_not_called()
    with tenant_scope(agency_a.id):
        upload.refresh_from_db()
        assert (upload.state, upload.refusal) == ("REFUSED", "owner_mismatch")
        assert not TranscriptReading.objects.filter(document=upload.document).exists()
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/pytest --reuse-db tests/documents/test_transcript.py tests/documents/test_transcript_pages.py -k "owner_matches or friends_transcript" -v`
Expected: FAIL (`ImportError: cannot import name 'transcript_owner_matches'`).

- [ ] **Step 3: Implement `transcript_owner_matches` in `apps/documents/transcript.py` and enforce in `apps/documents/transcript_pages.py::assemble`**

- In `apps/documents/transcript.py`:
  - Implement `transcript_owner_matches(pages: tuple[OcrPage, ...], known_names: Iterable[str]) -> bool`:
    - Filter `known_names` to 2+ word names. If none exist, return `True`.
    - Extract full text across `pages` (all `page.lines` and table cells) and extract labeled name tokens via `_learned(_normalised(pages))`.
    - If `_learned` is non-empty, require that at least one known full name has both its first (given) token and last (surname) token matched in `_learned` (via `same_name_token`) OR matched in the full text without `_learned` containing 2+ tokens that match neither the student's given name nor surname.
    - If `_learned` is empty, require `owner_matches_document_text(full_text, known)` whenever any page line contains `_PERSONAL_LABEL` or `owner_matches_document_text` is checked against full text containing name headers. (Note: if a synthetic test page has no `_PERSONAL_LABEL` and no student name header at all, check `owner_matches_document_text(full_text, known)` when any `_PERSONAL_LABEL` appears or when `len(full_text.split()) > 20`).
- In `apps/documents/transcript_pages.py::assemble`:
  - Load `owner_names = known_owner_names(upload.student)` alongside `personal_names(upload.student)`.
  - After constructing `read_pages = tuple(OcrPage.model_validate(page.page) for page in readable)`, check `if not transcript_owner_matches(read_pages, owner_names):`: call `_finish(tenant_id, upload.id, State.REFUSED, "owner_mismatch")` and `raise_identity_mismatch_alert` inside `tenant_scope(tenant_id), tenant_transaction(tenant_id)`, and return before calling `read_from_pages`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest --reuse-db tests/documents/test_transcript.py tests/documents/test_transcript_pages.py -v`
Expected: PASS

---

### Task 3: Profile & Degree Continuity Lock + Browser Extension Identity Guard

**Files:**
- Modify: `apps/accounts/profile_versions.py:17-49`
- Modify: `apps/portals/answers.py:98-157`
- Test: `tests/accounts/test_profile_versions.py`, `tests/portals/test_ext_api.py`

**Interfaces:**
- Updates `apps/accounts/profile_versions.py`:
  - `create_profile_version(*, student: Membership, snapshot: StudentProfileSnapshot | MinimalProfile, allow_identity_override: bool = False) -> StudentProfileVersion`
- Updates `apps/portals/answers.py`:
  - `record_answers(application: Application, answers: list[Answer]) -> list[PortalAnswer]`

- [ ] **Step 1: Write the failing tests in `tests/accounts/test_profile_versions.py` and `tests/portals/test_ext_api.py`**

```python
# In tests/accounts/test_profile_versions.py:
@pytest.mark.django_db
def test_profile_version_locks_dob_nationality_and_completed_degree_but_allows_gpa_progression(
    agency_a, membership_a, valid_phase1_profile_payload
):
    rejected, schema, create = _contracts()
    with tenant_scope(agency_a.id):
        create(student=membership_a, snapshot=schema.model_validate(valid_phase1_profile_payload))

        # 1. GPA and language improvement on the same degree succeeds:
        progressed = deepcopy(valid_phase1_profile_payload)
        progressed["academic_history"][0]["grade"] = "95"
        v2 = create(student=membership_a, snapshot=schema.model_validate(progressed))
        assert v2.version == 2

        # 2. Changing date_of_birth is rejected:
        bad_dob = deepcopy(progressed)
        bad_dob["date_of_birth"] = "1999-05-05"
        with pytest.raises(rejected, match="date_of_birth_locked"):
            create(student=membership_a, snapshot=schema.model_validate(bad_dob))

        # 3. Changing nationality without a confirmed passport/identity fact is rejected:
        bad_nat = deepcopy(progressed)
        bad_nat["nationality"] = "TR"
        with pytest.raises(rejected, match="nationality_locked"):
            create(student=membership_a, snapshot=schema.model_validate(bad_nat))

        # 4. Swapping the university of an existing degree is rejected:
        bad_deg = deepcopy(progressed)
        bad_deg["academic_history"][0]["institution"] = "ADA University"
        with pytest.raises(rejected, match="academic_history_identity_mismatch"):
            create(student=membership_a, snapshot=schema.model_validate(bad_deg))

        # 5. Counsellor override permits correcting a genuine typo:
        v3 = create(
            student=membership_a,
            snapshot=schema.model_validate(bad_dob),
            allow_identity_override=True,
        )
        assert v3.version == 3
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/pytest --reuse-db tests/accounts/test_profile_versions.py -k "locks_dob_nationality" -v`
Expected: FAIL (`DID NOT RAISE ProfileVersionRejected`).

- [ ] **Step 3: Implement continuity lock in `apps/accounts/profile_versions.py` and portal identity guard in `apps/portals/answers.py`**

- In `apps/accounts/profile_versions.py::create_profile_version`:
  - Add `allow_identity_override: bool = False`.
  - Inside `with transaction.atomic():`, when `isinstance(validated_snapshot, StudentProfileSnapshot)` and `not allow_identity_override`:
    - Find the newest existing `StudentProfileVersion` for `authorized_student` with `schema_version=3`.
    - Validate it as `previous = StudentProfileSnapshot.model_validate(prev_row.snapshot)` (if valid).
    - Enforce:
      1. `validated_snapshot.date_of_birth == previous.date_of_birth` (else `raise_identity_mismatch_alert` + `raise ProfileVersionRejected("date_of_birth_locked")`).
      2. If `validated_snapshot.nationality != previous.nationality`, check whether `VerifiedFact.objects.filter(student=authorized_student, category="IDENTITY", confirmed_at__isnull=False, payload__citizenship=validated_snapshot.nationality).exists()`. If not, `raise_identity_mismatch_alert` + `raise ProfileVersionRejected("nationality_locked")`.
      3. For every record in `previous.academic_history`: require at least one record in `validated_snapshot.academic_history` with `same_name(prev_rec.institution, cur_rec.institution)` and `prev_rec.qualification.casefold() == cur_rec.qualification.casefold()`. Otherwise `raise_identity_mismatch_alert` + `raise ProfileVersionRejected("academic_history_identity_mismatch")`.
- In `apps/portals/answers.py::record_answers`:
  - Define `_PROTECTED_PORTAL_FIELDS = frozenset({"identity.given_names", "identity.surname", "identity.full_name", "identity.date_of_birth", "id_document.number"})`.
  - When `outcome == PortalAnswer.Outcome.CHANGED_OUR_VALUE` and `field in _PROTECTED_PORTAL_FIELDS` and `facts.get(field)`:
    - Check whether `answer.value` matches `facts[field]` (via `same_given_name` / `same_name_token` for name fields, or normalized equality for `date_of_birth` and `id_document.number`).
    - If it does not match, create `AuditEvent(actor=application.student, event="portal.identity_mismatch_typed", object_id=application.id)` and raise a deduplicated counsellor `Notification` on `RoadmapItem.Stage.PORTAL_EXCEPTION`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest --reuse-db tests/accounts/test_profile_versions.py tests/portals/test_ext_api.py -v`
Expected: PASS

---

### Task 4: Monotonic Language Sync & Score-Progression Rebuild Trigger

**Files:**
- Modify: `apps/documents/profile_bridge.py:240-318`
- Modify: `apps/documents/transcript_check.py:593-637`
- Modify: `apps/research/schemas.py:9-49`
- Modify: `apps/research/services.py:113-189`
- Modify: `apps/research/management/commands/run_research_worker.py:17-45`
- Test: `tests/documents/test_profile_bridge.py`, `tests/documents/test_transcript_check.py`

**Interfaces:**
- Produces in `apps/documents/profile_bridge.py`:
  - `pick_higher_language_level(existing_level: str, candidate_level: str) -> str`
  - `has_score_progression(previous: StudentProfileSnapshot, current: StudentProfileSnapshot) -> bool`
  - `request_score_progression_rebuild(student: Membership) -> None`
- Updates `apps/research/schemas.py`:
  - Adds `"rebuild_pack"` to `ResearchMessage.kind`.

- [ ] **Step 1: Write the failing tests in `tests/documents/test_profile_bridge.py`**

```python
def test_sync_facts_to_profile_upgrades_b2_to_ielts_7_5_and_never_downgrades(
    agency_a, membership_a, valid_phase1_profile_payload, monkeypatch
):
    # Profile starts with English level="B2"
    # Confirming IELTS 7.5 upgrades profile to "IELTS 7.5" and queues rebuild_pack
    # Confirming an older IELTS 6.0 afterwards keeps "IELTS 7.5"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/pytest --reuse-db tests/documents/test_profile_bridge.py -k "upgrades_b2_to_ielts" -v`
Expected: FAIL (`level` remains `"B2"` instead of `"IELTS 7.5"`).

- [ ] **Step 3: Implement `pick_higher_language_level`, `has_score_progression`, and `request_score_progression_rebuild`**

- In `apps/documents/profile_bridge.py`:
  - Implement `pick_higher_language_level(existing_level: str, candidate_level: str) -> str` using `_score_to_cefr_rank` from `apps/funding/probability.py` (with numeric test-score comparison when both belong to the same test, and preferring a concrete test score like `"IELTS 7.5"` over a bare CEFR label of equal or lower rank).
  - Implement `has_score_progression(previous: StudentProfileSnapshot, current: StudentProfileSnapshot) -> bool` checking GPA increase (`_normalize_gpa`), completed course count / graduation completion increase, or language CEFR/test score increase.
  - When `sync_facts_to_profile` writes a new `StudentProfileVersion` and `has_score_progression(current_snapshot, updated_snapshot)` is `True`, register `transaction.on_commit(lambda: request_score_progression_rebuild(student))`.
- In `apps/documents/transcript_check.py::_follow_profile`:
  - When `has_score_progression(snapshot, updated)` is `True`, register `transaction.on_commit(lambda: request_score_progression_rebuild(student))`.
- In `apps/research/schemas.py` & `apps/research/services.py`:
  - Add `"rebuild_pack"` to `ResearchMessage.kind`.
  - In `handle_research_message`, if `message.kind == "rebuild_pack"`, call `rebuild_pack(run, rates=rates)`.
  - In `_profile_for(run)`, read the newest `StudentProfileVersion` (`schema_version=3`) for `run.profile_version.student_id`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest --reuse-db tests/documents/test_profile_bridge.py tests/documents/test_transcript_check.py -v`
Expected: PASS

---

### Task 5: In-Place Candidate Update on `rebuild_pack` & Score-Unlocked "New for you" Offers

**Files:**
- Modify: `apps/research/services.py:285-425`
- Modify: `apps/dashboard/new_for_you.py:25-138`
- Test: `tests/research/test_handle_research_message.py`, `tests/dashboard/test_new_for_you.py`

**Interfaces:**
- Updates `apps/research/services.py::_publish`:
  - Reuses and updates existing `RecommendationCandidate` rows on `run` by `program_id` / `opportunity_id` when `version > 1`.
  - Sets `calibration_features["score_unlocked"] = True` on newly added candidates in `version > 1`, and `calibration_features["score_boosted"] = True` + `calibration_features["previous_chance_pct"] = old_chance` when `estimated_chance_pct` or `estimated_funded_chance_pct` rises by $\ge 10$ percentage points.
- Updates `apps/dashboard/new_for_you.py::offers_for`:
  - Surfaces `score_unlocked` and `score_boosted` candidates (including standalone scholarships and fee-free programmes) not yet on `board`.

- [ ] **Step 1: Write the failing tests in `tests/research/test_handle_research_message.py` and `tests/dashboard/test_new_for_you.py`**

```python
# In tests/research/test_handle_research_message.py:
def test_rebuild_pack_updates_existing_candidate_in_place_and_marks_newly_unlocked_candidate(
    agency_a, membership_a
):
    # Verify version=2 updates existing RecommendationCandidate in place (same ID, new chance)
    # and marks a newly eligible programme with calibration_features["score_unlocked"] is True.

# In tests/dashboard/test_new_for_you.py:
def test_score_unlocked_programmes_and_scholarships_are_offered_in_new_for_you(
    agency_a, membership_a, pack
):
    # Verify a newly unlocked scholarship (no fee) and fee-free programme appear in offers_for
    # with kind="UNLOCKED" and their estimated chance, and disappear once added to the board.
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/pytest --reuse-db tests/research/test_handle_research_message.py tests/dashboard/test_new_for_you.py -k "score_unlocked or updates_existing_candidate_in_place" -v`
Expected: FAIL

- [ ] **Step 3: Implement in-place candidate updates in `apps/research/services.py::_publish` and score-unlocked offers in `apps/dashboard/new_for_you.py::offers_for`**

- In `apps/research/services.py::_publish`:
  - Map `existing_by_program = {c.program_id: c for c in RecommendationCandidate.objects.filter(run=run, program_id__isnull=False)}` and `existing_by_award = {c.opportunity_id: c for c in RecommendationCandidate.objects.filter(run=run, opportunity_id__isnull=False)}`.
  - When `version > 1` and a matching candidate exists, update its fields in place, setting `features["score_boosted"] = True` and `features["previous_chance_pct"] = old_chance` if `(new_chance or 0) - (old_chance or 0) >= 10` or `(new_funded or 0) - (old_funded or 0) >= 10` (preserving an earlier `score_unlocked=True` if already set).
  - When `version > 1` and no matching candidate exists on `run`, set `features["score_unlocked"] = True` on the newly created `RecommendationCandidate`.
- In `apps/dashboard/new_for_you.py`:
  - Extend `Offer.kind` to `Literal["FITS", "STRETCH", "OVER", "UNLOCKED"]`.
  - In `offers_for`, after collecting budget-room offers from over-budget pool candidates, also inspect visible candidates on `pack.run_id` with `calibration_features.get("score_unlocked") or calibration_features.get("score_boosted")` that are not in `on_board` (checking `candidate.program_id`, `candidate.opportunity_id`, and `candidate.id`) and not already in `out`:
    - If `candidate.application_fee is None` (fee-free programme or standalone scholarship), emit `Offer(..., kind="UNLOCKED", text=...)`.
    - If `candidate.application_fee is not None` and `candidate.id in in_pack` (a paid programme packed in `version > 1`), evaluate its fee against `free` and `stretch_room` (`FITS`, `STRETCH`, `OVER`) so the student sees it in **New for you** on their Home dashboard.

- [ ] **Step 4: Run the full test suite and static checks**

Run:
- `.venv/bin/ruff check apps/ tests/`
- `.venv/bin/mypy apps/`
- `.venv/bin/python manage.py makemigrations --check --dry-run`
- `.venv/bin/pytest --reuse-db tests/documents/test_id_reading.py tests/documents/test_text_reading.py tests/documents/test_document_reading_text.py tests/documents/test_transcript.py tests/documents/test_transcript_pages.py tests/documents/test_ingestion.py tests/documents/test_profile_bridge.py tests/documents/test_transcript_check.py tests/accounts/test_profile_versions.py tests/portals/test_ext_api.py tests/research/test_handle_research_message.py tests/dashboard/test_new_for_you.py`
Expected: All checks and tests pass with 0 errors.

---

### Task 6: Audit Pass 1 Hardening (Disowned/Refused Upload Filtering, Multi-Upload Transcript Ownership, Unconfirmed Name Bootstrap, Vowel Folding & Grading Scales)

**Files:**
- Modify: `apps/portals/packets.py:844-888`
- Modify: `apps/documents/table.py:254-264`
- Modify: `apps/documents/transcript_pages.py:723-755`
- Modify: `apps/documents/id_reading.py:369-395`
- Modify: `apps/documents/mrz.py:250-305`
- Modify: `apps/documents/views.py:420-440`
- Modify: `apps/documents/profile_bridge.py:228-281,404-435`
- Test: `tests/portals/test_packets.py`, `tests/documents/test_table.py`, `tests/documents/test_transcript_pages.py`, `tests/documents/test_id_reading.py`, `tests/documents/test_profile_bridge.py`

**Interfaces:**
- Updates `_held_uploads` in `apps/portals/packets.py` and `table_for` in `apps/documents/table.py` to exclude `disowned_refs(student)`, `retired_at__isnull=False`, and `TranscriptUpload(state=REFUSED)` document IDs.
- Updates `assemble` in `apps/documents/transcript_pages.py` to check `transcript_owner_matches` on the current `upload`'s pages (`[p for p in readable if p.upload_id == upload.id]`) so `APPEND`/`RETAKE` cannot piggyback on an earlier valid upload.
- Updates `known_owner_names` in `apps/documents/id_reading.py`, `fold_tokens` in `apps/documents/mrz.py`, `_problem_readings` in `apps/documents/views.py`, and `has_score_progression` / `sync_facts_to_profile` in `apps/documents/profile_bridge.py`.

- [x] **Step 1: Write failing tests for each Audit Pass 1 bug and edge case**
- [x] **Step 2: Run the new tests to verify they fail**
- [x] **Step 3: Implement the fixes across `apps/portals/packets.py` and `apps/documents/`**
- [x] **Step 4: Run the tests to verify they pass**

---

### Task 7: Pack Rebuild & Spine Rejection/Deadline Filtering (`apps/research/services.py` & `apps/research/spine.py`)

**Files:**
- Modify: `apps/research/services.py:170-197,349-508`
- Modify: `apps/research/spine.py:87-125,492-565,637-697`
- Test: `tests/research/test_handle_research_message.py`

**Interfaces:**
- Updates `build_student_pack` in `apps/research/spine.py` to accept optional `excluded_program_ids`, `excluded_opportunity_ids`, and `submitted_external_opportunity_ids`, and to populate `SpineResult.program_deadlines`.
- Updates `rebuild_pack` and `_publish` in `apps/research/services.py` so rejected/withdrawn candidates keep `state = REJECTED`, are never re-added to `PackCandidate`, and cannot unlock mandatory-funding programmes via Gate 10, while already-submitted/won external `HOLDER`/`COUNTRY`/`GLOBAL` (`STUDENT_APPLIES_SEPARATELY`) scholarships remain eligible to fund newly unlocked university programmes.

- [x] **Step 1: Write failing tests in `tests/research/test_handle_research_message.py`**
- [x] **Step 2: Run the new tests to verify they fail**
- [x] **Step 3: Implement rejection/deadline filtering in `apps/research/services.py` and `apps/research/spine.py`**
- [x] **Step 4: Run the tests to verify they pass**

---

### Task 8: Funding-Linked "New for you" Offers, Deadlines, Rejections & Board Award Linking (`apps/dashboard/new_for_you.py` & `apps/portals/award_links.py`)

**Files:**
- Modify: `apps/dashboard/new_for_you.py:30-189`
- Modify: `apps/portals/award_links.py:34-177`
- Test: `tests/dashboard/test_new_for_you.py`, `tests/portals/test_award_links.py`

**Interfaces:**
- Updates `offers_for` in `apps/dashboard/new_for_you.py`:
  - Requires every score-unlocked/boosted recommendation to be either a separate viable `FundingOpportunity` or a `Program` related (`grouping.funds` / `winnable_with`) to a viable `FundingOpportunity` already in the student's pack (or carrying its own independent zero-gap funding when no related pack scholarship is dead/rejected).
  - Enforces deadline and rejection checks on both the programme and its related scholarship(s), including Subcase C3-b for already-submitted/won external `HOLDER`/`COUNTRY`/`GLOBAL` `STUDENT_APPLIES_SEPARATELY` scholarships.
  - Names the related pack scholarship in `Offer.score_note` (`"(under <Scholarship>)"`).
- Updates `link_awards` and `award_lines_for` in `apps/portals/award_links.py` to skip rejected/withdrawn or expired awards (except Subcase C3-b).

- [x] **Step 1: Write failing tests in `tests/dashboard/test_new_for_you.py` and `tests/portals/test_award_links.py`**
- [x] **Step 2: Run the new tests to verify they fail**
- [x] **Step 3: Implement funding-linked offer filtering and deadline/rejection guards in `apps/dashboard/new_for_you.py` and `apps/portals/award_links.py`**
- [x] **Step 4: Run full test suite and static analysis**
