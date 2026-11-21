from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from apps.accounts.models import StudentProfileVersion
from apps.accounts.profile_versions import create_profile_version
from apps.accounts.schemas import ExperienceRecord, LanguageEvidence, StudentProfileSnapshot
from apps.funding.models import RecommendationRun
from apps.research.queue import enqueue_research
from apps.research.schemas import ResearchMessage
from apps.tenancy.models import Membership

from .degree_match import same_degree
from .models import VerifiedFact
from .schemas import _cefr_code
from .text_reading import TESTS
from .verification import (
    disowned_refs,
    live_retired_refs,
    retired_hides,
    retired_refs,
    unsuperseded_facts,
)

logger = logging.getLogger(__name__)
_SOURCE_PREFIX = "profile-bridge"


def _latest_profile(student: Membership) -> StudentProfileVersion | None:
    return StudentProfileVersion.objects.filter(student=student).order_by("-version").first()


def _education_payload(record: dict[str, object]) -> dict[str, object]:
    """Canonical EDUCATION keys -- the ones verification.py reads.

    city and start_date are absent from AcademicRecord, so they stay None:
    a fact that does not state a detail never conflicts with a CV that does.
    """
    payload: dict[str, object] = {
        "institution_original": record["institution"],
        "degree_as_awarded": record["qualification"],
        "city": None,
        "country": record["country_code"],
        "start_date": None,
        "end_date": record.get("completed_on") or record.get("expected_completion"),
        "field": record.get("field"),
        "grade_native": record.get("grade"),
        "grade_scale": record.get("grading_scale"),
    }
    courses = record.get("courses")
    if isinstance(courses, list) and courses:
        payload["courses"] = courses
    return payload


def _language_payload(record: dict[str, object]) -> dict[str, object]:
    return {
        "language": record["language"],
        "cefr_level": record["level"],
        "test_name": None,
        "test_score": None,
        "evidence_type": record.get("evidence_type"),
    }


_SECTIONS: tuple[tuple[str, str, Callable[[dict[str, object]], dict[str, object]]], ...] = (
    ("academic_history", VerifiedFact.Category.EDUCATION, _education_payload),
    ("language_evidence", VerifiedFact.Category.LANGUAGE, _language_payload),
)


