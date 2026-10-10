"""Prepare one application: fill it, verify it against the page, and stop.

READY_TO_SUBMIT is the terminal success state of plan 2a. Submission, the two
authority modes and the 48-hour rule are plan 2b and are gated on the
portal-terms blocker in §10 of `phased requirements.md` -- there is deliberately
no code path here that could submit if a flag were flipped.
"""

from apps.tenancy.db import tenant_transaction

from .auth import CredentialProvider, reauthenticate, session_expired
from .challenge import STALL_THRESHOLD, UNKNOWN_KIND, detect_challenge
from .escalation import Trigger, escalate, request_first_portal_review
from .fill import FillInterrupted, MissingFact, ReadBackMismatch, read_back
from .models import Application, ApplicationStep, FieldMap
from .packets import NoFieldMap
from .profile import verified_values
from .resolve import resolve_challenge
from .session import PortalSession


def _record(application: Application, kind: str, detail: dict[str, object]) -> None:
    """Its own short transaction. The audit trail records what was really typed
    into a real portal, so each step is committed before the next one can
    fail -- one transaction around the whole fill would roll away the evidence
    that the fill happened."""
    with tenant_transaction(application.tenant_id):
        ApplicationStep.objects.create(
            tenant=application.tenant,
            application=application,
            sequence=application.next_step_sequence(),
            kind=kind,
            detail=detail,
        )


def _stalled_challenge(session: PortalSession, application: Application) -> bool:
    """Is this a challenge nothing recognises, rather than a portal error?

    Called at the one moment the stall heuristic's premise holds: a second
    interrupted fill, on a map re-learned seconds ago. Nothing works on this
    page and no marker matched, which is exactly "stalled with no marker".
    A hit reaches a consultant as UNSOLVED_CHALLENGE (PORTAL_EXCEPTION stage)
    rather than landing in the PORTAL_ERROR bucket -- ServiceResolver refuses to
    send an unknown kind to a paid provider, so this can only ever be a person.

    A marker-kind challenge here is left to the PORTAL_ERROR path: a fill has
    already failed twice, so there is nothing to continue into even if a
    provider solved it.
    """
    assert application.portal_form is not None  # never queued portal-less
    stalled = detect_challenge(
        session,
        page_url=application.portal_form.form_url,
        act_failures=STALL_THRESHOLD,
    )
    if stalled is None or stalled.kind != UNKNOWN_KIND:
        return False
    resolve_challenge(session, stalled, application=application)
    return True


def prepare_application(
    application: Application,
    session: PortalSession,
    *,
    provider: CredentialProvider | None = None,
) -> Application:
    """Fill and verify. Escalates rather than raising for the cases §5.4 names."""
    assert application.portal_form is not None  # never queued portal-less
    field_map = FieldMap.current_for(application.portal_form, application.tenant_id)
    if field_map is None:
        raise NoFieldMap(f"{application.portal_form.portal_host} has no current field map")

    # Inside a transaction, not at autocommit: `app.tenant_id` is
    # transaction-local (apps/tenancy/db.py), and both tables this reads --
    # tenancy_membership through the FK and documents_verifiedfact -- are FORCE
    # ROW LEVEL SECURITY. Without the GUC the policy compares against NULL and
    # every row disappears, so under the production NOBYPASSRLS role this
    # returns nothing and `application.student` raises. tenant_scope alone is a
    # ContextVar; it sets nothing in Postgres.
    with tenant_transaction(application.tenant_id):
        values = verified_values(application.student)
    missing = [
        entry["profile_field"]
        for entry in field_map.entries
        if not (values.get(entry["profile_field"]) or "").strip()
    ]
    if missing:
        # Before goto, deliberately: there is no reason to open a browser
        # against a portal for an application that cannot be completed.
        escalate(application, Trigger.MISSING_FACT, detail=", ".join(sorted(missing)))
        return application

    session.goto(application.portal_form.form_url)

    if session_expired(session, application.portal_form):
        # Constructed lazily, not at import time: every portal test that never
        # exercises this branch would otherwise need AWS credentials just to
        # import this module.
        from .auth import SecretsManagerCredentials

        active_provider = provider or SecretsManagerCredentials()
        if not reauthenticate(session, application, provider=active_provider):
            return application  # already escalated
        # Back on the form, and back on the same profile: the fill below skips
        # whatever the portal's own draft still holds (already_correct), so no
        # completed step is repeated.
        session.goto(application.portal_form.form_url)

    challenge = detect_challenge(session, page_url=application.portal_form.form_url)
    if challenge and not resolve_challenge(session, challenge, application=application):
        return application  # ConsultantResolver has already escalated

    from .engine import OffDomain
    from .fill import already_correct
    from .learn import PIILeak, RateLimited, UnmappedField, learn_form
    from .recovery import fill_with_recovery

    # Captured once, ahead of the closure: `field_map` itself is reassigned
    # below to fill_with_recovery's return value, and mypy cannot see that
    # relearn() only ever runs before that reassignment happens.
    profile_fields = [entry["profile_field"] for entry in field_map.entries]

    def relearn() -> FieldMap:
        """A learn pass scoped to this form, with the student's own values as
        the forbidden list -- a re-learn is the widest path for a page value to
        end up in a shared FieldMap, so it is checked hardest."""
        assert application.portal_form is not None  # asserted above; closures lose it
        return learn_form(
            session,
            application.portal_form,
            profile_fields=profile_fields,
            tenant_id=application.tenant_id,
            forbidden_values=list(values.values()),
        )

    try:
        # fill_with_recovery writes the FILL step itself, on every path out --
        # including the interrupted ones. It is the only place that knows what
        # each pass typed, and a partially filled real form must not be the one
        # thing missing from §5.5's audit trail.
        field_map = fill_with_recovery(
            session,
            application,
            field_map,
            values,
            relearn=relearn,
            skip=frozenset(already_correct(session, field_map, values)),
        )
    except MissingFact as error:
        escalate(application, Trigger.MISSING_FACT, detail=str(error))
        return application
    except FillInterrupted as error:
        if error.after_relearn and _stalled_challenge(session, application):
            # Already escalated as UNSOLVED_CHALLENGE by resolve_challenge.
            return application
        escalate(application, Trigger.PORTAL_ERROR, detail=str(error))
        return application
    except (RateLimited, UnmappedField) as error:
        # These messages are built entirely from our own field names and counts,
        # so interpolating them is safe.
        escalate(application, Trigger.PORTAL_ERROR, detail=str(error))
        return application
    except PIILeak:
        # The single most security-relevant thing the learn pass can report, and
        # until now it killed the worker instead of reaching a person. Host-only
        # detail deliberately: PIILeak names the selector observe() returned,
        # which is page-derived text.
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail="a re-learn produced a field map holding a student value",
        )
        return application
    except OffDomain:
        # reauthenticate() navigates to the login form, so a portal that moves
        # login to an SSO host raises this on an ordinary day. Host-only for the
        # same reason: the host named in the message is the page's, not ours.
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"the browser left {application.portal_form.portal_host}",
        )
        return application

    try:
        read_back(session, field_map, values)
    except ReadBackMismatch as mismatch:
        # Not a retry: the page holding something else means a selector
        # resolved somewhere we did not intend, and typing again would do it
        # a second time.
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"read-back mismatch on {mismatch.field}",
        )
        return application

    _record(application, "READ_BACK", {"field_map_version": field_map.version, "ok": True})
    with tenant_transaction(application.tenant_id):
        application.state = Application.State.READY_TO_SUBMIT
        application.save(update_fields=["state"])
    request_first_portal_review(application)
    return application
