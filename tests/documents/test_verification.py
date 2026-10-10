from datetime import date

import pytest

from apps.documents.models import VerifiedFact
from apps.documents.schemas import (
    AwardEntry,
    CVContent,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    PersonalInformation,
    PublicationEntry,
    ResearchEntry,
    SkillEntry,
    TimelineEntry,
)
from apps.documents.verification import (
    Verdict,
    fact_payload,
    spec_entries,
    unsuperseded_facts,
    verify_against_facts,
)
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

_EDUCATION = EducationEntry(
    degree_as_awarded="BSc Computer Science",
    institution_original="Example University",
    city="Berlin",
    country="DE",
    start_date="2020-09-01",
    end_date="2024-06-30",
)
_EXPERIENCE = ExperienceEntry(
    employer="Example GmbH",
    title="Research Assistant",
    city="Berlin",
    country="DE",
    start_date="2023-01-01",
    end_date="2024-01-01",
    bullets=("Ran the lab's data pipeline.",),
)
_RESEARCH = ResearchEntry(thesis_title="On Graph Sparsifiers", supervisor="Prof. Muster")
_LANGUAGE = LanguageEntry(language="German", cefr_level="C1", test_name="TestDaF", test_score="5")
_IDENTITY = PersonalInformation(full_name="Jane Doe", email="jane@example.com")
_SKILL = SkillEntry(name="Python", category="Tools")
_PUBLICATION = PublicationEntry(
    authors=("Doe, J.", "Roe, R."),
    self_author_index=0,
    title="A paper",
    venue="J. Things",
    year=2024,
)

_TIMELINE = TimelineEntry(
    start_date="2023-06-30",
    end_date="2023-11-01",
    statement="Full-time carer for a family member.",
)

#: One sample entry per claim-bearing CVContent field, and the fact category
#: each maps onto. Every test below is parametrized over this table, so a new
#: category cannot be added to CVContent without a verification test.
CATEGORY_CASES = (
    ("education", VerifiedFact.Category.EDUCATION, _EDUCATION),
    ("experience", VerifiedFact.Category.EXPERIENCE, _EXPERIENCE),
    ("research", VerifiedFact.Category.RESEARCH, _RESEARCH),
    ("publications", VerifiedFact.Category.PUBLICATION, _PUBLICATION),
    ("awards", VerifiedFact.Category.AWARD, AwardEntry(title="Best Poster, ExampleConf 2024")),
    ("skills", VerifiedFact.Category.SKILL, _SKILL),
    ("languages", VerifiedFact.Category.LANGUAGE, _LANGUAGE),
    ("personal_information", VerifiedFact.Category.IDENTITY, _IDENTITY),
    ("timeline", VerifiedFact.Category.TIMELINE, _TIMELINE),
)

#: Categories carrying comparable detail beyond their identity -- the only
#: ones that can ever produce CONFLICTING.
CONFLICT_CASES = (
    ("education", VerifiedFact.Category.EDUCATION, _EDUCATION, {"start_date": "2019-01-01"}),
    ("experience", VerifiedFact.Category.EXPERIENCE, _EXPERIENCE, {"end_date": "2030-01-01"}),
    ("research", VerifiedFact.Category.RESEARCH, _RESEARCH, {"supervisor": "Prof. Other"}),
    ("languages", VerifiedFact.Category.LANGUAGE, _LANGUAGE, {"cefr_level": "A2"}),
    (
        "timeline",
        VerifiedFact.Category.TIMELINE,
        _TIMELINE,
        {"statement": "Took a planned career break to develop leadership skills."},
    ),
)


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _content(field, entry):
    base = dict(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(_EDUCATION,),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )
    # personal_information is a single model, not a tuple of entries.
    base[field] = entry if field == "personal_information" else (entry,)
    return CVContent(**base)


def _fact(student, category, payload, *, confirmed):
    from django.utils import timezone

    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="consult-x",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        created_by=student,
    )


