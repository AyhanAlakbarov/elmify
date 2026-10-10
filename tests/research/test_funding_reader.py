import pytest

from apps.research.funding_judge import FundingDecision

WAIVER = "All admitted international students receive a 50% tuition waiver."

from uuid import uuid4  # noqa: E402

from django.utils import timezone  # noqa: E402

from apps.funding.models import (  # noqa: E402
    FundingBenefit,
    FundingFamily,
    FundingOpportunity,
    Institution,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)
from apps.research.discovery import ResearchLead  # noqa: E402
from apps.research.funding_reader import write_funding_decision  # noqa: E402

pytestmark = pytest.mark.django_db


@pytest.fixture
def program():
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}", name="Example University", country_code="DE",
        official_website="https://university.example.test",
    )
    return Program.objects.create(
        institution=institution, canonical_key=f"program:{uuid4()}", name="MSc Chemistry",
        campus_name="Main", city="Berlin", country_code="DE", location_key="de:berlin",
        degree_level="MASTER", teaching_languages=["English"], duration_months=24,
    )


@pytest.fixture
def sibling_program(program):
    """A second programme at the SAME institution as `program`.

    Exists for the INSTITUTION-scope precedence tests: an INSTITUTION row is
    keyed on institution+kind, so it can be written from any programme's
    page at that institution, not just the one that first agreed it.
    """
    return Program.objects.create(
        institution=program.institution, canonical_key=f"program:{uuid4()}", name="MSc Physics",
        campus_name="Main", city="Berlin", country_code="DE", location_key="de:berlin",
        degree_level="MASTER", teaching_languages=["English"], duration_months=24,
    )


@pytest.fixture
def snapshot():
    source = OfficialSource.objects.create(
        canonical_url="https://university.example.test/msc-chemistry",
        publisher="university.example.test", source_type=OfficialSource.Type.PROGRAM,
    )
    return OfficialSourceSnapshot.objects.create(
        source=source, sha256="a" * 64, s3_key="k", s3_version_id="v", byte_size=10,
        final_url=source.canonical_url, redirect_chain=[], admissions_cycle="2027",
        # retrieved_at has no default on the real model; the brief's fixture
        # omitted it (task-4 brief line 53) and IntegrityError'd on save.
        retrieved_at=timezone.now(),
    )


@pytest.fixture
def other_snapshot():
    """A second page, a different OfficialSource, for the no-downgrade rule (I6)."""
    source = OfficialSource.objects.create(
        canonical_url="https://university.example.test/msc-chemistry/fees",
        publisher="university.example.test", source_type=OfficialSource.Type.PROGRAM,
    )
    return OfficialSourceSnapshot.objects.create(
        source=source, sha256="b" * 64, s3_key="k2", s3_version_id="v", byte_size=10,
        final_url=source.canonical_url, redirect_chain=[], admissions_cycle="2027",
        retrieved_at=timezone.now(),
    )


LEAD = ResearchLead.from_url(
    "https://university.example.test/msc-chemistry", source_type="PROGRAM",
    funding_family="", discovered_by="seed:eacea",
)


def _decision(agreement="AGREED", scope="PROGRAM", **overrides):
    fields = dict(
        kind="I2_PROGRAMME_ATTACHED", scope=scope, internationals_included="YES",
        nationality_shape="OPEN", route="AUTOMATIC_ON_ADMISSION", money_form="FEE_WAIVER",
        holder="INSTITUTION", tuition="PARTIAL", living="NONE", extras=("HOUSING",),
        obligation=(), offered="YES",
        agreement=agreement, quotes=(WAIVER,), name="Tuition waiver", disputed=(),
    )
    fields.update(overrides)
    return FundingDecision(**fields)  # type: ignore[arg-type]


def _write(decision, program, snapshot, lead=LEAD):
    return write_funding_decision(
        decision, program=program, lead=lead, source=snapshot.source, snapshot=snapshot,
    )


