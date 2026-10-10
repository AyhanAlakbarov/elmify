"""Tenant-scoped portal work. Mirrors apps/research/worker.py deliberately."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .escalation import Trigger, escalate
from .models import Application
from .profiles import open_portal_session
from .schemas import PortalMessage
from .services import prepare_application
from .session import PortalSession

logger = logging.getLogger(__name__)


def process_portal_message(
    message: PortalMessage, handler: Callable[[PortalMessage], None]
) -> None:
    """Tenant scope for the message; transactions belong to each write.

    Deliberately NOT one atomic block around the handler, which is where
    apps/research/worker.py puts it. That handler makes one fetch; this one
    drives a browser for minutes, and a transaction held open that long keeps a
    Postgres connection idle-in-transaction and -- worse -- rolls back the
    ApplicationStep rows describing what was actually typed into a real portal
    if anything later fails. Every writer below opens its own short
    tenant_transaction instead.
    """
    with tenant_scope(message.tenant_id):
        handler(message)


def handle_portal_message(
    message: PortalMessage,
    *,
    session_factory: Callable[
        [Application], AbstractContextManager[PortalSession]
    ] = open_portal_session,
) -> None:
    """Open a browser for one application and prepare it.

    ``session_factory`` is injected so every test above this line runs against
    FakePortalSession; production passes the real one.
    """
    with tenant_transaction(message.tenant_id):
        # select_related, not a lazy traversal: `app.tenant_id` is
        # transaction-local, so a forward FK resolved after this block runs with
        # no GUC set. Django resolves forward FKs through _base_manager, which
        # bypasses TenantManager, leaving RLS as the only filter -- and under a
        # NOBYPASSRLS role that filter matches nothing, so `application.student`
        # would raise RelatedObjectDoesNotExist out of the worker loop.
        application = Application.objects.select_related("student", "portal_form").get(
            id=message.application_id
        )

    # SQS redelivers whenever a visibility timeout expires under a slow fill,
    # so the state is the idempotence guard: an application already prepared or
    # blocked is not typed into a second time. There is no row lock, because
    # holding one for the whole browser session is the long transaction this
    # worker exists to avoid, and there is only one consumer.
    if application.state != Application.State.PREPARING:
        logger.info("PortalSkip application=%s state=%s", application.id, application.state)
        return

    try:
        with session_factory(application) as session:
            prepare_application(application, session)
    except Exception:
        # Escalate AND re-raise. Escalating is what stops an unanticipated
        # failure -- a browser that dies, an OffDomain outside the fill span, a
        # database blip -- from stranding the application in PREPARING with no
        # exception_item and nobody told. Re-raising is what keeps SQS
        # redelivery and the DLQ doing their job; swallowing here would turn a
        # crash into a silently deleted message. escalate() opens its own short
        # transaction, so it is safe on a crash path, and the state it writes
        # makes the redelivery a no-op at the check above.
        #
        # Host only: an exception message from a portal page must never be
        # interpolated into a notification or a log line.
        #
        # Only from PREPARING. The `with` above also raises on context-manager
        # *exit* -- _LoopThread.close()'s join timeout, browser teardown -- long
        # after prepare_application returned. Escalating there would flip a
        # READY_TO_SUBMIT application to BLOCKED_PORTAL_ERROR, or replace a
        # MISSING_FACT escalation's state and exception_item and orphan its
        # RoadmapItem. The in-memory state is accurate: prepare_application and
        # _escalate both mutate this instance.
        if application.state == Application.State.PREPARING:
            assert application.portal_form is not None  # never queued portal-less
            escalate(
                application,
                Trigger.PORTAL_ERROR,
                detail=(
                    f"preparing this application on "
                    f"{application.portal_form.portal_host} failed"
                ),
            )
        raise
