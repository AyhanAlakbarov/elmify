from datetime import UTC, datetime

import pytest

from apps.accounts.models import StudentProfileVersion
from apps.documents.letter_approval import compute_letter_flags
from apps.documents.letter_schemas import ClaimKind, LetterClaim, LetterContent, LetterUnit
from apps.documents.letter_verification import verify_letter_claims
from apps.documents.letters import _inputs_payload
from apps.documents.models import NarrativeInput, VerifiedFact
from apps.documents.research_fit.home_context import (
    DEFAULT_INDICATOR,
    infer_home_country,
    propose_home_country_context,
    select_indicator_for_context,
)
from apps.documents.verification import Verdict
from apps.funding.models import ApplicationPrompt, Program
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, name: str) -> Membership:
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _fact(student: Membership, category: str, payload: dict) -> VerifiedFact:
    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref="doc:test",
        confirmed_by=student,
        confirmed_at=datetime.now(tz=UTC),
        created_by=student,
    )


def test_infer_home_country_prefers_identity_citizenship_and_excludes_target(
    agency_a, django_user_model
) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "hc_infer_1")
        f_id = _fact(student, VerifiedFact.Category.IDENTITY, {"citizenship": "Azerbaijan"})
        f_edu = _fact(student, VerifiedFact.Category.EDUCATION, {"country": "DE"})
        assert infer_home_country({f_id.id: f_id, f_edu.id: f_edu}, target_country_code="DE") == (
            "AZ",
            "Azerbaijan",
        )
        assert infer_home_country({f_id.id: f_id}, target_country_code="AZ") is None


def test_infer_home_country_falls_back_to_education_country(agency_a, django_user_model) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "hc_infer_2")
        f_edu1 = _fact(student, VerifiedFact.Category.EDUCATION, {"country": "NG"})
        f_edu2 = _fact(student, VerifiedFact.Category.EDUCATION, {"country": "DE"})
        inferred = infer_home_country(
            {f_edu1.id: f_edu1, f_edu2.id: f_edu2}, target_country_code="DE"
        )
        assert inferred == ("NG", "Nigeria")


def test_infer_home_country_reads_onboarding_profile_nationality_before_abroad_education(
    agency_a, django_user_model
) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "hc_infer_onboarding")
        StudentProfileVersion.objects.create(
            student=student,
            version=1,
            schema_version=3,
            snapshot={"nationality": "AZ", "country_of_residence": "TR"},
        )
        # Student did their bachelor's abroad in Turkey and has no ID document fact yet:
        f_edu = _fact(student, VerifiedFact.Category.EDUCATION, {"country": "TR"})
        inferred = infer_home_country(
            {f_edu.id: f_edu}, target_country_code="DE", student=student
        )
        assert inferred == ("AZ", "Azerbaijan")


def test_propose_home_country_context_returns_none_without_default_country_when_unknown(
    agency_a, django_user_model, caplog
) -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> object:
        calls.append(url)
        return []

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "hc_infer_none")
        f_res = _fact(
            student,
            VerifiedFact.Category.RESEARCH,
            {"title": "Solar grid stability without any country field"},
        )
        facts = {f_res.id: f_res}
        assert infer_home_country(facts, target_country_code="DE") is None
        entry = propose_home_country_context(
            student=student,
            facts=facts,
            target_country_code="DE",
            fetch_json=fake_fetch,
        )
        assert entry is None
        assert calls == []
        assert "no home country distinct from target" in caplog.text


def test_select_indicator_matches_domain_keywords_and_defaults_to_rnd(
    agency_a, django_user_model
) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "hc_ind_1")
        f_energy = _fact(
            student,
            VerifiedFact.Category.RESEARCH,
            {"title": "Grid integration of solar photovoltaic inverters"},
        )
        code, _name = select_indicator_for_context({f_energy.id: f_energy})
        assert code == "EG.FEC.RNEW.ZS"

        code_default, _ = select_indicator_for_context({})
        assert code_default == DEFAULT_INDICATOR[0]


