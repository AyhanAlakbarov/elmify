"""Autonomous recovery: a changed form is re-learned, not escalated.

Design point 5 of the spec. Section 5.2's "create review tasks rather than
guessing" is satisfied by recording -- a RecoveryEvent naming both field map
versions is reviewable after the fact -- rather than by stopping, because a
portal that renamed an input should not queue every student behind a human.

This module also owns the FILL step of §5.5's audit trail, because it is the
only place that knows what each pass actually typed -- see _record_fill.
"""

import logging
from collections.abc import Callable

from apps.tenancy.db import tenant_transaction

from .fill import FillInterrupted, fill_form
from .models import Application, ApplicationStep, FieldMap, RecoveryEvent
from .session import PortalSession

logger = logging.getLogger(__name__)


def _record_fill(
    application: Application,
    field_map: FieldMap,
    values: dict[str, str],
    filled: list[str],
) -> None:
    """One FILL step per fill pass: which map version, which fields that pass
    typed, and what into them.

    Written here rather than by the caller because this is the only place that
    knows what each pass actually typed. Two things follow from that. A resume
    skips whatever the portal's own draft already holds (``already_correct``),
    so "every entry in the map" would claim the platform typed fields it
    deliberately left alone. And an interrupted first pass has already put
    values on a real form -- ``relearn()`` below can raise RateLimited,
    UnmappedField or PIILeak, and without this the only record of what was typed
    into a live application would go with it.

    Its own short transaction, for the reason the whole fill path avoids one big
    one: evidence that the fill happened must not roll back with the failure.

    A pass that typed nothing writes no step: the first act() failing is already
    recorded as a RECOVERY or an ESCALATION, and an empty FILL row is noise in
    an audit trail whose whole job is naming what was typed.
    """
    if not filled:
        return
    with tenant_transaction(application.tenant_id):
        ApplicationStep.objects.create(
            tenant=application.tenant,
            application=application,
            sequence=application.next_step_sequence(),
            kind="FILL",
            detail={
                "field_map_version": field_map.version,
                "filled": filled,
                "values": {name: values[name] for name in filled},
            },
        )


def fill_with_recovery(
    session: PortalSession,
    application: Application,
    field_map: FieldMap,
    values: dict[str, str],
    *,
    relearn: Callable[[], FieldMap],
    skip: frozenset[str] = frozenset(),
) -> FieldMap:
    """Fill; on a selector miss, re-learn this form once and finish it.

    Returns the field map that actually completed the form -- the caller reads
    back against that one, not against the map it started with.

    One re-learn, never a loop: each attempt is a full learn pass (~$0.76 for a
    36-field form), and a form we cannot map twice in a row is a portal error
    rather than drift.

    Every pass records its own FILL step, including a pass that was interrupted
    and one that failed on a freshly re-learned map. §5.5's audit trail is what
    was typed into someone's live application, and no path out of here may lose
    it.
    """
    try:
        typed = fill_form(session, field_map, values, skip=skip)
    except FillInterrupted as interrupted:
        return _relearn_and_finish(
            session, application, field_map, values, relearn, skip, interrupted
        )
    _record_fill(application, field_map, values, typed)
    return field_map


def _relearn_and_finish(
    session: PortalSession,
    application: Application,
    field_map: FieldMap,
    values: dict[str, str],
    relearn: Callable[[], FieldMap],
    skip: frozenset[str],
    interrupted: FillInterrupted,
) -> FieldMap:
    """The recovery half, split out only because ``except ... as`` unbinds its
    name at the end of the block and this needs it throughout."""
    assert application.portal_form is not None  # never queued portal-less
    _record_fill(application, field_map, values, interrupted.filled)
    replacement = relearn()
    with tenant_transaction(application.tenant_id):
        RecoveryEvent.objects.create(
            portal_form=application.portal_form,
            kind=RecoveryEvent.Kind.SELECTOR_MISS,
            page_url=application.portal_form.form_url,
            replaced_field_map=field_map,
            replacement_field_map=replacement,
            detail={"profile_field": interrupted.profile_field},
        )
        ApplicationStep.objects.create(
            tenant=application.tenant,
            application=application,
            sequence=application.next_step_sequence(),
            kind="RECOVERY",
            detail={
                "kind": RecoveryEvent.Kind.SELECTOR_MISS.value,
                "from_version": field_map.version,
                "to_version": replacement.version,
                "profile_field": interrupted.profile_field,
            },
        )
    logger.info(
        "PortalRecovery kind=SELECTOR_MISS portal=%s from=%s to=%s",
        application.portal_form.portal_host,
        field_map.version,
        replacement.version,
    )
    # Fields already typed are not typed again. If the re-learn happened
    # because the page navigated rather than because one input moved, the
    # skipped fields are stale -- and prepare_application's read-back over
    # the replacement map is what catches that.
    try:
        typed = fill_form(session, replacement, values, skip=set(interrupted.filled) | set(skip))
    except FillInterrupted as second:
        _record_fill(application, replacement, values, second.filled)
        # after_relearn is what tells prepare_application that nothing works on
        # a map learned seconds ago -- the one moment §5.1's stall heuristic is
        # describing something true.
        raise FillInterrupted(
            second.filled, second.profile_field, after_relearn=True
        ) from second
    _record_fill(application, replacement, values, typed)
    return replacement
