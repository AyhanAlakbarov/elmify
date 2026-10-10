from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.django_db


def test_the_message_carries_identifiers_only():
    """A queue is a durable store with its own retention policy. Student values
    in a message body would be a second copy of their personal data governed by
    different rules from the first."""
    from apps.portals.schemas import PortalMessage

    message = PortalMessage(
        kind="prepare_application", tenant_id=uuid4(), application_id=uuid4()
    )

    assert set(message.model_dump()) == {
        "schema_version",
        "kind",
        "tenant_id",
        "application_id",
    }
    with pytest.raises(ValidationError):
        PortalMessage(
            kind="prepare_application",
            tenant_id=uuid4(),
            application_id=uuid4(),
            given_name="Ada",
        )


def test_portal_work_goes_to_a_standard_queue():
    """No group id: the portal queue is standard, like every other queue in
    infra/template.yaml. One task consumes it one message at a time."""
    from apps.portals.queue import enqueue_portal_work
    from apps.portals.schemas import PortalMessage

    client = Mock()
    application_id = uuid4()

    enqueue_portal_work(
        PortalMessage(
            kind="prepare_application", tenant_id=uuid4(), application_id=application_id
        ),
        client=client,
        queue_url="q",
    )

    kwargs = client.send_message.call_args.kwargs
    assert "MessageGroupId" not in kwargs
    assert str(application_id) in kwargs["MessageBody"]


def test_a_redelivered_message_does_not_prepare_twice(agency_a, membership_a):
    """SQS redelivers whenever a visibility timeout expires under a slow fill.
    Re-running the whole prepare would type into a real portal a second time."""
    from apps.portals import worker
    from apps.portals.models import Application, PortalForm
    from apps.portals.schemas import PortalMessage
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="apply.example.edu", form_key=f"k-{uuid4()}")
        application = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            state=Application.State.READY_TO_SUBMIT,
        )

        def never(_application):  # pragma: no cover -- must not be called
            raise AssertionError("a prepared application must not be prepared again")

        worker.handle_portal_message(
            PortalMessage(
                kind="prepare_application",
                tenant_id=agency_a.id,
                application_id=application.id,
            ),
            session_factory=never,
        )


def test_the_handler_runs_inside_the_message_tenant(agency_a, membership_a):
    """The scope comes from the message. Note what is deliberately NOT asserted:
    that a transaction is open around the handler. app.tenant_id is
    transaction-local, so it is established per write by tenant_transaction
    rather than once around a browser session -- see process_portal_message."""
    from apps.portals import worker
    from apps.portals.schemas import PortalMessage
    from apps.tenancy.context import current_tenant_id

    seen = {}
    message = PortalMessage(
        kind="prepare_application", tenant_id=agency_a.id, application_id=uuid4()
    )

    worker.process_portal_message(message, lambda _: seen.update(tenant=current_tenant_id()))

    assert seen["tenant"] == agency_a.id
