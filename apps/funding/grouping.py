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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from apps.documents.templatetags.cv_countries import country_name

from .models import RecommendationCandidate


@dataclass(frozen=True)
class Placed:
    candidate: RecommendationCandidate
    #: The other awards this programme also appears under ("also under ...").
    also_under: tuple[str, ...]
    #: "" for a programme of this list; the other list's name ("in Other
    #: options", "in your pack") for one an open award pulled in from it.
    elsewhere: str = ""
    #: Country-resolved scholarship amount for this programme when the heading
    #: award varies its stipend/benefit by destination country ("" when uniform).
    award_amount: str = ""


def award_amounts_for_country(
    funding_card: Mapping[str, object] | None,
    country_code: str = "",
) -> tuple[str, ...]:
    """Resolve an award's amounts for a specific host `country_code` when the
    award carries per-country rates (`amounts_by_country`), falling back to
    `default_amounts` or the summary `amounts` list."""
    card = funding_card if isinstance(funding_card, Mapping) else {}
    by_country = card.get("amounts_by_country")
    cc = (country_code or "").strip().upper()
    if isinstance(by_country, Mapping) and by_country and cc:
        country_list = by_country.get(cc)
        if isinstance(country_list, Sequence) and not isinstance(country_list, str):
            return tuple(str(a) for a in country_list if a)
        defaults = card.get("default_amounts")
        if isinstance(defaults, Sequence) and not isinstance(defaults, str):
            return tuple(str(a) for a in defaults if a)
        return ()
    raw_amounts = card.get("amounts")
    if isinstance(raw_amounts, Sequence) and not isinstance(raw_amounts, str):
        return tuple(str(a) for a in raw_amounts if a)
    return ()


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


def _destination_countries(award: RecommendationCandidate) -> set[str]:
    card = award.funding_card or {}
    raw = (
        card.get("destination_countries")
        or card.get("eligible_countries")
        or card.get("host_countries")
        or card.get("countries")
        or ()
    )
    if isinstance(raw, str):
        return {c.strip().upper() for c in raw.split(",") if c.strip()}
    if isinstance(raw, Sequence):
        return {str(c).strip().upper() for c in raw if str(c).strip()}
    return set()


def _is_outbound_home_scholarship(
    award: RecommendationCandidate, home_country: str
) -> bool:
    from apps.funding.probability import is_post_admission_gov_scholarship

    card = award.funding_card or {}
    dest = _destination_countries(award)
    if dest:
        return True
    home_countries = [str(c).strip().upper() for c in (card.get("home_countries") or ())]
    hc = home_country.strip().upper()
    aw_cc = (award.country_code or "").strip().upper()
    if hc and aw_cc == hc:
        return True
    if hc and hc in home_countries and not aw_cc:
        return True
    if is_post_admission_gov_scholarship(
        award.program_name, country_code=aw_cc, home_country=hc
    ):
        return True
    return False


def funds(
    award: RecommendationCandidate,
    programme: RecommendationCandidate,
    *,
    home_country: str = "",
) -> bool:
    """Whether this award can pay for this programme, by the award's own scope."""
    home_countries = (award.funding_card or {}).get("home_countries") or []
    if home_countries and home_country and home_country not in home_countries:
        return False
    if programme.program_id is not None and programme.program_id in award.funds_program_ids:
        return True
    scope = _scope(award)
    if scope == "INSTITUTION":
        return award.institution_id is not None and award.institution_id == programme.institution_id
    if scope in ("HOLDER", "COUNTRY"):
        hc = home_country.strip().upper()
        aw_cc = (award.country_code or "").strip().upper()
        prog_cc = (programme.country_code or "").strip().upper()
        if _is_outbound_home_scholarship(award, hc):
            if not prog_cc or (hc and prog_cc == hc):
                return False
            dest = _destination_countries(award)
            if dest:
                return prog_cc in dest and _levels_agree(award, programme)
            if not award.funds_program_ids:
                return _levels_agree(award, programme)
            return False
        if scope == "HOLDER" and hc and aw_cc == hc:
            return False
        return (
            bool(aw_cc)
            and aw_cc == prog_cc
            and _levels_agree(award, programme)
        )
    if scope == "GLOBAL":
        return _levels_agree(award, programme)
    return False


def group_label(award: RecommendationCandidate | None, *, home_country: str = "") -> str:
    if award is None:
        return "Programmes without separate funding"
    scope = _scope(award)
    if (
        scope in ("HOLDER", "COUNTRY")
        and award.country_code
        and not (home_country and award.country_code == home_country)
        and not _destination_countries(award)
    ):
        return f"Eligible programmes in {country_name(award.country_code)}"
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
    home_country: str = "",
) -> list[FundingGroup]:
    """One group per award, programmes beneath; unfunded programmes last.

    ``extra`` is the student's other list (the pool for the pack, the pack for
    the pool). Its programmes appear under every award here that funds them,
    marked ``extra_label``, and never in this list's unfunded group: they have
    their own list.
    """
    awards = sorted((c for c in candidates if c.opportunity_id is not None), key=_award_order)

    def _programmes(rows: Sequence[RecommendationCandidate]) -> list[RecommendationCandidate]:
        return sorted(
            (c for c in rows if c.opportunity_id is None),
            key=lambda c: (c.rank if c.rank is not None else 999999, c.program_name),
        )

    programmes, others = _programmes(candidates), _programmes(extra)
    under = {
        p.id: [a for a in awards if funds(a, p, home_country=home_country)]
        for p in (*programmes, *others)
    }

    def _placed(p: RecommendationCandidate, award: RecommendationCandidate, where: str) -> Placed:
        fcard = award.funding_card if isinstance(award.funding_card, Mapping) else {}
        has_country_rates = bool(fcard.get("amounts_by_country"))
        resolved_amt = (
            "; ".join(award_amounts_for_country(fcard, p.country_code or ""))
            if has_country_rates and p.country_code
            else ""
        )
        return Placed(
            p,
            tuple(o.program_name for o in under[p.id] if o.id != award.id),
            where,
            award_amount=resolved_amt,
        )

    groups = [
        FundingGroup(
            award=award,
            programmes=tuple(
                [_placed(p, award, "") for p in programmes if award in under[p.id]]
                + [_placed(p, award, extra_label) for p in others if award in under[p.id]]
            ),
            label=group_label(award, home_country=home_country),
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
