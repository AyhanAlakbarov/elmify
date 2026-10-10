from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from apps.tenancy.models import Membership

from .audit import record_event
from .letter_schemas import LetterContent
from .letter_verification import LetterClaimVerdict, verify_letter_claims
from .models import ConsentEvent, DocumentDraft, NarrativeInput
from .schemas import CVContent
from .verification import ClaimVerdict, Verdict, unsuperseded_facts, verify_against_facts

_BLOCKING_VERDICTS = frozenset({Verdict.CONFLICTING, Verdict.UNSUPPORTED})
_COUNSELOR_ROLES = frozenset({Membership.Role.COUNSELOR, Membership.Role.OWNER})
#: Kinds whose content is LetterContent-shaped rather than CVContent-shaped.
#: CORE_NARRATIVE is a letter engine artifact too (apps.documents.letters
#: passes it around as `LetterContent`), not a CV.
_LETTER_KINDS = frozenset({DocumentDraft.Kind.MOTIVATION_LETTER, DocumentDraft.Kind.CORE_NARRATIVE})

#: verdicts_for now returns whichever verdict shape matches the document's
#: kind -- CV drafts get ClaimVerdict (claim_path), letter drafts get
#: LetterClaimVerdict (unit_archetype). Both carry `.verdict`, which is all
#: is_blocked and _BLOCKING_VERDICTS ever read.
AnyClaimVerdict = ClaimVerdict | LetterClaimVerdict


class ApprovalBlocked(ValueError):
    """Raised whenever mark_ready (or revoke_consent) refuses to act.

    ``verdicts`` carries the blocking ClaimVerdicts when the refusal is
    verdict-based, so a caller can show the student which claims blocked
    without recomputing verdicts_for outside the lock, against a ledger that
    may have moved on by then. It is empty for every other kind of refusal
    (wrong actor, wrong status, malformed content).

    The exception message never contains ``ClaimVerdict.claim_text`` --
    that is document text, and this repo's rule is that document text never
    reaches anything log-shaped (exception messages end up in tracebacks and
    logs). The message may name counts and ``claim_path``s; text lives only
    on the ``verdicts`` attribute.
    """

    def __init__(self, message: str, *, verdicts: tuple[AnyClaimVerdict, ...] = ()) -> None:
        super().__init__(message)
        self.verdicts = verdicts


def is_blocked(verdicts: tuple[AnyClaimVerdict, ...]) -> bool:
    return any(verdict.verdict in _BLOCKING_VERDICTS for verdict in verdicts)


def verdicts_for(document: DocumentDraft) -> tuple[AnyClaimVerdict, ...]:
    """Classify a draft's stored content against its student's live ledger.

    Read-only: this is what the review overlay renders, and what mark_ready
    re-runs under lock before it will approve anything.

    Dispatches on ``document.kind``: a CV (or anything else outside
    ``_LETTER_KINDS``) is validated and classified as CVContent, unchanged
    from before. MOTIVATION_LETTER/CORE_NARRATIVE content is LetterContent-
    shaped instead, so it is validated and classified with
    ``verify_letter_claims`` against the same student's facts, plus that
    student's narrative inputs. ``immigration=False`` is passed because
    ``verify_letter_claims`` ignores that argument by design -- it can never
    change a returned verdict's label, only
    ``apps.documents.letters.is_letter_blocked``'s separate blocking
    decision is immigration-aware, and that check has already run before
    this function is ever reached via mark_letter_ready. Do not "fix" this
    into reading a real immigration flag; there is nothing here for it to
    change.

    Raises ApprovalBlocked (not pydantic.ValidationError) if the stored
    content doesn't validate against its kind's schema -- content is fully
    app-controlled (only create_draft/counselor_quick_edit/generate_letter
    write it, always via the matching content type's model_dump), so this
    should never happen, but it fails closed rather than let a
    ValidationError -- which embeds the raw offending input -- escape into
    a caller's traceback.
    """
    if document.kind in _LETTER_KINDS:
        try:
            letter_content = LetterContent.model_validate(document.content)
        except ValidationError:
            raise ApprovalBlocked(f"document {document.id} has malformed content") from None
        facts = {fact.id: fact for fact in unsuperseded_facts(document.student)}
        inputs = {
            entry.id: entry for entry in NarrativeInput.objects.filter(student=document.student)
        }
        return verify_letter_claims(letter_content, facts=facts, inputs=inputs, immigration=False)
    try:
        content = CVContent.model_validate(document.content)
    except ValidationError:
        raise ApprovalBlocked(f"document {document.id} has malformed content") from None
    return verify_against_facts(content, unsuperseded_facts(document.student))


