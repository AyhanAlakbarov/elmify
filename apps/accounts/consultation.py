import json
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, replace
from typing import cast
from uuid import UUID

from django import forms
from django.db import transaction
from pydantic import TypeAdapter, ValidationError

from apps.documents.models import TranscriptReading
from apps.documents.transcript import Highlight
from apps.funding.models import RecommendationRun
from apps.tenancy.models import Membership

from .forms import answer_adapter, question_field
from .profile_versions import create_profile_version
from .schemas import StudentProfileSnapshot


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
    "nationality": "Your nationality",
    "country_of_residence": "Where do you live now?",
    "date_of_birth": "Your date of birth",
    "academic_history": "Your degree so far",
    "expected_completion": "When do you expect to graduate?",
    "target_field": "What do you want to study, and anything specific within it?",
    "allowed_countries": "Which countries would you consider? Leave empty for anywhere",
    "excluded_countries": "Any countries to rule out?",
    "intended_intake": "When do you want to start?",
    "funding_dependency": "Can you go without a scholarship?",
    "self_funding_capacity": "How much can you cover yourself per year for tuition and living?",
    "application_budget": "How much can you spend on application fees?",
    "career_intent": (
        "After the master's, do you want to work in that country, return home, "
        "or continue to a PhD?"
    ),
    "acceptable_teaching_languages": "Which languages could you study in?",
    "language_evidence": "Which language certificates do you have, or plan to take and by when?",
    "additional_notes": "Anything else we should know?",
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
    _question("allowed_countries", _always),
    _question("excluded_countries", _always),
    _question("intended_intake", _always),
    _question("funding_dependency", _always),
    _question(
        "self_funding_capacity",
        lambda draft: draft.answer("funding_dependency") in {"IMPORTANT", "OPTIONAL"},
    ),
    _question("application_budget", _always),
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
        if key == "academic_history":
            # The highlights were about the reading's record, which the student
            # just replaced. reading_id stays: finalize records what they kept as
            # the correction to that reading.
            return replace(self, answers=answers, correction_key=None, highlights=())
        return replace(self, answers=answers, correction_key=None)

    def with_correction(self, key: str) -> ConsultationDraft:
        return replace(self, correction_key=key)


def session_key(*, tenant_id: UUID, membership_id: UUID) -> str:
    return f"consultation:{tenant_id}:{membership_id}"


def read_draft(
    session: MutableMapping[str, object], *, tenant_id: UUID, membership_id: UUID
) -> ConsultationDraft:
    key = session_key(tenant_id=tenant_id, membership_id=membership_id)
    raw = session.get(key)
    if raw is None:
        return ConsultationDraft(tenant_id, membership_id, {})
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
            raise ValueError
        if UUID(str(envelope["tenant_id"])) != tenant_id:
            raise ValueError
        if UUID(str(envelope["membership_id"])) != membership_id:
            raise ValueError
        answers = envelope["answers"]
        if not isinstance(answers, dict) or set(answers) - set(_QUESTIONS_BY_KEY):
            raise ValueError
        if any(_canonical_answer(key, value) != value for key, value in answers.items()):
            raise ValueError
        json.dumps(answers)
        correction = envelope.get("correction_key")
        if correction is not None and (
            not isinstance(correction, str) or correction not in answers
        ):
            raise ValueError
        reading = envelope.get("reading_id")
        reading_id = UUID(str(reading)) if reading is not None else None
        highlights = _HIGHLIGHTS.validate_python(envelope.get("highlights", []))
        return ConsultationDraft(
            tenant_id, membership_id, dict(answers), correction, reading_id, highlights
        )
    except (KeyError, TypeError, ValueError):
        session.pop(key, None)
        session.modified = True  # type: ignore[attr-defined]
        return ConsultationDraft(tenant_id, membership_id, {})


def write_draft(session: MutableMapping[str, object], draft: ConsultationDraft) -> None:
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
    session[session_key(tenant_id=draft.tenant_id, membership_id=draft.membership_id)] = envelope
    session.modified = True  # type: ignore[attr-defined]


def clear_draft(session: MutableMapping[str, object], draft: ConsultationDraft) -> None:
    session.pop(session_key(tenant_id=draft.tenant_id, membership_id=draft.membership_id), None)
    session.modified = True  # type: ignore[attr-defined]


def next_profile_question(draft: ConsultationDraft) -> ProfileQuestion | None:
    if draft.correction_key is not None:
        return _QUESTIONS_BY_KEY[draft.correction_key]
    return next(
        (
            question
            for question in QUESTIONS
            if question.asked_when(draft) and question.key not in draft.answers
        ),
        None,
    )


def consultation_progress(draft: ConsultationDraft) -> tuple[int, int]:
    """(answered, applicable_total) for the wizard's progress indicator.

    The denominator is dynamic: conditional questions enter it only once
    their asked_when predicate holds, so the total can grow as answers
    land (the wizard progress indicator; documented behavior).
    """
    applicable = [question for question in QUESTIONS if question.asked_when(draft)]
    answered = sum(1 for question in applicable if question.key in draft.answers)
    return answered, len(applicable)


def _profile_payload(draft: ConsultationDraft) -> dict[str, object]:
    """The answers as a profile: the graduation answer goes into its record."""
    payload = {key: value for key, value in draft.answers.items() if key != "expected_completion"}
    graduation = draft.answer("expected_completion")
    if graduation is not None and _undated(payload):
        history = cast(list[dict[str, object]], payload["academic_history"])
        payload["academic_history"] = [
            {**history[0], "expected_completion": graduation},
            *history[1:],
        ]
    return payload


def validate_draft(draft: ConsultationDraft) -> StudentProfileSnapshot:
    return StudentProfileSnapshot.model_validate(_profile_payload(draft))


def prefill_from_latest_reading(
    draft: ConsultationDraft, *, membership: Membership
) -> ConsultationDraft:
    """Put the latest transcript reading into the draft, if it is not accepted yet.

    Continuing past the summary is the student's acceptance (spec T2), so once
    the newest reading is accepted nothing is offered -- an older unaccepted one
    is superseded, never re-offered. A draft that already holds an academic
    record -- typed or prefilled -- is left alone. A reading that is not a valid
    academic record, or whose highlights do not parse, is not offered: the
    student types it (read_draft would otherwise drop the draft on every
    request).
    """
    if "academic_history" in draft.answers:
        return draft
    reading = TranscriptReading.objects.filter(student=membership).order_by("-created_at").first()
    if reading is None or reading.accepted is not None:
        return draft
    try:
        history = _canonical_answer("academic_history", [reading.record])
        highlights = _HIGHLIGHTS.validate_python(reading.highlights)
    except ValidationError:
        return draft
    return replace(
        draft,
        answers={**draft.answers, "academic_history": history},
        reading_id=reading.id,
        highlights=highlights,
    )


@transaction.atomic
def finalize_consultation(
    *, membership: Membership, draft: ConsultationDraft
) -> tuple[StudentProfileSnapshot, RecommendationRun]:
    payload = _profile_payload(draft)
    snapshot = StudentProfileSnapshot.model_validate(payload)
    profile = create_profile_version(student=membership, snapshot=snapshot)
    if draft.reading_id is not None:
        kept = cast(list[object], payload["academic_history"])[0]
        TranscriptReading.objects.filter(id=draft.reading_id, student=membership).update(
            accepted=kept
        )
    return snapshot, RecommendationRun.objects.create(profile_version=profile)


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
