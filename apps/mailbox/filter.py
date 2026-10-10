"""The sender allowlist, derived from this student's own pack.

Spec decision 3 describes this as the origins of the OfficialSource rows behind
the pack's programmes. That join does not exist: a RecommendationCandidate
carries a free-text program_name and one EvidenceClaim, and no FK to the
catalog at all. So the allowlist is built from each candidate's own evidence
URL -- the page that candidate's recommendation was evidenced against -- which
is the same set reached by the only join the schema offers.

On Gmail's content tier the listing is already a search for these domains
(sync.py::_search_for), so strangers' mail is never listed. Elsewhere Gmail
fetches one metadata call per message, and Graph lists by date, before this
filter runs -- listing headers is not free there. What this module guarantees is narrower and still
the whole privacy argument: a message BODY is never fetched for a sender that
does not match.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from apps.funding.models import PackCandidate
from apps.funding.services import current_pack
from apps.mailbox.models import LearnedSender
from apps.mailbox.providers import _SEARCHABLE_DOMAIN, sender_domain
from apps.portals.models import Application
from apps.research.hosts import is_hosting_platform, registrable_domain
from apps.tenancy.models import Membership

#: RFC 2606 / RFC 6761 reserved names plus the one this codebase mints itself:
#: apps/funding/services.py gives a student-named programme the placeholder
#: https://research.pending.internal/named-program/<uuid>, and its own
#: docstring warns it must never be displayed as a verified source. It must not
#: become a domain the platform reads mail from either.
_RESERVED_SUFFIXES = (".internal", ".local", ".localhost", ".test", ".invalid", ".example")


#: RFC 1035: a label is at most 63 octets, a name at most 253 characters in its
#: dotted form. `registrable_domain` does not enforce either -- it is a suffix
#: match, not a validator -- so an attacker-controlled From header with an
#: absurd host reached `_key` unfiltered and its key (equally absurd) reached
#: `MailSignal.sender_domain`, a `varchar(253)` column. That is not a display
#: problem: `DataError: value too long for type character varying(253)` is
#: raised inside the header loop's `get_or_create`, uncaught, aborting the
#: whole sync for every other message in the same batch (fix round 2 finding).
_MAX_HOST_LENGTH = 253
_MAX_LABEL_LENGTH = 63


def _usable(host: str) -> bool:
    """Whether ``host`` (already IDNA-encoded) is a plain hostname we may key.

    The full match is what bounds attacker text (final review I4): a From
    header's newline, space or slash never reaches a signal, a card, an
    escalation or a log line. Same pattern as the Gmail search guard.
    """
    return (
        bool(_SEARCHABLE_DOMAIN.fullmatch(host))
        and not host.endswith(_RESERVED_SUFFIXES)
        and len(host) <= _MAX_HOST_LENGTH
        and all(len(label) <= _MAX_LABEL_LENGTH for label in host.split("."))
    )


def _ascii_host(host: str) -> str:
    """``host`` in its IDNA (punycode) form, or "" when it has none.

    münchen.de keys as xn--mnchen-3ya.de; a fullwidth look-alike maps to the
    plain name it resolves as; a Cyrillic one keys as its own punycode, never
    as the Latin name it imitates.
    """
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def _host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold()


#: Consumer webmail used by millions of unrelated people. A domain here must
#: never become a LearnedSender: a scammer (or the student themself) mailing a
#: leaked tag from one of these would otherwise teach the platform to read
#: every stranger's mail sent to it afterward (Task 5 fix round 1, finding 2).
#: The tagged message itself is still read either way -- reading is broader
#: than learning -- only the write is refused.
_FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.de",
        "gmx.net",
        "web.de",
        "mail.ru",
        "yandex.ru",
        "yandex.com",
        "qq.com",
        "163.com",
    }
)

#: Hosts shared by many institutions: their registrable domain names the vendor,
#: so keying on it would read every customer's mail as this student's -- a pack
#: link to sites.google.com must not allowlist accounts.google.com (final
#: review I3). Keep the full host for these. Extend when a new multi-tenant
#: portal, form or site vendor appears.
#:
#: Only vendors the Public Suffix List's private section does NOT cover need
#: naming: `_key` reads that section, so a herokuapp.com or netlify.app
#: customer already keys as its own host. The second group below was measured
#: 2026-09-26 (security finding, vuln 1) as absent from it -- kth.smapply.io
#: keyed as smapply.io and read every smapply customer's mail as this
#: student's. amazonaws.com is listed because the section covers only some of
#: its service subdomains.
_SHARED_PLATFORMS = (
    frozenset(
        {
            "dreamapply.com",
            "google.com",
            "googleusercontent.com",
            "office.com",
            "sharepoint.com",
            "microsoft.com",
            "live.com",
            "linkedin.com",
            "wixsite.com",
            "wix.com",
            "medium.com",
            "github.io",
            "notion.site",
            "typeform.com",
            "jotform.com",
            "smapply.io",
            "smapply.org",
            "smapply.ca",
            "academicworks.com",
            "submittable.com",
            "fluidreview.com",
            "qualtrics.com",
            "force.com",
            "salesforce.com",
            "site.com",
            "moveon4.de",
            "wordpress.com",
            "amazonaws.com",
        }
    )
    | _FREE_MAIL_DOMAINS
)


#: Hosts where one literal host serves every customer, told apart only by URL
#: PATH -- unlike a shared platform's subdomain (kth.smapply.io), no suffix of
#: this host is ever a single customer's own name, so it must never become a
#: link target (security finding 2026-09-26, follow-up 2: a pack link to
#: https://sites.google.com/view/kth-msc must not admit
#: https://sites.google.com/view/attacker). Reading is unaffected -- `_key`
#: still keys these on the full host, which is correct for "may we read this".
_PATH_TENANTED_HOSTS = frozenset(
    {
        "sites.google.com",
        "docs.google.com",
        "forms.office.com",
        "forms.gle",
        "form.jotform.com",
        "typeform.com",
    }
)


def _is_platform_host(host: str) -> bool:
    """Whether ``host`` is a shared platform's own name, never one customer's
    corner of it: a bare `_SHARED_PLATFORMS` apex, a bare PSL private suffix
    (an empty private-aware registrable domain, e.g. a bare herokuapp.com),
    or a path-tenanted host or one of its subdomains.

    Shared by `link_hosts` (such a host must never become a link target --
    security finding 2026-09-26, follow-up 1 and 2) and `learnable_domain`
    (must never become a LearnedSender -- same finding, follow-up 3), so the
    same test is not written twice. `learnable_domain` layers one further,
    stricter check of its own on top: see its docstring for why a link
    target and a learned sender cannot share that one.

    Callers must pass a casefolded host with no trailing dot (both current
    callers already do).
    """
    return (
        host in _SHARED_PLATFORMS
        or registrable_domain(host) == ""
        or host_in(host, _PATH_TENANTED_HOSTS) != ""
    )


def _key(host: str) -> str:
    """The allowlist key for a host: its registrable domain, "" if none.

    A pack link to www.tum.de must allowlist mail from tum.de and mail.tum.de,
    which suffix matching on the full host never did. The registrable domain,
    from the Public Suffix List snapshot, is what the institution owns:
    metu.edu.tr, never edu.tr -- and, reading the list's private section,
    uni.herokuapp.com, never herokuapp.com.

    This key is for READING (which senders a pack justifies). Acting on a link
    checks full hosts instead: see `link_hosts`.
    """
    host = _ascii_host(host.strip().casefold().rstrip("."))
    if not _usable(host):
        return ""
    domain = registrable_domain(host)
    if not domain:
        # registrable_domain keys a hosting platform's own root (medium.com,
        # sites.google.com) as "" -- it names the landlord, not a publisher.
        # Reading still keys it on the full host, as for _SHARED_PLATFORMS.
        return host if is_hosting_platform(host) else ""
    return host if domain in _SHARED_PLATFORMS else domain


def sender_key(sender: str) -> str:
    """The allowlist key for a From value, or ""."""
    return _key(sender_domain(sender))


def learnable_domain(domain: str, *, own_domains: Iterable[str]) -> bool:
    """Whether ``domain`` may become a LearnedSender (Task 5 fix round 1,
    finding 2). Never a free-mail domain, and never this connection's own
    address or a tagged address's own domain -- ``own_domains`` carries both.
    The message is still read either way; this only gates the write.

    Also never a shared-platform apex, a bare public-suffix-list private
    suffix, or a path-tenanted host (security finding 2026-09-26, follow-ups
    1-3): `_key` returns a shared platform's OWN host verbatim when the
    sender IS the platform apex (mail from no-reply@smapply.io keys as
    "smapply.io" itself, not a customer subdomain), and `host_in`'s suffix
    match then admits every *.smapply.io customer once the student confirms
    it. `_is_platform_host` is the shared test for that (and for
    `link_hosts`' matching guard).

    One further check is unique to THIS function, not shared with
    `link_hosts`: a domain whose PRIVATE-AWARE registrable domain is itself a
    `_SHARED_PLATFORMS` entry is refused too, even when the domain is a
    subdomain rather than the bare apex. Some platforms (Qualtrics,
    Salesforce, `site.com`) hand out subdomains that are shared across every
    customer, and `registrable_domain` (private-aware) collapses
    kth.smapply.io to smapply.io exactly the way it collapses
    eu.qualtrics.com to qualtrics.com -- nothing in this check can tell a
    genuine institution's own corner of smapply.io apart from an attacker's,
    so it refuses both alike (controller ruling, security finding
    2026-09-26: fail-closed accepted). That costs nothing a student needs: a
    portal the student applies through is already vouched by its
    Application.portal_host, so tagged mail from kth.smapply.io is still read
    as a signal -- reading is broader than learning -- only a LearnedSender
    row is refused. A link target does not need this stricter rule: it is
    limited to the full hosts a pack or an application actually NAMED, so a
    genuine kth.smapply.io link stays open under `link_hosts` while neither
    it nor eu.qualtrics.com can be learned as a sender here.
    """
    # Registrable, not the key: eu.outlook.com is still outlook.com, and
    # _SHARED_PLATFORMS includes every _FREE_MAIL_DOMAINS entry.
    return (
        domain not in own_domains
        and not _is_platform_host(domain)
        and registrable_domain(domain) not in _SHARED_PLATFORMS
    )


def learn_answered_sender(
    student: Membership, sender: str, portal_host: str, *, own_addresses: Iterable[str]
) -> bool:
    """The student named who sent a portal's email: read it, not yet trusted.

    Standing at the portal they just registered on, the student read the
    sender off that portal's own email (spec §2a) and typed it into the dock.
    That is stronger evidence than a leaked tag, but it is still text the
    student typed -- a look-alike address copied by mistake would otherwise
    open links on every subdomain of a domain nobody vetted. So the row is
    written **unconfirmed**, exactly like a sender first learned from a tag
    (sync.py): `confirmed_at` stays NULL, `allowed_senders` reads it,
    `link_hosts` does not trust it as a link target, and the existing confirm
    button (`mailbox/views.py`) remains the only way to change that (ruling
    F8). The `learned` flag this function's return value drives reports
    whether a row was written, not whether it is trusted.

    Same guards as learning from a tag, via `learnable_domain`: never free
    mail, never the student's own domain, and never a shared platform's own
    host -- a STRIPS portal on a shared platform (e.g. dreamapply.com) is
    refused here for the same reason kth.smapply.io is, and is read only
    through a human-curated `PortalForm.sender_domains` row, never through a
    per-student learn (ruling F7).

    Run inside the student's tenant transaction. False when the domain may
    never be learned (or `sender` names no usable domain).
    """
    domain = sender_key(sender)
    own = {sender_key(address) for address in own_addresses} - {""}
    if not domain or not learnable_domain(domain, own_domains=own):
        return False
    LearnedSender.objects.get_or_create(
        student=student,
        domain=domain,
        defaults={"tenant_id": student.tenant_id, "portal_host": portal_host},
    )
    return True


def vouched_senders(student: Membership) -> dict[str, UUID | None]:
    """Every domain this student's pack and applications justify reading, and
    the application each one belongs to.

    A mapping rather than a set because the sync needs both answers and they
    come from the same two queries. Resolving the application separately, per
    matched message, would walk these same rows again to learn something this
    pass already knew. `None` is a pack domain that is nobody's portal.

    Separate from `allowed_senders` (which adds learned domains on top) so
    `unconfirmed_senders` can subtract exactly this set: a domain the pack or
    an application vouches for is never "unconfirmed", however it was first
    learned (Task 5 fix round 1, finding 3).

    Read inside the caller's tenant transaction: every queryset here is
    tenant-scoped except the forward hop to PortalForm, which is platform-shared
    by design.
    """
    senders: dict[str, UUID | None] = {}
    urls, forms = _vouching_rows(student)
    for url in urls:
        if host := _key(_host_of(url)):
            senders.setdefault(host, None)

    # Tracks the first application_id claimed for each host, kept apart from
    # `senders` itself: a pack-only host is already `None` in `senders` before
    # this loop runs (nobody's portal), and once a host is marked ambiguous
    # below `senders[host]` is `None` too -- neither can tell "never claimed by
    # a form" from "claimed, then made ambiguous" from "pack-only". This dict
    # can, because it is only ever written by this loop.
    claimed_by: dict[str, UUID] = {}
    for application_id, portal_host, learned in forms:
        # A portal's own domains win over a pack entry of the same name: the
        # application is the more specific answer, and a signal that names one
        # is what moves that application's state.
        for entry in (portal_host, *(learned or ())):
            if not (host := _key(str(entry))):
                continue
            first_claimant = claimed_by.get(host)
            if first_claimant is None:
                claimed_by[host] = application_id
                senders[host] = application_id
            elif first_claimant != application_id:
                # Two applications share this portal host -- an ordinary case
                # (a student applying to two programmes at one university).
                # Attributing the domain to whichever application the
                # queryset happened to return last would let a RECEIVED
                # verdict flip the WRONG application to CONFIRMED. Mark it
                # ambiguous instead: the domain stays allowed (the signal and
                # notification card still fire) but apply_verdict's
                # `if application is not None` branch -- the state-change /
                # step-writing one -- naturally skips it. `claimed_by` is left
                # pointing at the original claimant, so a THIRD application
                # sharing this host is compared against it too and the host
                # stays ambiguous rather than flipping back to a specific id.
                senders[host] = None

    return senders


def _vouching_rows(
    student: Membership,
) -> tuple[list[str], list[tuple[UUID, str, list[str] | None]]]:
    """The pack's evidence URLs and each application's (id, portal host,
    sender domains): the rows both `vouched_senders` (reading) and
    `link_hosts` (acting) derive from, so the two cannot drift apart."""
    pack = current_pack(student)
    urls = (
        list(
            PackCandidate.objects.filter(pack_version=pack).values_list(
                "candidate__evidence__source_url", flat=True
            )
        )
        if pack is not None
        else []
    )
    # A portal-less application (dashboard spec §7) has no host to vouch for;
    # left in, its NULL would reach `str(host)` below as the string "None".
    forms = list(
        Application.objects.filter(student=student, portal_form__isnull=False).values_list(
            "id", "portal_form__portal_host", "portal_form__sender_domains"
        )
    )
    return urls, forms


def link_hosts(student: Membership) -> set[str]:
    """Every host a link in this student's mail may be opened on.

    ACTING, not reading (security finding 2026-09-26, vuln 1). A sender key is
    a registrable domain -- right for "may we read this", wrong for "may we
    send the student's browser there": a pack link to kth.smapply.io must not
    make attacker.smapply.io a link target, whoever mailed it. So these are
    the FULL hosts the pack's evidence URLs and the applications' portals
    name; a link host matches one exactly or is a subdomain of it. A pack
    link to www.tum.de therefore does not cover portal.tum.de -- only a named
    tum.de or an application on portal.tum.de does.

    Confirmed learned senders stay link targets, as before this split: they
    are registrable keys, but ones the student confirmed personally. An
    unconfirmed one never is. Same tenant transaction as `vouched_senders`.
    """
    urls, forms = _vouching_rows(student)
    named = [_host_of(url) for url in urls] + [str(host) for _id, host, _learned in forms]
    hosts: set[str] = set()
    for raw in named:
        host = _ascii_host(raw.strip().casefold().rstrip("."))
        # _key only validates here: "" for anything unusable or unregistrable,
        # so a bare suffix such as github.io never becomes a link target.
        # _is_platform_host excludes a platform's own name too, whatever _key
        # said about it (security finding 2026-09-26, follow-ups 1 and 2): a
        # pack named at the platform's bare apex, or at a path-tenanted host
        # like sites.google.com, must not become a link target either.
        if _key(host) and not _is_platform_host(host):
            hosts.add(host)
    hosts.update(
        LearnedSender.objects.filter(student=student, confirmed_at__isnull=False).values_list(
            "domain", flat=True
        )
    )
    return hosts


def allowed_senders(
    student: Membership, *, vouched: dict[str, UUID | None] | None = None
) -> dict[str, UUID | None]:
    """Every domain `vouched_senders` returns, plus every domain learned from
    mail to this student's own tags (sync.py). Read, but not trusted until
    confirmed -- unconfirmed_senders says which. `vouched` is a
    `vouched_senders` result the caller already holds (never mutated).
    """
    senders = dict(vouched_senders(student) if vouched is None else vouched)
    for domain in LearnedSender.objects.filter(student=student).values_list("domain", flat=True):
        senders.setdefault(domain, None)
    return senders


def unconfirmed_senders(
    student: Membership, *, vouched: dict[str, UUID | None] | None = None
) -> set[str]:
    """Learned sender domains this student has not confirmed. Never trusted.

    Excludes any domain the pack or an application already vouches for (Task 5
    fix round 1, finding 3): an unconfirmed `LearnedSender` row -- which a
    leaked tag can create for ANY domain, including a real university's -- must
    never downgrade a domain the platform already trusts on its own evidence.
    """
    if vouched is None:
        vouched = vouched_senders(student)
    return set(
        LearnedSender.objects.filter(student=student, confirmed_at__isnull=True)
        .exclude(domain__in=vouched)
        .values_list("domain", flat=True)
    )


def tracking_since(student: Membership) -> datetime | None:
    """Where a first sync starts: the moment the platform began tracking.

    The earlier of the recommendation run behind the current pack and this
    student's first application. Nothing a university sent before either
    existed can be about them, and the platform answers for the pack and the
    applications, not for the inbox. None when there is neither -- and then
    allowed_senders is empty too, so there is nothing to read.

    Read inside the caller's tenant transaction, like allowed_senders.
    """
    moments = []
    pack = current_pack(student)
    if pack is not None:
        moments.append(pack.run.created_at)
    first_application = (
        Application.objects.filter(student=student)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if first_application is not None:
        moments.append(first_application)
    return min(moments, default=None)


def matched_domain(sender: str, allowed: Iterable[str]) -> str:
    """The allowlist entry `sender` belongs to, or "".

    Takes any iterable of domains so a caller can pass `allowed_senders(...)`
    straight in -- iterating a dict yields its keys.
    """
    return host_in(sender_domain(sender), allowed)


def host_in(host: str, allowed: Iterable[str]) -> str:
    """The allowlist entry `host` belongs to, or "".

    Suffix matching anchored on a leading dot, the same shape as
    apps/research/domains.py::_matches. `tum.de.example` is a different
    organisation that merely contains the string, and a substring test would
    hand it this student's mail.

    Separate from `matched_domain` because two callers have a bare hostname,
    not an address: Task 11 checks a URL's host against this same list, and
    faking an address to reuse an address matcher is the kind of trick that
    reads fine today and wrong at 3am.
    """
    if not host:
        return ""
    for domain in allowed:
        if host == domain or host.endswith(f".{domain}"):
            return domain
    return ""
