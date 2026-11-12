import logging
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.documents.coverage import items_of
from apps.documents.models import CVRelevanceAnswer
from apps.documents.relevance import ask_item, item_language, judge, requirement_sentences
from apps.documents.schemas import AwardEntry, CertificationEntry
from apps.research.decisions import Answer, DecisionsUnavailable
from apps.tenancy.context import tenant_scope

from .test_render import _content

pytestmark = pytest.mark.django_db


class _Jev:
    """A decisions client: answers `answer` at `chance`, records each state."""

    def __init__(self, answer="unrelated", chance=0.95, fail=None):
        self.answer, self.chance, self.fail, self.states = answer, chance, fail, []

    def __call__(self, state, questions, *, model, provider):
        if self.fail is not None:
            raise self.fail
        self.states.append(state)
        probabilities = {"asked_for": 0.0, "same_field": 0.0, "general_merit": 0.0,
                         "unrelated": 0.0, "cannot_tell": 0.0}
        probabilities[self.answer] = self.chance
        return {qid: Answer(id=qid, value=self.answer, confidence=self.chance,
                            probabilities=probabilities, model=model, provider=provider)
                for qid in questions}


@pytest.fixture
def on(settings):
    settings.CV_RELEVANCE_LANGUAGES = frozenset({"en"})
    settings.CV_RELEVANCE_BAR = 0.9


@pytest.fixture
def programme(program_factory):
    from apps.funding.models import OfficialSource, OfficialSourceSnapshot, ProgramStatement

    p = program_factory(name="MSc Chemistry")
    source = OfficialSource.objects.create(
        canonical_url=f"https://official.example/{uuid4()}",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, s3_key=f"official-sources/{uuid4()}", s3_version_id="1",
        sha256="0" * 64, final_url=source.canonical_url, redirect_chain=[],
        retrieved_at=timezone.now(), admissions_cycle="2027", content_type="text/html",
        byte_size=1,
    )
    ProgramStatement.objects.create(program=p, snapshot=snapshot, kind="COMPETENCY",
                                    requirement="REQUIRED", text="A bachelor's in chemistry.",
                                    label="chemistry degree")
    return p


def _items():
    content = _content().model_copy(update={
        "awards": (AwardEntry(title="Chess club prize", date="2019-05-01"),),
        "certifications": (CertificationEntry(title="IELTS Academic 7.5"),
                           CertificationEntry(title="Первая помощь"),),
    })
    return items_of(content)


def test_an_item_language_is_read_from_its_script():
    assert item_language("First Aid, Red Cross (2022)") == "en"
    assert item_language("Первая помощь") == "ru"
    assert item_language("Bakı Dövlət Universiteti mükafatı") == "tr_az"
    assert item_language("急救证书") == "other"


def test_switched_off_asks_nothing(agency_a, membership_a, programme, settings):
    settings.CV_RELEVANCE_LANGUAGES = frozenset()
    jev = _Jev()
    with tenant_scope(agency_a.id):
        assert judge(_items(), student=membership_a, programme=programme, client=jev) == {}
    assert jev.states == []


def test_only_switched_on_languages_and_never_a_language_test_are_asked(
    agency_a, membership_a, programme, on
):
    """Review Focus 5: a Cyrillic line with only `en` on is kept unasked."""
    jev = _Jev()
    with tenant_scope(agency_a.id):
        verdicts = judge(_items(), student=membership_a, programme=programme, client=jev)
    assert [s["cv_line"]["text"] for s in jev.states] == ["Chess club prize (2019)"]
    assert len(verdicts) == 1


def test_a_programme_with_no_statements_asks_nothing(agency_a, membership_a, program_factory, on):
    jev = _Jev()
    with tenant_scope(agency_a.id):
        assert judge(_items(), student=membership_a, programme=program_factory(),
                     client=jev) == {}
    assert jev.states == []


def test_jev_sees_one_line_and_the_requirements_and_never_the_student(
    agency_a, membership_a, programme, on
):
    jev = _Jev()
    with tenant_scope(agency_a.id):
        judge(_items(), student=membership_a, programme=programme, client=jev)
    (state,) = jev.states
    assert set(state) == {"programme", "requirements", "cv_line"}
    assert "Jane Doe" not in repr(state) and "jane@example.com" not in repr(state)
    assert list(state["requirements"].values()) == ["A bachelor's in chemistry."]


def test_a_second_run_is_served_from_the_cache(agency_a, membership_a, programme, on):
    first, second = _Jev(), _Jev()
    with tenant_scope(agency_a.id):
        a = judge(_items(), student=membership_a, programme=programme, client=first)
        b = judge(_items(), student=membership_a, programme=programme, client=second)
        assert CVRelevanceAnswer.objects.filter(student=membership_a).count() == 1
    assert a == b and second.states == []


def test_jev_unavailable_keeps_everything_and_says_who_failed(
    agency_a, membership_a, programme, on, caplog
):
    """Review Focus 1."""
    jev = _Jev(fail=DecisionsUnavailable("typesafe answered 503", kind="failed"))
    with tenant_scope(agency_a.id), caplog.at_level(logging.WARNING):
        assert judge(_items(), student=membership_a, programme=programme, client=jev) == {}
    assert "typesafe answered 503" in caplog.text


def test_a_spent_window_keeps_everything(agency_a, membership_a, programme, on, monkeypatch):
    """Review Focus 1: the skill-match limiter, counted once per CV."""
    from apps.documents import relevance

    monkeypatch.setattr(relevance, "rate_limited", lambda *a, **kw: True)
    jev = _Jev()
    with tenant_scope(agency_a.id):
        assert judge(_items(), student=membership_a, programme=programme, client=jev) == {}
    assert jev.states == []


def test_ask_item_reads_the_chance_of_unrelated(programme):
    (chess,) = [i for i in _items() if i.text.startswith("Chess")]
    verdict = ask_item(chess, programme=programme, sentences=requirement_sentences(programme),
                       client=_Jev("same_field", 0.8))
    assert (verdict.answer, verdict.chance, verdict.unrelated) == ("same_field", 0.8, 0.0)
