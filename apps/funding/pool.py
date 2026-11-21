"""What a student is evaluated against: catalog programmes and served awards.

**This query is INTERIM and cell selection REPLACES it** (spec section 10.1).
Do not grow it into the real thing. Cell selection picks a supply cell --
destination x level x holder kind -- and asks the catalog for that cell; this
asks the catalog for "anything whose name looks like the student's field", which
is a different question that happens to return rows today. Extending it a filter
at a time produces something that is neither, and that nobody can delete.

Two rules here DO survive the replacement, and both are about what the pool may
not do:

- **It never reads an unserved row.** The serve gate is the catalog's promise
  (spec 8.6); a pool that second-guessed it would put a disputed award in front
  of a student through the back door.
- **It never narrows on a preference.** `excluded_countries` is a refusal and
  filters; `allowed_countries` is a preference and does not. The evaluator
  decides on a preference and says why, where a student can read it -- a pool
  that filtered on one would hide funding the student would have taken, with no
  reason attached anywhere.
- **It never admits a body that is not RECOGNISED** (institution provenance
  gate spec §7.2): a programme on its `evidence_domain`, a HOLDER award on its
  `holder_domain`. The filter sits in the query, before the limit, so gated
  rows never spend it.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce
from uuid import UUID

from django.conf import settings
from django.db.models import Case, Exists, IntegerField, OuterRef, Q, QuerySet, Value, When

from apps.accounts.field_taxonomy import PRESERVED_SHORT_TOKENS, resolve_field_taxonomy
from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.evaluation import _wants_top_universities_only
from apps.funding.models import (
    FundingOpportunity,
    FundingOpportunityProgram,
    Program,
    ProgramStatement,
)
from apps.research.models import Organisation, OrganisationDomain, ProvenanceVerdict
from apps.research.provenance import WAITING_REASONS, Verdict

_FIELD_STOP_WORDS = frozenset(
    {
        "a", "an", "and", "at", "by", "degree", "for", "from", "in", "into",
        "ma", "master", "masters", "meng", "msc", "of", "on", "or", "program",
        "programme", "studies", "the", "to", "with",
    }
)


def _phrase_tokens(phrase: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9+#]+", phrase.casefold())
        if (len(token) >= 3 or token in PRESERVED_SHORT_TOKENS) and token not in _FIELD_STOP_WORDS
    ]


def _word_or_substring_q(term: str) -> Q:
    cleaned = term.strip()
    if len(cleaned) <= 3:
        return Q(name__iregex=rf"(^|[^a-zA-Z0-9]){re.escape(cleaned)}([^a-zA-Z0-9]|$)")
    return Q(name__icontains=cleaned)


def _field_filter(target_field: str, research_interests: Sequence[str] = ()) -> Q:
    resolution = resolve_field_taxonomy(target_field, research_interests)
    phrases = tuple(
        dict.fromkeys(
            p
            for p in (
                target_field.strip(),
                *resolution.canonical_degree_titles,
                *(i.strip() for i in research_interests if i and i.strip()),
            )
            if p
        )
    )
    query = _word_or_substring_q(target_field)
    for phrase in phrases:
        query |= _word_or_substring_q(phrase)
        tokens = _phrase_tokens(phrase)
        if len(tokens) >= 2:
            query |= reduce(operator.and_, (_word_or_substring_q(token) for token in tokens))
        elif len(tokens) == 1:
            query |= _word_or_substring_q(tokens[0])
    for parent in resolution.parent_fields:
        if parent:
            query |= _word_or_substring_q(parent)
    return query


@dataclass(frozen=True)
class PoolResult:
    programs: tuple[Program, ...]
    #: Served HOLDER awards. An award is an application of its own, never a
    #: discount on a programme (owner decision 2026-09-19).
    awards: tuple[FundingOpportunity, ...]
    #: Why the pool is empty, in words a student reads. Empty when it is not.
    #: P1-7: never a silently short pack -- "we found nothing" and "we did not
    #: look" are indistinguishable to the person waiting for a pack.
    empty_reason: str = ""
    #: Bodies left out because their verdict is not computed yet (spec §7.1).
    #: The run records them; the sweep re-runs the student when one resolves.
    pending_bodies: tuple[UUID, ...] = ()


def _pending(
    programs: QuerySet[Program], awards: QuerySet[FundingOpportunity]
) -> tuple[tuple[UUID, ...], int]:
    """(bodies whose verdict is still to come, how many rows wait on them).

    Waiting means no verdict row for the domain, or a WAITING_REASONS one. A
    row that could not be admitted whatever the verdict (evidence off its
    domain) waits on nothing, and neither does a REJECTED body's domain: no
    check will ever run for it.
    """
    settled = ProvenanceVerdict.objects.exclude(reason_code__in=WAITING_REASONS).values("domain")
    admissible = programs.filter(evidence_institutional=True).exclude(evidence_domain="")
    domains = set(
        admissible.exclude(evidence_domain__in=settled).values_list("evidence_domain", flat=True)
    ) | set(
        awards.exclude(holder_domain="")
        .exclude(holder_domain__in=settled)
        .values_list("holder_domain", flat=True)
    )
    owners = dict(
        ProvenanceVerdict.objects.filter(domain__in=domains).values_list(
            "domain", "organisation_id"
        )
    )
    owners.update(
        OrganisationDomain.objects.filter(registrable_domain__in=domains - owners.keys())
        .values_list("registrable_domain", "organisation_id")
    )
    rejected = set(
        Organisation.objects.filter(
            id__in=owners.values(), status=Organisation.Status.REJECTED
        ).values_list("id", flat=True)
    )
    waiting = {domain for domain, body in owners.items() if body not in rejected}
    rows = (
        admissible.filter(evidence_domain__in=waiting).count()
        + awards.filter(holder_domain__in=waiting).count()
    )
    return tuple(sorted({owners[domain] for domain in waiting})), rows


def candidate_pool(
    profile: StudentProfileSnapshot, *, limit: int
) -> PoolResult:
    """Programmes and served awards worth evaluating for this student.

    `limit` is required and has no default: an unbounded pool is an unbounded
    evaluation, and every caller should have had to think about the number.
    """
    resolution = resolve_field_taxonomy(profile.target_field, profile.research_interests)
    programs = Program.objects.filter(
        _field_filter(profile.target_field, profile.research_interests),
        degree_level="MASTER",
    )
    if profile.excluded_countries:
        programs = programs.exclude(country_code__in=profile.excluded_countries).exclude(
            awarding_institutions__country_code__in=profile.excluded_countries
        )
    awards = FundingOpportunity.objects.filter(scope_type="HOLDER", served=True)
    if profile.excluded_countries:
        home_code = (profile.nationality or "").upper()
        excluded_award_countries = [
            c for c in profile.excluded_countries if c.upper() != home_code
        ]
        if excluded_award_countries:
            awards = awards.exclude(
                country_code__in=excluded_award_countries
            ).exclude(organisation__country_code__in=excluded_award_countries)
    # Any suspension at all, on `suspension_quote` rather than a year match on
    # `suspended_for`. The quote is the marker: a suspension naming no intake
    # leaves `suspended_for` blank and is still a suspension (that field's own
    # comment on the model), so the year test said nothing about exactly the
    # case with no year to test. `funding_opportunity_served_not_suspended`
    # now makes served-and-suspended impossible at the database, so this
    # filters nothing in practice -- it is kept, and kept total rather than
    # clever, because the unserve sweep for a withdrawn award that nothing
    # re-reads is still owed (spec section 19).
    awards = awards.filter(suspension_quote="")

    pending: tuple[UUID, ...] = ()
    waiting_rows = 0
    matching_programs, matching_awards = programs, awards
    if settings.PROVENANCE_GATE_ENFORCED:
        pending, waiting_rows = _pending(programs, awards)
        # A REJECTED body is never checked again (_pending, the checker), so its
        # last RECOGNISED verdict is stale and must not keep admitting it.
        recognised = (
            ProvenanceVerdict.objects.filter(verdict=Verdict.RECOGNISED)
            .exclude(organisation__status=Organisation.Status.REJECTED)
            .values("domain")
        )
        programs = programs.filter(evidence_institutional=True, evidence_domain__in=recognised)
        awards = awards.filter(holder_domain__in=recognised)

    # Ordered by allowed-country match, teaching-language match, exact/canonical
    # title match, then parent-field fallback and canonical_key, so `limit` takes
    # eligible country/language degrees and specialized degrees ahead of generic ones
    # without hard-filtering preferences when the catalogue is sparse.
    exact_q = _word_or_substring_q(profile.target_field)
    for title in resolution.canonical_degree_titles:
        exact_q |= _word_or_substring_q(title)
    if resolution.parent_fields and resolution.preferred_track_keywords:
        parent_q = reduce(
            operator.or_, (_word_or_substring_q(p) for p in resolution.parent_fields)
        )
        track_q = reduce(
            operator.or_, (_word_or_substring_q(kw) for kw in resolution.preferred_track_keywords)
        )
        exact_q |= parent_q & track_q
    country_priority = (
        Case(
            When(country_code__in=profile.allowed_countries, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
        if profile.allowed_countries
        else Value(0, output_field=IntegerField())
    )
    lang_variants = sorted(
        {
            variant
            for lang in profile.acceptable_teaching_languages
            if lang and lang.strip()
            for variant in (
                lang.strip(),
                lang.strip().title(),
                lang.strip().lower(),
                lang.strip().upper(),
            )
        }
    )
    lang_priority = (
        Case(
            When(teaching_languages__overlap=lang_variants, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
        if lang_variants
        else Value(0, output_field=IntegerField())
    )
    duration_priority = (
        Case(
            When(
                Q(duration_months__lte=12)
                if profile.duration_preference == "ONE_YEAR"
                else Q(duration_months__gt=12),
                then=Value(0),
            ),
            default=Value(1),
            output_field=IntegerField(),
        )
        if profile.duration_flexibility == "NON_NEGOTIABLE"
        and profile.duration_preference in ("ONE_YEAR", "TWO_YEAR")
        else Value(0, output_field=IntegerField())
    )
    wants_top_tier = _wants_top_universities_only(profile)
    top_tier_priority = (
        Case(
            When(
                Q(provision_type=Program.ProvisionType.JOINT)
                | Q(academic_track=Program.AcademicTrack.RESEARCH)
                | Exists(
                    FundingOpportunityProgram.objects.filter(
                        program_id=OuterRef("pk")
                    )
                )
                | Exists(
                    ProgramStatement.objects.filter(
                        program_id=OuterRef("pk"),
                        kind=ProgramStatement.Kind.COMPETENCY,
                    )
                ),
                then=Value(0),
            ),
            default=Value(1),
            output_field=IntegerField(),
        )
        if wants_top_tier
        else Value(0, output_field=IntegerField())
    )
    chosen = tuple(
        programs.annotate(
            _in_allowed_country=country_priority,
            _in_teaching_lang=lang_priority,
            _in_duration=duration_priority,
            _exact_field=Case(
                When(exact_q, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            _top_tier_priority=top_tier_priority,
        ).order_by(
            "_in_allowed_country",
            "_in_teaching_lang",
            "_in_duration",
            "_exact_field",
            "_top_tier_priority",
            "canonical_key",
        )[:limit]
    )
    corridor_countries = {
        code
        for code in (
            profile.nationality,
            profile.country_of_residence,
            *profile.allowed_countries,
            *(program.country_code for program in chosen),
        )
        if code
    }
    if corridor_countries:
        awards = awards.annotate(
            _corridor_match=Case(
                When(
                    Q(country_code__in=corridor_countries)
                    | Q(organisation__country_code__in=corridor_countries),
                    then=Value(0),
                ),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("_corridor_match", "canonical_key")
    else:
        awards = awards.order_by("canonical_key")
    chosen_awards = tuple(awards[:limit])

    reason = ""
    if not chosen and not chosen_awards:
        if pending:
            # Never "no programme matches" while checks are pending (spec §7.1):
            # that is "we did not look yet", which P1-7 says must read differently.
            reason = (
                "1 programme or award is still being checked"
                if waiting_rows == 1
                else f"{waiting_rows} programmes or awards are still being checked"
            ) + " and will appear if confirmed."
        elif gated := (
            matching_programs.count() + matching_awards.count()
            if settings.PROVENANCE_GATE_ENFORCED
            else 0
        ):
            # Every match was gated out: "none matches" would be false.
            reason = (
                "1 matching programme or award is not shown because its"
                if gated == 1
                else f"{gated} matching programmes or awards are not shown because their"
            ) + " institution's recognition is not confirmed."
        else:
            countries = (
                f", excluding {', '.join(sorted(profile.excluded_countries))}"
                if profile.excluded_countries
                else ""
            )
            reason = (
                f"No programme or award in the catalogue matches {profile.target_field} "
                f"for a {profile.intended_intake.year} intake{countries}. "
                "This is what we have read so far, not a statement that none exists."
            )
    return PoolResult(
        programs=chosen, awards=chosen_awards, empty_reason=reason, pending_bodies=pending
    )
