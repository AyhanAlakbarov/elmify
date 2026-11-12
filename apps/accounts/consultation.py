import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import cast
from uuid import UUID

from django import forms
from django.db import transaction
from django.utils import timezone
from pydantic import TypeAdapter, ValidationError

from apps.documents.models import TranscriptReading, VerifiedFact
from apps.documents.schemas import _cefr_code
from apps.documents.text_reading import TESTS
from apps.documents.transcript import Highlight
from apps.documents.verification import (
    disowned_refs,
    live_retired_refs,
    retired_hides,
    retired_refs,
    unsuperseded_facts,
)
from apps.funding.models import RecommendationRun
from apps.reference_data import COUNTRY_TO_CURRENCY, ISO_4217_CODES
from apps.tenancy.models import Membership

from .field_taxonomy import (
    TaxonomyParser,
    needs_field_disambiguation,
    resolve_field_taxonomy,
    resolve_field_taxonomy_with_llm,
)
from .forms import answer_adapter, normalize_country_code, question_field
from .models import ConsultationDraftRecord, StudentProfileVersion
from .profile_versions import create_profile_version
from .schemas import StudentProfileSnapshot

logger = logging.getLogger(__name__)


def _validation_error_fields(exc: ValidationError) -> list[tuple[object, str]]:
    """Extract only field locations and error types, never raw input values (PII-safe)."""
    return [(err.get("loc"), str(err.get("type", ""))) for err in exc.errors()]


@dataclass(frozen=True)
class ProfileQuestion:
    key: str
    field_factory: Callable[[], forms.Field]
    asked_when: Callable[[ConsultationDraft], bool]
    label: str


#: Student-facing question text. The wizard renders these, never the raw keys
#: (design-lint-baseline defect 2). Every key in QUESTIONS must have an entry —
#: a missing one raises KeyError at import, not silently mid-wizard.
QUESTION_LABELS = {
    "nationality": "Your nationality (country name or 2-letter code)",
    "country_of_residence": "Where do you live now? (country name or 2-letter code)",
    "date_of_birth": "Your date of birth",
    "academic_history": "Where do you study & your degree so far",
    "expected_completion": "When do you expect to graduate?",
    "target_field": "What do you want to study, and anything specific within it?",
    "research_interests": (
        "Which direction or sub-fields fit what you want to study? "
        "Comma-separated, or leave blank to include all"
    ),
    "allowed_countries": "Which countries would you consider? Leave empty for anywhere",
    "excluded_countries": "Any countries to rule out?",
    "intended_intake": "When do you want to start?",
    "funding_dependency": "Can you go without a scholarship?",
    "self_funding_capacity": (
        "How much can you cover yourself per year for tuition and living? "
        "Leave blank if you can cover the full cost"
    ),
    "application_budget": "How much can you spend on application fees?",
    "budget_stretch": (
        "If an exceptional opportunity appears, how much more could you spend on "
        "application fees?"
    ),
    "career_intent": (
        "After the master's, do you want to work in that country, return home, "
        "or go into academic research?"
    ),
    "acceptable_teaching_languages": "Which languages could you study in?",
    "language_evidence": (
        "Which official language certificates (e.g., IELTS, TOEFL, TestDaF) do you have, "
        "or plan to take and by when? (A prior degree only waives a test where the target "
        "programme explicitly accepts Medium of Instruction waivers upon graduation)"
    ),
    "additional_notes": (
        "Anything else we should know? "
        "(e.g., years of work or research experience, 1-year or 2-year preference, "
        "top universities only, or no funding needed)"
    ),
}


def _question(key: str, asked_when: Callable[[ConsultationDraft], bool]) -> ProfileQuestion:
    return ProfileQuestion(key, lambda: question_field(key), asked_when, QUESTION_LABELS[key])


def _always(_draft: ConsultationDraft) -> bool:
    return True


def _latest_record(answers: Mapping[str, object]) -> dict[str, object] | None:
    history = answers.get("academic_history")
    if isinstance(history, list) and history and isinstance(history[0], dict):
        return cast(dict[str, object], history[0])
    return None


def _undated(answers: Mapping[str, object]) -> bool:
    """The latest degree says neither when it ended nor when it will."""
    record = _latest_record(answers)
    return record is not None and not (
        record.get("completed_on") or record.get("expected_completion")
    )


#: Identity basics first (facts, not preferences -- spec 3.1), then the seven
#: questions of spec 3.2. academic_history is asked only when no transcript
#: reading prefilled it: next_profile_question skips any key already answered.
#: expected_completion is not a profile field: it is folded into the latest
#: academic record by _profile_payload, and asked only when that record is undated.
#: The transcript's questions come last: the reading runs while the others are
#: answered (spec 3.1).
QUESTIONS = (
    _question("nationality", _always),
    _question("country_of_residence", _always),
    _question("date_of_birth", _always),
    _question("target_field", _always),
    _question(
        "research_interests",
        lambda draft: needs_field_disambiguation(draft.answer("target_field")),
    ),
    _question("allowed_countries", _always),
    _question("excluded_countries", _always),
    _question("intended_intake", _always),
    _question("funding_dependency", _always),
    _question(
        "self_funding_capacity",
        lambda draft: draft.answer("funding_dependency") in {"IMPORTANT", "OPTIONAL"},
    ),
    _question("application_budget", _always),
    _question("budget_stretch", _always),
    _question("career_intent", _always),
    _question("acceptable_teaching_languages", _always),
    _question(
        "language_evidence", lambda draft: bool(draft.answer("acceptable_teaching_languages"))
    ),
    _question("academic_history", _always),
    _question("expected_completion", lambda draft: _undated(draft.answers)),
    _question("additional_notes", _always),
)
_QUESTIONS_BY_KEY = {question.key: question for question in QUESTIONS}

_HIGHLIGHTS: TypeAdapter[tuple[Highlight, ...]] = TypeAdapter(tuple[Highlight, ...])


def _canonical_answer(key: str, value: object) -> object:
    adapter = answer_adapter(key)
    return json.loads(adapter.dump_json(adapter.validate_python(value)))