@pytest.mark.parametrize(("field", "category", "entry"), CATEGORY_CASES)
def test_confirmed_fact_yields_supported(agency_a, django_user_model, field, category, entry):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, f"v-sup-{field}")
        fact = _fact(student, category, fact_payload(entry, category=category), confirmed=True)
        verdicts = verify_against_facts(_content(field, entry), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith(field)]
        assert matching and all(v.verdict == Verdict.SUPPORTED for v in matching)


@pytest.mark.parametrize(("field", "category", "entry"), CATEGORY_CASES)
def test_unconfirmed_fact_yields_uncertain(agency_a, django_user_model, field, category, entry):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, f"v-unc-{field}")
        fact = _fact(student, category, fact_payload(entry, category=category), confirmed=False)
        verdicts = verify_against_facts(_content(field, entry), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith(field)]
        assert matching and all(v.verdict == Verdict.UNCERTAIN for v in matching)


@pytest.mark.parametrize(("field", "category", "entry"), CATEGORY_CASES)
def test_claim_with_no_fact_yields_unsupported(agency_a, field, category, entry):
    with tenant_scope(agency_a.id):
        verdicts = verify_against_facts(_content(field, entry), [])
        matching = [v for v in verdicts if v.claim_path.startswith(field)]
        assert matching and all(v.verdict == Verdict.UNSUPPORTED for v in matching)


@pytest.mark.parametrize(("field", "category", "entry", "override"), CONFLICT_CASES)
def test_stated_differing_detail_yields_conflicting(
    agency_a, django_user_model, field, category, entry, override
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, f"v-con-{field}")
        payload = {**fact_payload(entry, category=category), **override}
        fact = _fact(student, category, payload, confirmed=True)
        verdicts = verify_against_facts(_content(field, entry), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith(field)]
        assert any(v.verdict == Verdict.CONFLICTING for v in matching)


@pytest.mark.parametrize(("field", "category", "entry", "override"), CONFLICT_CASES)
def test_absent_detail_on_the_fact_never_conflicts(
    agency_a, django_user_model, field, category, entry, override
):
    """'Not stated' is not 'stated differently' -- a sparse bridged fact must
    not turn every date on the CV into a blocking CONFLICTING verdict."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, f"v-abs-{field}")
        payload = {**fact_payload(entry, category=category)}
        for key in override:
            payload[key] = None
        fact = _fact(student, category, payload, confirmed=True)
        verdicts = verify_against_facts(_content(field, entry), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith(field)]
        assert all(v.verdict != Verdict.CONFLICTING for v in matching)


def test_verify_never_raises_and_never_mutates_content(agency_a):
    with tenant_scope(agency_a.id):
        content = _content("education", _EDUCATION)
        verdicts = verify_against_facts(content, [])
        assert any(v.verdict == Verdict.UNSUPPORTED for v in verdicts)
        assert content.education[0].institution_original == "Example University"


@pytest.mark.parametrize(
    "malformed_payload",
    [["not", "a", "dict"], "just a string", {"unrelated_key": "value"}],
    ids=["list", "string", "dict-missing-keys"],
)
def test_verify_never_raises_on_malformed_fact_payload(
    agency_a, django_user_model, malformed_payload
):
    """VerifiedFact.payload is an unconstrained JSONField -- a malformed row
    (written by some future bug, not this module) must be classified, not
    crash the approval path that sits downstream of verify_against_facts."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v-malformed")
        fact = _fact(student, VerifiedFact.Category.EDUCATION, malformed_payload, confirmed=True)
        verdicts = verify_against_facts(_content("education", _EDUCATION), [fact])
        assert isinstance(verdicts, tuple)
        matching = [v for v in verdicts if v.claim_path.startswith("education")]
        assert matching  # classified (as UNSUPPORTED, since nothing matches), not raised


