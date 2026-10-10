"""`FundingOpportunity.organisation` -- the link that replaced a string.

`holder_domain` was a string "because the register lives on another branch"
(2026-09-18). It does not any more, and a string holder cannot carry the second
domain, the cadence or the read state the verifier needs.
"""

from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import IntegrityError

from apps.funding.models import FundingOpportunity
from apps.research.models import Organisation, OrganisationDomain
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db


def _holder_fields(**overrides):
    fields = {
        "canonical_key": f"read:holder:{uuid4()}",
        "name": "Foundation Award",
        "family": "PRIVATE_FOUNDATION",
        "scope_type": "HOLDER",
        "holder": "PRIVATE_FOUNDATION",
        "holder_domain": "bwstiftung.de",
        "holder_name": "Baden-Württemberg Stiftung",
    }
    fields.update(overrides)
    return fields


@pytest.mark.django_db(transaction=True)
def test_a_holder_scoped_award_requires_an_organisation():
    with pytest.raises(IntegrityError, match="funding_opportunity_scope_shape_valid"):
        with transaction.atomic():
            FundingOpportunity.objects.create(**_holder_fields(organisation=None))


def test_a_holder_scoped_award_with_an_organisation_is_accepted():
    organisation = record_organisation(
        domain="bwstiftung.de",
        name="Baden-Württemberg Stiftung",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )
    award = FundingOpportunity.objects.create(**_holder_fields(organisation=organisation))
    assert award.organisation_id == organisation.pk


@pytest.mark.django_db(transaction=True)
def test_a_non_holder_award_needs_no_organisation():
    """The constraint tightened one branch of the scope shape and must not have
    leaked into the other four."""
    award = FundingOpportunity.objects.create(
        canonical_key=f"read:global:{uuid4()}",
        name="Open to all",
        family="PRIVATE_FOUNDATION",
        scope_type="GLOBAL",
    )
    assert award.organisation_id is None


def _targets(executor: MigrationExecutor, selected: dict[str, str]):
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] not in selected]
    targets.extend(selected.items())
    return targets


#: research/0022 depends on funding/0049 (it creates the `runtime_engine`
#: role its write policy targets), so leaving `research` unselected -- at its
#: own head -- while a caller pins `funding` behind 0049 asks the executor
#: for an infeasible mixed forward/backward plan. Pin research at its
#: pre-decision-layer leaf whenever a call also pins `funding`; never when
#: `funding` is absent, so `_migrate({})` (this file's "back to head" call)
#: still reaches research's true head.
# privacy/0002 also depends on funding/0049 (the owner-only grant), same hazard.
_RESEARCH_PIN = {"research": "0009_site_job_record_rls", "privacy": "0001_initial"}


def _migrate(selected: dict[str, str]) -> None:
    executor = MigrationExecutor(connection)
    if "funding" in selected:
        selected = {**_RESEARCH_PIN, **selected}
    executor.migrate(_targets(executor, selected))


@pytest.mark.django_db(transaction=True)
def test_the_backfill_links_every_pre_existing_holder_row():
    """Every other test here exercises the post-migration model on an empty
    table, so the RunPython inside 0044 never runs. This one inserts HOLDER rows
    at 0043 -- before `organisation` exists -- migrates forward through the real
    backfill, and checks what came out.

    Two rows on ONE domain, because that is the case that decides whether the
    backfill creates one CANDIDATE organisation or two: the second row must find
    the first row's `OrganisationDomain`, not mint a duplicate and collide on
    `primary_domain`.
    """
    first_id, second_id = uuid4(), uuid4()
    try:
        _migrate({"funding": "0043_grade_key"})
        with connection.cursor() as cursor:
            for row_id, name in ((first_id, "Award A"), (second_id, "Award B")):
                cursor.execute(
                    """
                    INSERT INTO funding_fundingopportunity
                        (id, canonical_key, name, family, scope_type,
                         cv_format_requirement, kind, holder, holder_domain,
                         holder_name, agreement, served, money_form, route,
                         nationality_shape, internationals_included, obligation,
                         found_via, review, review_note, reviewed_sha256,
                         disputed, suspended_for, suspension_quote)
                    VALUES (%s, %s, %s, 'PRIVATE_FOUNDATION', 'HOLDER',
                            '', '', 'PRIVATE_FOUNDATION', 'bwstiftung.de',
                            'Baden-Württemberg Stiftung', '', false, '', '',
                            '', '', '', '', '', '', '', '', '', '')
                    """,
                    [row_id, f"read:backfill:{row_id}", name],
                )

        _migrate({"funding": "0044_organisation_fk"})
        # Then all the way to head before asserting. The assertions read through
        # the LIVE model, which knows every column the current chain defines, so
        # leaving the database pinned at 0044 fails on whichever column a later
        # migration added (it was `unconfirmed`, from 0045, within the hour).
        # The backfill has already run by this point; nothing after it touches
        # what is being checked.
        _migrate({})

        linked = FundingOpportunity.objects.filter(id__in=(first_id, second_id))
        assert linked.count() == 2
        organisation_ids = {row.organisation_id for row in linked}
        assert None not in organisation_ids
        assert len(organisation_ids) == 1, "one domain must yield one organisation"

        organisation = Organisation.objects.get(pk=organisation_ids.pop())
        assert organisation.primary_domain == "bwstiftung.de"
        assert organisation.status == "CANDIDATE"
        assert organisation.kind == "PRIVATE_FOUNDATION"
        assert organisation.found_via == ["BACKFILL:holder_domain"]
        assert OrganisationDomain.objects.filter(
            registrable_domain="bwstiftung.de"
        ).count() == 1

        # The headline assertion the plan asks for, stated over the table rather
        # than over the two rows this test happens to know about.
        assert not FundingOpportunity.objects.filter(
            scope_type="HOLDER", organisation__isnull=True
        ).exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM funding_fundingopportunity WHERE id IN (%s, %s)",
                [first_id, second_id],
            )
            cursor.execute(
                "DELETE FROM research_organisationdomain "
                "WHERE registrable_domain = 'bwstiftung.de'"
            )
            cursor.execute(
                "DELETE FROM research_organisation WHERE primary_domain = 'bwstiftung.de'"
            )
        _migrate({})