@dataclass(frozen=True)
class ConsultationDraft:
    tenant_id: UUID
    membership_id: UUID
    answers: dict[str, object]
    correction_key: str | None = None
    #: The transcript reading that prefilled academic_history, and what the
    #: summary screen marks on it: failed checks and unsure answers (spec T2).
    reading_id: UUID | None = None
    highlights: tuple[Highlight, ...] = ()

    def answer(self, key: str) -> object | None:
        return self.answers.get(key)

    def with_answer(self, key: str, value: object) -> ConsultationDraft:
        answers = {**self.answers, key: value}
        if key == "funding_dependency" and value == "MANDATORY":
            answers.pop("self_funding_capacity", None)
        if key == "target_field" and (
            not needs_field_disambiguation(value)
            or value != self.answers.get("target_field")
        ):
            answers.pop("research_interests", None)
        if key == "acceptable_teaching_languages" and isinstance(value, (list, tuple)):
            if not value:
                answers.pop("language_evidence", None)
            elif isinstance(answers.get("language_evidence"), list):
                selected_cf = {str(lang).casefold() for lang in value}
                answers["language_evidence"] = [
                    row
                    for row in cast(list[object], answers["language_evidence"])
                    if isinstance(row, dict)
                    and str(row.get("language", "")).casefold() in selected_cf
                ]
        if key == "academic_history":
            prev_hist = self.answers.get("academic_history")
            if (
                isinstance(value, list)
                and len(value) == 1
                and isinstance(value[0], dict)
                and isinstance(prev_hist, list)
                and prev_hist
                and isinstance(prev_hist[0], dict)
            ):
                merged_first = dict(value[0])
                prev_inst = str(prev_hist[0].get("institution") or "").strip().casefold()
                new_inst = str(merged_first.get("institution") or "").strip().casefold()
                if (
                    not merged_first.get("courses")
                    and prev_hist[0].get("courses")
                    and prev_inst == new_inst
                ):
                    merged_first["courses"] = prev_hist[0]["courses"]
                answers["academic_history"] = [merged_first, *prev_hist[1:]]
            if not _undated(answers):
                answers.pop("expected_completion", None)
            # The highlights were about the reading's record, which the student
            # just replaced. reading_id stays: finalize records what they kept as
            # the correction to that reading.
            return replace(self, answers=answers, correction_key=None, highlights=())
        return replace(self, answers=answers, correction_key=None)

    def with_correction(self, key: str) -> ConsultationDraft:
        return replace(self, correction_key=key)


def read_draft(*, tenant_id: UUID, membership_id: UUID) -> ConsultationDraft:
    """The student's stored draft, or an empty one. A stored envelope that no longer
    validates (an answer no longer asked, a non-canonical value, another tenant's or
    student's ids) is deleted, never raised: the page must always render."""
    record = ConsultationDraftRecord.objects.filter(student_id=membership_id).first()
    if record is None:
        return ConsultationDraft(tenant_id, membership_id, {})
    raw = record.envelope
    try:
        envelope = cast(Mapping[str, object], raw)
        if not isinstance(raw, dict) or set(envelope) - {
            "tenant_id",
            "membership_id",
            "answers",
            "correction_key",
            "reading_id",
            "highlights",
        }:
            raise ValueError("unexpected envelope keys")
        if UUID(str(envelope["tenant_id"])) != tenant_id:
            raise ValueError("envelope tenant_id mismatch")
        if UUID(str(envelope["membership_id"])) != membership_id:
            raise ValueError("envelope membership_id mismatch")
        answers = envelope["answers"]
        if not isinstance(answers, dict) or set(answers) - set(_QUESTIONS_BY_KEY):
            raise ValueError("unknown answer keys")
        if any(_canonical_answer(key, value) != value for key, value in answers.items()):
            raise ValueError("non-canonical answer value")
        json.dumps(answers)
        correction = envelope.get("correction_key")
        if correction is not None and (
            not isinstance(correction, str) or correction not in answers
        ):
            raise ValueError("invalid correction_key")
        reading = envelope.get("reading_id")
        reading_id = UUID(str(reading)) if reading is not None else None
        highlights = _HIGHLIGHTS.validate_python(envelope.get("highlights", []))
        return ConsultationDraft(
            tenant_id, membership_id, dict(answers), correction, reading_id, highlights
        )
    except (KeyError, TypeError, ValueError) as exc:
        reason = (
            str(_validation_error_fields(exc))
            if isinstance(exc, ValidationError)
            else f"{type(exc).__name__}: {exc}"
        )
        logger.warning(
            "consultation.read_draft discarded invalid draft for membership %s (%s)",
            membership_id,
            reason,
        )
        record.delete()
        return ConsultationDraft(tenant_id, membership_id, {})


def write_draft(draft: ConsultationDraft) -> None:
    envelope: dict[str, object] = {
        "tenant_id": str(draft.tenant_id),
        "membership_id": str(draft.membership_id),
        "answers": draft.answers,
    }
    if draft.correction_key is not None:
        envelope["correction_key"] = draft.correction_key
    if draft.reading_id is not None:
        envelope["reading_id"] = str(draft.reading_id)
    if draft.highlights:
        envelope["highlights"] = [highlight.model_dump() for highlight in draft.highlights]
    ConsultationDraftRecord.objects.update_or_create(
        student_id=draft.membership_id, defaults={"envelope": envelope}
    )


def clear_draft(draft: ConsultationDraft) -> None:
    ConsultationDraftRecord.objects.filter(student_id=draft.membership_id).delete()


def next_profile_question(
    draft: ConsultationDraft,
    *,
    parser: TaxonomyParser | None = None,
    student_id: str = "anonymous",
) -> ProfileQuestion | None:
    if draft.correction_key is not None:
        question: ProfileQuestion | None = _QUESTIONS_BY_KEY[draft.correction_key]
    else:
        raw_field_pre = draft.answer("target_field")
        if parser is not None and isinstance(raw_field_pre, str) and raw_field_pre.strip():
            resolve_field_taxonomy_with_llm(
                raw_field_pre, parser=parser, student_id=student_id
            )
        question = next(
            (
                q
                for q in QUESTIONS
                if q.asked_when(draft) and q.key not in draft.answers
            ),
            None,
        )
    if question is not None and question.key == "research_interests":
        raw_field = draft.answer("target_field")
        if isinstance(raw_field, str) and raw_field.strip():
            resolution = (
                resolve_field_taxonomy_with_llm(
                    raw_field, parser=parser, student_id=student_id
                )
                if parser is not None
                else resolve_field_taxonomy(raw_field)
            )
            prompt = resolution.disambiguation_question
            if prompt:
                return replace(question, label=prompt)
    return question