def _current_fact_for_slot(
    student: Membership, *, category: str, index: int
) -> VerifiedFact | None:
    """The live fact for one profile slot.

    Keyed on the slot index, not the profile version: source_ref carries the
    version for provenance, so it changes every time the student saves, and
    matching on it would make every run look like a brand-new fact.

    # ponytail: slot index is the record identity. Reordering academic_history
    # makes two slots supersede each other's facts; the fix is a stable id on
    # AcademicRecord, which is an apps.accounts schema change, not this module's.
    """
    return (
        VerifiedFact.objects.filter(
            student=student,
            category=category,
            source_ref__startswith=f"{_SOURCE_PREFIX}:",
            source_ref__endswith=f":{index}",
            superseded_by__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )


@transaction.atomic
def bridge_profile_to_facts(student: Membership) -> tuple[VerifiedFact, ...]:
    """Seed the ledger from the student's latest profile snapshot.

    Idempotent: an unchanged slot writes nothing, a changed slot writes exactly
    one superseding row, and slots that did not change are untouched. Everything
    written is a candidate (confirmed_by=None) -- the bridge never produces
    something the generator may use.
    """
    profile = _latest_profile(student)
    if profile is None:
        return ()
    created: list[VerifiedFact] = []
    held_degrees = list(
        unsuperseded_facts(student)
        .filter(category=VerifiedFact.Category.EDUCATION)
        .exclude(source_ref__startswith=f"{_SOURCE_PREFIX}:")
    )
    for section, category, build_payload in _SECTIONS:
        for index, record in enumerate(profile.snapshot.get(section, [])):
            if not isinstance(record, dict):
                continue
            payload = build_payload(record)
            existing = _current_fact_for_slot(student, category=category, index=index)
            if existing is not None and existing.payload == payload:
                continue
            if (
                existing is None
                and category == VerifiedFact.Category.EDUCATION
                and any(
                    isinstance(f.payload, dict) and same_degree(f.payload, record) == "same"
                    for f in held_degrees
                )
            ):
                continue
            created.append(
                VerifiedFact.objects.create(
                    student=student,
                    category=category,
                    payload=payload,
                    source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                    source_ref=f"{_SOURCE_PREFIX}:{profile.id}:{index}",
                    confirmed_by=None,
                    supersedes=existing,
                    created_by=student,
                )
            )
    return tuple(created)


def _parse_iso_date(raw: object) -> date | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    m_ym = re.match(r"^(\d{4})-(\d{2})$", text)
    if m_ym:
        try:
            return date(int(m_ym.group(1)), int(m_ym.group(2)), 1)
        except ValueError:
            return None
    m_y = re.match(r"^(\d{4})$", text)
    if m_y:
        try:
            return date(int(m_y.group(1)), 1, 1)
        except ValueError:
            return None
    return None


def _fact_span_months(
    start_raw: object, end_raw: object, *, today: date, default_months: int = 0
) -> int:
    start_dt = _parse_iso_date(start_raw)
    end_dt = _parse_iso_date(end_raw)
    if start_dt is not None:
        if end_dt is None and start_dt <= today:
            end_dt = today
        if end_dt is not None and end_dt >= start_dt:
            months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
            return max(1, min(600, months))
    return default_months


def _fact_month_set(start_raw: object, end_raw: object, *, today: date) -> set[int]:
    start_dt = _parse_iso_date(start_raw)
    end_dt = _parse_iso_date(end_raw)
    if start_dt is None:
        return set()
    if end_dt is None and start_dt <= today:
        end_dt = today
    if end_dt is None or end_dt < start_dt:
        return set()
    start_ym = start_dt.year * 12 + start_dt.month
    end_ym = end_dt.year * 12 + end_dt.month
    if end_ym == start_ym:
        return {start_ym}
    return set(range(start_ym, min(start_ym + 600, end_ym)))


def _experience_record_from_fact(
    fact: VerifiedFact, *, today: date
) -> ExperienceRecord | None:
    p = fact.payload if isinstance(fact.payload, dict) else {}
    if fact.category == VerifiedFact.Category.EXPERIENCE:
        title = str(p.get("title") or "").strip()
        employer = str(p.get("employer") or "").strip()
        if not title and not employer:
            return None
        summary = f"{title} at {employer}" if (title and employer) else (title or employer)
        title_cf = title.casefold()
        kind: Literal["WORK", "RESEARCH", "INTERNSHIP", "OTHER"]
        if "intern" in title_cf or "trainee" in title_cf:
            kind = "INTERNSHIP"
        elif bool(p.get("unpaid")):
            kind = "OTHER"
        else:
            kind = "WORK"
        raw_months = p.get("months")
        if isinstance(raw_months, int) and 0 <= raw_months <= 600:
            months = raw_months
        else:
            months = _fact_span_months(
                p.get("start_date"), p.get("end_date"), today=today, default_months=0
            )
        return ExperienceRecord(kind=kind, summary=summary[:1000], months=months)
    if fact.category == VerifiedFact.Category.RESEARCH:
        thesis = str(p.get("thesis_title") or p.get("title") or "").strip()
        inst = str(p.get("institution") or "").strip()
        if not thesis and not inst:
            return None
        summary = f"{thesis} ({inst})" if (thesis and inst) else (thesis or inst)
        raw_months = p.get("months")
        if isinstance(raw_months, int) and 0 <= raw_months <= 600:
            months = raw_months
        else:
            months = _fact_span_months(
                p.get("start_date"), p.get("end_date"), today=today, default_months=0
            )
        return ExperienceRecord(kind="RESEARCH", summary=summary[:1000], months=months)
    return None


def _deduplicated_experience_from_facts(
    facts: list[VerifiedFact],
    *,
    today: date,
    existing: tuple[ExperienceRecord, ...] = (),
) -> list[ExperienceRecord]:
    by_key: dict[tuple[str, str], ExperienceRecord] = {
        (rec.kind, rec.summary.casefold()): rec for rec in existing
    }
    fact_by_key: dict[tuple[str, str], tuple[ExperienceRecord, VerifiedFact]] = {}
    for fact in facts:
        rec = _experience_record_from_fact(fact, today=today)
        if rec is not None:
            fact_by_key[(rec.kind, rec.summary.casefold())] = (rec, fact)
    covered_by_kind: dict[str, set[int]] = {}
    for key, (rec, fact) in fact_by_key.items():
        p = fact.payload if isinstance(fact.payload, dict) else {}
        raw_months = p.get("months")
        if not (isinstance(raw_months, int) and 0 <= raw_months <= 600):
            month_set = _fact_month_set(p.get("start_date"), p.get("end_date"), today=today)
            if month_set:
                covered = covered_by_kind.setdefault(rec.kind, set())
                non_overlapping = len(month_set - covered)
                covered |= month_set
                rec = rec.model_copy(update={"months": min(600, non_overlapping)})
        by_key[key] = rec
    return list(by_key.values())[:50]


def experience_records_from_facts(
    student: Membership, *, today: date | None = None
) -> list[ExperienceRecord]:
    """Build deduplicated `ExperienceRecord` rows from confirmed `EXPERIENCE` / `RESEARCH` facts."""
    today_dt = today or timezone.localdate()
    disowned = disowned_refs(student)
    retired, live = retired_refs(student), live_retired_refs(student)
    facts = [
        f
        for f in unsuperseded_facts(student)
        .filter(
            category__in=(VerifiedFact.Category.EXPERIENCE, VerifiedFact.Category.RESEARCH),
            confirmed_at__isnull=False,
        )
        .exclude(source_ref__in=disowned)
        .exclude(source_ref__startswith=f"{_SOURCE_PREFIX}:")
        .order_by("created_at")
        if not retired_hides(f, retired, live)
    ]
    return _deduplicated_experience_from_facts(facts, today=today_dt)


_CEFR_RANK: dict[str, int] = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
_EV_TYPE_RANK: dict[str, int] = {"OTHER": 1, "ATTESTED": 2, "DEGREE": 3, "TEST": 4}


def _language_level_rank(level: str) -> tuple[int, Decimal]:
    from apps.funding.eligibility import _extract_test_and_score, _level_to_cefr

    cleaned = level.strip()
    if not cleaned:
        return (0, Decimal(0))
    upper = cleaned.upper()
    if upper in _CEFR_RANK:
        return (_CEFR_RANK[upper], Decimal(0))
    ts = _extract_test_and_score(cleaned)
    score = Decimal(str(ts[1])) if ts is not None else Decimal(0)
    inferred_cefr = _level_to_cefr(cleaned)
    if inferred_cefr is None and re.search(
        r"\b(?:native|mother\s+tongue|bilingual|first\s+language)\b", cleaned.casefold()
    ):
        inferred_cefr = "C2"
    if inferred_cefr is None:
        cefr_tok = str(_cefr_code(cleaned) or "").strip().upper()
        if cefr_tok in _CEFR_RANK:
            inferred_cefr = cefr_tok
    rank = _CEFR_RANK.get(inferred_cefr or "", 0)
    if ts is None and rank == 0:
        nums = re.findall(r"\d+(?:\.\d+)?", cleaned)
        score = Decimal(nums[-1]) if nums else Decimal(0)
    return (rank, score)


def pick_higher_language_level(old_level: str, new_level: str) -> str:
    """Return whichever of `old_level` and `new_level` represents stronger evidence."""
    if not old_level.strip():
        return new_level
    if not new_level.strip():
        return old_level
    old_rank = _language_level_rank(old_level)
    new_rank = _language_level_rank(new_level)
    if new_rank >= old_rank:
        return new_level
    return old_level


def _parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value.replace(",", "."))
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _uk_honours_rank(grade: str | None) -> int | None:
    if not grade:
        return None
    low = grade.strip().casefold()
    if "first" in low or low in ("1st", "1st class"):
        return 4
    if "2:1" in low or "2.1" in low or "upper second" in low or "ii.i" in low:
        return 3
    if "2:2" in low or "2.2" in low or "lower second" in low or "ii.ii" in low:
        return 2
    if "third" in low or low in ("3rd", "3rd class"):
        return 1
    return None