def test_an_agreed_programme_award_is_served_at_program_scope(program, snapshot):
    opportunity = _write(_decision(), program, snapshot)
    assert opportunity.scope_type == "PROGRAM" and opportunity.program == program
    assert opportunity.served is True and opportunity.agreement == "AGREED"
    assert opportunity.family == "DEPARTMENT_OR_PROGRAM"
    assert opportunity.money_form == "FEE_WAIVER" and opportunity.found_via == LEAD.discovered_by
    assert list(opportunity.programs.all()) == [program]
    claim = opportunity.evidence_claims.get()
    assert claim.claim == WAIVER and claim.claim_class == OfficialEvidenceClaim.ClaimClass.FUNDING
    assert claim.evidence_strength == "DIRECT" and claim.visibility == "STUDENT_FACING"
    kinds = sorted(
        FundingBenefit.objects.filter(opportunity=opportunity).values_list("kind", flat=True)
    )
    assert kinds == ["HOUSING", "TUITION"]


def test_an_institution_wide_award_anchors_at_the_institution(program, snapshot):
    decision = _decision(scope="INSTITUTION", kind="I1_UNIVERSITY_WIDE")
    opportunity = _write(decision, program, snapshot)
    assert opportunity.scope_type == "INSTITUTION"
    assert opportunity.institution == program.institution and opportunity.program is None
    assert opportunity.family == "UNIVERSITY_WIDE"


def test_an_institution_scope_award_on_a_joint_programme_is_not_written(snapshot):
    """A joint programme has no single institution to anchor an INSTITUTION-scope
    award to -- Program.institution is null for ProvisionType.JOINT, and the real
    consortium members live in awarding_institutions instead. Measured 2026-09-15:
    on the funding-reader-precision live run this crashed the database's
    funding_opportunity_scope_shape_valid check constraint on a real EACEA joint
    master's page. Nothing is written and nothing raises."""
    joint_program = Program.objects.create(
        institution=None, canonical_key=f"program:{uuid4()}", name="Joint MSc Coastal Engineering",
        campus_name="Consortium", city="Berlin", country_code="DE", location_key="de:consortium",
        degree_level="MASTER", teaching_languages=["English"], duration_months=24,
        provision_type=Program.ProvisionType.JOINT,
    )
    decision = _decision(scope="INSTITUTION", kind="I1_UNIVERSITY_WIDE")
    opportunity = _write(decision, joint_program, snapshot)
    assert opportunity is None
    assert not FundingOpportunity.objects.exists()


def test_two_of_three_is_stored_but_not_served(program, snapshot):
    opportunity = _write(_decision(agreement="UNAGREED"), program, snapshot)
    assert opportunity.served is False and opportunity.agreement == "UNAGREED"
    assert opportunity.evidence_claims.get().visibility == "INTERNAL"
    assert opportunity.evidence_claims.get().evidence_strength == "DIRECT"


def test_an_abstained_award_is_an_ecosystem_clue(program, snapshot):
    opportunity = _write(_decision(agreement="ABSTAINED"), program, snapshot)
    assert opportunity.served is False
    assert opportunity.evidence_claims.get().evidence_strength == "ECOSYSTEM_CLUE"


def test_a_lead_that_cannot_support_a_claim_is_never_served(program, snapshot):
    clue = ResearchLead.from_url(
        LEAD.canonical_url, source_type="PROGRAM", funding_family="",
        evidence_strength="ECOSYSTEM_CLUE",
    )
    assert _write(_decision(), program, snapshot, lead=clue).served is False


def test_a_loan_is_recorded_as_repayable(program, snapshot):
    opportunity = _write(_decision(money_form="LOAN", tuition="FULL", extras=()), program, snapshot)
    benefit = FundingBenefit.objects.get(opportunity=opportunity)
    assert benefit.kind == "TUITION" and str(benefit.repayable_share) == "1.000"


def test_an_obligation_is_kept_on_the_row(program, snapshot):
    decision = _decision(obligation=("WORK_IN_HOST", "REPAY_ON_BREACH"))
    opportunity = _write(decision, program, snapshot)
    assert opportunity.obligation == "REPAY_ON_BREACH;WORK_IN_HOST"