def consultation_progress(draft: ConsultationDraft) -> tuple[int, int]:
    """(answered, applicable_total) for the wizard's progress indicator.

    The denominator is dynamic: conditional questions enter it only once
    their asked_when predicate holds, so the total can grow as answers
    land (the wizard progress indicator; documented behavior).
    """
    applicable = [question for question in QUESTIONS if question.asked_when(draft)]
    if draft.correction_key is not None:
        for index, question in enumerate(applicable):
            if question.key == draft.correction_key:
                return index, len(applicable)
    answered = sum(1 for question in applicable if question.key in draft.answers)
    return answered, len(applicable)


def previous_question_key(draft: ConsultationDraft) -> str | None:
    """Return the key of the most recently answered applicable question before the current step."""
    if draft.correction_key is not None:
        return None
    applicable = [q.key for q in QUESTIONS if q.asked_when(draft)]
    current = next((k for k in applicable if k not in draft.answers), None)
    if current is None:
        answered_keys = [k for k in applicable if k in draft.answers]
        return answered_keys[-1] if answered_keys else None
    idx = applicable.index(current)
    prior_answered = [k for k in applicable[:idx] if k in draft.answers]
    return prior_answered[-1] if prior_answered else None


_ZERO_EXPERIENCE_RE = re.compile(
    r"\b(?:no|zero|0|without|don'?t\s+have(?:\s+any)?|do\s+not\s+have(?:\s+any)?)\s+"
    r"(?:full[- ]time\s+|professional\s+|relevant\s+|prior\s+)?work\s+experience\b"
    r"|\bfresh\s+graduate\b",
    re.IGNORECASE,
)
_NEGATED_OR_REQUIRED_PREFIX_RE = re.compile(
    r"\b(?:no|not|never|without|don'?t|doesn'?t|didn'?t|lack|lacking|zero"
    r"|require|requires|requiring|required|need|needs|needing|needed"
    r"|avoid|avoiding|exclude|excluding)\b",
    re.IGNORECASE,
)
_EXPERIENCE_SPAN_RE = re.compile(
    r"\b(\d{1,2})\s*(?:\+\s*)?(years?|yrs?|months?|mos?)\s+(?:of\s+)?"
    r"(?:full[- ]time\s+|professional\s+|relevant\s+|academic\s+)?"
    r"(work|professional|research|internship)\s+experience\b",
    re.IGNORECASE,
)


def _experience_from_notes(notes: object) -> list[dict[str, object]] | None:
    if not isinstance(notes, str) or not notes.strip():
        return None
    text = notes.strip()
    records: list[dict[str, object]] = []
    for match in _EXPERIENCE_SPAN_RE.finditer(text):
        clause_prefix = re.split(r"[,.;!?\n]", text[: match.start()])[-1][-60:]
        if _NEGATED_OR_REQUIRED_PREFIX_RE.search(clause_prefix):
            continue
        amount = int(match.group(1))
        unit = match.group(2).casefold()
        raw_kind = match.group(3).casefold()
        months = amount * 12 if unit.startswith("y") else amount
        if months <= 0 or months > 600:
            continue
        if raw_kind == "research":
            kind = "RESEARCH"
        elif raw_kind == "internship":
            kind = "INTERNSHIP"
        else:
            kind = "WORK"
        records.append(
            {
                "kind": kind,
                "summary": match.group(0).strip()[:200],
                "months": months,
            }
        )
    if records:
        return records
    if _ZERO_EXPERIENCE_RE.search(text):
        return []
    return None


_TOP_UNIVERSITIES_RE = re.compile(
    r"\b(?:only\s+)?(?:top|elite|prestigious|world[- ]class|flagship|best|highest[- ]ranked"
    r"|top[- ]ranked|top[- ]tier|tier[- ]1)\s+"
    r"(?:universit(?:y|ies)|schools?|institutions?|program(?:me)?s?|master'?s|scholarships?)\b"
    r"|\b(?:universit(?:y|ies)|schools?|institutions?)\s+(?:that\s+are\s+)?"
    r"(?:in\s+the\s+)?(?:top\s+\d+|qs\s+top|times\s+higher\s+education\s+top|world\s+top)\b",
    re.IGNORECASE,
)
_NEGATED_PRIORITY_PREFIX_RE = re.compile(
    r"\b(?:not|no|never|don'?t|do\s+not|doesn'?t|without)\s+"
    r"(?:care\s+about\s+|need\s+|want\s+|looking\s+for\s+|only\s+)?$",
    re.IGNORECASE,
)
_STRICT_MODIFIER_RE = re.compile(
    r"\b(?:only|strictly|exclusively|must(?:\s+be)?|non[- ]negotiable|nothing\s+but)\b",
    re.IGNORECASE,
)
_NEGATED_STRICT_RE = re.compile(
    r"\b(?:not|no|never)\s+(?:strictly|only|exclusively|necessarily)\b",
    re.IGNORECASE,
)
_NO_FUNDING_NEEDED_RE = re.compile(
    r"\b(?:don'?t|do\s+not|doesn'?t)\s+(?:care\s+about|need|want|require|mind)\s+"
    r"(?:any\s+)?(?:funding(?:\s+options?)?|scholarships?|financial\s+aid|grants?|stipends?)\b"
    r"|\b(?:no|without\s+any|ignore|ignoring|skip)\s+"
    r"(?:funding(?:\s+options?)?|scholarships?|financial\s+aid)\s*"
    r"(?:needed|required|necessary|options?)?\b"
    r"|\b(?:fully\s+self[- ]funded|self[- ]funded\s+only|100%\s+self[- ]funded"
    r"|pay\s+full\s+tuition\s+myself|cover\s+(?:the\s+)?full\s+cost\s+myself)\b",
    re.IGNORECASE,
)
_NO_RETURN_BOND_RE = re.compile(
    r"\b(?:no|without|avoid|exclude)\s+(?:any\s+)?(?:return[- ]service|return\s+bond"
    r"|home[- ]country\s+return|mandatory\s+return|return\s+obligation)\b",
    re.IGNORECASE,
)
_GOV_POST_ADMISSION_SCHOLARSHIP_RE = re.compile(
    r"\b(?:post[- ]admission\s+(?:government\s+|state\s+|external\s+|national\s+)?scholarship"
    r"|admission[- ]contingent\s+(?:government\s+|state\s+)?scholarship"
    r"|(?:government|state|ministry|national|external)\s+scholarship\s+after\s+(?:getting\s+|securing\s+)?admission"
    r"|admission\s+(?:offer\s+)?(?:required\s+)?first\s*(?:,\s*)?(?:and\s+)?then\s+(?:get\s+)?(?:the\s+)?(?:government\s+|state\s+)?scholarship"
    r"|get\s+(?:just\s+)?(?:the\s+)?admission\s+and\s+then\s+(?:get\s+)?(?:the\s+)?scholarship"
    r"|(?:state|government)\s+program(?:me)?(?:\s+scholarship)?\s+after\s+admission"
    r"|d[öo]vl[əe]t\s+proqram[ıi]?)\b",
    re.IGNORECASE,
)
_FUNDING_FIRST_NOTE_RE = re.compile(
    r"\b(?:funding\s+first|cheapest\s+options?|lowest\s+cost|maximize\s+funding"
    r"|full\s+funding\s+is\s+my\s+only\s+priority)\b",
    re.IGNORECASE,
)
_BALANCED_NOTE_RE = re.compile(
    r"\b(?:academic\s+fit\s+first|best\s+fit\s+first|quality\s+over\s+cost"
    r"|prestigious\s+scholarships?\s+only)\b",
    re.IGNORECASE,
)
_DURATION_PREF_RE = re.compile(
    r"(?:(?:\b(?:prefer|want|only|strictly|looking\s+for|must\s+be|seeking)\s+(?:a\s+)?)"
    r"(1[- ]year|one[- ]year|1\s+year|one\s+year|12[- ]month|12\s+months"
    r"|2[- ]year|two[- ]year|2\s+years?|two\s+years?|24[- ]month|24\s+months)"
    r"(?!\s+(?:of\s+)?(?:full[- ]time\s+|professional\s+|relevant\s+|academic\s+|prior\s+)?"
    r"(?:work|professional|research|internship)\s+experience\b))"
    r"|(?:\b(1[- ]year|one[- ]year|1\s+year|one\s+year|12[- ]month|12\s+months"
    r"|2[- ]year|two[- ]year|2\s+years?|two\s+years?|24[- ]month|24\s+months)\s+"
    r"(?:only|master'?s?|msc|ma|program(?:me)?s?|degrees?|tracks?|courses?|duration|studies)\b)",
    re.IGNORECASE,
)


