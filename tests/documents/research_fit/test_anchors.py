from uuid import uuid4

import pytest

from apps.documents.letter_schemas import Storyline
from apps.documents.models import VerifiedFact
from apps.documents.research_fit.anchors import (
    Anchor,
    TopicPhrase,
    banned_terms,
    guard_phrase,
    infer_fit_mode,
    pick_anchor,
    site_language,
    student_profile_terms,
    topic_phrase,
)

pytestmark = pytest.mark.django_db  # program_factory needs the DB; the rest is pure


class _Response:
    def __init__(self, parsed):
        self.output_parsed = parsed
        self.output = []


class _Parser:
    def __init__(self, *phrases):
        self.responses = [_Response(TopicPhrase(phrase=p)) for p in phrases]
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _fact(category, payload, confirmed=True):
    return VerifiedFact(
        id=uuid4(), category=category, payload=payload,
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        confirmed_by_id=uuid4() if confirmed else None,
    )


def _facts(*facts):
    return {f.id: f for f in facts}


def test_the_strongest_anchor_is_research_then_experience_then_education():
    research = _fact(
        "RESEARCH", {"thesis_title": "A gait controller for the BSU quadruped", "methods": ["MPC"]}
    )
    experience = _fact(
        "EXPERIENCE", {"role": "Intern", "employer": "Azercell", "description": "network planning"}
    )
    education = _fact(
        "EDUCATION",
        {"institution_original": "Baku State University", "field_of_study": "Computer Science"},
    )
    assert pick_anchor(_facts(research, experience, education), None).rung == 1
    assert pick_anchor(_facts(experience, education), None).rung == 2
    assert pick_anchor(_facts(education), None).rung == 3


def test_experience_beats_bare_skill_and_thesis_education_beats_bare_education():
    from apps.documents.evidence.readings import UsableBullet, UsableReading

    skill = _fact("SKILL", {"name": "Python"})
    experience = _fact(
        "EXPERIENCE", {"role": "Engineer", "description": "distributed consensus systems"}
    )
    bare_edu = _fact("EDUCATION", {"field_of_study": "Computer Science"})
    thesis_edu = _fact(
        "EDUCATION",
        {"field_of_study": "Computer Science", "thesis_title": "Stochastic Demand Forecasting"},
    )
    # Skill comes first in dict order, but experience must still win within rung 2.
    chosen_rung2 = pick_anchor({skill.id: skill, experience.id: experience}, None)
    assert chosen_rung2.fact_id == experience.id
    # Bare education comes first in dict order, but thesis education wins within rung 3.
    chosen_rung3 = pick_anchor({bare_edu.id: bare_edu, thesis_edu.id: thesis_edu}, None)
    assert chosen_rung3.fact_id == thesis_edu.id
    # UsableReading thesis beats bare education when no rung 1/2 fact exists.
    reading = UsableReading(
        source="upload",
        url=None,
        document_id=None,
        summary="Thesis on graph neural networks.",
        kind="thesis",
        names=(),
        first_commit=None,
        last_commit=None,
        bullets=(UsableBullet("Trained message-passing GNN.", ("GNN",), "supported"),),
    )
    chosen_reading = pick_anchor({bare_edu.id: bare_edu}, None, readings=(reading,))
    assert chosen_reading.rung == 2
    assert "graph neural networks" in chosen_reading.text.lower()


def test_the_storyline_theme_is_the_last_rung():
    theme = Storyline(theme="grid integration of renewable energy", theme_kind="MATCH",
                      anchors=(uuid4(),), future="a")
    anchor = pick_anchor({}, theme)
    assert anchor == Anchor(rung=4, text="grid integration of renewable energy", fact_id=None)
    assert pick_anchor({}, None) is None


def test_banned_terms_carry_the_name_and_every_institution():
    identity = _fact("IDENTITY", {"full_name": "Aysel Mammadova"})
    education = _fact("EDUCATION", {"institution_original": "Baku State University"})
    experience = _fact("EXPERIENCE", {"employer": "Azercell"})
    banned = banned_terms(_facts(identity, education, experience))
    assert {"aysel mammadova", "aysel", "mammadova", "baku state university", "azercell"} <= banned