def test_rewriting_the_same_award_updates_one_row(program, snapshot):
    first = _write(_decision(agreement="UNAGREED"), program, snapshot)
    second = _write(_decision(agreement="AGREED"), program, snapshot)
    assert first.id == second.id
    assert FundingOpportunity.objects.filter(kind="I2_PROGRAMME_ATTACHED").count() == 1
    assert second.served is True
    # The controller ruling (task-4 brief amendment): a re-read must not leave
    # the first write's claims lying around once the joins that pinned them
    # are gone, and it must not raise ProtectedError doing so.
    assert OfficialEvidenceClaim.objects.filter(claim=WAIVER).count() == 1


def test_an_agreed_institution_award_survives_a_later_unagreed_sibling_read(
    program, sibling_program, snapshot, other_snapshot
):
    decision = _decision(scope="INSTITUTION", kind="I1_UNIVERSITY_WIDE")
    first = _write(decision, program, snapshot)
    assert first.served is True and first.agreement == "AGREED"
    unagreed = _decision(
        scope="INSTITUTION", kind="I1_UNIVERSITY_WIDE", agreement="UNAGREED"
    )
    second = _write(unagreed, sibling_program, other_snapshot)
    assert second.id == first.id
    second.refresh_from_db()
    assert second.served is True and second.agreement == "AGREED"
    assert OfficialEvidenceClaim.objects.filter(claim=WAIVER).count() == 1


def test_an_agreed_institution_award_is_replaced_by_a_later_agreed_read(
    program, sibling_program, snapshot
):
    first = _write(
        _decision(scope="INSTITUTION", kind="I1_UNIVERSITY_WIDE"), program, snapshot
    )
    replacement_text = "All admitted students receive a full grant."
    replacement = _decision(
        scope="INSTITUTION", kind="I1_UNIVERSITY_WIDE", money_form="GRANT",
        quotes=(replacement_text,),
    )
    second = _write(replacement, sibling_program, snapshot)
    assert second.id == first.id
    assert second.money_form == "GRANT"
    assert OfficialEvidenceClaim.objects.filter(claim=WAIVER).count() == 0
    assert OfficialEvidenceClaim.objects.filter(claim=replacement_text).count() == 1


def test_an_agreed_award_with_no_money_stated_is_stored_but_not_served(program, snapshot):
    """C1 belt and braces: agreement on a sentence that names no benefit and no
    form of money is agreement on nothing a student can be told they get."""
    decision = _decision(money_form="UNSTATED", tuition="UNSTATED", living="NONE", extras=())
    opportunity = _write(decision, program, snapshot)
    assert opportunity.agreement == "AGREED" and opportunity.served is False


def test_a_negation_is_never_served_by_the_writer(program, snapshot):
    opportunity = _write(_decision(offered="NO"), program, snapshot)
    assert opportunity.served is False


def test_program_and_programs_scope_are_different_rows(program, snapshot):
    """I6(a): the key carries the scope, so a PROGRAMS award never overwrites a
    PROGRAM award of the same kind on the same programme."""
    one = _write(_decision(scope="PROGRAM"), program, snapshot)
    many = _write(_decision(scope="PROGRAMS"), program, snapshot)
    assert one.id != many.id
    assert many.scope_type == "PROGRAM"


def test_an_agreed_programme_award_survives_an_unagreed_read_of_another_page(
    program, snapshot, other_snapshot
):
    """I6(b): pooled pages of one programme share a key; a blurrier second page
    must not unserve what the first page stated clearly."""
    first = _write(_decision(), program, snapshot)
    second = _write(_decision(agreement="UNAGREED"), program, other_snapshot)
    second.refresh_from_db()
    assert second.id == first.id
    assert second.served is True and second.agreement == "AGREED"
    assert second.evidence_claims.get().source == snapshot.source