def _add_constraint(
    payload: dict[str, object],
    *,
    target_key: str,
    kind: str,
    value: str,
) -> None:
    existing_non_neg = [
        item
        for item in cast(list[dict[str, str]], payload.get("non_negotiables") or [])
        if isinstance(item, dict)
    ]
    existing_neg = [
        item
        for item in cast(list[dict[str, str]], payload.get("negotiable_preferences") or [])
        if isinstance(item, dict)
    ]
    pair = (kind.upper(), value.casefold())
    for item in (*existing_non_neg, *existing_neg):
        if (str(item.get("kind", "")).upper(), str(item.get("value", "")).casefold()) == pair:
            return
    target_list = list(existing_non_neg if target_key == "non_negotiables" else existing_neg)
    target_list.append({"kind": kind, "value": value})
    payload[target_key] = target_list


def _priorities_from_notes(notes: object, payload: dict[str, object]) -> None:
    if not isinstance(notes, str) or not notes.strip():
        return
    text = notes.strip()

    wants_top = False
    for match in _TOP_UNIVERSITIES_RE.finditer(text):
        clause_prefix = re.split(r"[,.;!?\n]", text[: match.start()])[-1][-45:]
        if _NEGATED_PRIORITY_PREFIX_RE.search(clause_prefix.strip() + " "):
            continue
        wants_top = True
        clause = re.split(r"[.;!?\n]", text[max(0, match.start() - 35) : match.end() + 35])[0]
        is_strict = bool(
            _STRICT_MODIFIER_RE.search(clause) and not _NEGATED_STRICT_RE.search(clause)
        )
        target_key = "non_negotiables" if is_strict else "negotiable_preferences"
        _add_constraint(
            payload,
            target_key=target_key,
            kind="OTHER",
            value="TOP_UNIVERSITIES_ONLY",
        )
        break

    if _NO_FUNDING_NEEDED_RE.search(text):
        _add_constraint(
            payload,
            target_key="negotiable_preferences",
            kind="OTHER",
            value="NO_FUNDING_NEEDED",
        )
        payload["funding_dependency"] = "OPTIONAL"
        payload.setdefault("self_funding_capacity", None)

    if _NO_RETURN_BOND_RE.search(text):
        _add_constraint(
            payload,
            target_key="negotiable_preferences",
            kind="OTHER",
            value="NO_RETURN_BOND",
        )

    wants_gov_post_admission = False
    for gov_match in _GOV_POST_ADMISSION_SCHOLARSHIP_RE.finditer(text):
        clause_prefix = re.split(r"[,.;!?\n]", text[: gov_match.start()])[-1][-45:]
        if _NEGATED_PRIORITY_PREFIX_RE.search(clause_prefix.strip() + " "):
            continue
        wants_gov_post_admission = True
        _add_constraint(
            payload,
            target_key="negotiable_preferences",
            kind="OTHER",
            value="GOV_SCHOLARSHIP_AFTER_ADMISSION",
        )
        break

    if (
        payload.get("career_intent") == "WORK_ABROAD"
        and "mobility_priorities" not in payload
        and re.search(
            r"\b(?:post[- ]study\s+work|work\s+visa|stay\s+and\s+work|job\s+market)\b",
            text,
            re.IGNORECASE,
        )
    ):
        payload["mobility_priorities"] = ["POST_STUDY_WORK"]

    if "strategy" not in payload:
        if (
            _FUNDING_FIRST_NOTE_RE.search(text)
            and not wants_top
            and not wants_gov_post_admission
        ):
            payload["strategy"] = "FUNDING_FIRST"
        elif wants_top or wants_gov_post_admission or _BALANCED_NOTE_RE.search(text):
            payload["strategy"] = "BALANCED"

    if "duration_preference" not in payload:
        _apply_duration_preference_from_notes(text, payload)


