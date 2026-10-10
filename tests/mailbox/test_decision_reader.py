"""One Jev reading that abstains (dashboard spec §4). A fake client stands in for
the decision layer's transport; ask() itself, the question shapes and the state
are real."""

from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.mailbox import decision_bars
from apps.mailbox.classify import MailVerdict
from apps.mailbox.decision_reader import (
    READ_LIMIT,
    UNAVAILABLE,
    keep_verified,
    read_decision,
    strip_identifiers,
)
from apps.research.decisions import (
    Answer,
    Choice,
    DecisionBudgetExhausted,
    DecisionsUnavailable,
    StateTooLarge,
)

LETTER = (
    "Dear Amina Yusuf (amina.yusuf@gmail.com, +994 50 123 45 67),\n\n"
    "We are pleased to inform you that you have been admitted to the Master's programme "
    "Informatics at the Technical University of Munich for the winter semester 2027/28."
)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


class FakeJev:
    """Answers every question asked; records the state it was sent."""

    def __init__(self, nouls: dict[str, float], choices: dict[str, str]) -> None:
        self.nouls, self.choices, self.states = nouls, choices, []

    def __call__(self, state, questions, *, model, provider):
        self.states.append(state)
        answers = {}
        for qid, question in questions.items():
            if isinstance(question, Choice):
                top = self.choices.get(qid, question.options[-1])
                answers[qid] = Answer(
                    id=qid, value=top, confidence=0.9,
                    probabilities={o: (0.9 if o == top else 0.1 / (len(question.options) - 1))
                                   for o in question.options},
                    model=model, provider=provider,
                )
            else:
                p = self.nouls.get(qid, 0.01)
                answers[qid] = Answer(
                    id=qid, value=p >= 0.5, confidence=max(p, 1 - p),
                    probabilities={"true": p, "false": 1 - p}, model=model, provider=provider,
                )
        return answers


def _read(fake, *, funding="", **kwargs):
    return read_decision(
        LETTER, "tum.de", "M.Sc. Informatics", "TUM", funding,
        student_id=uuid4(), names=frozenset({"amina", "yusuf"}),
        addresses=("amina.yusuf@gmail.com",), client=fake, **kwargs,
    )


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(decision_bars, "MEASURED_ON", "2026-10-20")
    monkeypatch.setattr(decision_bars, "BARS", {})  # every bar at the 0.95 default


def test_no_name_address_or_phone_reaches_the_request() -> None:
    fake = FakeJev({"is_decision": 0.99, "gate:ADMITTED": 0.99}, {"outcome": "ADMITTED"})
    _read(fake)
    payload = repr(fake.states)
    for identifier in ("Amina", "Yusuf", "amina.yusuf@gmail.com", "123 45 67"):
        assert identifier not in payload
    assert "[name]" in payload and "[email]" in payload and "[phone]" in payload


def test_the_subject_travels_in_the_state_stripped_like_the_body() -> None:
    """Ruling F19: the spec's state carries the subject."""
    fake = FakeJev({}, {})
    _read(fake, subject="Admission decision for Amina Yusuf")
    (state,) = fake.states
    assert state["email"]["subject"] == "Admission decision for [name] [name]"


def test_the_state_has_descriptive_keys_and_one_request_asks_everything() -> None:
    fake = FakeJev({}, {})
    _read(fake, funding="TUM Excellence Scholarship")
    (state,) = fake.states
    assert set(state) == {"email", "application"}
    assert state["email"]["from_domain"] == "tum.de"
    assert state["application"] == {
        "programme": "M.Sc. Informatics", "university": "TUM",
        "funding": "TUM Excellence Scholarship",
    }


def test_a_cleared_gate_that_agrees_with_the_choice_reads_the_outcome(measured) -> None:
    reading = _read(FakeJev({"is_decision": 0.99, "gate:ADMITTED": 0.97}, {"outcome": "ADMITTED"}))
    assert (reading.is_decision, reading.outcome, reading.measured) == (True, "ADMITTED", True)


def test_until_the_bars_are_learned_a_reading_says_so() -> None:
    reading = _read(FakeJev({"is_decision": 0.99, "gate:ADMITTED": 0.99}, {"outcome": "ADMITTED"}))
    assert (reading.outcome, reading.measured) == ("ADMITTED", False)


@pytest.mark.parametrize(
    ("nouls", "choice"),
    [
        ({"is_decision": 0.99, "gate:ADMITTED": 0.80}, "ADMITTED"),   # gate under its bar
        ({"is_decision": 0.99, "gate:REJECTED": 0.99}, "ADMITTED"),   # gate for another option
        ({"is_decision": 0.99}, "NOT_STATED"),                        # nothing stated
        ({"is_decision": 0.70, "gate:ADMITTED": 0.99}, "ADMITTED"),   # not surely a decision
    ],
)
def test_anything_short_of_the_rule_abstains(measured, nouls, choice) -> None:
    reading = _read(FakeJev(nouls, {"outcome": choice}))
    assert reading.outcome == ""