def test_propose_home_country_context_creates_verified_input_and_is_idempotent(
    agency_a, django_user_model
) -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> object:
        calls.append(url)
        return [
            {"page": 1},
            [
                {
                    "indicator": {
                        "id": "EG.FEC.RNEW.ZS",
                        "value": (
                            "Renewable energy consumption "
                            "(% of total final energy consumption)"
                        ),
                    },
                    "country": {"id": "AZ", "value": "Azerbaijan"},
                    "date": "2021",
                    "value": 1.3000,
                }
            ],
        ]

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "hc_propose_1")
        f_id = _fact(student, VerifiedFact.Category.IDENTITY, {"citizenship": "AZ"})
        f_res = _fact(
            student,
            VerifiedFact.Category.RESEARCH,
            {"title": "Solar grid stability in renewable energy networks"},
        )
        facts = {f_id.id: f_id, f_res.id: f_res}

        entry = propose_home_country_context(
            student=student,
            facts=facts,
            target_country_code="DE",
            fetch_json=fake_fetch,
        )
        assert entry is not None
        assert entry.kind == NarrativeInput.Kind.HOME_COUNTRY_CIRCUMSTANCES
        assert entry.proposed_by == NarrativeInput.ProposedBy.ENGINE
        assert entry.provenance["entity"] == "Azerbaijan"
        assert entry.provenance["year"] == 2021
        assert entry.provenance["value"] == "1.3"
        assert (
            entry.provenance["source_url"]
            == "https://data.worldbank.org/indicator/EG.FEC.RNEW.ZS?locations=AZ"
        )
        assert len(calls) == 1

        # Second call reuses the stored row without another HTTP call:
        second = propose_home_country_context(
            student=student,
            facts=facts,
            target_country_code="DE",
            fetch_json=fake_fetch,
        )
        assert second is not None and second.id == entry.id
        assert len(calls) == 1

        # _inputs_payload surfaces source_url and entity for the generation prompt:
        payload_json = _inputs_payload({entry.id: entry})
        assert "https://data.worldbank.org/indicator/EG.FEC.RNEW.ZS?locations=AZ" in payload_json
        assert '"entity": "Azerbaijan"' in payload_json


def test_sourced_home_country_claim_verifies_supported_and_blocks_fabricated_figure(
    agency_a, django_user_model
) -> None:
    def fake_fetch(_url: str) -> object:
        return [
            {"page": 1},
            [
                {
                    "indicator": {
                        "id": "EG.FEC.RNEW.ZS",
                        "value": (
                            "Renewable energy consumption "
                            "(% of total final energy consumption)"
                        ),
                    },
                    "country": {"id": "AZ", "value": "Azerbaijan"},
                    "date": "2021",
                    "value": 1.3,
                }
            ],
        ]

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "hc_verify_1")
        f_id = _fact(student, VerifiedFact.Category.IDENTITY, {"citizenship": "AZ"})
        f_res = _fact(student, VerifiedFact.Category.RESEARCH, {"title": "Solar power systems"})
        entry = propose_home_country_context(
            student=student,
            facts={f_id.id: f_id, f_res.id: f_res},
            target_country_code="DE",
            fetch_json=fake_fetch,
        )
        assert entry is not None

        good_text = (
            "In Azerbaijan, renewable energy consumption stood at 1.3 percent in 2021."
        )
        good_claim = LetterClaim(
            text=good_text,
            span_start=0,
            span_end=len(good_text),
            kind=ClaimKind.SOURCED,
            input_id=entry.id,
            source_url=entry.provenance["source_url"],
        )
        good_content = LetterContent(
            language="en",
            units=(
                LetterUnit(
                    archetype="HOME_COUNTRY_CONTRIBUTION",
                    text=good_text,
                    claims=(good_claim,),
                ),
            ),
        )
        verdicts = verify_letter_claims(
            good_content,
            facts={f_id.id: f_id, f_res.id: f_res},
            inputs={entry.id: entry},
            immigration=False,
        )
        assert verdicts[0].verdict == Verdict.SUPPORTED

        prompt_stub = ApplicationPrompt(
            source=ApplicationPrompt.Source.EXTRACTED,
            funder_kind=ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP,
            structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        )
        flags = compute_letter_flags(
            prompt=prompt_stub,
            letter_required=Program.LetterRequired.REQUIRED,
            facts={f_id.id: f_id, f_res.id: f_res},
            binding_violation_after_retry=False,
            content=good_content,
            claim_verdicts=verdicts,
        )
        assert not any(f.reason == "source_unverified" for f in flags)

        # Fabricating a different figure (15 percent instead of 1.3) is UNSUPPORTED:
        bad_text = (
            "In Azerbaijan, renewable energy consumption stood at 15 percent in 2021."
        )
        bad_claim = LetterClaim(
            text=bad_text,
            span_start=0,
            span_end=len(bad_text),
            kind=ClaimKind.SOURCED,
            input_id=entry.id,
            source_url=entry.provenance["source_url"],
        )
        bad_content = LetterContent(
            language="en",
            units=(
                LetterUnit(
                    archetype="HOME_COUNTRY_CONTRIBUTION",
                    text=bad_text,
                    claims=(bad_claim,),
                ),
            ),
        )
        bad_verdicts = verify_letter_claims(
            bad_content,
            facts={f_id.id: f_id, f_res.id: f_res},
            inputs={entry.id: entry},
            immigration=False,
        )
        assert bad_verdicts[0].verdict == Verdict.UNSUPPORTED
