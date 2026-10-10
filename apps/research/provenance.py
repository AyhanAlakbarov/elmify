"""Institution provenance: the verdict vocabulary and its one writer.

Spec: docs/superpowers/specs/2026-09-26-institution-provenance-gate-design.md
§4 (verdicts), §8 (storage). Admission rests only on evidence the attacker
cannot write; content checks may only veto; absence is never BLOCKED.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from django.db import transaction

from apps.funding.models import FundingOpportunity, OfficialEvidenceClaim, Program

from .hosts import is_hosting_platform, is_institutional_url, registrable_domain
from .models import (
    _BLOCKED_REASONS,
    _RECOGNISED_REASONS,
    _UNCONFIRMED_REASONS,
    Organisation,
    OrganisationDomain,
    ProvenanceVerdict,
    ProvenanceVerdictChange,
)
from .register import record_organisation

Verdict = ProvenanceVerdict.Verdict
Reason = ProvenanceVerdict.Reason

RECOGNISED_REASONS: frozenset[str] = frozenset(_RECOGNISED_REASONS)
UNCONFIRMED_REASONS: frozenset[str] = frozenset(_UNCONFIRMED_REASONS)
BLOCKED_REASONS: frozenset[str] = frozenset(_BLOCKED_REASONS)
#: A pack build leaves these out and queues them rather than excluding them for
#: a reason (spec §7.1): the check has simply not happened yet.
WAITING_REASONS: frozenset[str] = frozenset({Reason.NOT_EVALUATED, Reason.REGISTER_NOT_LOADED})


def verdict_of(reason_code: str) -> str:
    if reason_code in RECOGNISED_REASONS:
        return Verdict.RECOGNISED
    if reason_code in BLOCKED_REASONS:
        return Verdict.BLOCKED
    return Verdict.UNCONFIRMED


def evidence_of(urls: Iterable[str]) -> tuple[str, bool]:
    """(the single registrable domain of the evidence, whether it is all
    institutional) -- ("", False) when there is none or it disagrees (spec §3)."""
    listed = tuple(urls)
    domains = {registrable_domain(url) for url in listed}
    if len(domains) != 1 or "" in domains:
        return "", False
    domain = domains.pop()
    return domain, all(is_institutional_url(url, domain) for url in listed)


def record_program_evidence(program: Program, *, institution_name: str) -> tuple[str, bool]:
    """Set a programme's `evidence_domain`/`evidence_institutional` from its own
    `OfficialEvidenceClaim` source URLs, and record the evidence body -- never
    the `Institution` row found by name, which is exactly the hole a fake page
    naming a real university walks through (spec §3, §1).

    The one function the catalogue writer and `backfill_evidence_domain` both
    call, so a programme written before this existed and one written after it
    get the same answer (provenance-gate plan Task 3, ruling I2).
    """
    domain, institutional = evidence_of(
        OfficialEvidenceClaim.objects.filter(program=program).values_list(
            "source__canonical_url", flat=True
        )
    )
    if (program.evidence_domain, program.evidence_institutional) != (domain, institutional):
        program.evidence_domain, program.evidence_institutional = domain, institutional
        program.save(update_fields=["evidence_domain", "evidence_institutional"])
    if domain and not is_hosting_platform(domain):
        # The body the verdict attaches to. No country: the page's country is
        # a model reading of the attacker's page (spec §5.2). The name is a
        # label, never a key, and truncated to Organisation.name's max length
        # -- a JOINT row's institution_name is several names joined with "; ".
        record_organisation(
            domain=domain, name=institution_name[:300], kind="INSTITUTION",
            country_code="", found_via="CATALOG:programme",
        )
    return domain, institutional


#: Fixed wording per reason, English then Azerbaijani (spec §4.1, §9.4).
#: Pinned by tests/research/test_provenance_storage.py.
WORDING: dict[str, tuple[str, str]] = {
    # AZ wording awaits a native-speaker check; "tanınan" (recognised, present
    # participle) is used for institutions and "məlum" (known) for an
    # accreditor, never "tanınmış" (well-known/famous) -- see fix round 1.
    Reason.REGISTER: (
        "Named on its country's official register of recognised institutions.",
        "Ölkəsinin tanınan ali təhsil müəssisələrinin rəsmi reyestrində göstərilib.",
    ),
    Reason.CURATED_LIST: (
        "Named on a reviewed official list.",
        "Yoxlanılmış rəsmi siyahıda göstərilib.",
    ),
    Reason.FUNDER_LIST: (
        "Named by a scholarship funder's own list of institutions.",
        "Təqaüd verən qurumun öz müəssisələr siyahısında göstərilib.",
    ),
    Reason.VOUCHED_BY_LINK: (
        "Shown as part of a recognised institution on that institution's own website.",
        "Tanınan müəssisənin öz saytında onun tərkib hissəsi kimi göstərilib.",
    ),
    Reason.GOVERNMENT_ZONE: (
        "A government body, on a domain only governments can hold.",
        "Yalnız dövlət qurumlarına verilən domendə yerləşən dövlət qurumudur.",
    ),
    Reason.NOT_EVALUATED: ("Not checked yet.", "Hələ yoxlanılmayıb."),
    Reason.REGISTER_NOT_LOADED: (
        "Its country's register has not been read yet.",
        "Ölkəsinin reyestri hələ oxunmayıb.",
    ),
    Reason.ABSENT_FROM_REGISTER: (
        "Not found on its country's register; this alone is not proof of a problem.",
        "Ölkəsinin reyestrində tapılmadı; bu, tək başına problem olduğunu sübut etmir.",
    ),
    Reason.NO_DOMAIN_BINDING: (
        "Its website could not yet be tied to an official record.",
        "Saytı hələ rəsmi qeydlə əlaqələndirilə bilmədi.",
    ),
    Reason.UNMAPPED_LIST_ROW: (
        "Listed officially, but its website is not confirmed yet.",
        "Rəsmi siyahıdadır, lakin saytı hələ təsdiqlənməyib.",
    ),
    Reason.DOMAIN_REGISTERED_AFTER_LISTING: (
        "Its web address was registered again after it was listed; we are re-checking.",
        "Sayt ünvanı siyahıya salındıqdan sonra yenidən qeydiyyatdan keçib; yenidən yoxlayırıq.",
    ),
    # Controller ruling: no UNCONFIRMED/BLOCKED wording may open with positive
    # recognition language -- recognition_note prefixes it with "Recognition
    # not confirmed:", so "Recognised, but ..." read as a contradiction.
    Reason.VETO_CONFLICT: (
        "Named by an official source, but its pages carry wording we must check by hand.",
        "Rəsmi mənbədə göstərilib, lakin səhifələrində əl ilə yoxlanmalı ifadələr var.",
    ),
    Reason.EVIDENCE_OFF_DOMAIN: (
        "The programme's pages are not on the institution's own website.",
        "Proqramın səhifələri müəssisənin öz saytında deyil.",
    ),
    Reason.LOOKUP_FAILED: (
        "An official source could not be reached; we will try again.",
        "Rəsmi mənbəyə çatmaq mümkün olmadı; yenidən cəhd edəcəyik.",
    ),
    Reason.NO_HOLDER_BODY: (
        "The award does not name the body that pays it.",
        "Təqaüd onu ödəyən qurumu göstərmir.",
    ),
    Reason.VOUCH_LINK_MISSING: (
        "The recognised institution no longer links to it; we are re-checking.",
        "Tanınan müəssisə artıq ona keçid vermir; yenidən yoxlayırıq.",
    ),
    Reason.NO_REGISTER: (
        "We have no official register for this country.",
        "Bu ölkə üçün rəsmi reyestrimiz yoxdur.",
    ),
    Reason.MILL_LIST: (
        "On a published list of unaccredited institutions.",
        "Akkreditasiyasız müəssisələrin dərc olunmuş siyahısındadır.",
    ),
    Reason.ACCREDITATION_MILL: (
        "Claims accreditation from a known fake accreditor.",
        "Məlum saxta akkreditasiya qurumunun akkreditasiyasını iddia edir.",
    ),
    Reason.FEE_TO_RELEASE_AWARD: (
        "Asks for a fee to release a scholarship.",
        "Təqaüdü vermək üçün ödəniş tələb edir.",
    ),
    Reason.DEGREE_FOR_PAYMENT: (
        "Offers a degree for payment without study.",
        "Təhsil almadan ödənişlə diplom təklif edir.",
    ),
}


def _domain_verdict(domain: str) -> tuple[UUID | None, str]:
    """(the body judged on `domain`, its reason code); no verdict row is
    `not_evaluated`, owned by whichever body the domain belongs to."""
    row = (
        ProvenanceVerdict.objects.filter(domain=domain)
        .values_list("organisation_id", "reason_code")
        .first()
    )
    if row is not None:
        return row
    body = (
        OrganisationDomain.objects.filter(registrable_domain=domain)
        .values_list("organisation_id", flat=True)
        .first()
    )
    return body, Reason.NOT_EVALUATED


def provenance_of_program(program: Program) -> tuple[UUID | None, str]:
    """The tenant copy for a programme candidate: its evidence body and code.

    Admissible means RECOGNISED on its own `evidence_domain` AND all its
    evidence institutional (spec §3) -- exactly the pool's filter. Evidence off
    the domain is the reason whatever the domain's verdict, except BLOCKED,
    which says more.
    """
    domain = program.evidence_domain
    if not domain:
        return None, Reason.EVIDENCE_OFF_DOMAIN
    body, code = _domain_verdict(domain)
    # A hosting-platform domain is never institutional (is_institutional_url),
    # so it lands here too, and never reads as "not checked yet".
    if not program.evidence_institutional and code not in BLOCKED_REASONS:
        return body, Reason.EVIDENCE_OFF_DOMAIN
    return body, code


def programme_verdict(program: Program) -> tuple[str, str]:
    """(verdict, reason) for an operator command (spec §7.5)."""
    _body, code = provenance_of_program(program)
    return verdict_of(code), code


def provenance_of_award(award: FundingOpportunity) -> tuple[UUID | None, str]:
    """The tenant copy for a HOLDER award: judged on its `holder_domain`."""
    if award.organisation_id is None:
        return None, Reason.NO_HOLDER_BODY
    if not award.holder_domain:
        # Nothing can be checked, and nothing will be (bodies_in_play skips it).
        return award.organisation_id, Reason.NO_DOMAIN_BINDING
    body, code = _domain_verdict(award.holder_domain)
    return body or award.organisation_id, code


def provenance_of_named(source_url: str) -> tuple[UUID | None, str] | None:
    """The tenant copy for a named programme, read from the verdict on the
    domain of the URL a counsellor verified -- with the short-circuits
    `check_named_url` takes before it checks anything. None when that domain
    has no verdict row: its check never ran, and only the worker may run it."""
    domain = registrable_domain(source_url)
    if not domain or is_hosting_platform(domain):
        return None, Reason.NO_DOMAIN_BINDING
    if not is_institutional_url(source_url, domain):
        return None, Reason.EVIDENCE_OFF_DOMAIN
    row = (
        ProvenanceVerdict.objects.filter(domain=domain)
        .values_list("organisation_id", "reason_code", "organisation__status")
        .first()
    )
    if row is None:
        return None
    body, code, status = row
    if status == Organisation.Status.REJECTED:
        return body, Reason.NO_DOMAIN_BINDING
    return body, code


def recognition_note(reason_code: str) -> str:
    """What a student reads beside a programme whose recognition is not
    confirmed (owner decision, spec preamble); "" for any other code, and ""
    (never a raise) for a code this table does not know."""
    if not reason_code or verdict_of(reason_code) != Verdict.UNCONFIRMED:
        return ""
    wording = WORDING.get(reason_code)
    if wording is None:
        return ""
    return f"Recognition not confirmed: {wording[0]}"


def candidate_note(reason_code: str) -> str:
    """What a person reads beside a candidate from its tenant code: why a
    BLOCKED one cannot be added, or the UNCONFIRMED note; "" otherwise."""
    return blocked_note(reason_code) or recognition_note(reason_code)


def blocked_note(reason_code: str) -> str:
    """What a STUDENT reads beside a candidate: only why a BLOCKED one cannot
    be added. An unconfirmed one is never shown to a student (spec §0.18)."""
    if reason_code in BLOCKED_REASONS:
        return f"Cannot be added: {WORDING[reason_code][0]}"
    return ""


@transaction.atomic
def record_verdict(
    organisation: Organisation,
    domain: str,
    *,
    verdict: str,
    reason_code: str,
    evidence: dict[str, object],
    now: datetime,
    next_check_at: datetime | None,
) -> ProvenanceVerdict:
    """Write the verdict for one (body, registrable domain) pair and, when it
    changed, one history row.

    `first_bound_at` is set by the row's first RECOGNISED verdict and kept
    through every later re-check and downgrade of the same row: it is the date
    a later registration date is compared with (spec §5.5), so a lapse must
    not reset the takeover clock. Another domain is another row, with its own.
    """
    if verdict_of(reason_code) != verdict:
        raise ValueError(f"{reason_code} is not a {verdict} reason")
    current = ProvenanceVerdict.objects.select_for_update().filter(domain=domain).first()
    first_bound_at = current.first_bound_at if current is not None else None
    if verdict == Verdict.RECOGNISED and first_bound_at is None:
        first_bound_at = now
    row, _created = ProvenanceVerdict.objects.update_or_create(
        domain=domain,
        defaults={
            "organisation": organisation,
            "verdict": verdict,
            "reason_code": reason_code,
            "evidence": evidence,
            "checked_at": now,
            "next_check_at": next_check_at,
            "first_bound_at": first_bound_at,
        },
    )
    if current is None or (current.verdict, current.reason_code) != (verdict, reason_code):
        ProvenanceVerdictChange.objects.create(
            organisation=organisation,
            domain=domain,
            old=current.verdict if current is not None else "",
            new=verdict,
            reason_code=reason_code,
            at=now,
        )
    return row


@dataclass(frozen=True)
class Recognition:
    """One route that names the body and binds it to `bound_domain` (spec §5.1-§5.3, §5.7)."""

    reason: str
    bound_domain: str
    source_slug: str = ""
    source_url: str = ""
    list_date: str = ""
    #: The country of a register row -- the only country a mill-list entry
    #: accepts as an override (spec §5.4 rule 1).
    country_code: str = ""
    identifier: tuple[str, str] | None = None
    vouch_url: str = ""
    admitted_via: str = ""


@dataclass(frozen=True)
class MillHit:
    source: str
    revision: str
    country_code: str
    overridden: bool


@dataclass(frozen=True)
class ContentHit:
    reason: str
    span: str
    url: str


@dataclass(frozen=True)
class RdapResult:
    status: str
    registered: date | None = None
    detail: str = ""


@dataclass(frozen=True)
class Facts:
    domain: str
    recognitions: tuple[Recognition, ...] = ()
    unverified_list_row: bool = False
    mill: MillHit | None = None
    content_hits: tuple[ContentHit, ...] = ()
    content_checks: str = "run"
    #: Why the content checks were skipped, beside the status: blocking.content_facts.
    content_checks_detail: str = ""
    rdap: RdapResult = field(default_factory=lambda: RdapResult("skipped"))
    first_bound_at: datetime | None = None
    #: recognition.register_state's "not_loaded" / "unbound_rows" / "absent",
    #: or "no_register": no register is shipped for the country (or there is
    #: no country), so nothing is about to load and nothing is waited for.
    register_state: str = "not_loaded"
    lookup_failed: bool = False
    was_vouched: bool = False


@dataclass(frozen=True)
class Decision:
    verdict: str
    reason_code: str
    bound_domain: str
    evidence: dict[str, object]


#: Strongest first. A register is the authority itself; a vouch is one hop
#: from one.
_PRIORITY: tuple[str, ...] = (
    Reason.REGISTER, Reason.CURATED_LIST, Reason.FUNDER_LIST,
    Reason.GOVERNMENT_ZONE, Reason.VOUCHED_BY_LINK,
)


def decide(facts: Facts) -> Decision:
    """Evidence to verdict (spec §4, §5). Order, and it is the whole function:

    1. a mill-list domain, not overridden by its own country's register -> BLOCKED;
    2. a usable recognition -> RECOGNISED, unless a content veto hit
       (veto_conflict) or the domain was registered after we first bound it;
    3. a recognition was offered but none of them bind `facts.domain` (each
       is on a hosting platform, or bound to a different domain) ->
       UNCONFIRMED(no_domain_binding), whatever the content checks say;
    4. no recognition and a content veto hit -> BLOCKED;
    5. otherwise UNCONFIRMED, with the most specific reason. Absence is never BLOCKED.

    **Each body is judged for its own domain.** A list row recognises the body
    of its own website domain, never a different, unchecked one: a
    `Recognition` is usable only when its `bound_domain` is the same
    registrable domain as `facts.domain` (controller ruling, fix round 1).
    ESMT is the probe that motivated this -- its recognising row's
    `domains[]` is esmt.org while its recognised website is esmt.berlin
    (spec §5.2) -- and admitting `chosen.bound_domain` unchecked let a lookup
    on esmt.org come back RECOGNISED, bound to esmt.berlin, a domain nothing
    about esmt.org's own evidence ever named.
    """
    evidence: dict[str, object] = {
        "content_checks": facts.content_checks,
        "content_checks_detail": facts.content_checks_detail,
        "rdap": {
            "status": facts.rdap.status,
            "date": facts.rdap.registered.isoformat() if facts.rdap.registered else "",
            "detail": facts.rdap.detail,
        },
    }
    if facts.content_hits:
        evidence["content_hits"] = [
            {"reason": hit.reason, "span": hit.span[:300], "url": hit.url}
            for hit in facts.content_hits
        ]
    if facts.mill is not None:
        # Recorded whether or not it decides anything, so an override is
        # visible in the evidence rather than only in the verdict it did not
        # produce.
        evidence["mill"] = {
            "source": facts.mill.source,
            "revision": facts.mill.revision,
            "country_code": facts.mill.country_code,
            "overridden": facts.mill.overridden,
        }
        if not facts.mill.overridden:
            return Decision(Verdict.BLOCKED, Reason.MILL_LIST, facts.domain, evidence)
    domain = registrable_domain(facts.domain)
    usable = sorted(
        (
            r
            for r in facts.recognitions
            if not is_hosting_platform(r.bound_domain)
            and registrable_domain(r.bound_domain) == domain
        ),
        key=lambda r: _PRIORITY.index(r.reason),
    )
    if usable:
        chosen = usable[0]
        evidence.update(
            {
                "source_slug": chosen.source_slug,
                "source_url": chosen.source_url,
                "list_date": chosen.list_date,
                "identifier": (
                    {"scheme": chosen.identifier[0], "value": chosen.identifier[1]}
                    if chosen.identifier
                    else None
                ),
                "vouch_url": chosen.vouch_url,
                "admitted_via": chosen.admitted_via,
            }
        )
        if facts.content_hits:
            return Decision(
                Verdict.UNCONFIRMED, Reason.VETO_CONFLICT, chosen.bound_domain, evidence
            )
        if _taken_over(facts):
            return Decision(
                Verdict.UNCONFIRMED, Reason.DOMAIN_REGISTERED_AFTER_LISTING,
                chosen.bound_domain, evidence,
            )
        return Decision(Verdict.RECOGNISED, chosen.reason, chosen.bound_domain, evidence)
    if facts.recognitions:
        # Every offered recognition was dropped for its domain, not for what
        # the page says -- a domain gap, never a fraud signal, so a content
        # veto here must never escalate this to BLOCKED, and a data gap
        # elsewhere (register_not_loaded, absent_from_register) must never
        # hide it either.
        return Decision(Verdict.UNCONFIRMED, Reason.NO_DOMAIN_BINDING, facts.domain, evidence)
    if facts.content_hits:
        return Decision(Verdict.BLOCKED, facts.content_hits[0].reason, facts.domain, evidence)
    return Decision(Verdict.UNCONFIRMED, _unconfirmed_reason(facts), facts.domain, evidence)


def _taken_over(facts: Facts) -> bool:
    """Registered after OUR first binding: a re-registered expired domain looks
    exactly like this, and so does a rebrand -- hence UNCONFIRMED, never BLOCKED."""
    return (
        facts.rdap.status == "ok"
        and facts.rdap.registered is not None
        and facts.first_bound_at is not None
        and facts.rdap.registered > facts.first_bound_at.date()
    )


def _unconfirmed_reason(facts: Facts) -> str:
    if facts.unverified_list_row:
        return Reason.UNMAPPED_LIST_ROW
    if facts.was_vouched:
        return Reason.VOUCH_LINK_MISSING
    if facts.lookup_failed:
        return Reason.LOOKUP_FAILED
    if is_hosting_platform(facts.domain) or facts.register_state == "unbound_rows":
        return Reason.NO_DOMAIN_BINDING
    if facts.register_state == "absent":
        return Reason.ABSENT_FROM_REGISTER
    if facts.register_state == "no_register":
        return Reason.NO_REGISTER
    return Reason.REGISTER_NOT_LOADED
