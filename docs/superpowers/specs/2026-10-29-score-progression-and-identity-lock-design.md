# Dynamic Mid-Semester Score Progression & Anti-Account-Sharing Identity Lock

**Date:** 2026-10-29  
**Status:** Draft (pending builder check & owner approval)

---

## 1. Intent and Why

Two real-world situations happen during an application cycle:

1. **Legitimate mid-semester score progression:** A student's GPA rises after a new semester's grades land, they complete additional prerequisite courses/ECTS, or they retake an English/German proficiency exam (e.g., moving from `B2` / `IELTS 6.0` to `IELTS 7.5`). The platform must dynamically propagate those verified improvements into the student's profile, refresh admission and scholarship probabilities on their active board cards, re-evaluate the catalogue to unlock previously ineligible programmes and scholarships, and surface newly unlocked options in **New for you** on the student's Home dashboard.
2. **Account-sharing prevention ("friend using the student's account"):** Because a paid cycle includes document reading, AI tailoring, and browser-extension co-pilot packet generation, a student might try to hand their account (or paired browser extension) to a friend so the friend can upload their own transcript/IELTS/CV, swap profile details, or fill their own university portal forms. The platform must lock the account to the single human student who owns it, verify ownership across every document upload and profile edit, and hard-block + alert the assigned counsellor whenever third-party identity data appears.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **G1 — End-to-end document ownership verification:** Verify that the account holder's name (both given name and surname, transliteration-aware via `apps/documents/mrz.py`) matches the person named on every uploaded **passport/ID**, **language certificate**, **diploma**, **academic transcript**, and **CV**, and that any printed date of birth does not contradict the student's locked `date_of_birth`.
- **G2 — Profile & degree continuity lock:** Once a student has a finalized full profile (`schema_version=3`) or a confirmed `IDENTITY` / `ID_DOCUMENT` fact, lock core identity anchors (`date_of_birth`, `nationality` unless backed by a confirmed passport/ID for that citizenship, and already-completed degrees where `completed_on` is set). Allow mid-semester updates to an in-progress degree's `grade`, `grading_scale`, `courses`, and `completed_on`, while refusing attempts to swap an existing degree's `institution` or `qualification` to a different university/degree without a counsellor override.
- **G3 — Extension portal identity guard:** Detect when someone using the paired browser extension overwrites a pre-filled core identity field (`identity.given_names`, `identity.surname`, `identity.date_of_birth`, `id_document.number`) with a value that does not match the student's verified identity, and escalate to the assigned counsellor.
- **G4 — Monotonic language & academic progression sync:** Fix `sync_facts_to_profile` (`apps/documents/profile_bridge.py`) so a newly confirmed language test score (e.g., `IELTS 7.5`) is compared by CEFR/score rank against the existing profile entry rather than being shadowed by an older `B2` or lower test score.
- **G5 — Automatic pack rebuild & live board probability refresh:** Read the student's newest `schema_version=3` `StudentProfileVersion` in `_profile_for(run)` (`apps/research/services.py`), automatically queue a `rebuild_pack` job when `sync_facts_to_profile` or `transcript_check._follow_profile` records an improved GPA, coursework/ECTS, or language score, and update existing `RecommendationCandidate` rows in place on `rebuild_pack` so active `Application` board cards reflect the student's new `% chance` immediately.
- **G6 — Surface score-unlocked programmes & scholarships in "New for you":** Extend `offers_for` (`apps/dashboard/new_for_you.py`) so programmes and standalone scholarships newly unlocked by a mid-semester score improvement (or whose admission/funded chance jumped by $\ge 10$ percentage points and are not yet on the board) appear in **New for you** on the student Home page.

### Non-Goals
- Biometric / facial recognition matching on passport photos.
- Blocking legitimate transliteration differences across Azerbaijani, Turkish, Russian (transliterated), and English spellings (already handled by `mrz.same_given_name` and `mrz.same_name_token`) or patronymic middle tokens (`oğlu`, `qızı`, `-zadeh`, etc.).