def _verdict_label(verdict: AnyClaimVerdict) -> str:
    """A structured identifier for a blocking verdict's error summary --
    ``claim_path`` for the CV engine's ClaimVerdict, ``unit_archetype`` for
    the letter engine's LetterClaimVerdict. Never ``claim_text``: that is
    document text, and this module's rule (see ApprovalBlocked's docstring)
    is that document text never reaches anything log-shaped."""
    if isinstance(verdict, LetterClaimVerdict):
        return verdict.unit_archetype
    return verdict.claim_path


def _is_active_counselor_or_owner(document: DocumentDraft, membership: Membership) -> bool:
    return (
        membership.active
        and membership.tenant_id == document.tenant_id
        and membership.role in _COUNSELOR_ROLES
    )


def _check_consent_authority(document: DocumentDraft, accepted_by: Membership) -> None:
    if not accepted_by.active:
        raise ApprovalBlocked("accepting membership is not active")
    if document.approval_mode == DocumentDraft.ApprovalMode.PER_DOCUMENT:
        if accepted_by.id != document.student_id:
            raise ApprovalBlocked(
                "PER_DOCUMENT approval must be accepted by the document's own student"
            )
        return
    if not _is_active_counselor_or_owner(document, accepted_by):
        raise ApprovalBlocked(
            "COUNSELOR_APPROVES mode requires an active counselor or owner in the same tenant"
        )


def _check_revoke_authority(document: DocumentDraft, revoked_by: Membership) -> None:
    if revoked_by.active and revoked_by.id == document.student_id:
        return
    if _is_active_counselor_or_owner(document, revoked_by):
        return
    raise ApprovalBlocked(
        "revocation must come from the document's own student or an active counselor/owner "
        "in the tenant"
    )


@transaction.atomic
def mark_ready(*, document: DocumentDraft, accepted_by: Membership) -> DocumentDraft:
    """Approve a draft, or refuse to.

    Verdicts are recomputed here from the locked row's own content and the
    student's ledger -- never taken from the caller. UNSUPPORTED and
    CONFLICTING have no override path for anyone, so there is deliberately no
    argument through which a caller could assert a draft is clean.
    """
    locked = DocumentDraft.objects.select_for_update().get(id=document.id)
    if locked.status == DocumentDraft.Status.APPROVED:
        return locked  # idempotent: never re-stamp approved_by/approved_at
    if locked.status != DocumentDraft.Status.DRAFT:
        raise ApprovalBlocked(f"cannot approve a {locked.status} draft")
    _check_consent_authority(locked, accepted_by)
    verdicts = verdicts_for(locked)
    if is_blocked(verdicts):
        blocking = tuple(v for v in verdicts if v.verdict in _BLOCKING_VERDICTS)
        summary = ", ".join(f"{_verdict_label(v)}={v.verdict}" for v in blocking)
        raise ApprovalBlocked(
            f"document carries {len(blocking)} blocking claim verdict(s): {summary}",
            verdicts=blocking,
        )
    locked.status = DocumentDraft.Status.APPROVED
    locked.approved_by = accepted_by
    locked.approved_at = timezone.now()
    locked.save(update_fields=["status", "approved_by", "approved_at"])
    ConsentEvent.objects.create(
        document=locked, mode=locked.approval_mode, granted_by=accepted_by
    )
    record_event(actor=accepted_by, event="document.approved", object_id=locked.id)
    return locked


@transaction.atomic
def revoke_consent(*, document: DocumentDraft, revoked_by: Membership) -> ConsentEvent | None:
    """Close the open consent event, and pull an APPROVED draft back to DRAFT.

    Consent is the release condition (spec: "what remains genuinely the
    student's ... is consent for the document to go out in their name"), so
    revoking it must actually stop release. Leaving status alone would strand
    the row APPROVED with no open ConsentEvent -- permanently
    approved-without-consent, since mark_ready short-circuits on APPROVED and
    would never write a replacement event. A SUPERSEDED draft's event may
    still be closed, but its status does not change; there is nothing left to
    release.

    revoked_by must be the draft's own student, or an active COUNSELOR/OWNER
    in the same tenant -- checked regardless of whether there's an open event
    to close, so an unauthorized caller can't distinguish "already revoked"
    from "not allowed to look".
    """
    locked = DocumentDraft.objects.select_for_update().get(id=document.id)
    _check_revoke_authority(locked, revoked_by)
    event = (
        ConsentEvent.objects.select_for_update()
        .filter(document=locked, revoked_at__isnull=True)
        .first()
    )
    if event is None:
        return None
    event.revoked_at = timezone.now()
    event.save(update_fields=["revoked_at"])
    record_event(actor=revoked_by, event="document.consent_revoked", object_id=document.id)
    if locked.status == DocumentDraft.Status.APPROVED:
        locked.status = DocumentDraft.Status.DRAFT
        locked.approved_by = None
        locked.approved_at = None
        locked.save(update_fields=["status", "approved_by", "approved_at"])
    return event
