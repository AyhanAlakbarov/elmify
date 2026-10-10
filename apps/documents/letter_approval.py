"""The last gate a motivation letter passes through: a three-way outcome
between blocked (refused outright, no override), flagged (routed to the
counselor queue, stays a draft) and clean (auto-approved).

Mirrors ``apps/documents/approval.py`` (Plan A's CV-side sibling) in
convention -- ``ApprovalBlocked`` is reused unchanged, audit events go
through ``apps.documents.audit.record_event``, and the real blocking rule
(``UNSUPPORTED``, plus immigration-``UNCERTAIN``) is never reimplemented
here: it lives in exactly one place, ``apps.documents.letters
.is_letter_blocked``.

A flag is different from a block: a flag means "a human should look at
this before it goes out", not "this cannot go out". There is deliberately
no counselor override for a block -- if you're looking for one, you want
the flagged path, not this one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from django.utils import timezone

from apps.funding.models import ApplicationPrompt, Program
from apps.tenancy.models import Membership

from .approval import ApprovalBlocked, mark_ready
from .audit import record_event
from .letter_gates import LetterGateViolation
from .letter_schemas import ClaimKind, LetterContent
from .letter_verification import LetterClaimVerdict, verify_letter_claims
from .letters import is_letter_blocked
from .models import DocumentDraft, NarrativeInput, VerifiedFact
from .research_fit.service import recheck_research_fit
from .verification import _SPEC_BY_CATEGORY, Verdict, _details_conflict, _fact_payload, _identity


def _no_recheck(inputs: dict[UUID, NarrativeInput]) -> tuple[UUID, ...]:
    return ()


@dataclass(frozen=True)
class CounselorFlag:
    reason: str
    detail: str


def find_conflicting_facts(facts: dict[UUID, VerifiedFact]) -> frozenset[UUID]:
    """Group unsuperseded facts by category; within a group, two facts about
    the *same thing* whose compared details disagree are both flagged.

    Reuses the CV engine's own identity/detail split (``verification.
    _SPEC_BY_CATEGORY`` / ``_identity`` / ``_details_conflict``) rather than
    reimplementing it: two EDUCATION facts with different
    institution_original/degree_as_awarded are about *different* degrees, so
    they must never be compared on detail keys just because they happen to
    share a payload key.

    Falls back to the old "any shared payload key differs" comparison only
    when neither fact in a pair states any recognised identity key (or the
    category is one ``_SPEC_BY_CATEGORY`` doesn't know) -- there is then no
    way to tell whether the two facts are "about" the same thing, and this
    module's gates fail closed rather than silently letting an
    unidentifiable pair pass uncompared.
    """
    by_category: dict[str, list[tuple[UUID, VerifiedFact]]] = {}
    for fact_id, fact in facts.items():
        by_category.setdefault(fact.category, []).append((fact_id, fact))

    conflicting: set[UUID] = set()
    for category, group in by_category.items():
        spec = _SPEC_BY_CATEGORY.get(category)
        for i, (id_a, fact_a) in enumerate(group):
            for id_b, fact_b in group[i + 1 :]:
                payload_a, payload_b = _fact_payload(fact_a), _fact_payload(fact_b)
                if spec is not None:
                    identity_a, identity_b = _identity(spec, payload_a), _identity(spec, payload_b)
                    if any(identity_a) or any(identity_b):
                        if identity_a == identity_b and _details_conflict(
                            spec, payload_a, payload_b
                        ):
                            conflicting.update((id_a, id_b))
                        continue
                shared_keys = set(payload_a) & set(payload_b)
                if any(payload_a[key] != payload_b[key] for key in shared_keys):
                    conflicting.update((id_a, id_b))
    return frozenset(conflicting)


# 2026-09-14 amendment (docs/research/2026-09-14-letter-storytelling-evidence.md):
# Chevening's readers name school-era examples as the failure, but a student
# who has only old examples must not be *blocked* -- so this is a counselor
# flag, never a gate.
_EXAMPLE_ARCHETYPES = frozenset({"LEADERSHIP_EXAMPLE", "RELATIONSHIP_COMMUNITY"})
_DATE_KEYS = ("end_date", "date", "start_date", "year")
_RECENT_YEARS = 5


def _fact_year(fact: VerifiedFact) -> int | None:
    for key in _DATE_KEYS:
        value = fact.payload.get(key)
        if value:
            digits = str(value)[:4]
            return int(digits) if digits.isdigit() else None
    return None


def find_stale_examples(content: LetterContent, facts: dict[UUID, VerifiedFact]) -> tuple[str, ...]:
    """Archetypes of example units whose every dated anchor is older than
    ``_RECENT_YEARS``. Undated facts never count against the student -- an
    example unit with no dated FACTUAL claim never appears here."""
    cutoff = timezone.now().year - _RECENT_YEARS
    stale = []
    for unit in content.units:
        if unit.archetype not in _EXAMPLE_ARCHETYPES:
            continue
        years = [
            _fact_year(facts[claim.fact_id])
            for claim in unit.claims
            if claim.kind == ClaimKind.FACTUAL and claim.fact_id in facts
        ]
        dated = [year for year in years if year is not None]
        if dated and max(dated) < cutoff:
            stale.append(unit.archetype)
    return tuple(stale)


def compute_letter_flags(
    *,
    prompt: ApplicationPrompt,
    letter_required: str,
    facts: dict[UUID, VerifiedFact],
    binding_violation_after_retry: bool,
    content: LetterContent | None = None,
    claim_verdicts: tuple[LetterClaimVerdict, ...] = (),
    stale_inputs: tuple[UUID, ...] = (),
) -> tuple[CounselorFlag, ...]:
    """Everything that routes a letter to the counselor queue without
    blocking it outright. Order is stable (checked in this order) so
    ``AuditEvent`` rows come out in a predictable sequence."""
    flags: list[CounselorFlag] = []
    if prompt.source == ApplicationPrompt.Source.UNRESOLVED:
        flags.append(
            CounselorFlag(
                "prompt_unresolved", "no verified or extracted prompt record for this programme"
            )
        )
    if letter_required == Program.LetterRequired.UNKNOWN:
        flags.append(
            CounselorFlag(
                "letter_required_unknown", "whether this programme wants a letter is unresolved"
            )
        )
    if find_conflicting_facts(facts):
        flags.append(CounselorFlag("conflicting_facts", "two student-stated facts disagree"))
    if binding_violation_after_retry:
        flags.append(
            CounselorFlag(
                "binding_constraint_unmet",
                "a binding limit was still violated after the single retry",
            )
        )
    if content is not None:
        stale = find_stale_examples(content, facts)
        if stale:
            flags.append(
                CounselorFlag(
                    "example_not_recent",
                    f"examples older than {_RECENT_YEARS} years: {', '.join(stale)}",
                )
            )
    unverified = [
        v.claim_text for v in claim_verdicts
        if v.claim_kind == ClaimKind.SOURCED and v.verdict == Verdict.UNCERTAIN
    ]
    if unverified:
        flags.append(
            CounselorFlag(
                "source_unverified",
                "sourced claims with a URL but no verified producer: " + "; ".join(unverified),
            )
        )
    if stale_inputs:
        flags.append(
            CounselorFlag(
                "source_stale",
                "the cited page no longer carries the sentence for inputs: "
                + ", ".join(str(i) for i in stale_inputs),
            )
        )
    return tuple(flags)


def mark_letter_ready(
    *,
    document: DocumentDraft,
    content: LetterContent,
    gate_violations: tuple[LetterGateViolation, ...],
    prompt: ApplicationPrompt,
    letter_required: str,
    facts: dict[UUID, VerifiedFact],
    inputs: dict[UUID, NarrativeInput],
    binding_violation_after_retry: bool,
    accepted_by: Membership,
    recheck: Callable[[dict[UUID, NarrativeInput]], tuple[UUID, ...]] = recheck_research_fit,
) -> DocumentDraft:
    """Three-way outcome for a finished letter draft.

    Blocked (``is_letter_blocked``) raises ``ApprovalBlocked`` -- no
    override, ever. Otherwise, any counselor flag records one
    ``document.letter_flag.<reason>`` audit event per flag and leaves the
    draft in ``DRAFT`` (visible on the counselor queue). A clean letter
    delegates to Plan A's ``mark_ready``, which re-derives its own verdicts
    from the locked document's stored content and auto-approves.

    **Claim verdicts are re-derived here, never accepted from the caller.**
    This function used to take a ``claim_verdicts`` tuple and block on it,
    which put this plan's one non-negotiable rule -- an immigration letter
    carrying an ``UNCERTAIN`` claim is blocked, with no override -- entirely
    in the hands of whoever built that tuple. Plan A's ``mark_ready`` is not
    the backstop for it either: ``approval.verdicts_for`` hardcodes
    ``immigration=False`` and ``approval._BLOCKING_VERDICTS`` does not
    contain ``UNCERTAIN`` at all, so a caller passing ``()`` waived the
    immigration rule outright and every downstream check agreed the letter
    was clean. ``content``/``facts``/``inputs`` are therefore required, and
    ``verify_letter_claims`` runs on them here with this prompt's real
    ``immigration`` flag.

    **What is still trusted from the caller: ``gate_violations``** (and
    ``binding_violation_after_retry``). Re-deriving those needs
    ``forbidden_institution_names``, ``prompt.questions``,
    ``header_block_required``, ``document_language``, ``paired_content`` and
    ``storyline`` threaded in as well -- a larger interface change, and a
    quality/UX concern rather than the PII-and-legal-declaration risk the
    verdicts carry. Whoever wires the first live caller of this function
    owns closing that: a gate violation asserted away is a letter that
    reaches a reader with a wrong institution name in it.
    """
    # getattr, not prompt.immigration: the test doubles used across this
    # plan are plain stand-ins that only set the fields their own test
    # exercises. Real ApplicationPrompt rows always carry immigration.
    immigration = getattr(prompt, "immigration", False)
    claim_verdicts = verify_letter_claims(
        content, facts=facts, inputs=inputs, immigration=immigration
    )
    if is_letter_blocked(claim_verdicts, gate_violations, immigration=immigration):
        raise ApprovalBlocked("letter carries a blocking claim verdict or gate violation")

    flags = compute_letter_flags(
        prompt=prompt,
        letter_required=letter_required,
        facts=facts,
        binding_violation_after_retry=binding_violation_after_retry,
        content=content,
        claim_verdicts=claim_verdicts,
        stale_inputs=recheck(inputs),
    )
    if flags:
        # actor=None, not accepted_by: a counselor flag is a system-detected
        # condition (an unresolved prompt, a stale example, ...), not an
        # action the caller took -- accepted_by could be the student
        # themselves, and attributing a detection to them would misrepresent
        # who did what in the audit trail. Matches the existing convention
        # for an analogous auto-detected event
        # (apps.documents.prompt_resolution._create_unresolved's
        # "document.prompt_unresolved", also actor=None).
        for flag in flags:
            record_event(
                actor=None,
                event=f"document.letter_flag.{flag.reason}",
                object_id=document.id,
            )
        return document

    # mark_ready recomputes verdicts itself from the locked row's own stored
    # content (Plan A's approval.py:verdicts_for, now kind-aware for letter
    # drafts) -- never from anything a caller asserts. Two independent
    # recomputations, then: this function's own, against `content` and the
    # ledger it was handed (the only one that is immigration-aware), and
    # mark_ready's, against the locked row under lock. The second catches a
    # `content` argument that does not match what was actually stored.
    return mark_ready(document=document, accepted_by=accepted_by)