### Anti-Goals (Failure Modes to Avoid)
- **Silent downgrade:** A re-read or older language certificate (`IELTS 6.0` or `B2`) overwriting a newly confirmed `IELTS 7.5` (`C1`).
- **False positive lockouts on legitimate mid-semester updates:** Blocking a student from updating their GPA from `3.2` to `3.6`, adding semester 5 courses, or marking an in-progress Bachelor's degree as completed.
- **Breaking `runtime_web` / `runtime_engine` DB role isolation:** `offers_for` and web views must never query shared catalogue tables (`Program`, `FundingOpportunity`, `OutcomeCalibrationRecord`); all catalogue re-evaluation happens in the research worker (`rebuild_pack`) and is stored on tenant-scoped `RecommendationCandidate` rows.
- **Orphaned duplicate candidates on `rebuild_pack`:** Creating duplicate `RecommendationCandidate` rows for the same `(run, program)` or `(run, opportunity)` across pack versions, which would leave stale `version=1` candidates outside `in_pack` and confuse `offers_for`.

---

## 3. Architecture & Detailed Design

### 3.1 Document Ownership Verification (`apps/documents/`)

1. **Shared Owner-Matching Helper (`apps/documents/id_reading.py` & `apps/documents/mrz.py`)**
   - Extract/expose `known_owner_names(student: Membership) -> list[str]` and `owner_birth_date(student: Membership) -> str | None` so all document readers check against the same ground truth:
     - `student.user.get_full_name()` / `first_name + last_name`
     - Confirmed `VerifiedFact` rows in `Category.IDENTITY` (`full_name`, `given_names + surname`)
     - Latest `StudentProfileVersion` (`schema_version=3`) `snapshot["date_of_birth"]` and confirmed `identity.date_of_birth` facts.
   - Expose `owner_matches_full_name(candidate_name: str, known_names: Iterable[str]) -> bool` (requiring both a given-name match via `mrz.same_given_name` and a surname token match via `mrz.same_name_token` against at least one known full name) and `owner_matches_document_text(text: str, known_names: Iterable[str]) -> bool` (checking that for at least one known full name with $\ge 2$ tokens, both the first token / given name and the last token / surname match tokens in `text` via `mrz.same_name_token`).

2. **Passports / ID Documents (`apps/documents/id_reading.py`)**
   - Keep `_owner_matches(given, surname, known)`.
   - Add a date-of-birth check: if `owner_birth_date(reading.student)` is known and the passport's proven/agreed `identity.date_of_birth` differs from it, mark `OWNER_UNCHECKED` keys as `proven=False, why="owner_mismatch"`.