def _apply_duration_preference_from_notes(text: str, payload: dict[str, object]) -> None:
    dur_match = _DURATION_PREF_RE.search(text)
    if dur_match is None:
        return
    raw_token = (dur_match.group(1) or dur_match.group(2) or "").casefold()
    is_one_year = raw_token.startswith(("1", "one"))
    clause_prefix = re.split(r"[,.;!?\n]", text[: dur_match.start()])[-1][-40:]
    negated_dur = bool(
        re.search(
            r"\b(?:no|not|avoid|exclude|without|don'?t\s+want|do\s+not\s+want)\s+"
            r"(?:a\s+|any\s+)?$",
            clause_prefix,
            re.IGNORECASE,
        )
    )
    if negated_dur:
        is_one_year = not is_one_year
    pref = "ONE_YEAR" if is_one_year else "TWO_YEAR"
    window = text[max(0, dur_match.start() - 30) : min(len(text), dur_match.end() + 40)]
    strict = bool(
        negated_dur
        or (_STRICT_MODIFIER_RE.search(window) and not _NEGATED_STRICT_RE.search(window))
        or re.search(
            r"\bno\s+(?:1[- ]year|one[- ]year|2[- ]year|two[- ]year)\b",
            text,
            re.IGNORECASE,
        )
    )
    payload["duration_preference"] = pref
    if strict:
        payload["duration_flexibility"] = "NON_NEGOTIABLE"
        payload["longer_program_justifications"] = []
        return
    payload["duration_flexibility"] = "WEIGHTED"
    if pref != "ONE_YEAR":
        payload["longer_program_justifications"] = []
        return
    justifications: list[str] = []
    if re.search(r"\bfund(?:ing|ed)|scholarship\b", text, re.IGNORECASE):
        justifications.append("FUNDING")
    if re.search(r"\binternship|industry|placement\b", text, re.IGNORECASE):
        justifications.append("INTERNSHIP")
    if re.search(r"\bresearch|thesis|phd|lab\b", text, re.IGNORECASE):
        justifications.append("RESEARCH")
    payload["longer_program_justifications"] = justifications or ["FUNDING", "RESEARCH"]


def _profile_payload(
    draft: ConsultationDraft,
    *,
    parser: TaxonomyParser | None = None,
    student_id: str = "anonymous",
) -> dict[str, object]:
    """The answers as a profile: the graduation answer goes into its record,
    and an interdisciplinary/ambiguous `target_field` expands its canonical
    degree-title variants into `research_interests` alongside the student's
    chosen sub-direction."""
    payload = {key: value for key, value in draft.answers.items() if key != "expected_completion"}
    raw_field = payload.get("target_field")
    if isinstance(raw_field, str) and needs_field_disambiguation(
        raw_field, parser=parser, student_id=student_id
    ):
        raw_interests = payload.get("research_interests")
        typed_interests = (
            [str(item) for item in raw_interests if str(item).strip()]
            if isinstance(raw_interests, (list, tuple))
            else []
        )
        resolution = (
            resolve_field_taxonomy_with_llm(
                raw_field, typed_interests, parser=parser, student_id=student_id
            )
            if parser is not None
            else resolve_field_taxonomy(raw_field, typed_interests)
        )
        merged: list[str] = []
        seen: set[str] = set()
        for item in (*typed_interests, *resolution.canonical_degree_titles[:8]):
            norm = " ".join(item.split())
            if norm and norm.casefold() not in seen:
                seen.add(norm.casefold())
                merged.append(norm)
        payload["research_interests"] = merged[:20]
    graduation = draft.answer("expected_completion")
    if graduation is not None and _undated(payload):
        history = cast(list[dict[str, object]], payload["academic_history"])
        payload["academic_history"] = [
            {**history[0], "expected_completion": graduation},
            *history[1:],
        ]
    if "experience" not in payload:
        parsed_exp = _experience_from_notes(payload.get("additional_notes"))
        if parsed_exp is not None:
            payload["experience"] = parsed_exp
    _priorities_from_notes(payload.get("additional_notes"), payload)
    return payload


def validate_draft(
    draft: ConsultationDraft,
    *,
    parser: TaxonomyParser | None = None,
    student_id: str = "anonymous",
) -> StudentProfileSnapshot:
    return StudentProfileSnapshot.model_validate(
        _profile_payload(draft, parser=parser, student_id=student_id)
    )


def _prefill_identity_fact(
    payload: Mapping[str, object],
    draft_answers: Mapping[str, object],
    updates: dict[str, object],
    *,
    fact_id: UUID,
) -> None:
    if "nationality" not in draft_answers:
        raw_cit = payload.get("citizenship")
        if isinstance(raw_cit, str) and raw_cit.strip():
            try:
                updates["nationality"] = _canonical_answer(
                    "nationality", normalize_country_code(raw_cit)
                )
            except ValidationError as exc:
                logger.debug(
                    "consultation._prefill_identity_fact skipped nationality from fact %s: %s",
                    fact_id,
                    _validation_error_fields(exc),
                )
    if "date_of_birth" not in draft_answers:
        raw_dob = payload.get("date_of_birth")
        if isinstance(raw_dob, str) and raw_dob.strip():
            try:
                updates["date_of_birth"] = _canonical_answer(
                    "date_of_birth", raw_dob.strip()[:10]
                )
            except ValidationError as exc:
                logger.debug(
                    "consultation._prefill_identity_fact skipped date_of_birth from fact %s: %s",
                    fact_id,
                    _validation_error_fields(exc),
                )