def test_guard_strips_names_institutions_capitalised_phrases_and_years():
    banned = frozenset({"aysel mammadova", "aysel", "mammadova", "baku state university"})
    phrase = guard_phrase(
        "Gait control for the Baku State University quadruped by Aysel Mammadova in 2024",
        banned=banned,
    )
    assert phrase == "gait control for the quadruped by in"
    assert "baku" not in phrase and "aysel" not in phrase and "2024" not in phrase


def test_guard_strips_a_bare_lowercase_banned_token():
    # Not part of a capitalised run, so _CAPITALISED_PHRASE cannot be what
    # removes it: this is the only test that fails if the banned-term pass
    # in guard_phrase is broken or deleted.
    phrase = guard_phrase(
        "legged locomotion research with mammadova group",
        banned=frozenset({"mammadova"}),
    )
    assert phrase == "legged locomotion research with group"


def test_guard_caps_at_twelve_words_and_lowercases():
    # lowercase words on purpose: a run of capitalised words IS a capitalised
    # phrase and the guard strips it (see the test above)
    phrase = guard_phrase(" ".join(f"word{i}" for i in range(20)) + " Extra", banned=frozenset())
    assert len(phrase.split()) == 12
    assert phrase == phrase.lower()


def test_topic_phrase_asks_the_model_for_verified_anchors_and_guards_the_answer():
    parser = _Parser("Legged locomotion control at Baku State University")
    anchor = Anchor(rung=1, text="A gait controller for the BSU quadruped", fact_id=uuid4())
    phrase = topic_phrase(
        anchor, parser=parser, student_id="s", banned=frozenset({"baku state university"})
    )
    assert phrase == "legged locomotion control at"
    call = parser.calls[0]
    assert call["text_format"] is TopicPhrase
    assert call["max_output_tokens"] == 200 and call["store"] is False
    assert "DATA" in call["input"][0]["content"]


class _Boom(Exception):
    """Stands for a model SDK's transport errors (e.g. openai.APIConnectionError,
    RateLimitError, APITimeoutError): plain Exception subclasses, not
    ValueError/ValidationError, that _ask must degrade rather than raise (D11)."""


class _RaisingParser:
    def parse(self, **kwargs):
        raise _Boom("network down")


def test_topic_phrase_degrades_to_the_anchor_text_on_a_transport_failure():
    # If _ask narrows its except back to ValidationError, _Boom is not a
    # ValidationError and this call raises instead of degrading.
    anchor = Anchor(rung=1, text="A gait controller for the BSU quadruped", fact_id=uuid4())
    phrase = topic_phrase(
        anchor, parser=_RaisingParser(), student_id="s", banned=frozenset()
    )
    assert phrase == "a gait controller for the bsu quadruped"


def test_topic_phrase_does_not_call_the_model_for_the_theme():
    parser = _Parser()
    anchor = Anchor(rung=4, text="Grid integration of renewable energy", fact_id=None)
    result = topic_phrase(anchor, parser=parser, student_id="s", banned=frozenset())
    assert result == "grid integration of renewable energy"
    assert parser.calls == []


@pytest.mark.parametrize(
    "code,expected",
    [
        ("DE", "de"), ("AT", "de"), ("TR", "tr"), ("NL", "nl"),
        ("GB", None), ("US", None), ("AZ", "az"),
    ],
)
def test_site_language_comes_from_the_programme_country(code, expected, program_factory):
    assert site_language(program_factory(country_code=code)) == expected


def test_a_name_with_an_apostrophe_or_a_period_is_still_subtracted():
    """PR #114 review: the guard normalised punctuation away and THEN
    subtracted terms that still carried it, so nothing matched.

    Measured before the fix, the query that reached the provider was
    "a gait controller ... supervised by o brien". The existing test uses a
    punctuation-free name, which is exactly why it could not see this.
    """
    banned = frozenset({"maria", "maria o'brien", "o'brien", "univ. of texas at austin"})
    assert "brien" not in guard_phrase(
        "supervised by Maria O'Brien on prosthetic gait", banned=banned
    )
    assert "texas" not in guard_phrase("gait study at Univ. of Texas at Austin", banned=banned)


