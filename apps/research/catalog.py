"""CatalogWriter (design §2.5): the only discovery stage that touches the DB.

Four rules decide every branch here:

* No evidence, no row. ``Program`` has no visibility column, so a row that no
  official page vouched for is indistinguishable from one that was.
* An ECOSYSTEM_CLUE lead writes nothing: §2.3 keeps clues internal until
  primary evidence upgrades them.
* Claims beat seeds for anything a hard gate reads, or that a student filters
  on. A catalogue supplies names; teaching language and duration come from the
  cited claims or not at all. A funding family works the same way: a page's
  own cited claim outranks the seed adapter's uncited assertion, because the
  student-facing citations on the row must actually support what the row says.
* A funding family is stated -- by the page in a cited claim, or by the seed
  adapter as a fallback when the page states none -- or the opportunity is not
  written.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from apps.funding.models import (
    FundingOpportunity,
    FundingOpportunityEvidenceClaim,
    FundingOpportunityProgram,
    Institution,
    InstitutionEvidenceClaim,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
    ProgramEvidenceClaim,
)
from apps.reference_data import ISO_3166_ALPHA2_CODES, ISO_4217_CODES

from .discovery import ResearchLead, catalog_key, location_key
from .extraction import ExtractedClaims
from .hosts import registrable_domain
from .provenance import record_program_evidence

_MAX_TEACHING_LANGUAGES = 10
_MAX_DURATION_MONTHS = 60
_MAX_CLAIM_CHARS = 4_000


@dataclass(frozen=True)
class ResolvedProgram:
    institution_name: str
    country_code: str
    city: str
    program_name: str
    degree_level: str
    teaching_languages: tuple[str, ...]
    duration_months: int


@dataclass(frozen=True)
class CatalogWriteResult:
    #: None for a jointly-awarded programme: no Institution is invented for it.
    institution: Institution | None
    program: Program
    claims: tuple[OfficialEvidenceClaim, ...]
    opportunity: FundingOpportunity | None
    #: Dates whose year the model fabricated, dropped rather than stored. Not a
    #: silence: run_discovery reports the run's total in DiscoveryReport.degraded.
    unreadable_dates: int = 0


def resolve_program(lead: ResearchLead, claims: ExtractedClaims) -> ResolvedProgram | None:
    """Names from the catalogue if it has them, gated facts from the page only."""
    seed = lead.identity
    institution_name = (seed.institution_name if seed else "") or (claims.institution_name or "")
    program_name = (seed.program_name if seed else "") or (claims.program_name or "")
    city = (seed.city if seed else "") or (claims.city or "")
    country_code = ((seed.country_code if seed else "") or (claims.country_code or "")).upper()
    # Cited claims only: _teaching_language_gate reads the first of these, and a
    # student must not be gated on an aggregator's uncited assertion (§2.2).
    languages = tuple(dict.fromkeys(claim.language for claim in claims.teaching_languages))
    duration = claims.duration_months
    if not (institution_name and program_name and languages):
        return None
    if country_code not in ISO_3166_ALPHA2_CODES:
        return None
    if duration is None or not 1 <= duration <= _MAX_DURATION_MONTHS:
        return None
    return ResolvedProgram(
        institution_name=institution_name,
        country_code=country_code,
        city=city,
        program_name=program_name,
        degree_level=seed.degree_level if seed else "MASTER",
        teaching_languages=languages[:_MAX_TEACHING_LANGUAGES],
        duration_months=duration,
    )


def _front_door(values: Iterable[str | None]) -> str | None:
    """The first page that states the field wins -- pages arrive in queue order."""
    return next((value for value in values if value), None)


def pool_claims(pages: Sequence[ExtractedClaims]) -> ExtractedClaims | None:
    """Pool one programme's pages into the five facts resolve_program gates on.

    Only the gate fields pool. Claims never do -- every OfficialEvidenceClaim
    stays attached to the snapshot it was extracted from, so this result is used
    for nothing but the gate, and a held page still writes its own claim text.

    Names and facts are treated differently on purpose. Across the 25 hosts a
    union completes, the two name fields disagreed on 11 and 21 -- always as
    variants ("master wocc" against "master wocc: contemporary challenges in the
    worlds of work"; one host differing only in a curly apostrophe) -- while
    country never disagreed and duration disagreed twice, meaningfully ([6, 36]
    on life.univ-cotedazur.eu, [24, 36] on ntnu.edu). So a name takes the front
    door's version, and a contradicted fact refuses the whole group: choosing
    between 6 and 36 months invents the fact this increment exists to stop.

    ``pages[0]`` is the front door. Returns None when a fact is contradicted.
    """
    if not pages:
        return None
    countries = {page.country_code.upper() for page in pages if page.country_code}
    durations = {page.duration_months for page in pages if page.duration_months is not None}
    if len(countries) > 1 or len(durations) > 1:
        return None
    return pages[0].model_copy(
        update={
            "institution_name": _front_door(page.institution_name for page in pages),
            "program_name": _front_door(page.program_name for page in pages),
            # city is not one of the five gate fields, but it rides the same
            # front-door-wins rule as the other name fields -- left out of this
            # update dict it would carry pages[0]'s value unchanged via
            # model_copy, silently losing it when the front door omits city
            # and a sibling page states it (whole-branch review, Fix 4c).
            "city": _front_door(page.city for page in pages),
            "country_code": next(iter(countries), None),
            "duration_months": next(iter(durations), None),
            # resolve_program dedupes by language name, so concatenation is enough.
            "teaching_languages": tuple(
                claim for page in pages for claim in page.teaching_languages
            ),
        }
    )


#: How far from the run date a stated date may fall and still be readable.
#:
#: What this bounds is not a *wrong* deadline but an *unreadable* one. On the
#: 2026-08-30 run over all 169 EACEA consortium sites, 132 of 407 cited dates
#: (32%) and 52 of 100 uncited ones (52%) carried an impossible year -- 101,
#: 1515, 4444, 8188. The day and month were correct in every sample inspected;
#: only the year was fabricated, assembled from the day and month digits when
#: the quoted sentence did not bind a year ("31st of March" -> 3131-03-31,
#: "15th Feb 2026" -> 1515-02-15, "September 25" -> 2509-01-01). Every
#: plausible value observed fell in 2025-2027 against a 2027 cycle.
#:
#: Years, never days: a day-level window would reject a legitimate "1 December"
#: the moment it passed, which is a different question from whether it was read
#: correctly. Evidence:
#: docs/superpowers/research/2026-08-30-eacea-full-catalogue-run.md §5.
_YEARS_BEHIND = 2
_YEARS_AHEAD = 4


def date_is_readable(value: date | None, now: datetime) -> bool:
    """Whether a stated date could belong to an admissions cycle near ``now``.

    A missing date is readable -- there is nothing to mistrust. Absorbing the
    ``None`` here keeps the two callers below (the row this emits, and the count
    that reports on it) one expression, so they cannot drift apart.
    """
    if value is None:
        return True
    return now.year - _YEARS_BEHIND <= value.year <= now.year + _YEARS_AHEAD


#: Symbols for the currencies that carry one in the corpus -- 595 of 618 claims
#: are EUR, GBP or USD. Anything else must state its code.
_CURRENCY_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$"}


def _money(
    label: str, amount: Decimal, currency: str, period: str, evidence: str
) -> str | None:
    """A money row, or None when what it calls a currency is not one, or unquoted.

    ISO_4217_CODES is the same pinned set the database already enforces on
    FundingBenefit and CostComponent (funding_benefit_currency_iso4217). Only the
    extraction schema was looser: its ^[A-Z]{3}$ accepts any three capitals, so a
    model with nothing to say said PCT, NOM, VAR, DUR, SCH, UNP, INS, SEM and NOT
    -- 20 of 618 money claims on the 2026-08-30 run.

    The currency check is here and not in the schema on purpose: a validator
    rejects the whole response over one field, and the date defect discarded 13
    pages' worth of institutions and funding claims that way. Do not move it.

    The quotation check catches what the currency check cannot: ccd-stede.eu
    produced "6 SEK per MONTHS" for a page stating "6 months" -- SEK is a real
    ISO code, so the list check passes it, and the evidence string is the only
    thing that shows the *model's own quotation* never names SEK. This is a
    self-consistency check, not grounding in the page: nothing here verifies
    ``evidence`` against the page's actual text -- ``supporting_excerpt_offsets``
    exists on the claim but is unused -- so a model that fabricated both the
    currency and a matching quotation would still pass.
    """
    if currency not in ISO_4217_CODES:
        return None
    # ponytail: three ceilings, all "withhold rather than publish uncited":
    # (1) a page writing "1 400 kr" for SEK gets no symbol -- add one when a
    #     real source is measured losing a claim to it, not before.
    # (1b) a bare symbol credits any currency that uses it: "$1,400" quotes
    #     currency="USD" even on a Canadian or Australian dollar page, because
    #     the symbol table has no way to tell CAD/AUD/USD apart. Add
    #     disambiguation (a currency-name check, or refusing the bare symbol
    #     for non-USD dollar codes) when a real source is measured losing a
    #     claim to it, same trigger as (1).
    # (2) the code must appear as its own word (\bEUR\b), not as a substring --
    #     a plain "in evidence" check let currency="EUR" pass on evidence text
    #     that only said "European Commission", with no amount or currency
    #     anywhere in it, because EUR sits inside European/eurozone/chauffeur/
    #     entrepreneur. That inverted the rule: strongest for the currencies
    #     that almost never appear and weakest for EUR, which is 552 of the
    #     corpus's 618 money claims. The trade this makes instead: a page that
    #     spells the currency out ("1,400 euros a month") also fails \bEUR\b
    #     and is dropped. Add a name map (euro/pound/dollar) if a real source
    #     is measured losing a claim to that -- Task 6 measures this.
    symbol = _CURRENCY_SYMBOLS.get(currency)
    quoted = bool(re.search(rf"\b{re.escape(currency)}\b", evidence, re.IGNORECASE)) or (
        symbol is not None and symbol in evidence
    )
    if not quoted:
        return None
    return f"{label}: {amount} {currency} per {period}"


def claim_rows(
    program: ResolvedProgram, claims: ExtractedClaims, *, now: datetime | None = None
) -> tuple[tuple[str, str], ...]:
    """(claim_class, claim text) per extracted fact, for Task 10's windows."""
    classes = OfficialEvidenceClaim.ClaimClass
    checked_at = now or timezone.now()
    # These two rows are derived from `program` (the resolved programme), not
    # from `claims` (this page's own extraction), and carry no quotation --
    # true before pooling and still true now. Every other row below cites this
    # page's own claims; do not describe these two that way (design doc §Part 1).
    rows: list[tuple[str, str]] = [
        (
            classes.IDENTITY,
            f"{program.institution_name} offers {program.program_name} "
            f"({program.degree_level})",
        )
    ]
    for language in claims.teaching_languages:
        rows.append(
            (classes.STRUCTURE, f"Teaching language: {language.language} — {language.evidence}")
        )
    rows.append((classes.STRUCTURE, f"Programme duration: {program.duration_months} months"))
    if claims.admission_regime is not None:
        rows.append(
            (
                classes.STRUCTURE,
                f"Admission regime {claims.admission_regime.regime}: "
                f"{claims.admission_regime.evidence}",
            )
        )
    for criterion in claims.eligibility_criteria:
        # The comparable travels with the quote or it is discarded: ExtractedClaims is
        # transient, so a field claim_rows does not emit was paid for at fetch time and
        # then thrown away. An applicant condition without its number cannot close a
        # route, which is the whole point of extracting it.
        if criterion.comparable_value is None:
            comparable = ""
        elif criterion.comparable_currency is None:
            comparable = f" [{criterion.comparable_value}]"
        elif criterion.comparable_currency not in ISO_4217_CODES:
            comparable = ""
        else:
            comparable = f" [{criterion.comparable_value} {criterion.comparable_currency}]"
        rows.append(
            (
                classes.ELIGIBILITY,
                f"{criterion.kind}: {criterion.requirement}{comparable} — {criterion.evidence}",
            )
        )
    # claims.deadline is deliberately not emitted. It is the schema-v1 field and
    # carries no evidence, so a claim built from it cites nothing -- against this
    # module's first rule. It is also the worse of the two date paths: on the
    # 2026-08-30 run 52% of its values had an impossible year against 32% for
    # the cited key_dates, NTNU's was the page's own render timestamp read as a
    # deadline, and only 4 pages of 429 had a plausible uncited date and no
    # cited one. key_dates covers the same ground with a quotation attached.
    for key_date in claims.key_dates:
        if not date_is_readable(key_date.on, checked_at):
            # The year is a transcription artifact, but the quoted sentence usually
            # gives the date correctly ("the deadline set for 1 December 2026") even
            # though the parsed value doesn't -- so the citation is kept and only the
            # unreliable parse is dropped. A silently missing row would be
            # indistinguishable from a page that states no deadline at all, which is
            # worse than surfacing an unparsed one for a human to read.
            rows.append(
                (
                    classes.DEADLINE,
                    f"{key_date.kind}: date stated but not read reliably — {key_date.evidence}",
                )
            )
            continue
        rows.append(
            (
                classes.DEADLINE,
                f"{key_date.kind}: "
                + ("published per target, no central date" if key_date.decentralised
                   else str(key_date.on))
                + f" — {key_date.evidence}",
            )
        )
    if claims.commitment_payment is not None and claims.commitment_payment.kind != "NONE":
        payment = claims.commitment_payment
        # Same precedent as the unreadable date above: a garbled currency is one
        # mangled field, not proof the page said nothing. Dropping the whole row
        # would be indistinguishable from no commitment payment at all, and it is
        # window_days -- a deadline-shaped fact -- that would be lost with it, for
        # a reason that has nothing to do with the due-window.
        amount_text = (
            f"{payment.amount} {payment.currency}"
            if payment.currency in ISO_4217_CODES
            else "amount stated but currency not read reliably"
        )
        rows.append(
            (
                classes.TUITION,
                f"{payment.kind}: {amount_text}"
                + (f", due within {payment.window_days} days of an offer"
                   if payment.window_days is not None else "")
                + f" — {payment.evidence}",
            )
        )
    for track in claims.funding_tracks:
        # Coverage travels with the track: ExtractedClaims is transient -- nothing
        # persists it -- so a field claim_rows does not emit is extracted and then
        # thrown away. Commitment-payment coverage decides whether an outcome
        # exists for the student at all, and financial proof decides the visa gate.
        rows.append(
            (
                classes.FUNDING,
                f"{track.name} ({track.initiation}, financial proof "
                f"{track.satisfies_financial_proof or 'UNSTATED'}, commitment payment "
                f"{track.covers_commitment_payment or 'UNSTATED'}): {track.evidence}",
            )
        )
    if claims.return_service is not None:
        # FUNDING, not ELIGIBILITY: a bond is a property of the award, not a bar the
        # applicant clears. Emitted here or discarded -- ExtractedClaims is transient.
        rows.append(
            (
                classes.FUNDING,
                f"Return service: {claims.return_service.months} months — "
                f"{claims.return_service.evidence}",
            )
        )
    charges = (*claims.fees, *claims.costs)
    if claims.application_fee is not None:
        charges = (*charges, claims.application_fee)
    for charge in charges:
        if text := _money(
            charge.label, charge.amount, charge.currency, charge.period, charge.evidence
        ):
            rows.append((classes.TUITION, text))
    for benefit in claims.benefits:
        if text := _money(
            benefit.label, benefit.amount, benefit.currency, benefit.period, benefit.evidence
        ):
            rows.append((classes.FUNDING, text))
    if claims.funding_family is not None:
        rows.append(
            (
                classes.FUNDING,
                f"Funding family {claims.funding_family.family}: "
                f"{claims.funding_family.evidence}",
            )
        )
    return tuple((claim_class, text[:_MAX_CLAIM_CHARS]) for claim_class, text in rows)


def _origin(url: str) -> str:
    return f"https://{urlsplit(url).hostname}/"


#: Measured 2026-09-13: 7 of 7 composite names written by discover are caught,
#: 15 of 15 plain names are not, and 19 of DEQAR's 9,030 real institutions are
#: flagged (0.2%) -- bilingual names joined by a slash, and Finnish university
#: consortia. The bias is deliberate; see the 2026-09-13 providers design §3.2.
_JOINT_NAME_MARKERS = (";", " / ", "consortium")


def names_several_providers(name: str) -> bool:
    """Whether a provider name looks like several universities rather than one.

    The FALLBACK only. The source's own ``awards_jointly`` is the primary rule
    and is the one that catches a coordinator's plain name -- which no name
    rule can see.
    """
    lowered = name.casefold().rstrip()
    return any(marker in lowered for marker in _JOINT_NAME_MARKERS) or lowered.endswith(
        "universities"
    )


@transaction.atomic
def write_catalog_entry(
    *,
    lead: ResearchLead,
    claims: ExtractedClaims,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    now: datetime | None = None,
    program_facts: ResolvedProgram | None = None,
) -> CatalogWriteResult | None:
    if lead.evidence_strength == "ECOSYSTEM_CLUE":
        return None  # internal until primary evidence upgrades it (§2.3)
    if not lead.can_support_claim:
        return None  # a catalogue seeds names; it does not create rows (§2.5)
    # Supplied by the pooled path, which resolved the group once. `claims` is
    # still this page's own, so the rows it writes cite this page.
    program_facts = program_facts or resolve_program(lead, claims)
    if program_facts is None:
        return None
    checked_at = now or timezone.now()
    unreadable_dates = sum(
        1
        for key_date in claims.key_dates
        if not date_is_readable(key_date.on, checked_at)
    )
    rows = claim_rows(program_facts, claims, now=checked_at)
    if not rows:
        return None  # no evidence, no student-facing row
    # The source's promise first, the name's shape second. A coordinator's
    # plain name ("University of Glasgow") is invisible to any name rule --
    # only the seed knows EACEA lists one consortium per row.
    jointly_awarded = lead.awards_jointly or names_several_providers(
        program_facts.institution_name
    )
    institution = None
    if not jointly_awarded:
        institution, _created = Institution.objects.get_or_create(
            canonical_key=catalog_key(
                program_facts.country_code, program_facts.institution_name
            ),
            defaults={
                "name": program_facts.institution_name,
                "country_code": program_facts.country_code,
                "official_website": _origin(source.canonical_url),
            },
        )
    program, _created = Program.objects.get_or_create(
        institution=institution,
        canonical_key=catalog_key(program_facts.degree_level, program_facts.program_name),
        # Constant per institution, not per city: §2.5's dedupe key is
        # (institution, programme name, degree level), and a catalogue's
        # "Nürnberg" against a university's "Nuremberg" must not fork the row.
        # ponytail: revisit when a genuinely multi-campus programme appears.
        location_key=location_key(
            country_code=program_facts.country_code, city=program_facts.institution_name
        ),
        # Which site vouches for the row is part of its identity: without it a
        # fake page naming the same university and programme attaches its
        # claims to the real row, emptying its evidence_domain and putting the
        # fake URL on the student's card (provenance gate spec §3). Set on
        # create only; nothing rewrites it.
        origin_domain=registrable_domain(source.canonical_url),
        defaults={
            "name": program_facts.program_name,
            # A city is a city or nothing. On a JOINT row institution_name is
            # several universities in one string ("A; B; C"), and
            # evaluation.py's LOCATION gate compares city by equality -- so
            # borrowing it here excluded the programme from every student who
            # named a real city. Empty lets that gate fall through to
            # country_code and location_key, which is the honest answer when
            # no page stated a city. location_key above keeps institution_name
            # on purpose; that is a dedupe key, not a place.
            "campus_name": program_facts.city,
            "city": program_facts.city,
            "country_code": program_facts.country_code,
            "degree_level": program_facts.degree_level,
            "teaching_languages": list(program_facts.teaching_languages),
            "duration_months": program_facts.duration_months,
            "provision_type": (
                Program.ProvisionType.JOINT
                if jointly_awarded
                else Program.ProvisionType.SINGLE
            ),
            # The scraped string, unsplit: a name is not a binding, so the
            # curator gets what the page said and decides (design §3.3).
            "provider_text": program_facts.institution_name if jointly_awarded else "",
        },
    )
    written: list[OfficialEvidenceClaim] = []
    for claim_class, text in rows:
        claim = OfficialEvidenceClaim.objects.create(
            source=source,
            snapshot=snapshot,
            claim=text,
            evidence_strength=lead.evidence_strength,
            visibility=lead.visibility,
            claim_class=claim_class,
            last_checked_at=checked_at,
        )
        ProgramEvidenceClaim.objects.get_or_create(program=program, evidence_claim=claim)
        if claim_class == OfficialEvidenceClaim.ClaimClass.IDENTITY and institution is not None:
            InstitutionEvidenceClaim.objects.get_or_create(
                institution=institution, evidence_claim=claim
            )
        written.append(claim)
    # The programme's own evidence decides its body (institution provenance
    # gate spec §3) -- never the Institution row above, which is found by NAME
    # and so can be reached by a fake page naming a real university. Shared
    # with `backfill_evidence_domain` (ruling I2) so a programme written
    # before this existed gets the same answer as one written after.
    record_program_evidence(program, institution_name=program_facts.institution_name)
    # Claims beat seeds here too (module rule above): a page's own cited
    # FundingFamilyClaim outranks the seed adapter's assertion, because the
    # seed's family has no citation attached and family is a field students
    # filter on (whole-branch review, Fix 4). The seed is the fallback only
    # when the page states no family at all.
    family = (
        claims.funding_family.family if claims.funding_family is not None else ""
    ) or lead.funding_family
    opportunity = _write_opportunity(family, program, written) if family else None
    return CatalogWriteResult(
        institution, program, tuple(written), opportunity, unreadable_dates
    )


def _write_opportunity(
    family: str, program: Program, claims: list[OfficialEvidenceClaim]
) -> FundingOpportunity:
    """Stated by the seed adapter or cited by the page. Never inferred.

    FundingFamily is an eleven-value contract; choosing one from context and
    writing it unsourced is exactly the inference P1-4 forbids.
    """
    opportunity, _created = FundingOpportunity.objects.get_or_create(
        canonical_key=catalog_key(family, str(program.id)),
        defaults={
            "name": program.name,
            "family": family,
            "scope_type": "PROGRAM",
            "program": program,
        },
    )
    FundingOpportunityProgram.objects.get_or_create(opportunity=opportunity, program=program)
    for claim in claims:
        FundingOpportunityEvidenceClaim.objects.get_or_create(
            opportunity=opportunity, evidence_claim=claim
        )
    return opportunity