def test_an_uncertain_decision_question_abstains_on_availability_too() -> None:
    reading = _read(FakeJev({"is_decision": 0.70}, {}))
    assert reading.is_decision is None


def test_the_funding_is_asked_only_when_the_card_has_one(measured) -> None:
    fake = FakeJev(
        {"is_decision": 0.99, "fgate:NOT_AWARDED": 0.99, "gate:ADMITTED": 0.99},
        {"outcome": "ADMITTED", "funding": "NOT_AWARDED"},
    )
    assert _read(fake, funding="TUM Excellence").funding_outcome == "REJECTED"
    assert _read(fake).funding_outcome == ""


def test_an_offer_of_another_programme_is_its_own_question(measured) -> None:
    reading = _read(FakeJev({"is_decision": 0.99, "other_programme": 0.98}, {}))
    assert reading.other_programme_offered is True


@pytest.mark.parametrize(
    "error",
    [
        DecisionsUnavailable("transport", kind="failed"),
        DecisionBudgetExhausted("spent"),
        StateTooLarge("too large"),
    ],
)
def test_jev_unavailable_is_an_abstention_never_a_fallback(error) -> None:
    def down(*_args, **_kwargs):
        raise error

    assert _read(down) is UNAVAILABLE


def test_no_key_configured_is_an_abstention() -> None:
    """The real ask() with no client and no key (tests/conftest.py clears both)."""
    assert _read(None) is UNAVAILABLE


def test_our_own_rate_limit_abstains_before_any_request() -> None:
    fake = FakeJev({}, {})
    student = uuid4()
    for _ in range(READ_LIMIT):
        read_decision(LETTER, "tum.de", "p", "u", "", student_id=student, client=fake)
    assert read_decision(LETTER, "tum.de", "p", "u", "", student_id=student, client=fake) is (
        UNAVAILABLE
    )
    assert len(fake.states) == READ_LIMIT


def test_quotes_the_classifier_returns_are_kept_only_when_they_are_in_the_email() -> None:
    verdict = MailVerdict(
        label="DECISION", offered_programme="MSc Statistics",
        outcome_conditions=("final transcript", "a signed contract"),
    )
    kept = keep_verified(verdict, "We offer you MSc  Statistics, subject to your Final Transcript.")
    assert kept.offered_programme == "MSc Statistics"
    assert kept.outcome_conditions == ("final transcript",)


def test_a_date_is_not_mistaken_for_a_phone_number() -> None:
    assert strip_identifiers("Due 2027-06-15.", names=frozenset()) == "Due 2027-06-15."


def test_a_decomposed_dotted_capital_still_matches_the_name() -> None:
    """transcript.personal_names folds İ; a mail may spell it as I + U+0307."""
    assert strip_identifiers("Dear ALİYEV", names=frozenset({"aliyev"})) == "Dear [name]"


def test_another_address_than_the_student_s_own_is_stripped_too() -> None:
    assert strip_identifiers("cc: advisor@uni.example", names=frozenset()) == "cc: [email]"


@pytest.mark.parametrize("number", ["0176/12345678", "+49 176/1234 5678"])
def test_a_phone_number_written_with_slashes_is_stripped(number) -> None:
    assert strip_identifiers(f"Call {number} today", names=frozenset()) == "Call [phone] today"


@pytest.mark.parametrize("text", ["Due 15/06/2027.", "Winter semester 2027/28."])
def test_a_slashed_date_or_semester_is_not_a_phone_number(text) -> None:
    assert strip_identifiers(text, names=frozenset()) == text


def test_an_azerbaijani_schwa_name_matches_its_latin_spelling() -> None:
    """Fix round 1, item 5: an account named Əliyev, a mail writing Aliyev."""
    from apps.documents.transcript import _fold

    assert strip_identifiers("Dear Aliyev", names=frozenset({_fold("Əliyev")})) == "Dear [name]"


@pytest.mark.parametrize(
    "override",
    [
        {"DECISIONS_PROVIDER": {"default": "typesafe", "mail_decision": "adapter:openai"}},
        {"TYPESAFE_MODEL": "some/other-model"},
        {"DECISIONS_BASE_URL": "https://proxy.example/api"},
    ],
)
def test_only_jev_may_read_student_mail(settings, override) -> None:
    """Fix round 1, item 4: the owner's permission covers TypeSafe's Jev only."""
    for name, value in override.items():
        setattr(settings, name, value)
    fake = FakeJev({}, {})
    assert _read(fake) is UNAVAILABLE
    assert fake.states == []


def test_any_other_failure_abstains_and_logs_only_its_type(caplog) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("quoted: amina.yusuf@gmail.com")

    with caplog.at_level("INFO"):
        assert _read(broken) is UNAVAILABLE
    assert "RuntimeError" in caplog.text
    assert "amina" not in caplog.text