def test_a_two_letter_surname_does_not_shred_the_query():
    """The other direction of the same line: an unanchored str.replace turned
    "climate policy for coastal livelihoods" into "c mate po cy for coastal ve
    hoods" for every student called Li, Wu, Ng or An -- a destroyed query whose
    outcome reads as "the institution does nothing related"."""
    banned = frozenset({"wei li", "wei", "li"})
    assert guard_phrase("climate policy for coastal livelihoods", banned=banned) == (
        "climate policy for coastal livelihoods"
    )
    assert "wei" not in guard_phrase("Wei Li studies lithium batteries", banned=banned)


def test_with_the_model_down_no_capitalised_name_reaches_a_query():
    """The fallback strips every capitalised run again (2026-10-14): a supervisor's
    name is capitalised exactly like a title-case title, and banned_terms holds only
    the student's own name and schools. A title-case title is therefore skipped while
    the model is down -- never searched as "of" and never with a name in it."""
    for title in ("Protein Folding with Ayse Yilmaz", "Monte Carlo Simulation of Protein Folding",
                  "Prof Smith Lab at Harvard University", "Max Planck Institute"):
        anchor = Anchor(rung=1, text=title, fact_id=uuid4())
        assert topic_phrase(
            anchor, parser=_RaisingParser(), student_id="s", banned=frozenset()
        ) == "", title


def test_a_phrase_needs_two_real_words_or_it_is_not_searched():
    anchor = Anchor(rung=4, text="Gait at", fact_id=None)
    assert topic_phrase(anchor, parser=_Parser(), student_id="s", banned=frozenset()) == ""
    anchor = Anchor(rung=4, text="quadruped gait control", fact_id=None)
    assert topic_phrase(anchor, parser=_Parser(), student_id="s", banned=frozenset()) == (
        "quadruped gait control"
    )


def test_student_profile_terms_extracts_technical_vocabulary_and_drops_pii():
    uid = uuid4()
    identity = VerifiedFact(
        id=uuid4(),
        category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": "Leyla Mammadova"},
        confirmed_by_id=uid,
    )
    research = VerifiedFact(
        id=uuid4(),
        category=VerifiedFact.Category.RESEARCH,
        payload={
            "title": "Lyapunov Quadruped Stabilization",
            "methods": ["stochastic MPC", "kalman filtering"],
            "institution": "Baku State University",
        },
        confirmed_by_id=uid,
    )
    storyline = Storyline(
        theme="nonlinear control under delay",
        theme_kind="MATCH",
        anchors=(research.id,),
        turn=research.id,
        gap="distributed sensor fusion",
        future="autonomous legged inspection",
    )
    terms = student_profile_terms({identity.id: identity, research.id: research}, storyline)
    assert "lyapunov" in terms
    assert "stochastic" in terms
    assert "kalman" in terms
    assert "distributed" in terms
    assert "leyla" not in terms
    assert "mammadova" not in terms


def test_infer_fit_mode_classifies_direct_transfer_pivot_and_curriculum_bridge():
    fid = uuid4()
    assert (
        infer_fit_mode(
            anchor_rung=1,
            anchor_text="quadruped locomotion control under actuator saturation",
            sentence="Prof. Smith leads research on quadruped locomotion and torque control.",
            kind="named_person",
        )
        == "direct"
    )
    assert (
        infer_fit_mode(
            anchor_rung=1,
            anchor_text="stochastic differential equations for financial option pricing",
            sentence="The group studies epidemiological disease transmission dynamics.",
            kind="research_group",
        )
        == "method_transfer"
    )
    pivot_story = Storyline(
        theme="computational neuroscience",
        theme_kind="PIVOT",
        anchors=(fid,),
        future="neural decoding",
    )
    assert (
        infer_fit_mode(
            anchor_rung=4,
            anchor_text="computational neuroscience",
            sentence="The Neural Computation Lab studies spike train decoding.",
            kind="research_group",
            storyline=pivot_story,
        )
        == "pivot_bridge"
    )
    assert (
        infer_fit_mode(
            anchor_rung=3,
            anchor_text="BSc in Mechanical Engineering",
            sentence="The Autonomous Systems Track covers state estimation and motion planning.",
            kind="module_or_track",
        )
        == "curriculum_bridge"
    )

