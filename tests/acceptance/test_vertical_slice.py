import pytest

from apps.funding.models import PackVersion
from apps.funding.services import PublicationBlocked, auto_publish_pack
from apps.tenancy.context import tenant_scope


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_thin_slice_publishes_automatically_after_research(slice_driver) -> None:
    run = slice_driver.student_submits_profile_and_starts_research()
    message = slice_driver.receive_message()
    assert message.tenant_id == run.tenant_id
    pending = slice_driver.student_opens_dashboard()
    # The deleted htmx poll became a plain meta refresh, present only while
    # research is still running (spec §5).
    assert pending.contains('<meta http-equiv="refresh" content="15">')
    _fund_the_slice_programme()
    slice_driver.worker_processes(message)
    page = slice_driver.student_opens_dashboard()
    with tenant_scope(run.tenant_id):
        pack = PackVersion.objects.get(run=run, published_at__isnull=False)
    assert pack.published_at is not None
    assert page.contains("Official source")
    # The page groups under the funding (spec §5): the served award heads the
    # pack, and the funded programme renders as a programme row.
    assert page.contains("Foundation Stipend")
    assert page.contains("<h4>MSc Chemistry</h4>")
    assert page.contains("Funding gap")
    assert page.contains("Approved v")
    assert not page.contains('http-equiv="refresh"')


def _fund_the_slice_programme() -> None:
    """A tuition waiver the programme's own page states, as the funding reader
    writes it. The consultation's funding is MANDATORY, so an unfunded
    programme never passes the funding-route gate and the pack held the award
    alone -- no programme row, nothing for "Funding gap" to render on."""
    from decimal import Decimal
    from uuid import uuid4

    from apps.funding.models import (
        CostComponent,
        FundingBenefit,
        FundingOpportunity,
        FundingOpportunityProgram,
        Program,
    )

    program = Program.objects.get(name="MSc Chemistry")
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    opportunity = FundingOpportunity.objects.create(
        canonical_key=f"read:PROGRAM:{uuid4()}", name="Departmental Tuition Waiver",
        family="DEPARTMENT_OR_PROGRAM", scope_type="PROGRAM", program=program,
        kind="I2_PROGRAMME_ATTACHED", agreement="AGREED", served=True,
        money_form="FEE_WAIVER", route="AUTOMATIC_ON_ADMISSION",
    )
    FundingOpportunityProgram.objects.create(opportunity=opportunity, program=program)
    FundingBenefit.objects.create(
        opportunity=opportunity, kind="TUITION", amount=Decimal("12000"), currency="EUR",
        period="ANNUAL", description="Tuition is waived in full.",
    )


@pytest.mark.django_db(transaction=True)
def test_superseded_pack_cannot_be_republished(slice_driver) -> None:
    run = slice_driver.student_submits_profile_and_starts_research()
    slice_driver.worker_processes(slice_driver.receive_message())
    with tenant_scope(run.tenant_id):
        published = PackVersion.objects.get(run=run, published_at__isnull=False)
        changed = PackVersion.objects.create(run=published.run, version=published.version + 1)
        auto_publish_pack(changed)
        stale = PackVersion.objects.get(id=published.id)
        assert stale.superseded_at is not None
        with pytest.raises(PublicationBlocked, match="superseded"):
            auto_publish_pack(stale)