def _collect_language_fact(
    payload: Mapping[str, object],
    lang_rows_by_name: dict[str, dict[str, object]],
    *,
    today_iso: str,
) -> None:
    from apps.documents.profile_bridge import _EV_TYPE_RANK, pick_higher_language_level

    test_name = str(payload.get("test_name") or "").strip()
    raw_lang = str(payload.get("language") or TESTS.get(test_name) or "").strip()
    if not raw_lang:
        return
    raw_cefr = str(_cefr_code(payload.get("cefr_level")) or "").strip()
    score = str(payload.get("test_score") or "").strip()
    level_str = raw_cefr or (f"{test_name} {score}".strip() if score else test_name)
    if not level_str:
        return
    raw_ev = str(payload.get("evidence_type") or "").strip().upper()
    if test_name or score or raw_ev == "TEST":
        ev_type = "TEST"
    elif raw_ev in ("DEGREE", "OTHER"):
        ev_type = raw_ev
    else:
        ev_type = "ATTESTED"
    raw_date = str(payload.get("test_date") or "").strip()[:10]
    avail_by = raw_date if len(raw_date) == 10 else today_iso
    lang_key = raw_lang.casefold()
    existing_lang = lang_rows_by_name.get(lang_key)
    if existing_lang is None:
        lang_rows_by_name[lang_key] = {
            "language": raw_lang[:100],
            "level": level_str[:50],
            "evidence_type": ev_type,
            "available_by": avail_by,
        }
        return
    prev_lvl = str(existing_lang.get("level") or "")
    prev_ev_type = str(existing_lang.get("evidence_type") or "ATTESTED").upper()
    prev_auth = _EV_TYPE_RANK.get(prev_ev_type, 0)
    cur_auth = _EV_TYPE_RANK.get(ev_type, 0)
    if cur_auth > prev_auth:
        lang_rows_by_name[lang_key] = {
            "language": str(existing_lang["language"]),
            "level": level_str[:50],
            "evidence_type": ev_type,
            "available_by": avail_by,
        }
    elif cur_auth == prev_auth:
        best_lvl = pick_higher_language_level(prev_lvl, level_str)
        kept_prev = best_lvl == prev_lvl and best_lvl != level_str
        lang_rows_by_name[lang_key] = {
            "language": str(existing_lang["language"]),
            "level": best_lvl[:50],
            "evidence_type": ev_type,
            "available_by": existing_lang["available_by"] if kept_prev else avail_by,
        }


def _extract_education_candidate(
    payload: Mapping[str, object], *, today_iso: str
) -> dict[str, object] | None:
    inst = str(payload.get("institution_original") or "").strip()
    country = normalize_country_code(payload.get("country"))
    qual = str(payload.get("degree_as_awarded") or "").strip()
    if not (inst and country and qual):
        return None
    field_val = str(payload.get("field") or "").strip() or "not stated"
    grade_val = str(payload.get("grade_native") or "").strip() or "not stated"
    scale_val = str(payload.get("grade_scale") or "").strip() or "not stated"
    end_raw = str(payload.get("end_date") or "").strip()[:10]
    completed_on = end_raw if (len(end_raw) == 10 and end_raw <= today_iso) else None
    expected_comp = end_raw if (len(end_raw) == 10 and end_raw > today_iso) else None
    courses = payload.get("courses")
    return {
        "institution": inst[:200],
        "country_code": country,
        "qualification": qual[:100],
        "field": field_val[:200],
        "grade": grade_val[:50],
        "grading_scale": scale_val[:100],
        "completed_on": completed_on,
        "expected_completion": expected_comp,
        "courses": courses if isinstance(courses, list) else [],
    }


def _prefill_from_verified_facts(
    draft: ConsultationDraft, *, membership: Membership
) -> ConsultationDraft:
    """Prefill identity, language, and diploma/CV education answers from confirmed
    `VerifiedFact` rows (Variant 6, onboarding friction design 2026-10-15).

    Never overwrites an answer the student already typed in `draft.answers`, and
    never reads facts generated by `profile-bridge:`.
    """
    disowned = disowned_refs(membership)
    retired, live = retired_refs(membership), live_retired_refs(membership)
    confirmed = [
        f
        for f in unsuperseded_facts(membership)
        .filter(
            category__in=(
                VerifiedFact.Category.IDENTITY,
                VerifiedFact.Category.LANGUAGE,
                VerifiedFact.Category.EDUCATION,
            ),
            confirmed_at__isnull=False,
        )
        .exclude(source_ref__in=disowned)
        .exclude(source_ref__startswith="profile-bridge:")
        .order_by("created_at")
        if not retired_hides(f, retired, live)
    ]
    if not confirmed:
        return draft

    updates: dict[str, object] = {}
    today_iso = timezone.localdate().isoformat()
    lang_rows_by_name: dict[str, dict[str, object]] = {}
    edu_candidates: list[dict[str, object]] = []

    for fact in confirmed:
        p = fact.payload if isinstance(fact.payload, dict) else {}
        if fact.category == VerifiedFact.Category.IDENTITY:
            _prefill_identity_fact(p, draft.answers, updates, fact_id=fact.id)
        elif fact.category == VerifiedFact.Category.LANGUAGE:
            _collect_language_fact(p, lang_rows_by_name, today_iso=today_iso)
        elif fact.category == VerifiedFact.Category.EDUCATION:
            edu = _extract_education_candidate(p, today_iso=today_iso)
            if edu is not None:
                edu_candidates.append(edu)

    if lang_rows_by_name:
        if "language_evidence" not in draft.answers:
            try:
                updates["language_evidence"] = _canonical_answer(
                    "language_evidence", list(lang_rows_by_name.values())
                )
            except ValidationError as exc:
                logger.debug(
                    "consultation._prefill_from_verified_facts skipped "
                    "language_evidence for membership %s: %s",
                    membership.id,
                    _validation_error_fields(exc),
                )
        if "acceptable_teaching_languages" not in draft.answers:
            langs = [str(row["language"]) for row in lang_rows_by_name.values()]
            try:
                updates["acceptable_teaching_languages"] = _canonical_answer(
                    "acceptable_teaching_languages", langs
                )
            except ValidationError as exc:
                logger.debug(
                    "consultation._prefill_from_verified_facts skipped "
                    "acceptable_teaching_languages for membership %s: %s",
                    membership.id,
                    _validation_error_fields(exc),
                )

    if (
        edu_candidates
        and "academic_history" not in draft.answers
        and not TranscriptReading.objects.filter(student=membership).exists()
    ):
        graded = [
            c
            for c in edu_candidates
            if c["grade"] != "not stated" and c["grading_scale"] != "not stated"
        ]
        chosen_edu = graded[-1] if graded else edu_candidates[-1]
        try:
            updates["academic_history"] = _canonical_answer(
                "academic_history", [chosen_edu]
            )
        except ValidationError as exc:
            logger.debug(
                "consultation._prefill_from_verified_facts skipped "
                "academic_history for membership %s: %s",
                membership.id,
                _validation_error_fields(exc),
            )

    if not updates:
        return draft
    return replace(draft, answers={**draft.answers, **updates}, correction_key=None)