@pytest.mark.parametrize(
    ("scope", "kind"), [("PROGRAM", "I2_PROGRAMME_ATTACHED"), ("INSTITUTION", "I1_UNIVERSITY_WIDE")]
)
def test_an_agreed_award_is_downgraded_by_an_unagreed_reread_of_its_own_page(
    program, snapshot, scope, kind
):
    """I6(b): the same page blurring or withdrawing its own statement may, at any scope."""
    _write(_decision(scope=scope, kind=kind), program, snapshot)
    second = _write(_decision(scope=scope, kind=kind, agreement="UNAGREED"), program, snapshot)
    assert second.served is False and second.agreement == "UNAGREED"


def test_the_model_label_is_capped_before_it_becomes_the_shared_name(program, snapshot):
    """M3: the label is shared, student-visible and not verified against the page."""
    long_label = "x" * 200
    decision = _decision(name=long_label)
    assert len(_write(decision, program, snapshot).name) == 80


def test_an_unserved_row_keeps_its_quote_internal(program, snapshot):
    decision = _decision(money_form="UNSTATED", tuition="UNSTATED", living="NONE", extras=())
    opportunity = _write(decision, program, snapshot)
    assert opportunity.agreement == "AGREED" and opportunity.served is False
    assert opportunity.evidence_claims.get().visibility == "INTERNAL"


def test_every_quote_becomes_one_evidence_claim(program, snapshot):
    second = "Housing is guaranteed for the first year."
    opportunity = _write(_decision(quotes=(WAIVER, second)), program, snapshot)
    assert sorted(opportunity.evidence_claims.values_list("claim", flat=True)) == sorted(
        [WAIVER, second]
    )


from apps.research.funding_reader import review_funding  # noqa: E402


def test_the_disputed_fields_are_stored_for_the_reviewer(program, snapshot):
    row = _write(_decision(agreement="UNAGREED", disputed=("route", "money_form")), program,
                 snapshot)
    assert row.disputed == "route;money_form"


def test_accepting_serves_the_row_and_its_quotes(program, snapshot):
    row = _write(_decision(agreement="UNAGREED"), program, snapshot)
    review_funding(row, accepted=True, note="checked the page", now=timezone.now())
    row.refresh_from_db()
    assert row.served is True and row.review == "ACCEPTED" and row.review_note == "checked the page"
    assert row.reviewed_sha256 == snapshot.sha256 and row.reviewed_at is not None
    assert row.evidence_claims.get().visibility == "STUDENT_FACING"


def test_rejecting_unserves_the_row_and_hides_its_quotes(program, snapshot):
    row = _write(_decision(), program, snapshot)
    review_funding(row, accepted=False, note="waiver is for EU students only", now=timezone.now())
    row.refresh_from_db()
    assert row.served is False and row.review == "REJECTED"
    assert row.evidence_claims.get().visibility == "INTERNAL"


def test_a_reread_of_the_same_page_version_never_overrides_a_human(program, snapshot):
    row = _write(_decision(), program, snapshot)
    review_funding(row, accepted=False, note="wrong", now=timezone.now())
    again = _write(_decision(), program, snapshot)
    again.refresh_from_db()
    assert again.id == row.id and again.review == "REJECTED" and again.served is False


def test_a_changed_page_reopens_the_decision(program, snapshot):
    row = _write(_decision(agreement="UNAGREED"), program, snapshot)
    review_funding(row, accepted=True, note="ok", now=timezone.now())
    changed = OfficialSourceSnapshot.objects.create(
        source=snapshot.source, sha256="c" * 64, s3_key="k3", s3_version_id="v", byte_size=10,
        final_url=snapshot.final_url, redirect_chain=[], admissions_cycle="2027",
        retrieved_at=timezone.now(),
    )
    reread = _write(_decision(agreement="UNAGREED"), program, changed)
    reread.refresh_from_db()
    assert reread.review == "" and reread.reviewed_sha256 == "" and reread.served is False


def test_another_page_cannot_reopen_a_human_decision(program, sibling_program, snapshot,
                                                     other_snapshot):
    row = _write(_decision(scope="INSTITUTION", kind="I1_UNIVERSITY_WIDE"), program, snapshot)
    review_funding(row, accepted=False, note="not for internationals", now=timezone.now())
    other = _write(_decision(scope="INSTITUTION", kind="I1_UNIVERSITY_WIDE"), sibling_program,
                   other_snapshot)
    other.refresh_from_db()
    assert other.review == "REJECTED" and other.served is False