def _is_inverted_grade_scale(scale: str) -> bool:
    low = scale.casefold()
    if "6.0" in low or "1-6" in low or "swiss" in low:
        return False
    return any(
        token in low
        for token in ("german", "austrian", "bavarian", "1.0-5.0", "1-5", "1.0-4.0", "1 - 5")
    )


def has_score_progression(old: StudentProfileSnapshot, new: StudentProfileSnapshot) -> bool:
    """True when `new` improves on `old` in GPA/grade, completed courses, or language evidence."""
    old_langs = {ev.language.casefold(): ev for ev in old.language_evidence}
    for ev in new.language_evidence:
        prev_ev = old_langs.get(ev.language.casefold())
        if prev_ev is None:
            return True
        if _EV_TYPE_RANK.get(ev.evidence_type, 0) > _EV_TYPE_RANK.get(prev_ev.evidence_type, 0):
            return True
        if _language_level_rank(ev.level) > _language_level_rank(prev_ev.level):
            return True

    for cur in new.academic_history:
        cur_fact = {
            "institution_original": cur.institution,
            "degree_type": cur.qualification,
            "field": cur.field,
        }
        prev = next(
            (
                h
                for h in old.academic_history
                if same_degree(
                    {
                        "institution_original": h.institution,
                        "degree_type": h.qualification,
                        "field": h.field,
                    },
                    cur_fact,
                )
                == "same"
                or (
                    h.institution.casefold() == cur.institution.casefold()
                    and h.qualification.casefold() == cur.qualification.casefold()
                )
            ),
            None,
        )
        if prev is None:
            return True
        prev_completed = sum(1 for c in prev.courses if not c.in_progress)
        cur_completed = sum(1 for c in cur.courses if not c.in_progress)
        if cur_completed > prev_completed:
            return True
        if prev.completed_on is None and cur.completed_on is not None:
            return True
        prev_uk = _uk_honours_rank(prev.grade)
        cur_uk = _uk_honours_rank(cur.grade)
        if prev_uk is not None and cur_uk is not None:
            if cur_uk > prev_uk:
                return True
            continue
        prev_g = _parse_decimal(prev.grade)
        cur_g = _parse_decimal(cur.grade)
        if prev_g is not None and cur_g is not None and cur_g != prev_g:
            scale = (cur.grading_scale or prev.grading_scale or "").casefold()
            if _is_inverted_grade_scale(scale):
                if cur_g < prev_g:
                    return True
            elif cur_g > prev_g:
                return True
    old_exp_months = sum(r.months for r in (old.experience or ()))
    new_exp_months = sum(r.months for r in (new.experience or ()))
    if new_exp_months > old_exp_months:
        return True
    return False