_EUROZONE_COUNTRIES = (
    "AD", "AT", "BE", "BG", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR",
    "IE", "IT", "LT", "LU", "LV", "MC", "ME", "MT", "NL", "PT", "SI", "SK",
    "SM", "VA",
)

_COUNTRY_CURRENCY_HINTS: dict[str, str] = {
    **dict.fromkeys(_EUROZONE_COUNTRIES, "EUR"),
    **COUNTRY_TO_CURRENCY,
    "GB": "GBP",
    "US": "USD",
    "CA": "CAD",
    "AU": "AUD",
    "NZ": "NZD",
    "CH": "CHF",
    "LI": "CHF",
    "PL": "PLN",
    "CZ": "CZK",
    "HU": "HUF",
    "RO": "RON",
    "IS": "ISK",
    "RS": "RSD",
    "UA": "UAH",
    "BY": "BYN",
    "MD": "MDL",
    "AM": "AMD",
    "RU": "RUB",
    "SE": "SEK",
    "NO": "NOK",
    "DK": "DKK",
    "JP": "JPY",
    "KR": "KRW",
    "CN": "CNY",
    "TW": "TWD",
    "HK": "HKD",
    "SG": "SGD",
    "BN": "BND",
    "MY": "MYR",
    "ID": "IDR",
    "VN": "VND",
    "TH": "THB",
    "PH": "PHP",
    "AE": "AED",
    "SA": "SAR",
    "QA": "QAR",
    "KW": "KWD",
    "BH": "BHD",
    "OM": "OMR",
    "JO": "JOD",
    "IL": "ILS",
    "IR": "IRR",
    "IQ": "IQD",
    "IN": "INR",
    "PK": "PKR",
    "BD": "BDT",
    "LK": "LKR",
    "NP": "NPR",
    "EG": "EGP",
    "MA": "MAD",
    "TN": "TND",
    "DZ": "DZD",
    "NG": "NGN",
    "KE": "KES",
    "ZA": "ZAR",
    "BR": "BRL",
    "MX": "MXN",
    "AR": "ARS",
    "CL": "CLP",
    "CO": "COP",
    "PE": "PEN",
}


def default_currency_for_draft(draft: ConsultationDraft) -> str:
    """Return a default ISO 4217 currency code for money steps based on prior money answers
    or the student's country_of_residence / nationality (fallback 'EUR')."""
    for key in ("application_budget", "self_funding_capacity"):
        prior = draft.answer(key)
        if isinstance(prior, dict):
            curr = prior.get("currency")
            if isinstance(curr, str) and curr in ISO_4217_CODES:
                return curr
    for country_key in ("country_of_residence", "nationality"):
        cc = draft.answer(country_key)
        if isinstance(cc, str) and cc in _COUNTRY_CURRENCY_HINTS:
            return _COUNTRY_CURRENCY_HINTS[cc]
    return "EUR"


def seed_from_latest_profile(
    draft: ConsultationDraft, *, membership: Membership
) -> ConsultationDraft:
    """When a student with a finalized profile opens `/student/profile/` with no active
    draft, pre-seed the draft from their latest `StudentProfileVersion` so they land on
    'Check your answers' and can edit individual fields via 'Change'."""
    if draft.answers:
        return draft
    latest = (
        StudentProfileVersion.objects.filter(student=membership, schema_version=3)
        .order_by("-version")
        .first()
    )
    if latest is None or not isinstance(latest.snapshot, dict):
        return draft
    raw_snap = (
        {k: v for k, v in latest.snapshot.items() if k != "weights"}
        if latest.snapshot.get("weights") == {}
        else latest.snapshot
    )
    try:
        snapshot = StudentProfileSnapshot.model_validate(raw_snap)
    except ValidationError as exc:
        logger.warning(
            "consultation.seed_from_latest_profile skipped invalid snapshot for membership %s: %s",
            membership.id,
            _validation_error_fields(exc),
        )
        return draft
    dumped = snapshot.model_dump(mode="json")
    seeded: dict[str, object] = {}
    for q in QUESTIONS:
        if q.key == "expected_completion":
            continue
        if q.key == "self_funding_capacity" and snapshot.funding_dependency == "MANDATORY":
            continue
        if q.key == "research_interests" and not needs_field_disambiguation(snapshot.target_field):
            continue
        if q.key in dumped:
            try:
                seeded[q.key] = _canonical_answer(q.key, dumped[q.key])
            except ValidationError as exc:
                logger.warning(
                    "consultation.seed_from_latest_profile key %s failed "
                    "validation for membership %s: %s",
                    q.key,
                    membership.id,
                    _validation_error_fields(exc),
                )
                return draft
    if not seeded:
        return draft
    return replace(draft, answers=seeded, correction_key=None)


def prefill_from_latest_reading(
    draft: ConsultationDraft, *, membership: Membership
) -> ConsultationDraft:
    """Put the latest transcript reading and confirmed document facts into the draft.

    The newest reading only -- an older one is superseded, never re-offered. Once
    the transcript check accepted it (plan 3b), what the student checked is
    pre-filled, with no doubts left to mark; until then, the reader's record and
    its highlights. A draft that already holds an academic record -- typed or
    prefilled -- is left alone. A reading that is not a valid academic record, or
    whose highlights do not parse, is not offered: the student types it
    (read_draft would otherwise drop the draft on every request).
    """
    draft = _prefill_from_verified_facts(draft, membership=membership)
    if "academic_history" in draft.answers:
        return _with_checked_degree(draft, membership)
    reading = TranscriptReading.objects.filter(student=membership).order_by("-created_at").first()
    if reading is None:
        return draft
    if reading.accepted is not None:
        try:
            history = _canonical_answer("academic_history", [reading.accepted])
        except ValidationError as exc:
            logger.warning(
                "consultation.prefill_from_latest_reading accepted reading %s invalid: %s",
                reading.id,
                _validation_error_fields(exc),
            )
            return draft
        return replace(
            draft,
            answers={**draft.answers, "academic_history": history},
            reading_id=reading.id,
            highlights=(),
            correction_key=None,
        )
    if _reading_answer(reading) is None:
        return draft
    return use_reading(draft, reading)