@pytest.fixture
def funder_lead():
    """A lead on the holder's own site, not a programme's."""
    return ResearchLead.from_url(
        "https://foundation.example.test/stipendien", source_type="FUNDER",
        funding_family="PRIVATE_FOUNDATION", discovered_by="R4_SEARCH:exa",
    )


def _holder_decision(**overrides):
    fields = dict(
        kind="I0_HOLDER_AWARD", scope="HOLDER_OWN", offered="YES",
        internationals_included="YES", nationality_shape="OPEN",
        route="STUDENT_APPLIES_SEPARATELY", money_form="GRANT", holder="PRIVATE_FOUNDATION",
        tuition="UNSTATED", living="FULL", extras=(), obligation=(), agreement="AGREED",
        quotes=("Das Stipendium beträgt 992 Euro monatlich.",),
        name="Foundation Stipendium", disputed=(),
    )
    fields.update(overrides)
    return FundingDecision(**fields)  # type: ignore[arg-type]


def test_a_holder_own_award_is_served_on_its_holders_own_page(snapshot, funder_lead):
    from apps.research.funding_reader import write_holder_decision

    row = write_holder_decision(
        _holder_decision(), holder_domain="example-foundation.org",
        holder_name="Example Foundation", lead=funder_lead, source=snapshot.source,
        snapshot=snapshot,
    )
    assert row is not None and row.served is True
    assert row.scope_type == "HOLDER" and row.holder == "PRIVATE_FOUNDATION"
    assert row.holder_domain == "example-foundation.org" and row.family == "PRIVATE_FOUNDATION"
    assert row.institution_id is None and row.program_id is None
    assert row.evidence_claims.count() == 1


def test_a_holder_row_with_no_money_form_and_no_benefit_is_not_served(snapshot, funder_lead):
    from apps.research.funding_reader import write_holder_decision

    row = write_holder_decision(
        _holder_decision(
            internationals_included="UNSTATED", nationality_shape="UNSTATED", route="UNSTATED",
            money_form="UNSTATED", holder="EMPLOYER", living="UNSTATED",
            quotes=("We support our employees' studies.",), name="Staff study support",
        ),
        holder_domain="example-corp.org", holder_name="Example Corp", lead=funder_lead,
        source=snapshot.source, snapshot=snapshot,
    )
    assert row is not None and row.served is False
    assert row.family == "INDUSTRIAL_SPONSORSHIP"


def test_a_programme_scoped_decision_never_takes_the_holder_writer(snapshot, funder_lead):
    from apps.research.funding_reader import write_holder_decision

    with pytest.raises(ValueError):
        write_holder_decision(
            _holder_decision(scope="PROGRAM"), holder_domain="example-foundation.org",
            holder_name="Example Foundation", lead=funder_lead, source=snapshot.source,
            snapshot=snapshot,
        )


def test_the_database_refuses_a_holder_row_without_an_organisation():
    """Was "without a holder_domain" until 2026-09-23. The scope-shape
    constraint now requires the FK instead of the string, so the old body
    passed on the new constraint rather than the one it named -- green for a
    reason it was not testing. The FK's own test is
    tests/funding/test_funding_models.py; this keeps the reader's copy honest.
    """
    from django.db import IntegrityError

    with pytest.raises(IntegrityError, match="funding_opportunity_scope_shape_valid"):
        FundingOpportunity.objects.create(
            canonical_key="x", name="x", family="PRIVATE_FOUNDATION", scope_type="HOLDER",
            holder="PRIVATE_FOUNDATION", holder_domain="example-foundation.org",
            organisation=None,
        )


