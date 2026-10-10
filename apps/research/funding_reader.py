"""Read the money attached to a programme off the pages already fetched.

Spec: docs/superpowers/specs/2026-09-13-institution-programme-funding-search-design.md
sections 4.3 and 4.4. The reading and agreement live in
apps.research.funding_judge; this module is the catalogue side.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.funding.card import AmountLine, AwardCard
from apps.funding.models import (
    FundingBenefit,
    FundingBenefitEvidenceClaim,
    FundingOpportunity,
    FundingOpportunityEvidenceClaim,
    FundingOpportunityProgram,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Period,
    Program,
)

from .cycle_verification import record_read_evidence
from .discovery import ResearchLead, catalog_key
from .funding_judge import DecidedAmount, FundingDecision
from .funding_terms import funding_terms
from .register import record_organisation
from .resolution.writers import award_subject, sync_award_dispute, withdraw_item

#: Kept by name for its five callers; the words are data now (docs/research/funding-terms.csv),
#: in every page language, because readable_text drops each section this does not match.
_FUNDING_TERMS = funding_terms()


_FAMILY: dict[str, str] = {
    "I1_UNIVERSITY_WIDE": "UNIVERSITY_WIDE",
    "I2_PROGRAMME_ATTACHED": "DEPARTMENT_OR_PROGRAM",
    "I3_STIPEND_OR_ASSISTANTSHIP": "STIPEND_OR_ASSISTANTSHIP",
    "I4_RESEARCH_PATHWAY": "RESEARCH_ECOSYSTEM_PATHWAY",
    "I5_FUNDED_DUAL_DEGREE": "DEPARTMENT_OR_PROGRAM",
    "I6_RELOCATION_HOUSING_TRAVEL": "RELOCATION_HOUSING_INSURANCE_TRAVEL",
    "I7_PAID_PLACEMENT": "DEPARTMENT_OR_PROGRAM",
}
#: Family by holder, for HOLDER_OWN awards. FundingFamily has no loan family:
#: a lender's scheme is filed under PRIVATE_FOUNDATION with money_form LOAN
#: carrying the meaning -- recorded compromise, not a judgement.
_FAMILY_BY_HOLDER: dict[str, str] = {
    "NATIONAL_GOVERNMENT": "GOVERNMENT_SCHOLARSHIP",
    "SUBNATIONAL_GOVERNMENT": "GOVERNMENT_SCHOLARSHIP",
    "EMBASSY_BILATERAL": "GOVERNMENT_SCHOLARSHIP",
    "POLITICAL_FOUNDATION": "PRIVATE_FOUNDATION",
    "RELIGIOUS": "PRIVATE_FOUNDATION",
    "PRIVATE_FOUNDATION": "PRIVATE_FOUNDATION",
    "PROFESSIONAL_BODY": "PRIVATE_FOUNDATION",
    "ALUMNI": "PRIVATE_FOUNDATION",
    "BANK_OR_LENDER": "PRIVATE_FOUNDATION",
    "EMPLOYER": "INDUSTRIAL_SPONSORSHIP",
    "INTERGOVERNMENTAL": "MULTILATERAL",
    "REGIONAL_FUND": "MULTILATERAL",
    "DIASPORA_AFFINITY": "AFFINITY_OR_DIASPORA",
    "INSTITUTION": "UNIVERSITY_WIDE",
    "UNSTATED": "PRIVATE_FOUNDATION",
}

#: Public name for the sweep harness, which credits a host to its CLASSIFIED
#: family (spec 6.7). One map, so the tally and the reader cannot disagree.
FAMILY_BY_HOLDER = _FAMILY_BY_HOLDER

_OTHER_BENEFIT = {"LANGUAGE_YEAR": "OTHER", "VISA": "OTHER"}

#: A stated sum's purpose -> the benefit row that carries it. LIVING is the
#: one purpose whose kind depends on the award (_benefit_kinds says the same).
_BENEFIT_FOR = {
    "TUITION": "TUITION", "TRAVEL": "TRAVEL", "HOUSING": "HOUSING",
    "INSURANCE": "INSURANCE", "RELOCATION": "RELOCATION", "TOTAL": "OTHER", "OTHER": "OTHER",
}


def _benefit_kind(covers: str, decision: FundingDecision) -> str:
    if covers == "LIVING":
        return "ASSISTANTSHIP" if decision.kind == "I3_STIPEND_OR_ASSISTANTSHIP" else "STIPEND"
    return _BENEFIT_FOR[covers]


def _period_of(amount: DecidedAmount) -> str:
    """The Period a figure is stored under. OTHER has none, and then `amount`
    is already None, so the stored FULL_PROGRAM describes no number."""
    return amount.period if amount.period in Period.values else Period.FULL_PROGRAM


def _card_columns(decision: FundingDecision) -> dict[str, object]:
    return {
        "tuition": decision.tuition,
        "living": decision.living,
        "timing": decision.timing,
        "cycle": decision.cycle,
        "duration_text": "" if decision.duration == "UNSTATED" else decision.duration[:40],
        "duration_months": decision.duration_months,
        "card_quotes": {field: quote[:1_000] for field, quote in decision.card_quotes},
    }


def card_of(decision: FundingDecision) -> AwardCard:
    """The card a decision would write, before it is written -- for measuring.

    Task 5's test holds it to `award_card` of the written row, so a tally
    computed from decisions counts exactly what the pack will read.
    """
    return AwardCard(
        route=decision.route,
        tuition=decision.tuition,
        living=decision.living,
        amounts=tuple(sorted(
            (
                AmountLine(
                    kind=_benefit_kind(a.covers, decision), amount_text=a.amount_text[:40],
                    amount=a.amount, currency=a.currency, period=_period_of(a),
                    bound=a.bound, quote=a.quote[:1_000],
                )
                for a in decision.amounts
            ),
            key=lambda line: (line.kind, line.amount_text),
        )),
        duration_text="" if decision.duration == "UNSTATED" else decision.duration[:40],
        duration_months=decision.duration_months,
        timing=decision.timing,
        cycle=decision.cycle,
        unconfirmed=decision.unconfirmed,
        quotes=tuple(sorted((field, quote[:1_000]) for field, quote in decision.card_quotes)),
    )


def _benefit_kinds(decision: FundingDecision) -> list[str]:
    kinds: list[str] = []
    if decision.tuition in {"PARTIAL", "FULL"}:
        kinds.append("TUITION")
    if decision.living in {"PARTIAL", "FULL"}:
        is_assistantship = decision.kind == "I3_STIPEND_OR_ASSISTANTSHIP"
        kinds.append("ASSISTANTSHIP" if is_assistantship else "STIPEND")
    kinds.extend(_OTHER_BENEFIT.get(extra, extra) for extra in decision.extras)
    return list(dict.fromkeys(kinds))


def _suspension(decision: FundingDecision) -> dict[str, str]:
    """What a negation that won records on the row (spec 3.5.3).

    Kept on the row rather than derived at read time: the card shows the
    sentence beside the award -- "scholarship not offered for the 2026-2028
    intake" -- and a student is never shown a suspension without its quote.
    """
    if decision.offered != "NO" or not decision.suspension_quote:
        return {"suspended_for": "", "suspension_quote": ""}
    return {
        "suspended_for": "" if decision.applies_to == "UNSTATED" else decision.applies_to[:24],
        "suspension_quote": decision.suspension_quote[:300],
    }


def _served(decision: FundingDecision, lead: ResearchLead) -> bool:
    """The serve gate, identical for a programme award and a holder's own.

    Unchanged in shape since tiered agreement (spec 8.6) -- what changed is what
    `AGREED` means: every EXISTENCE field unanimous rather than every decided
    field. One consequence is worth knowing and is deliberate: a decision whose
    readings split on `money_form` has that field blanked, so the last clause
    below leaves it unserved unless the award also names a benefit. Nothing
    concrete is known about the money in that case, which is the one detail
    split that should still cost the row.
    """
    return (
        decision.agreement == "AGREED"
        and lead.can_support_claim
        and decision.offered == "YES"
        and bool(_benefit_kinds(decision) or decision.money_form != "UNSTATED")
    )


@transaction.atomic
def write_funding_decision(
    decision: FundingDecision,
    *,
    program: Program,
    lead: ResearchLead,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    now: datetime | None = None,
) -> FundingOpportunity | None:
    """The catalog row for one decided award. Served only when agreed.

    Scope decides the anchor and the database's check constraint refuses
    any other shape: an INSTITUTION award never hangs off one programme and
    a PROGRAM award never off the institution. A POINTER never reaches here.

    Returns None, writing nothing, when an INSTITUTION-scope award's
    programme is jointly provided (Program.institution is null for
    ProvisionType.JOINT; the consortium's members live in
    awarding_institutions instead) -- there is no single institution to
    anchor the award to, and guessing one is worse than not serving it.
    """
    if decision.scope == "POINTER":
        raise ValueError("a POINTER writes no funding row")
    institution_scope = decision.scope == "INSTITUTION"
    if institution_scope and program.institution_id is None:
        return None
    checked_at = now or timezone.now()
    scope_type = "INSTITUTION" if institution_scope else "PROGRAM"
    anchor_id = program.institution_id if institution_scope else program.id
    agreed = decision.agreement == "AGREED"
    served = _served(decision, lead)
    # decision.heading is part of what an award IS (spec 8.7): a page listing
    # several schemes of one kind, each under its own heading, is describing
    # several awards. decision.scope, not scope_type: PROGRAMS is stored as
    # PROGRAM and must not overwrite a programme-only award of the same kind.
    canonical_key = catalog_key(
        "read", f"{decision.scope}:{anchor_id}:{decision.heading}:{decision.kind}"
    )
    existing = FundingOpportunity.objects.filter(canonical_key=canonical_key).first()
    if existing is not None:
        same_page = existing.evidence_claims.filter(source=source).exists()
        if existing.review and (not same_page or existing.reviewed_sha256 == snapshot.sha256):
            # A human decided on a page version; only that page, changed, reopens it.
            return existing
        if not agreed and existing.agreement == "AGREED" and not same_page:
            # Many pages reach one key; a vaguer read of ANOTHER page must not
            # unserve an award a page stated clearly. Its own page may.
            return existing
    opportunity, _created = FundingOpportunity.objects.update_or_create(
        canonical_key=canonical_key,
        defaults={
            "name": (decision.name or program.name)[:80],
            "family": _FAMILY[decision.kind],
            "scope_type": scope_type,
            "institution": program.institution if institution_scope else None,
            "program": None if institution_scope else program,
            "kind": decision.kind,
            "agreement": decision.agreement,
            "served": served,
            "money_form": decision.money_form,
            "route": decision.route,
            "nationality_shape": decision.nationality_shape,
            "internationals_included": decision.internationals_included,
            "obligation": ";".join(sorted(decision.obligation)),
            "found_via": lead.discovered_by[:60],
            "disputed": ";".join(decision.disputed)[:200],
            "unconfirmed": ";".join(decision.unconfirmed)[:200],
            **_suspension(decision),
            **_card_columns(decision),
            "review": "",
            "review_note": "",
            "reviewed_at": None,
            "reviewed_sha256": "",
        },
    )
    if not institution_scope:
        FundingOpportunityProgram.objects.get_or_create(opportunity=opportunity, program=program)
    _write_rows(
        opportunity, decision, source=source, snapshot=snapshot, lead=lead, served=served,
        checked_at=checked_at,
    )
    # Step 0 of the verification ladder (spec 9.2): the dates this read found,
    # kept per intake -- this row's own fields keep only the last decision's.
    record_read_evidence(
        opportunity, decision, url=snapshot.final_url or source.canonical_url,
        sha256=snapshot.sha256, at=checked_at.date(), today=checked_at.date(),
    )
    # A row no reading could serve alone is a question for the platform's
    # operators (resolution queue, AWARD_DISPUTED); one now served is not.
    sync_award_dispute(opportunity, snapshot)
    return opportunity


def _write_rows(
    opportunity: FundingOpportunity,
    decision: FundingDecision,
    *,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    lead: ResearchLead,
    served: bool,
    checked_at: datetime,
) -> None:
    """The quotes and benefits of one decided award; shared by both writers.

    Served decides visibility: a quote nobody may show a student stays internal.
    """
    strength = "ECOSYSTEM_CLUE" if decision.agreement == "ABSTAINED" else lead.evidence_strength
    visibility = lead.visibility if served else "INTERNAL"
    # A re-read replaces the quotes. PROTECT FKs: joins, then benefits, then
    # claims -- whose ids must be collected before the joins go.
    old_claim_ids = list(opportunity.evidence_claims.values_list("id", flat=True))
    FundingBenefitEvidenceClaim.objects.filter(benefit__opportunity=opportunity).delete()
    FundingOpportunityEvidenceClaim.objects.filter(opportunity=opportunity).delete()
    FundingBenefit.objects.filter(opportunity=opportunity).delete()
    OfficialEvidenceClaim.objects.filter(id__in=old_claim_ids).delete()
    claims: list[OfficialEvidenceClaim] = []
    for quote in decision.quotes:
        claim = OfficialEvidenceClaim.objects.create(
            source=source,
            snapshot=snapshot,
            claim=quote,
            evidence_strength=strength,
            visibility=visibility,
            claim_class=OfficialEvidenceClaim.ClaimClass.FUNDING,
            last_checked_at=checked_at,
        )
        FundingOpportunityEvidenceClaim.objects.create(
            opportunity=opportunity, evidence_claim=claim
        )
        claims.append(claim)
    created: list[FundingBenefit] = []
    for kind in _benefit_kinds(decision):
        benefit = FundingBenefit.objects.create(
            opportunity=opportunity,
            kind=kind,
            period="FULL_PROGRAM",
            description=decision.quotes[0] if decision.quotes else "",
            repayable_share=Decimal("1") if decision.money_form == "LOAN" else Decimal("0"),
        )
        for claim in claims:
            FundingBenefitEvidenceClaim.objects.get_or_create(benefit=benefit, evidence_claim=claim)
        created.append(benefit)
    for amount in decision.amounts:
        _write_amount(opportunity, decision, amount, benefits=created, claims=claims)


def _write_amount(
    opportunity: FundingOpportunity,
    decision: FundingDecision,
    amount: DecidedAmount,
    *,
    benefits: list[FundingBenefit],
    claims: list[OfficialEvidenceClaim],
) -> None:
    """One decided sum onto its benefit: the level's row when it has no figure
    yet, a row of its own otherwise -- two sums of one kind are two rows, never
    one overwritten."""
    kind = _benefit_kind(amount.covers, decision)
    benefit = next((b for b in benefits if b.kind == kind and not b.amount_text), None)
    if benefit is None:
        benefit = FundingBenefit.objects.create(
            opportunity=opportunity,
            kind=kind,
            period="FULL_PROGRAM",
            description=amount.quote[:2_000],
            repayable_share=Decimal("1") if decision.money_form == "LOAN" else Decimal("0"),
        )
        for claim in claims:
            FundingBenefitEvidenceClaim.objects.get_or_create(benefit=benefit, evidence_claim=claim)
        benefits.append(benefit)
    benefit.amount = amount.amount
    benefit.currency = amount.currency
    benefit.period = _period_of(amount)
    benefit.amount_text = amount.amount_text[:40]
    benefit.amount_bound = amount.bound
    benefit.amount_quote = amount.quote[:1_000]
    # update_fields makes a write the runtime role's policy silently refused
    # raise ("did not affect any rows") instead of reporting success.
    benefit.save(update_fields=[
        "amount", "currency", "period", "amount_text", "amount_bound", "amount_quote",
    ])


@transaction.atomic
def write_holder_decision(
    decision: FundingDecision,
    *,
    holder_domain: str,
    holder_name: str,
    lead: ResearchLead,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    now: datetime | None = None,
) -> FundingOpportunity | None:
    """The catalog row for an award on its holder's own page (scope HOLDER_OWN).

    Same serve gate as a programme award. Identity is
    `(organisation, page, heading, kind)` (spec 8.7): the ORGANISATION, so two
    domains of one foundation reach one body rather than two; the PAGE and the
    HEADING, so a ministry's dozens of schemes are dozens of rows.

    **That last part reverses what this function used to guarantee** -- "every
    page of one foundation reaches one row per kind" -- and the reversal is the
    point. Under the old key a ministry's schemes collapsed into a single row
    carrying quotes from several of them, and a student saw one. An engine that
    cannot count DAAD's programmes is not finding all of them.
    """
    if decision.scope != "HOLDER_OWN":
        raise ValueError("write_holder_decision takes HOLDER_OWN decisions only")
    if not holder_domain:
        raise ValueError("a holder row needs the holder's registrable domain")
    # The register, not the string, is what a HOLDER row hangs off now. Reading
    # an award off a body's own page IS discovering that body, so this is the
    # route that records it -- and `record_organisation` is what makes a second
    # page of the same foundation reach the same row rather than a second one.
    organisation = record_organisation(
        domain=holder_domain,
        name=holder_name or holder_domain,
        kind=decision.holder,
        country_code="",
        found_via=f"READER:{lead.discovered_by}"[:120] if lead.discovered_by else "READER",
    )
    checked_at = now or timezone.now()
    served = _served(decision, lead)
    canonical_key = catalog_key(
        "read",
        f"HOLDER_OWN:{organisation.pk}:{source.id}:{decision.heading}:{decision.kind}",
    )
    existing = FundingOpportunity.objects.filter(canonical_key=canonical_key).first()
    if existing is not None and existing.review and existing.reviewed_sha256 == snapshot.sha256:
        return existing  # a human decided on this page version
    opportunity, _created = FundingOpportunity.objects.update_or_create(
        canonical_key=canonical_key,
        defaults={
            "name": (decision.name or holder_name)[:80],
            "family": _FAMILY_BY_HOLDER[decision.holder],
            "scope_type": "HOLDER",
            "institution": None,
            "program": None,
            "holder": decision.holder,
            "organisation": organisation,
            "holder_domain": holder_domain,
            "holder_name": holder_name[:300],
            "kind": decision.kind,
            "agreement": decision.agreement,
            "served": served,
            "money_form": decision.money_form,
            "route": decision.route,
            "nationality_shape": decision.nationality_shape,
            "internationals_included": decision.internationals_included,
            "obligation": ";".join(sorted(decision.obligation)),
            "found_via": lead.discovered_by[:60],
            "disputed": ";".join(decision.disputed)[:200],
            "unconfirmed": ";".join(decision.unconfirmed)[:200],
            **_suspension(decision),
            **_card_columns(decision),
            "review": "",
            "review_note": "",
            "reviewed_at": None,
            "reviewed_sha256": "",
        },
    )
    _write_rows(
        opportunity, decision, source=source, snapshot=snapshot, lead=lead, served=served,
        checked_at=checked_at,
    )
    # Step 0 of the verification ladder (spec 9.2): the dates this read found,
    # kept per intake -- this row's own fields keep only the last decision's.
    record_read_evidence(
        opportunity, decision, url=snapshot.final_url or source.canonical_url,
        sha256=snapshot.sha256, at=checked_at.date(), today=checked_at.date(),
    )
    sync_award_dispute(opportunity, snapshot)
    return opportunity


@transaction.atomic
def withdraw_unread(
    source: OfficialSource, snapshot: OfficialSourceSnapshot, decided_keys: set[str]
) -> int:
    """Unserve rows that only this page supported and this read no longer decides.

    A re-read that no longer finds an award is the page having changed, and a
    row nothing on the page says any more must stop being served -- previously
    it stood forever, because a read that decides nothing wrote nothing (spec
    3.5.4). Quotes are kept, so the withdrawal is readable. Two rows are left
    alone: one a human reviewed, and one another page also supports -- a
    vaguer read of this page may not unserve what another stated clearly.
    """
    withdrawn = 0
    rows = FundingOpportunity.objects.filter(evidence_claims__source=source).distinct()
    for row in rows:
        if row.canonical_key in decided_keys or row.review:
            continue
        if set(row.evidence_claims.values_list("source_id", flat=True)) != {source.id}:
            continue
        row.agreement, row.served = "WITHDRAWN", False
        row.save(update_fields=["agreement", "served"])
        # The page stopped saying it, so any open question about it is moot.
        withdraw_item("AWARD_DISPUTED", award_subject(row))
        withdrawn += 1
    return withdrawn


@transaction.atomic
def review_funding(
    row: FundingOpportunity, *, accepted: bool, note: str, now: datetime
) -> FundingOpportunity:
    """An operator's accept or reject, bound to the page version the quotes came from."""
    if accepted and row.suspension_quote:
        # The queue lists served=False rows, which is exactly where every
        # suspension sits, so this is the accept an operator is most likely to
        # reach by accident. Serving it publishes money the page denies.
        raise ValueError(
            "this award's own page withdrew it -- "
            f"{row.suspension_quote!r} -- so it cannot be served"
        )
    claims = list(row.evidence_claims.select_related("snapshot"))
    if not claims:
        raise ValueError("a funding row with no quote cannot be reviewed")
    claim_snapshot = claims[0].snapshot
    if claim_snapshot is None:
        raise ValueError("a funding row's quote has no snapshot to bind the review to")
    row.review = "ACCEPTED" if accepted else "REJECTED"
    row.review_note = note[:200]
    row.reviewed_at = now
    row.reviewed_sha256 = claim_snapshot.sha256
    row.served = accepted
    row.save(update_fields=["review", "review_note", "reviewed_at", "reviewed_sha256", "served"])
    OfficialEvidenceClaim.objects.filter(id__in=[claim.id for claim in claims]).update(
        visibility="STUDENT_FACING" if accepted else "INTERNAL"
    )
    return row