def _newest_unaccepted_reading(membership: Membership) -> TranscriptReading | None:
    reading = TranscriptReading.objects.filter(student=membership).order_by("-created_at").first()
    return reading if reading is not None and reading.accepted is None else None


def _reading_answer(
    reading: TranscriptReading,
) -> tuple[object, tuple[Highlight, ...]] | None:
    """The reading as an academic-history answer and its highlights, or None when it
    is not a valid record or its highlights do not parse."""
    try:
        return (
            _canonical_answer("academic_history", [reading.record]),
            _HIGHLIGHTS.validate_python(reading.highlights),
        )
    except ValidationError:
        return None


def late_reading(
    draft: ConsultationDraft, *, membership: Membership
) -> TranscriptReading | None:
    """A reading that finished after the student typed their degree. Offered on the
    review page, never applied without the student choosing it (onboarding friction
    design 2026-10-15, variant 2)."""
    if draft.reading_id is not None or "academic_history" not in draft.answers:
        return None
    reading = _newest_unaccepted_reading(membership)
    if reading is None or _reading_answer(reading) is None:
        return None
    return reading


def use_reading(draft: ConsultationDraft, reading: TranscriptReading) -> ConsultationDraft:
    """The draft with its degree replaced by the reading's record; nothing else changes."""
    answer = _reading_answer(reading)
    if answer is None:
        raise ValueError("the reading is not a valid academic record")
    history, highlights = answer
    new_answers = {**draft.answers, "academic_history": history}
    if not _undated(new_answers):
        new_answers.pop("expected_completion", None)
    return replace(
        draft,
        answers=new_answers,
        reading_id=reading.id,
        highlights=highlights,
        correction_key=None,
    )


def _with_checked_degree(draft: ConsultationDraft, membership: Membership) -> ConsultationDraft:
    """The draft's degree as the student checked it. A draft pre-filled from the reader's
    record before the transcript check was accepted would otherwise put the reader's values,
    not the student's fixes, into the profile (plan 3b spec audit P1)."""
    if draft.reading_id is None:
        return draft
    accepted = (
        TranscriptReading.objects.filter(id=draft.reading_id, student=membership)
        .values_list("accepted", flat=True)
        .first()
    )
    history = draft.answers.get("academic_history")
    if accepted is None or not isinstance(history, list) or not history:
        return draft
    try:
        checked = _canonical_answer("academic_history", [accepted])
    except ValidationError as exc:
        logger.warning(
            "consultation._with_checked_degree reading %s invalid accepted record: %s",
            draft.reading_id,
            _validation_error_fields(exc),
        )
        return draft
    new_history = [*cast(list[object], checked), *history[1:]]
    if new_history == history and not draft.highlights:
        return draft
    new_answers = {**draft.answers, "academic_history": new_history}
    if not _undated(new_answers):
        new_answers.pop("expected_completion", None)
    return replace(draft, answers=new_answers, highlights=())


@transaction.atomic
def finalize_consultation(
    *, membership: Membership, draft: ConsultationDraft
) -> tuple[StudentProfileSnapshot, RecommendationRun]:
    from apps.documents.profile_bridge import (
        bridge_profile_to_facts,
        experience_records_from_facts,
    )

    draft = _with_checked_degree(draft, membership)
    payload = _profile_payload(draft)
    # Only the id (and raw experience slot) are read here: validating a full stored row
    # inside this transaction would roll the intake back. The callback loads and validates it.
    previous_pair = (
        StudentProfileVersion.objects.filter(student=membership, schema_version=3)
        .order_by("-version")
        .values_list("id", "snapshot")
        .first()
    )
    previous_id = previous_pair[0] if previous_pair is not None else None
    if "experience" not in payload:
        fact_exp = experience_records_from_facts(membership)
        if fact_exp:
            payload["experience"] = [r.model_dump(mode="json") for r in fact_exp]
        elif (
            previous_pair is not None
            and isinstance(previous_pair[1], dict)
            and isinstance(previous_pair[1].get("experience"), list)
        ):
            try:
                payload["experience"] = _canonical_answer(
                    "experience", previous_pair[1]["experience"]
                )
            except ValidationError as exc:
                logger.warning(
                    "consultation.finalize_consultation skipped prior "
                    "experience for membership %s: %s",
                    membership.id,
                    _validation_error_fields(exc),
                )
    if previous_pair is not None and isinstance(previous_pair[1], dict):
        prev_snap = previous_pair[1]
        for preserved_key in ("mobility_priorities", "weights"):
            if preserved_key not in payload and preserved_key in prev_snap:
                payload[preserved_key] = prev_snap[preserved_key]
        if (prev_snap.get("additional_notes") or "") == (payload.get("additional_notes") or ""):
            for note_derived_key in (
                "strategy",
                "duration_preference",
                "duration_flexibility",
                "longer_program_justifications",
                "non_negotiables",
                "negotiable_preferences",
            ):
                if note_derived_key not in payload and note_derived_key in prev_snap:
                    payload[note_derived_key] = prev_snap[note_derived_key]
    try:
        snapshot = StudentProfileSnapshot.model_validate(payload)
    except ValidationError as exc:
        logger.warning(
            "consultation.finalize_consultation carried-over fields failed "
            "validation for membership %s (%s); falling back to fresh draft payload",
            membership.id,
            _validation_error_fields(exc),
        )
        snapshot = StudentProfileSnapshot.model_validate(_profile_payload(draft))
    # The reading stays unaccepted: the transcript check accepts it (plan 3b), and a profile
    # finalized first is updated then, as a new version.
    profile = create_profile_version(student=membership, snapshot=snapshot)
    run = RecommendationRun.objects.create(profile_version=profile)

    bridge_profile_to_facts(membership)

    def start_search() -> None:
        # Function-local: accounts must not import research at module load.
        from apps.research.tap import on_saved_versions

        on_saved_versions(previous_id, snapshot, membership)

    transaction.on_commit(start_search)
    return snapshot, run


def correction_key(error: ValidationError) -> str:
    detail = error.errors()[0]
    context = detail.get("ctx")
    if not isinstance(context, dict):
        context = {}
    target = context.get("target")
    if not isinstance(target, str):
        location = detail.get("loc")
        target = location[0] if isinstance(location, tuple) and location else None
    if not isinstance(target, str) or target not in _QUESTIONS_BY_KEY:
        raise ValueError("profile validation error target is unknown")
    return target