def test_the_database_refuses_an_unknown_holder():
    """With a real organisation, so `funding_opportunity_holder_valid` is the
    only constraint that can fire -- otherwise the scope shape refuses the row
    first and this passes without ever reaching the holder vocabulary."""
    from django.db import IntegrityError

    from apps.research.register import record_organisation

    organisation = record_organisation(
        domain="example-foundation.org", name="Example Foundation",
        kind="PRIVATE_FOUNDATION", country_code="DE", found_via="REGISTER",
    )
    with pytest.raises(IntegrityError, match="funding_opportunity_holder_valid"):
        FundingOpportunity.objects.create(
            canonical_key="y", name="y", family="PRIVATE_FOUNDATION", scope_type="HOLDER",
            holder="CHARITY", holder_domain="example-foundation.org",
            organisation=organisation,
        )


def test_every_holder_has_a_family_and_the_model_copy_has_not_drifted():
    from apps.funding.models import _HOLDER_VALUES
    from apps.research.funding_judge import _HOLDERS
    from apps.research.funding_reader import _FAMILY_BY_HOLDER

    assert _HOLDER_VALUES == _HOLDERS
    assert set(_FAMILY_BY_HOLDER) == set(_HOLDERS)
    # Every mapped family must be one the check constraint admits.
    assert set(_FAMILY_BY_HOLDER.values()) <= set(FundingFamily.values)


def test_a_won_negation_writes_the_row_unserved_with_its_intake_and_sentence(
    program, snapshot
):
    quote = (
        "Disclaimer (15/10/2025): the recruitment of the student intake for the academic "
        "year 2026-2028 will be without scholarship."
    )
    row = write_funding_decision(
        _decision(
            offered="NO", applies_to="2026-2028", stated_on="2025-10-15",
            suspension_quote=quote, quotes=(quote,),
        ),
        program=program, lead=LEAD, source=snapshot.source, snapshot=snapshot,
    )
    assert row is not None and row.served is False
    assert row.suspended_for == "2026-2028" and row.suspension_quote == quote


def test_a_yes_row_carries_no_suspension(program, snapshot):
    row = write_funding_decision(
        _decision(), program=program, lead=LEAD, source=snapshot.source, snapshot=snapshot
    )
    assert row is not None and row.suspended_for == "" and row.suspension_quote == ""


def test_a_reread_that_no_longer_decides_a_row_withdraws_it(program, snapshot):
    from apps.research.funding_reader import withdraw_unread

    row = write_funding_decision(
        _decision(), program=program, lead=LEAD, source=snapshot.source, snapshot=snapshot
    )
    assert row is not None and row.served is True
    assert withdraw_unread(snapshot.source, snapshot, set()) == 1
    row.refresh_from_db()
    assert row.agreement == "WITHDRAWN" and row.served is False
    # The quotes stay, so the withdrawal is readable rather than a gap.
    assert row.evidence_claims.count() == 1


def test_a_row_this_read_still_decides_is_not_withdrawn(program, snapshot):
    from apps.research.funding_reader import withdraw_unread

    row = write_funding_decision(
        _decision(), program=program, lead=LEAD, source=snapshot.source, snapshot=snapshot
    )
    assert row is not None
    assert withdraw_unread(snapshot.source, snapshot, {row.canonical_key}) == 0
    row.refresh_from_db()
    assert row.served is True


def test_a_row_another_page_also_supports_is_not_withdrawn(program, snapshot, other_snapshot):
    """A vaguer read of one page may not unserve what another page stated."""
    from apps.research.funding_reader import withdraw_unread

    row = write_funding_decision(
        _decision(), program=program, lead=LEAD, source=snapshot.source, snapshot=snapshot
    )
    assert row is not None
    OfficialEvidenceClaim.objects.create(
        source=other_snapshot.source, snapshot=other_snapshot, claim=WAIVER,
        evidence_strength="DIRECT", visibility="STUDENT_FACING",
        claim_class=OfficialEvidenceClaim.ClaimClass.FUNDING, last_checked_at=timezone.now(),
    )
    from apps.funding.models import FundingOpportunityEvidenceClaim

    FundingOpportunityEvidenceClaim.objects.create(
        opportunity=row, evidence_claim=OfficialEvidenceClaim.objects.latest("last_checked_at")
    )
    assert withdraw_unread(snapshot.source, snapshot, set()) == 0
    row.refresh_from_db()
    assert row.served is True


