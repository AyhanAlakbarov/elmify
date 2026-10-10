from unittest.mock import Mock

import pytest
from django.db import DatabaseError

from apps.accounts.profile_versions import create_profile_version
from apps.accounts.schemas import MinimalProfile
from apps.funding.models import RecommendationRun
from apps.research.dispatch import dispatch_recommendation_run, recover_undispatched_runs
from apps.research.schemas import ResearchMessage
from apps.tenancy.context import tenant_scope


def test_recommendation_run_has_a_dispatch_recovery_marker() -> None:
    assert "dispatched_at" in {field.name for field in RecommendationRun._meta.get_fields()}


def _queued_run(agency, membership) -> RecommendationRun:
    with tenant_scope(agency.id):
        profile = create_profile_version(
            student=membership,
            snapshot=MinimalProfile.model_validate(
                {
                    "target_field": "Chemistry",
                    "intended_intake": "2027-09-01",
                    "funding_dependency": "MANDATORY",
                    "strategy": "FUNDING_FIRST",
                    "application_budget": "150",
                }
            ),
        )
        return RecommendationRun.objects.create(profile_version=profile)


@pytest.mark.django_db(transaction=True)
def test_failed_dispatch_leaves_the_run_recoverable(agency_a, membership_a) -> None:
    run = _queued_run(agency_a, membership_a)
    client = Mock()
    client.send_message.side_effect = RuntimeError("SQS unavailable")

    assert not dispatch_recommendation_run(
        tenant_id=agency_a.id, run_id=run.id, client=client, queue_url="queue-url"
    )

    with tenant_scope(agency_a.id):
        run.refresh_from_db()
        assert run.dispatched_at is None


@pytest.mark.django_db(transaction=True)
def test_dispatch_database_failure_is_nonfatal(agency_a, membership_a, monkeypatch) -> None:
    run = _queued_run(agency_a, membership_a)

    def fail_lookup(*_args: object, **_kwargs: object) -> None:
        raise DatabaseError("database unavailable")

    monkeypatch.setattr(
        "apps.research.dispatch.RecommendationRun.objects.select_for_update",
        fail_lookup,
    )

    assert not dispatch_recommendation_run(
        tenant_id=agency_a.id, run_id=run.id, client=Mock(), queue_url="queue-url"
    )


@pytest.mark.django_db(transaction=True)
def test_recovery_dispatches_each_undispatched_run_once(agency_a, membership_a) -> None:
    run = _queued_run(agency_a, membership_a)
    client = Mock()

    assert recover_undispatched_runs(client=client, queue_url="queue-url") == 1
    assert recover_undispatched_runs(client=client, queue_url="queue-url") == 0

    message = ResearchMessage.model_validate_json(
        client.send_message.call_args.kwargs["MessageBody"]
    )
    assert message.run_id == run.id
    assert message.tenant_id == agency_a.id
    with tenant_scope(agency_a.id):
        run.refresh_from_db()
        assert run.dispatched_at is not None
