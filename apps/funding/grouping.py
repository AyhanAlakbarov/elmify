"""The pack grouped under the funding (dashboard spec §5).

Pure: candidates in, groups out. Reads only the tenant copies the worker wrote
(funds_program_ids, funding_card, institution_id, country_code, degree_level),
so the page that calls it reads no catalogue table.

Open awards (owner, 2026-10-04): a HOLDER or COUNTRY award names no programme,
so it heads every programme the student has in its country (and degree level,
where both sides carry one) -- "Eligible programmes in <country>". A GLOBAL award
heads every programme.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .models import RecommendationCandidate


@dataclass(frozen=True)
class Placed:
    candidate: RecommendationCandidate
    #: The other awards this programme also appears under ("also under ...").
    also_under: tuple[str, ...]
    #: "" for a programme of this list; the other list's name ("in Other
    #: options", "in your pack") for one an open award pulled in from it.
    elsewhere: str = ""


@dataclass(frozen=True)
class FundingGroup:
    #: None for the last group, "Programmes without separate funding".
    award: RecommendationCandidate | None
    programmes: tuple[Placed, ...]
    #: The heading over the programmes (group_label).
    label: str


def _scope(award: RecommendationCandidate) -> str:
    return str((award.funding_card or {}).get("scope", ""))


def _levels_agree(award: RecommendationCandidate, programme: RecommendationCandidate) -> bool:
    levels = (award.funding_card or {}).get("degree_levels") or []
    return not levels or not programme.degree_level or programme.degree_level in levels


def funds(award: RecommendationCandidate, programme: RecommendationCandidate) -> bool:
    """Whether this award can pay for this programme, by the award's own scope."""
    if programme.program_id is not None and programme.program_id in award.funds_program_ids:
        return True
    scope = _scope(award)
    if scope == "INSTITUTION":
        return award.institution_id is not None and award.institution_id == programme.institution_id
    if scope in ("HOLDER", "COUNTRY"):
        return (
            bool(award.country_code)
            and award.country_code == programme.country_code
            and _levels_agree(award, programme)
        )
    if scope == "GLOBAL":
        return _levels_agree(award, programme)
    return False


def group_label(award: RecommendationCandidate | None) -> str:
    if award is None:
        return "Programmes without separate funding"
    scope = _scope(award)
    if scope in ("HOLDER", "COUNTRY") and award.country_code:
        return f"Eligible programmes in {award.country_code}"
    if scope == "GLOBAL":
        return "Eligible programmes"
    return "Programmes it can pay for"


def _award_order(award: RecommendationCandidate) -> tuple[str, str]:
    return ((award.funding_card or {}).get("deadline") or "9999-12-31", award.program_name)


def group_under_funding(
    candidates: Sequence[RecommendationCandidate],
    *,
    extra: Sequence[RecommendationCandidate] = (),
    extra_label: str = "",
) -> list[FundingGroup]:
    """One group per award, programmes beneath; unfunded programmes last.

    ``extra`` is the student's other list (the pool for the pack, the pack for
    the pool). Its programmes appear under every award here that funds them,
    marked ``extra_label``, and never in this list's unfunded group: they have
    their own list.
    """
    awards = sorted((c for c in candidates if c.opportunity_id is not None), key=_award_order)

    def _programmes(rows: Sequence[RecommendationCandidate]) -> list[RecommendationCandidate]:
        return sorted((c for c in rows if c.opportunity_id is None), key=lambda c: c.program_name)

    programmes, others = _programmes(candidates), _programmes(extra)
    under = {p.id: [a for a in awards if funds(a, p)] for p in (*programmes, *others)}

    def _placed(p: RecommendationCandidate, award: RecommendationCandidate, where: str) -> Placed:
        return Placed(p, tuple(o.program_name for o in under[p.id] if o.id != award.id), where)

    groups = [
        FundingGroup(
            award=award,
            programmes=tuple(
                [_placed(p, award, "") for p in programmes if award in under[p.id]]
                + [_placed(p, award, extra_label) for p in others if award in under[p.id]]
            ),
            label=group_label(award),
        )
        for award in awards
    ]
    groups.append(
        FundingGroup(
            award=None,
            programmes=tuple(Placed(p, ()) for p in programmes if not under[p.id]),
            label=group_label(None),
        )
    )
    return groups