def test_a_row_a_human_reviewed_is_never_withdrawn_by_a_reread(program, snapshot):
    from apps.research.funding_reader import review_funding, withdraw_unread

    row = write_funding_decision(
        _decision(agreement="UNAGREED", disputed=("route",)),
        program=program, lead=LEAD, source=snapshot.source, snapshot=snapshot,
    )
    assert row is not None
    review_funding(row, accepted=True, note="checked the page", now=timezone.now())
    assert withdraw_unread(snapshot.source, snapshot, set()) == 0
    row.refresh_from_db()
    assert row.served is True and row.agreement == "UNAGREED"


def test_a_row_with_an_unconfirmed_detail_is_served_and_carries_the_caveat(
    snapshot, funder_lead
):
    """The serve gate's conditions are unchanged except that "every decided
    field unanimous" became "every EXISTENCE field unanimous" (spec 8.6). The
    caveat is persisted so the card can show it beside the quote -- a served row
    that silently dropped which field was unconfirmed would present a model's
    coin-flip as a fact."""
    from apps.research.funding_reader import write_holder_decision

    row = write_holder_decision(
        _holder_decision(
            route="UNSTATED", disputed=("route",), unconfirmed=("route",)
        ),
        holder_domain="example-foundation.org", holder_name="Example Foundation",
        lead=funder_lead, source=snapshot.source, snapshot=snapshot,
    )
    assert row is not None and row.served is True
    assert row.unconfirmed == "route"
    assert row.disputed == "route"
    # UNSTATED, not "": the column carries the judge's vocabulary, in which
    # UNSTATED already means "the page did not say". An unconfirmed detail is
    # deliberately indistinguishable from an unstated one on the value itself --
    # `unconfirmed` is what tells a card the difference.
    assert row.route == "UNSTATED", "a blanked field must not read as a decided value"


def test_a_row_whose_readings_split_on_offered_is_not_served(snapshot, funder_lead):
    """Pinned separately so a future change to the existence tuple fails loudly.
    `unconfirmed` is empty here on purpose: on an UNAGREED award the whole row
    is the caveat, and naming one field would suggest the rest was confirmed."""
    from apps.research.funding_reader import write_holder_decision

    row = write_holder_decision(
        _holder_decision(agreement="UNAGREED", disputed=("offered",)),
        holder_domain="example-foundation.org", holder_name="Example Foundation",
        lead=funder_lead, source=snapshot.source, snapshot=snapshot,
    )
    assert row is not None and row.served is False
    assert row.unconfirmed == ""


def test_a_holder_row_records_its_organisation_in_the_register(snapshot, funder_lead):
    """Reading an award off a body's own page IS discovering that body, so the
    writer is the route that records it -- and the row points at the register
    rather than at a string."""
    from apps.research.funding_reader import write_holder_decision
    from apps.research.models import Organisation

    row = write_holder_decision(
        _holder_decision(), holder_domain="example-foundation.org",
        holder_name="Example Foundation", lead=funder_lead, source=snapshot.source,
        snapshot=snapshot,
    )
    assert row is not None and row.organisation_id is not None
    organisation = Organisation.objects.get(pk=row.organisation_id)
    assert organisation.primary_domain == "example-foundation.org"
    assert organisation.kind == "PRIVATE_FOUNDATION"


from decimal import Decimal  # noqa: E402

from apps.funding.card import award_card, card_fill  # noqa: E402
from apps.research.funding_judge import DecidedAmount  # noqa: E402
from apps.research.funding_reader import card_of  # noqa: E402

STIPEND_LINE = "Scholars receive €1,200 per month for 24 months."


def _amount(**overrides):
    fields = dict(
        covers="LIVING", amount_text="€1,200", amount=Decimal("1200"), currency="EUR",
        period="MONTHLY", bound="EXACT", quote=STIPEND_LINE,
    )
    fields.update(overrides)
    return DecidedAmount(**fields)  # type: ignore[arg-type]