3. **Language Certificates & Diplomas (`apps/documents/text_reading.py`)**
   - In `prove(layout, first, second, kind, identifiers)`:
     - Before relying on `strip_identifiers(layout.content, identifiers)`, verify `owner_matches_document_text(layout.content, identifiers)` (where `identifiers` are the student's `_known_names(reading)`).
     - If `identifiers` is non-empty and the student's given name + surname do not appear anywhere in the unstripped OCR text `layout.content`, return every `ReadValue` with `proven=False, why="owner_mismatch"`.
     - In `apps/documents/fact_writer.py::write_facts`, `if any(v.why == "owner_mismatch" for v in values):` already short-circuits before writing any `VerifiedFact` or syncing to the profile! We extend that branch to also raise a counsellor alert (`Notification.raise_card` on `RoadmapItem.Stage.DOCUMENTS`, deduped per `reading.document_id`) when the student has an active `CounselorAssignment`.

4. **Academic Transcripts (`apps/documents/transcript.py`, `apps/documents/transcript_pages.py`, `apps/documents/transcript_check.py`)**
   - Add `transcript_owner_matches(pages: tuple[OcrPage, ...], known_names: Iterable[str]) -> bool` in `apps/documents/transcript.py`:
     - Collect all text across `pages` (lines and table cells).
     - Inspect any name tokens extracted after `_PERSONAL_LABEL` (`_learned(pages)`): if `_learned(pages)` found explicit student-name tokens after labels like `Name:`, `Surname:`, `Student:`, `Tələbə:`, `Adı, Soyadı:`, verify that at least one known full name matches those learned tokens (both given name and surname via `same_name_token`), OR that `owner_matches_document_text(full_page_text, known_names)` holds and `_learned(pages)` does not name a disjoint given+surname pair.
     - Even when no `_PERSONAL_LABEL` is matched, require `owner_matches_document_text(full_page_text, known_names)` whenever `known_names` has at least one 2+ word name.
   - In `apps/documents/transcript_pages.py::assemble`:
     - Before calling `read_from_pages` (so we never spend Jev calls on a friend's transcript), run `transcript_owner_matches(read_pages, raw_known_names)`.
     - If it fails, finish the upload as `State.REFUSED` with `refusal="owner_mismatch"`, refund/release or stop assembly, and raise a counsellor `Notification` (`RoadmapItem.Stage.DOCUMENTS`).
   - In `apps/documents/transcript_check.py::check_transcript`:
     - Guard against any pre-existing unverified reading whose `upload.refusal == "owner_mismatch"`.

5. **Uploaded CVs (`apps/documents/ingestion.py`)**
   - In `ingest_uploaded_cv`:
     - After `_extract_claims` returns `extracted: CVContent`, check `extracted.personal_information.full_name` against `known_owner_names(student)`.
     - If `known_owner_names(student)` has a 2+ word name and `not owner_matches_full_name(extracted.personal_information.full_name, known_owner_names(student))`:
       - Raise a counsellor `Notification` (`RoadmapItem.Stage.DOCUMENTS`) and raise `UnsupportedUpload("owner_mismatch")` before writing any `VerifiedFact` rows.

---

### 3.2 Profile & Degree Continuity Lock (`apps/accounts/profile_versions.py`)

In `create_profile_version(*, student: Membership, snapshot: StudentProfileSnapshot | MinimalProfile, allow_identity_override: bool = False)`:

- When `isinstance(snapshot, StudentProfileSnapshot)` and `not allow_identity_override`:
  - Load the latest existing full profile version (`schema_version=3`) for `student`, if any.
  - If a previous `StudentProfileSnapshot` exists:
    1. **`date_of_birth` lock:** `snapshot.date_of_birth` must equal `previous.date_of_birth`. Otherwise raise `ProfileVersionRejected("date_of_birth_locked")` and alert the counsellor.
    2. **`nationality` lock:** If `snapshot.nationality != previous.nationality`, check whether `student` has a confirmed `VerifiedFact` in `Category.IDENTITY` (`citizenship`) or `Category.ID_DOCUMENT` matching `snapshot.nationality`. If not, raise `ProfileVersionRejected("nationality_locked")` and alert the counsellor.
    3. **Academic history continuity lock:**
       - Every **completed** degree in `previous.academic_history` (`record.completed_on is not None`) must still be present in `snapshot.academic_history` with the same `institution` (compared via `degree_match.same_name`) and `qualification` (`casefold`).
       - If `previous.academic_history` had an **in-progress** degree (`record.expected_completion is not None` and `record.completed_on is None`), `snapshot.academic_history` may update its `grade`, `grading_scale`, `courses`, `expected_completion`, or transition it to `completed_on`, and may *append* a new degree, but may **not** replace that in-progress degree's `institution` with a different university (`not same_name(prev.institution, cur.institution)`) without `allow_identity_override=True`. Otherwise raise `ProfileVersionRejected("academic_history_identity_mismatch")` and alert the counsellor.

---

### 3.3 Browser Extension Portal Identity Guard (`apps/portals/answers.py`)

- In `record_answers(application: Application, answers: list[Answer])`:
  - When an answer has `answer.kind == "changed"` (`PortalAnswer.Outcome.CHANGED_OUR_VALUE`) on a core identity field (`field in {"identity.given_names", "identity.surname", "identity.full_name", "identity.date_of_birth", "id_document.number"}`):
    - Compare `answer.value` against the student's `facts[field]` (using `mrz.same_given_name` / `mrz.same_name_token` for name fields and normalized equality for `date_of_birth` / `id_document.number`).
    - If the user typed a different person's name, birth date, or passport number over the student's verified value:
      - Record an `AuditEvent(actor=application.student, event="portal.identity_mismatch_typed", object_id=application.id)` and raise a counsellor `Notification` on `RoadmapItem.Stage.PORTAL_EXCEPTION` (`"The student overwrote their verified {field} on the application portal for {application}. Check that the account is not being used by another person."`).

---

### 3.4 Dynamic Mid-Semester Score Progression & "New for you" (`apps/documents/`, `apps/research/`, `apps/dashboard/`)

1. **Monotonic Language Score Sync (`apps/documents/profile_bridge.py`)**
   - In `sync_facts_to_profile`:
     - When merging a confirmed `LANGUAGE` fact (`test_name`, `test_score`, `cefr_level`) into `existing_ev` (or building a new `LanguageEvidence`):
       - Build the candidate level string: `candidate_level = raw_cefr or (f"{test_name} {score}" if test_name and score else "")`.
       - Compare `candidate_level` against `existing_ev.level` using `_score_to_cefr_rank` from `apps/funding/probability.py` (plus numeric score tie-breaking when both name the same test, e.g. `IELTS 7.5` > `IELTS 6.5`, and preferring a specific test score like `IELTS 7.5` over a bare CEFR label `B2`/`C1` of equal or lower rank).
       - Keep whichever level is higher so a new `IELTS 7.5` upgrades an older `B2` or `IELTS 6.5`, while an older sitting never downgrades a higher score.

2. **Detecting Score Improvements & Enqueueing `rebuild_pack`**
   - Add helper `has_score_progression(previous: StudentProfileSnapshot, current: StudentProfileSnapshot) -> bool` in `apps/accounts/profile_versions.py` (or `apps/documents/profile_bridge.py`):
     - Returns `True` when:
       - Any academic record's normalized GPA (`_normalize_gpa(grade, grading_scale)`) increased;
       - Any academic record gained new completed courses (`len([c for c in courses if not c.in_progress])` increased) or transitioned from `expected_completion` to `completed_on`;
       - Any language evidence entry's CEFR rank (`_score_to_cefr_rank(ev.level)`) or numeric test score increased, or a new language with `status == "HAVE"` was added.
   - In `sync_facts_to_profile` (`apps/documents/profile_bridge.py`) and `_follow_profile` (`apps/documents/transcript_check.py`):
     - When `has_score_progression(current_snapshot, updated_snapshot)` is `True`, register a `transaction.on_commit` hook `request_score_progression_rebuild(student)` that finds the student's latest `RecommendationRun` (with `state in {PUBLISHED, DRAFT_READY}`) and enqueues `ResearchMessage(kind="rebuild_pack", tenant_id=student.tenant_id, run_id=run.id)`.
   - Add `"rebuild_pack"` to `ResearchMessage.kind` in `apps/research/schemas.py` and handle it in `apps/research/Services.py::handle_research_message` (or `run_research_worker.py`) by calling `rebuild_pack(run, rates=rates)`.

3. **Reading Latest Profile & Updating Candidates In-Place (`apps/research/services.py`)**
   - Update `_profile_for(run: RecommendationRun)`:
     - Look up the student from `run.profile_version.student_id` and load that student's newest `StudentProfileVersion` with `schema_version=3` (falling back to `run.profile_version` if none is newer).
   - Update `_publish` in `apps/research/services.py`:
     - Before creating `RecommendationCandidate` rows for `version > 1`, load existing `RecommendationCandidate` rows on `run` indexed by `program_id` and `opportunity_id`.
     - If a `RecommendationCandidate` already exists on `run` for that `program_id` (or `opportunity_id`):
       - Record `old_chance = existing.estimated_chance_pct` and `old_funded = existing.estimated_funded_chance_pct`.
       - Update the existing `RecommendationCandidate` row in place with the new `funding_gap`, `funding_gap_is_placeholder`, `currency`, `self_funded`, `funding_condition`, `estimated_chance_pct`, `estimated_funded_chance_pct`, `calibration_features`, `provenance_reason_code`, `provenance_body_id`, `rank`, and `_program_copy` / `_award_copy`.
       - If `version > 1` and `(new_chance - old_chance >= 10 or new_funded - old_funded >= 10)`, record `"previous_chance_pct": old_chance` (and `"score_boosted": True`) inside `calibration_features`.
       - Because `Application.candidate` FK points to this `RecommendationCandidate`, every active card on the student's and counsellor's board automatically displays the updated `% chance`!
     - If no `RecommendationCandidate` existed on `run` for that `program_id` (or `opportunity_id`) and `version > 1` (meaning the programme or scholarship was previously ineligible/unpacked and is now unlocked!):
       - Create the `RecommendationCandidate` row and mark `calibration_features["score_unlocked"] = True`.

4. **Surfacing Newly Unlocked Options in "New for you" (`apps/dashboard/new_for_you.py`) & Funding/Deadline/Rejection Rules**
   - **No Resurrection of Rejected Candidates (`apps/research/services.py::_publish` & `apps/research/spine.py::build_student_pack`):**
     - On `rebuild_pack` (`version > 1`), if an existing `RecommendationCandidate` has `state == REJECTED` (or the student has an `Application` with `outcome in ("REJECTED", "WITHDRAWN")` or `funding_outcome in ("REJECTED", "WITHDRAWN")`), keep `state = REJECTED`, exclude the rejected/withdrawn `program_id` / `opportunity_id` from `build_student_pack`, and never create a `PackCandidate` row for it.
     - If the student already submitted or won an external `HOLDER` / `COUNTRY` / `GLOBAL` scholarship (`route == "STUDENT_APPLIES_SEPARATELY"`, `state in ("SUBMITTED", "CONFIRMED")` or `outcome in ("ADMITTED", "ADMITTED_CONDITIONAL")`, `outcome not in ("REJECTED", "WITHDRAWN")`), preserve its eligibility in `build_student_pack` even after its external deadline passes so it can fund newly score-unlocked programmes whose own university deadlines are still open (Subcase C3-b).
   - **Funding-Linked & Deadline/Rejection-Aware Score Offers (`apps/dashboard/new_for_you.py::offers_for`):**
     - Score-unlocked / score-boosted offers must come **either** as:
       1. A **separate `FundingOpportunity`** (`candidate.opportunity_id is not None`) whose deadline has not passed, that has not been rejected/withdrawn, and whose covered programmes in the run (if any) are not all rejected/expired; **or**
       2. A **`Program`** (`candidate.opportunity_id is None`) that is related (`grouping.funds` / `winnable_with`) to at least one **viable `FundingOpportunity` already in the student's pack** (not rejected, not `REJECTED`/`WITHDRAWN` on the board, and not past its deadline unless Subcase C3-b holds), or carries its own independent zero-gap attached funding when no related pack scholarship is dead/rejected.
     - Never offer a programme under a scholarship whose deadline has passed (unless Subcase C3-b holds) or from which the student was rejected/withdrawn (`Application.outcome in ("REJECTED", "WITHDRAWN")` or `RecommendationCandidate.state == "REJECTED"`).
     - Never offer a programme or scholarship whose own deadline (`funding_card["deadline"]` or `calibration_features["application_deadline"]`) has passed or that the student already got `REJECTED`/`WITHDRAWN` from.
     - Name the related pack scholarship in `Offer.score_note` (e.g., `"unlocked by your updated scores (under DAAD Study Scholarship)"`).
   - **Board Award Linking (`apps/portals/award_links.py`):**
     - `link_awards` and `award_lines_for` must not link a newly added programme card to (or prompt/auto-create) an award whose `Application.outcome in ("REJECTED", "WITHDRAWN")` or whose deadline has passed unless Subcase C3-b holds.

### 3.5 Audit Pass 1 Hardening (`apps/portals/packets.py`, `apps/documents/`)
- Exclude `disowned_refs(student)`, `retired_at__isnull=False`, and `TranscriptUpload(state=REFUSED)` document IDs in `apps/portals/packets.py::_held_uploads` and `apps/documents/table.py::table_for` so a friend's refused upload is never attached to a portal packet or marked `UPLOADED` on the document table.
- In `apps/documents/transcript_pages.py::assemble`, validate `transcript_owner_matches` on the newly uploaded `upload`'s own pages as well as the combined cycle pages so `APPEND`/`RETAKE` cannot piggyback on an earlier valid upload.
- In `apps/documents/id_reading.py::known_owner_names`, fall back to unconfirmed non-disowned `IDENTITY` facts when `student.user.get_full_name()` is blank and no confirmed `IDENTITY` fact exists yet, and support ASCII `E↔A` vowel folding in `apps/documents/mrz.py::fold_tokens` for multi-`ə` Azerbaijani surnames (`Memmedzade` / `Mammadzada`).
- Make `owner_mismatch` / `owner_unknown` problem lines in `apps/documents/views.py` kind-aware, fix `is_downgrade` in `apps/documents/profile_bridge.py::sync_facts_to_profile` for test scores without `cefr_level`, and support Swiss (`1.0-6.0`) and UK honours (`First Class` > `2:1` > `2:2` > `Third`) scales in `has_score_progression`.

---

## 4. Builder Decisions (Marked as Engineering Calls)
- **Counsellor alert deduplication:** Use `Notification.raise_card` with `RoadmapItem.Stage.DOCUMENTS` (for document/profile identity mismatches) and `RoadmapItem.Stage.PORTAL_EXCEPTION` (for portal form identity overwrites), checking for an existing open notification mentioning the document/application before creating a duplicate.
- **Transliteration tolerance on transcripts & certificates:** Reuse `apps/documents/mrz.py` (`same_given_name`, `same_name_token`, ` PATRONYMICS`) so Azerbaijani/Turkish/Russian/English name variants (`Məmmədov` / `Mammadov`, `Əli` / `Ali`) never trigger false `owner_mismatch` flags.
- **Score-progression rebuild rate limit:** If a student confirms 5 facts in 10 seconds, coalesce or reuse `rebuild_pack` via `transaction.on_commit` so each committed profile improvement triggers a clean pack rebuild.