def enqueue_research_message(message: ResearchMessage) -> bool:
    try:
        enqueue_research(message, queue_url=settings.RESEARCH_QUEUE_URL)
        return True
    except Exception:
        logger.exception("rebuild_pack dispatch failed for run %s", message.run_id)
        return False


def request_score_progression_rebuild(student: Membership) -> bool:
    """Enqueue a `rebuild_pack` message for the student's active PUBLISHED run, if any."""
    run = (
        RecommendationRun.objects.filter(
            profile_version__student=student,
            state=RecommendationRun.State.PUBLISHED,
        )
        .order_by("-created_at")
        .first()
    )
    if run is None:
        return False
    return enqueue_research_message(
        ResearchMessage(kind="rebuild_pack", tenant_id=student.tenant_id, run_id=run.id)
    )


@transaction.atomic
def sync_facts_to_profile(student: Membership) -> StudentProfileVersion | None:
    """Propagate newly confirmed `LANGUAGE` and `EDUCATION` facts from `VerifiedFact`
    into a new `StudentProfileVersion` when the student already has a finalized profile.

    Mirrors `transcript_check._follow_profile`: if the student has not completed the
    consultation questionnaire yet (`latest is None`), returns `None` so onboarding
    prefills from the ledger when it runs.
    """
    latest = (
        StudentProfileVersion.objects.filter(student=student, schema_version=3)
        .order_by("-version")
        .first()
    )
    if latest is None or not isinstance(latest.snapshot, dict):
        return None
    raw_snap = (
        {k: v for k, v in latest.snapshot.items() if k != "weights"}
        if latest.snapshot.get("weights") == {}
        else latest.snapshot
    )
    try:
        snapshot = StudentProfileSnapshot.model_validate(raw_snap)
    except ValidationError:
        logger.warning(
            "profile version %s does not validate; sync_facts_to_profile skipped", latest.id
        )
        return None

    disowned = disowned_refs(student)
    retired, live = retired_refs(student), live_retired_refs(student)
    confirmed_facts = [
        f
        for f in unsuperseded_facts(student)
        .filter(
            category__in=(
                VerifiedFact.Category.LANGUAGE,
                VerifiedFact.Category.EDUCATION,
                VerifiedFact.Category.EXPERIENCE,
                VerifiedFact.Category.RESEARCH,
            ),
            confirmed_at__isnull=False,
        )
        .exclude(source_ref__in=disowned)
        .order_by("created_at")
        if not retired_hides(f, retired, live)
    ]
    if not confirmed_facts:
        return None

    history = list(snapshot.academic_history)
    teaching_langs = list(snapshot.acceptable_teaching_languages)
    lang_ev_by_name: dict[str, LanguageEvidence] = {
        ev.language.casefold(): ev for ev in snapshot.language_evidence
    }
    exp_facts: list[VerifiedFact] = []

    today = timezone.localdate()
    cefr_codes = ("A1", "A2", "B1", "B2", "C1", "C2")
    for fact in confirmed_facts:
        p = fact.payload if isinstance(fact.payload, dict) else {}
        if fact.category in (VerifiedFact.Category.EXPERIENCE, VerifiedFact.Category.RESEARCH):
            if _experience_record_from_fact(fact, today=today) is not None:
                exp_facts.append(fact)
        elif fact.category == VerifiedFact.Category.EDUCATION:
            grade_val = str(p.get("grade_native") or "").strip()
            scale_val = str(p.get("grade_scale") or "").strip()
            field_val = str(p.get("field") or "").strip()
            end_dt = _parse_iso_date(p.get("end_date"))
            for idx, held in enumerate(history):
                if same_degree(p, held.model_dump(mode="json")) == "same":
                    updates: dict[str, object] = {}
                    if grade_val and grade_val != "not stated":
                        updates["grade"] = grade_val[:50]
                    if scale_val and scale_val != "not stated":
                        updates["grading_scale"] = scale_val[:100]
                    if field_val and held.field in ("", "not stated"):
                        updates["field"] = field_val[:200]
                    if end_dt is not None and held.completed_on is None and end_dt <= today:
                        updates["completed_on"] = end_dt
                        updates["expected_completion"] = None
                    if updates:
                        candidate_rec = held.model_copy(update=updates)
                        if candidate_rec != held:
                            history[idx] = candidate_rec
                    break
        elif fact.category == VerifiedFact.Category.LANGUAGE:
            test_name = str(p.get("test_name") or "").strip()
            raw_lang = str(p.get("language") or TESTS.get(test_name) or "").strip()
            if not raw_lang:
                continue
            raw_cefr = str(_cefr_code(p.get("cefr_level")) or "").strip()
            score = str(p.get("test_score") or "").strip()
            matched_lang = next(
                (tl for tl in teaching_langs if tl.casefold() == raw_lang.casefold()),
                None,
            )
            if matched_lang is None:
                if len(teaching_langs) >= 10:
                    continue
                matched_lang = raw_lang[:100]
                teaching_langs.append(matched_lang)

            existing_ev = lang_ev_by_name.get(matched_lang.casefold())
            raw_ev = str(p.get("evidence_type") or "").strip().upper()
            fact_ev_type: Literal["ATTESTED", "TEST", "DEGREE", "OTHER"]
            if test_name or score or raw_ev == "TEST":
                fact_ev_type = "TEST"
            elif raw_ev == "DEGREE":
                fact_ev_type = "DEGREE"
            elif raw_ev == "OTHER":
                fact_ev_type = "OTHER"
            else:
                fact_ev_type = "ATTESTED"

            from apps.funding.eligibility import _level_to_cefr

            test_and_score_str = f"{test_name} {score}".strip() if score else test_name
            own_candidate_level = raw_cefr or test_and_score_str
            inferred_test_cefr = _level_to_cefr(test_and_score_str) if test_and_score_str else None
            preserved_cefr = (
                existing_ev.level
                if (
                    existing_ev is not None
                    and existing_ev.evidence_type == "TEST"
                    and fact_ev_type == "TEST"
                    and existing_ev.level.upper() in cefr_codes
                    and (
                        inferred_test_cefr is None
                        or _CEFR_RANK.get(inferred_test_cefr, 0)
                        >= _CEFR_RANK.get(existing_ev.level.upper(), 0)
                    )
                )
                else ""
            )
            candidate_level = raw_cefr or preserved_cefr or test_and_score_str
            if not candidate_level:
                continue
            avail_by = _parse_iso_date(p.get("test_date")) or today
            if existing_ev is not None:
                prev_auth = _EV_TYPE_RANK.get(existing_ev.evidence_type, 0)
                cur_auth = _EV_TYPE_RANK.get(fact_ev_type, 0)
                if cur_auth > prev_auth:
                    level_str = own_candidate_level
                    ev_type = fact_ev_type
                    eff_avail_by = avail_by
                elif cur_auth < prev_auth:
                    level_str = existing_ev.level
                    ev_type = existing_ev.evidence_type
                    eff_avail_by = existing_ev.available_by
                else:
                    level_str = pick_higher_language_level(existing_ev.level, candidate_level)
                    ev_type = fact_ev_type
                    is_downgrade = (
                        bool(own_candidate_level)
                        and _language_level_rank(own_candidate_level)
                        < _language_level_rank(existing_ev.level)
                    )
                    eff_avail_by = (
                        existing_ev.available_by
                        if (p.get("test_date") is None or is_downgrade)
                        else avail_by
                    )
            else:
                level_str = candidate_level
                ev_type = fact_ev_type
                eff_avail_by = avail_by

            new_ev = LanguageEvidence(
                language=matched_lang,
                level=level_str[:50],
                evidence_type=ev_type,
                available_by=eff_avail_by,
            )
            lang_ev_by_name[matched_lang.casefold()] = new_ev

    new_lang_tuple = tuple(lang_ev_by_name.values())[:20]
    new_history_tuple = tuple(history)
    new_teaching_tuple = tuple(teaching_langs)
    new_exp_tuple: tuple[ExperienceRecord, ...] | None = (
        tuple(
            _deduplicated_experience_from_facts(
                exp_facts, today=today, existing=snapshot.experience or ()
            )
        )
        if (exp_facts or snapshot.experience is not None)
        else None
    )
    if (
        new_history_tuple == snapshot.academic_history
        and new_lang_tuple == snapshot.language_evidence
        and new_teaching_tuple == snapshot.acceptable_teaching_languages
        and new_exp_tuple == snapshot.experience
    ):
        return None

    try:
        updated_snapshot = StudentProfileSnapshot.model_validate(
            {
                **snapshot.model_dump(mode="json"),
                "academic_history": [r.model_dump(mode="json") for r in new_history_tuple],
                "acceptable_teaching_languages": list(new_teaching_tuple),
                "language_evidence": [e.model_dump(mode="json") for e in new_lang_tuple],
                "experience": (
                    [e.model_dump(mode="json") for e in new_exp_tuple]
                    if new_exp_tuple is not None
                    else None
                ),
            }
        )
    except ValidationError:
        logger.warning("synced profile snapshot failed validation for student %s", student.id)
        return None

    created = create_profile_version(student=student, snapshot=updated_snapshot)
    if has_score_progression(snapshot, updated_snapshot):
        request_score_progression_rebuild(student)
    return created