def test_fact_stating_a_detail_the_claim_omits_never_conflicts(agency_a, django_user_model):
    """A fact may legitimately know more than the CV states -- a CEFR test
    result the claim doesn't repeat, a thesis supervisor the CV omits. That
    is the fact adding information, not contradicting the claim, so the
    detail guard must be symmetric: empty on *either* side skips the key."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v-sparse-claim")

        language_claim = LanguageEntry(language="German", cefr_level="C1")
        language_payload = {
            **fact_payload(language_claim, category=VerifiedFact.Category.LANGUAGE),
            "test_name": "TestDaF",
            "test_score": "5",
        }
        language_fact = _fact(
            student, VerifiedFact.Category.LANGUAGE, language_payload, confirmed=True
        )
        language_verdicts = verify_against_facts(
            _content("languages", language_claim), [language_fact]
        )
        language_matching = [v for v in language_verdicts if v.claim_path.startswith("languages")]
        assert language_matching and all(
            v.verdict == Verdict.SUPPORTED for v in language_matching
        )

        research_claim = ResearchEntry(thesis_title="On Graph Sparsifiers")
        research_payload = {
            **fact_payload(research_claim, category=VerifiedFact.Category.RESEARCH),
            "supervisor": "Prof. Muster",
        }
        research_fact = _fact(
            student, VerifiedFact.Category.RESEARCH, research_payload, confirmed=True
        )
        research_verdicts = verify_against_facts(
            _content("research", research_claim), [research_fact]
        )
        research_matching = [v for v in research_verdicts if v.claim_path.startswith("research")]
        assert research_matching and all(
            v.verdict == Verdict.SUPPORTED for v in research_matching
        )


def test_empty_identity_never_yields_supported(agency_a, django_user_model):
    """An identity built entirely from missing/empty payload keys isn't
    'about' anything and must not match an equally-empty fact -- a false
    SUPPORTED is the worst failure mode in this module."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v-empty-identity")
        # Awards, not skills: a SkillEntry now requires a non-empty name, so an
        # empty skill identity is unreachable. Awards are still bare strings
        # and can carry one, which is what this guard has to hold for.
        fact = _fact(student, VerifiedFact.Category.AWARD, {"title": ""}, confirmed=True)
        blank = AwardEntry(title="x").model_copy(update={"title": ""})
        verdicts = verify_against_facts(_content("awards", blank), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith("awards")]
        assert matching and all(v.verdict == Verdict.UNSUPPORTED for v in matching)


def _content_with_summary(summary):
    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(_EDUCATION,),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        summary=summary,
        document_language="en",
    )


def test_summary_none_yields_no_verdict(agency_a):
    with tenant_scope(agency_a.id):
        verdicts = verify_against_facts(_content_with_summary(None), [])
        assert not [v for v in verdicts if v.claim_path.startswith("summary")]


def test_unmatched_summary_yields_unsupported(agency_a):
    with tenant_scope(agency_a.id):
        pitch = "Motivated graduate with a passion for sustainable engineering"
        verdicts = verify_against_facts(_content_with_summary(pitch), [])
        matching = [v for v in verdicts if v.claim_path.startswith("summary")]
        assert matching and all(v.verdict == Verdict.UNSUPPORTED for v in matching)