def test_an_agreed_amount_lands_on_its_benefit_with_its_words(program, snapshot):
    row = _write(
        _decision(living="FULL", quotes=(WAIVER, STIPEND_LINE), amounts=(_amount(),)),
        program, snapshot,
    )
    (stipend,) = FundingBenefit.objects.filter(opportunity=row, kind="STIPEND")
    assert (stipend.amount, stipend.currency, stipend.period) == (Decimal("1200"), "EUR", "MONTHLY")
    assert (stipend.amount_text, stipend.amount_bound, stipend.amount_quote) == (
        "€1,200", "EXACT", STIPEND_LINE,
    )


def test_a_sum_for_no_stated_purpose_gets_a_benefit_of_its_own(program, snapshot):
    row = _write(_decision(amounts=(_amount(
        covers="TOTAL", amount_text="€5,000", amount=Decimal("5000"), period="ONE_OFF",
    ),)), program, snapshot)
    other = FundingBenefit.objects.get(opportunity=row, kind="OTHER")
    assert (other.amount, other.period) == (Decimal("5000"), "ONE_OFF")


def test_two_sums_of_one_kind_are_two_benefits_never_one_overwritten(program, snapshot):
    row = _write(_decision(amounts=(
        _amount(covers="TOTAL", amount_text="€5,000", amount=Decimal("5000"), period="ONE_OFF"),
        _amount(covers="OTHER", amount_text="€300", amount=Decimal("300"), period="ONE_OFF"),
    )), program, snapshot)
    others = FundingBenefit.objects.filter(opportunity=row, kind="OTHER")
    figures = sorted(others.values_list("amount", flat=True))
    assert figures == [Decimal("300"), Decimal("5000")]


def test_a_figure_the_arithmetic_cannot_use_keeps_its_words_and_no_number(program, snapshot):
    row = _write(_decision(amounts=(_amount(
        covers="TUITION", amount_text="€500", amount=None, currency=None, period="OTHER",
    ),)), program, snapshot)
    tuition = FundingBenefit.objects.get(opportunity=row, kind="TUITION")
    assert (tuition.amount, tuition.currency, tuition.amount_text) == (None, None, "€500")


def test_the_card_columns_are_written_and_a_reread_replaces_them(program, snapshot):
    row = _write(_decision(
        duration="24 months", duration_months=24, timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
        card_quotes=(("timing", WAIVER),),
    ), program, snapshot)
    assert (row.duration_text, row.duration_months, row.timing, row.cycle) == (
        "24 months", 24, "PRE_ARRIVAL", "ANNUAL_FIXED",
    )
    assert (row.tuition, row.living, row.card_quotes) == ("PARTIAL", "NONE", {"timing": WAIVER})
    again = _write(_decision(), program, snapshot)
    assert (again.duration_text, again.duration_months, again.timing) == ("", None, "UNSTATED")


def test_a_holder_award_writes_its_card_too(snapshot, funder_lead):
    from apps.research.funding_reader import write_holder_decision

    quote = "Das Stipendium beträgt 992 Euro monatlich."
    row = write_holder_decision(
        _holder_decision(amounts=(_amount(amount_text="992 Euro", amount=Decimal("992"),
                                          quote=quote),)),
        holder_domain="example-foundation.org", holder_name="Foundation", lead=funder_lead,
        source=snapshot.source, snapshot=snapshot,
    )
    stipend = FundingBenefit.objects.get(opportunity=row, kind="STIPEND")
    assert (stipend.amount, stipend.amount_text) == (Decimal("992"), "992 Euro")


def test_the_card_of_a_decision_and_of_its_written_row_are_the_same_card(program, snapshot):
    decision = _decision(
        living="FULL", quotes=(WAIVER, STIPEND_LINE), amounts=(_amount(),),
        duration="24 months", duration_months=24, timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
        card_quotes=(("timing", WAIVER),),
    )
    row = _write(decision, program, snapshot)
    written = award_card(row, list(FundingBenefit.objects.filter(opportunity=row)))
    assert written.amounts == card_of(decision).amounts
    assert card_fill(written) == card_fill(card_of(decision))