def test_summary_matching_confirmed_personal_fact_yields_supported(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v-summary-sup")
        summary = "Built and shipped three production data pipelines."
        payload = fact_payload(summary, category=VerifiedFact.Category.PERSONAL)
        fact = _fact(student, VerifiedFact.Category.PERSONAL, payload, confirmed=True)
        verdicts = verify_against_facts(_content_with_summary(summary), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith("summary")]
        assert matching and all(v.verdict == Verdict.SUPPORTED for v in matching)


def test_summary_matching_unconfirmed_personal_fact_yields_uncertain(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v-summary-unc")
        summary = "Built and shipped three production data pipelines."
        payload = fact_payload(summary, category=VerifiedFact.Category.PERSONAL)
        fact = _fact(student, VerifiedFact.Category.PERSONAL, payload, confirmed=False)
        verdicts = verify_against_facts(_content_with_summary(summary), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith("summary")]
        assert matching and all(v.verdict == Verdict.UNCERTAIN for v in matching)


def test_generatable_facts_excludes_unconfirmed_and_superseded(agency_a, django_user_model):
    from apps.documents.verification import generatable_facts, unsuperseded_facts

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v-gen")
        payload = fact_payload(_EDUCATION, category=VerifiedFact.Category.EDUCATION)
        unconfirmed = _fact(student, VerifiedFact.Category.EDUCATION, payload, confirmed=False)
        old = _fact(student, VerifiedFact.Category.SKILL, {"skill": "Rust"}, confirmed=True)
        new = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.SKILL,
            payload={"skill": "Go"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="consult-y",
            confirmed_by=student,
            confirmed_at=old.created_at,
            supersedes=old,
            created_by=student,
        )
        assert set(unsuperseded_facts(student)) == {unconfirmed, new}
        assert set(generatable_facts(student)) == {new}


# --- fields the ledger must carry to the model ------------------------------

_GLOSSED_EDUCATION = EducationEntry(
    degree_as_awarded="Bakalavr, Komputer Elmleri",
    degree_english="BSc in Computer Science",
    institution_original="Baki Dovlet Universiteti",
    institution_english="Baku State University",
    city="Baku",
    country="AZ",
    start_date="2017-09-15",
    end_date="2021-06-30",
    grade_native="89/100",
    grade_scale="1-100",
    ects_credits=240,
)
_DETAILED_RESEARCH = ResearchEntry(
    thesis_title="Sparse Recovery Methods for Telecom Churn Signals",
    supervisor="Prof. Rashad Aliyev",
    methods="Compressed sensing, LASSO regularisation.",
    outcomes="Reduced false-positive churn flags by 18%.",
)


@pytest.mark.parametrize("key", ["degree_english", "institution_english", "grade_scale"])
def test_education_payload_carries_the_fields_generation_needs(key):
    # fact_payload is the only writer of ledger payloads, and _facts_payload
    # sends those payloads verbatim to the model. A key dropped here can never
    # reach the CV -- the model would have to invent it, which is the one thing
    # this engine exists to prevent.
    payload = fact_payload(_GLOSSED_EDUCATION, category=VerifiedFact.Category.EDUCATION)
    assert payload[key] == getattr(_GLOSSED_EDUCATION, key)


@pytest.mark.parametrize("key", ["methods", "outcomes"])
def test_research_payload_carries_the_fields_generation_needs(key):
    payload = fact_payload(_DETAILED_RESEARCH, category=VerifiedFact.Category.RESEARCH)
    assert payload[key] == getattr(_DETAILED_RESEARCH, key)


def test_glossed_education_still_verifies_supported(agency_a, django_user_model):
    # The new keys must stay out of `identity`: identity is compared by exact
    # tuple equality, so a gloss there would stop a claim matching its own fact.
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gloss-1")
        fact = _fact(
            student,
            VerifiedFact.Category.EDUCATION,
            fact_payload(_GLOSSED_EDUCATION, category=VerifiedFact.Category.EDUCATION),
            confirmed=True,
        )
        verdicts = verify_against_facts(_content("education", _GLOSSED_EDUCATION), [fact])
    education = [v.verdict for v in verdicts if v.claim_path.startswith("education")]
    assert education == [Verdict.SUPPORTED]


def test_a_differing_gloss_does_not_conflict(agency_a, django_user_model):
    # And out of `detail`: a translation is not a fact that can disagree.
    # "BSc in Computer Science" vs "Bachelor of Science, Computer Science" is
    # the same degree, and CONFLICTING there would block a correct draft.
    stored = fact_payload(_GLOSSED_EDUCATION, category=VerifiedFact.Category.EDUCATION)
    claim = _GLOSSED_EDUCATION.model_copy(
        update={
            "degree_english": "Bachelor of Science, Computer Science",
            "institution_english": "Baku State Univ.",
            "grade_scale": "out of 100",
        }
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gloss-2")
        fact = _fact(student, VerifiedFact.Category.EDUCATION, stored, confirmed=True)
        verdicts = verify_against_facts(_content("education", claim), [fact])
    education = [v.verdict for v in verdicts if v.claim_path.startswith("education")]
    assert education == [Verdict.SUPPORTED]


def test_spec_entries_wraps_a_model_field_as_one_entry():
    """A pydantic v2 model is iterable over (key, value) pairs, so iterating
    personal_information directly yields a verdict per attribute name rather
    than one verdict for the person. This is the guard against that."""
    content = _content("education", _EDUCATION)
    entries = spec_entries(content, "personal_information")
    assert len(entries) == 1
    assert entries[0] is content.personal_information



_GRID_LANGUAGE = LanguageEntry(
    language="English",
    cefr_level="C1",
    test_name="IELTS",
    test_score="7.5",
    listening="C2",
    reading="C2",
    spoken_interaction="B2",
    spoken_production="B2",
    writing="C1",
)


@pytest.mark.parametrize(
    "key", ["listening", "reading", "spoken_interaction", "spoken_production", "writing"]
)
def test_language_payload_carries_the_self_assessment(key):
    # fact_payload is the only writer of ledger payloads and _facts_payload
    # sends them verbatim to the model. A key dropped here can never reach a
    # CV -- the same failure as the _PAYLOAD_KEYS drop fixed in 4a68575.
    payload = fact_payload(_GRID_LANGUAGE, category=VerifiedFact.Category.LANGUAGE)
    assert payload[key] == getattr(_GRID_LANGUAGE, key)


def test_a_revised_sub_skill_does_not_conflict(agency_a, django_user_model):
    """Pins a decision. These fields exist to be edited; if they sat in the
    spec's `detail` tuple, a student correcting one column would produce
    CONFLICTING and block their own draft."""
    stored = fact_payload(_GRID_LANGUAGE, category=VerifiedFact.Category.LANGUAGE)
    revised = _GRID_LANGUAGE.model_copy(update={"reading": "B1", "writing": "B1"})
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "grid-1")
        fact = _fact(student, VerifiedFact.Category.LANGUAGE, stored, confirmed=True)
        verdicts = verify_against_facts(_content("languages", revised), [fact])
    languages = [v.verdict for v in verdicts if v.claim_path.startswith("languages")]
    assert languages == [Verdict.SUPPORTED]


def test_language_payload_carries_mother_tongue():
    entry = LanguageEntry(language="Azerbaijani", cefr_level="C2", mother_tongue=True)
    payload = fact_payload(entry, category=VerifiedFact.Category.LANGUAGE)
    assert payload["mother_tongue"] is True


def test_a_revised_mother_tongue_does_not_conflict(agency_a, django_user_model):
    """Pins a decision, exactly as the sub-skill guard does. If mother_tongue
    sat in the LANGUAGE spec's detail tuple, a student correcting it would
    produce CONFLICTING and block their own draft."""
    stated = LanguageEntry(language="Azerbaijani", cefr_level="C2", mother_tongue=True)
    stored = fact_payload(stated, category=VerifiedFact.Category.LANGUAGE)
    revised = stated.model_copy(update={"mother_tongue": False})
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "mt-1")
        fact = _fact(student, VerifiedFact.Category.LANGUAGE, stored, confirmed=True)
        verdicts = verify_against_facts(_content("languages", revised), [fact])
    languages = [v.verdict for v in verdicts if v.claim_path.startswith("languages")]
    assert languages == [Verdict.SUPPORTED]


def test_skill_provenance_is_carried_but_never_compared(agency_a, django_user_model):
    """kind and evidence record how we read a repository, not what he claims.

    A byte count, an import count or the excerpt that named a technique can all
    change on re-ingest without the claim itself changing, so comparing them
    would turn "we counted differently this time" into a CONFLICTING verdict on
    his own CV. Same treatment as a publication's volume/issue/pages.
    """
    recorded = SkillEntry(
        name="torch", category="Tools", kind="library", evidence="imported by 9 files"
    )
    payload = fact_payload(recorded, category=VerifiedFact.Category.SKILL)
    assert payload["kind"] == "library"
    assert payload["evidence"] == "imported by 9 files"

    claimed = SkillEntry(
        name="torch", category="Tools", kind="technique", evidence="something else entirely"
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v-skill-prov")
        fact = _fact(student, VerifiedFact.Category.SKILL, payload, confirmed=True)
        verdicts = verify_against_facts(_content("skills", claimed), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith("skills")]
        assert matching and all(v.verdict == Verdict.SUPPORTED for v in matching)


def test_facts_come_back_in_the_applicants_own_order(agency_a, django_user_model):
    """Unordered rows became repeated skill headings on a rendered CV.

    Postgres returns rows in whatever order it likes without an ORDER BY;
    those rows are the model's prompt, and cv_base.html groups the skills it
    emits. This is the ordering that makes that grouping meaningful.
    """
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="ordering")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        names = ["first", "second", "third", "fourth", "fifth"]
        for name in names:
            VerifiedFact.objects.create(
                student=student,
                category=VerifiedFact.Category.SKILL,
                payload={"name": name},
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="upload:ordering",
                created_by=student,
            )
        assert [f.payload["name"] for f in unsuperseded_facts(student)] == names


def test_a_relocated_institution_conflicts_instead_of_passing(agency_a, django_user_model):
    """The bug: a generated CV moved a Strasbourg university to Bosnia.

    city/country were carried into the payload and never compared, so the
    claim came back SUPPORTED and every verdict on the document was clean.
    "BA" is a code ISO 3166-1 really assigns, so CountryCode cannot catch this
    one -- only the comparison can. The two checks are not redundant.
    """
    truth = EducationEntry(
        degree_as_awarded="MSc",
        institution_original="University of Strasbourg",
        city="Strasbourg",
        country="FR",
        start_date=date(2024, 9, 1),
    )
    relocated = truth.model_copy(update={"country": "BA"})
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v-relocated")
        fact = _fact(
            student,
            VerifiedFact.Category.EDUCATION,
            fact_payload(truth, category=VerifiedFact.Category.EDUCATION),
            confirmed=True,
        )
        verdicts = verify_against_facts(_content("education", relocated), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith("education")]
        assert matching and all(v.verdict == Verdict.CONFLICTING for v in matching)


def test_a_location_the_cv_never_stated_still_does_not_conflict(agency_a, django_user_model):
    """_details_conflict skips a key either side leaves empty.

    ExperienceEntry.city/country are optional precisely because a real CV
    names the employer and not the town; that absence must not read as a
    contradiction now that the keys are compared.
    """
    entry = ExperienceEntry(
        employer="EPFL",
        title="Research Intern",
        start_date=date(2025, 9, 1),
        bullets=("Benchmarked frameworks.",),
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v-nolocation")
        fact = _fact(
            student,
            VerifiedFact.Category.EXPERIENCE,
            fact_payload(entry, category=VerifiedFact.Category.EXPERIENCE),
            confirmed=True,
        )
        verdicts = verify_against_facts(_content("experience", entry), [fact])
        matching = [v for v in verdicts if v.claim_path.startswith("experience")]
        assert matching and all(v.verdict == Verdict.SUPPORTED for v in matching)


def test_an_experience_entry_keeps_its_supervisor_in_the_ledger():
    """The supervisor is the strongest single signal on an academic CV, and it
    was the one ExperienceEntry field fact_payload dropped. Generation
    serialises the whole payload into its prompt, so a key absent here can
    never be put back: a CV regenerated from the ledger loses the PI, and
    render._section_order then reads a research applicant as taught-track.
    """
    entry = ExperienceEntry(
        employer="EPFL",
        title="Research Assistant",
        supervisor="Prof. Schwaller",
        city="Lausanne",
        country="CH",
        start_date="2023-01-01",
        end_date="2024-06-30",
        # Required, min_length=1: S-010 makes an experience entry bullets
        # rather than a prose block, and the schema enforces it. Omit this and
        # the test fails on a pydantic ValidationError before it can reach the
        # KeyError it exists to prove.
        bullets=("Benchmarked three generative frameworks on one dataset.",),
    )

    payload = fact_payload(entry, category=VerifiedFact.Category.EXPERIENCE)

    assert payload["supervisor"] == "Prof. Schwaller"


def test_a_referee_is_verified_against_the_ledger_like_any_other_claim():
    """A referee is a claim about another person -- a name and an address that
    reach a funder -- so it must be confirmable and contradictable."""
    from apps.documents.models import VerifiedFact
    from apps.documents.schemas import ReferenceEntry
    from apps.documents.verification import fact_payload, payload_keys

    referee = ReferenceEntry(
        name="Prof. Ada Byron",
        position="Professor",
        institution="Example University",
        email="ada@example.com",
    )
    payload = fact_payload(referee, category=VerifiedFact.Category.REFERENCE)
    assert payload["name"] == "Prof. Ada Byron"
    assert payload["email"] == "ada@example.com"
    assert set(payload) <= set(payload_keys(VerifiedFact.Category.REFERENCE))


def test_the_medium_of_instruction_reaches_the_ledger():
    """S-050 needs the fact recorded before any layer can decide anything
    from it; it must be an askable key, not just a schema field."""
    from apps.documents.verification import payload_keys

    assert "medium_of_instruction" in payload_keys(VerifiedFact.Category.EDUCATION)


def test_an_experience_entry_keeps_its_project_in_the_ledger():
    """Same bargain as the supervisor above: carried so a regenerated CV keeps
    the project, never compared because where the model cuts "Research Intern,
    Project Title: X" between role and project moves run to run."""
    entry = ExperienceEntry(
        employer="EPFL",
        title="Research Intern",
        project="Generative AI for peptide organocatalyst design",
        bullets=("Benchmarked three generative frameworks on one dataset.",),
    )

    payload = fact_payload(entry, category=VerifiedFact.Category.EXPERIENCE)

    assert payload["project"] == "Generative AI for peptide organocatalyst design"


def test_an_experience_entry_keeps_its_unpaid_flag_in_the_ledger():
    """funder_templates/rhodes.py (R-080) and sisgp.py both section a CV on
    ExperienceEntry.unpaid, so it must survive the trip into a VerifiedFact
    payload -- carried, never compared, same bargain as supervisor and
    project above."""
    entry = ExperienceEntry(
        employer="Azerbaijani Chemistry Society",
        title="Volunteer tutor",
        unpaid=True,
        bullets=("Taught weekly chemistry classes to 20 school students.",),
    )

    payload = fact_payload(entry, category=VerifiedFact.Category.EXPERIENCE)

    assert payload["unpaid"] is True


def test_the_ledger_carries_every_field_the_audit_added():
    """Generation serialises the whole payload into its prompt, so a key absent
    from _PAYLOAD_KEYS can never be put back: a CV regenerated from the ledger
    would silently lose it. This is the same failure the supervisor had, caught
    once for all nine fields the 2026-09-15 section audit added.
    """
    from apps.documents.schemas import AwardEntry, EducationEntry, PublicationEntry

    education = fact_payload(
        EducationEntry(
            degree_as_awarded="MSc",
            institution_original="University of Strasbourg",
            supervisor="Prof. Varnek",
            funding="Funded by the IRC",
            relevant_coursework="Chemoinformatics, Machine Learning",
        ),
        category=VerifiedFact.Category.EDUCATION,
    )
    assert education["supervisor"] == "Prof. Varnek"
    assert education["funding"] == "Funded by the IRC"
    assert education["relevant_coursework"] == "Chemoinformatics, Machine Learning"

    post = fact_payload(
        ExperienceEntry(
            employer="EPFL", title="Research Intern", group="LIAC", bullets=("Benchmarked.",)
        ),
        category=VerifiedFact.Category.EXPERIENCE,
    )
    assert post["group"] == "LIAC"

    award = fact_payload(
        AwardEntry(title="Foundation Fellowship", awarding_body="UoL", detail="EUR 9,102 stipend"),
        category=VerifiedFact.Category.AWARD,
    )
    assert award["awarding_body"] == "UoL" and award["detail"] == "EUR 9,102 stipend"

    paper = fact_payload(
        PublicationEntry(authors=("A",), title="T", url="https://example.test/paper"),
        category=VerifiedFact.Category.PUBLICATION,
    )
    assert paper["url"] == "https://example.test/paper"

    from apps.documents.schemas import ReferenceEntry

    referee = fact_payload(
        ReferenceEntry(name="Prof. Varnek", do_not_contact=True),
        category=VerifiedFact.Category.REFERENCE,
    )
    assert referee["do_not_contact"] is True
