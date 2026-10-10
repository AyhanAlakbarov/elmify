import functools
import hashlib
import operator
from decimal import Decimal
from typing import Any
from uuid import uuid4

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.funding.models import _HOLDER_VALUES
from apps.tenancy.models import TenantScopedModel


class DomainLease(models.Model):
    domain = models.CharField(max_length=253, primary_key=True)
    available_at = models.DateTimeField()


class ConsultantResearchTask(TenantScopedModel):
    class State(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    url = models.URLField(max_length=2048)
    reason = models.CharField(max_length=200)
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="research_task_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "url"),
                condition=Q(state="OPEN"),
                name="research_task_open_url_uniq",
            ),
        ]


class Organisation(models.Model):
    """A body that holds money, or a host we have decided is not one.

    Shared-catalog data: every tenant reads it, only `runtime_engine` writes
    it (RLS in the migration beside this file, repointed by funding/0049), and
    `runtime_web` holds no grant on it at all. Nothing about a person is ever
    stored here, and nothing about a *cell* either -- `country_code` is where
    this body is, and the countries it funds derive from its awards.

    Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
    section 6.1.
    """

    #: One taxonomy, not two. A funder's kind IS its holder type, so this is the
    #: judge's holder vocabulary (`funding_judge._HOLDERS`, hand-copied to
    #: `funding.models._HOLDER_VALUES` because research imports funding and not
    #: the reverse; `tests/funding/test_funding_holder.py` stops the two
    #: drifting). A register and a reader that each keep their own idea of what a
    #: body is will disagree, and nothing will say which is right.
    #: INFRASTRUCTURE is deliberately NOT a kind (decision log row 6): a mail or
    #: CDN host is a REJECTED row carrying that reason.
    KIND_CHOICES = tuple((value, value) for value in _HOLDER_VALUES)

    class Status(models.TextChoices):
        #: A national register, DEQAR or a curated national file vouched for it.
        REGISTERED = "REGISTERED"
        #: Search, inventory, a hub page or a pointer found it; fetched and
        #: classified; vouched by no register. Status governs spend and dedupe
        #: only. What a student sees is decided by the body's provenance
        #: verdict (ProvenanceVerdict; 2026-09-26 gate spec §4, §15), never by status.
        CANDIDATE = "CANDIDATE"
        REJECTED = "REJECTED"

    class RejectedReason(models.TextChoices):
        INFRASTRUCTURE = "INFRASTRUCTURE"
        NOT_A_FUNDER = "NOT_A_FUNDER"
        DOES_NOT_EXIST = "DOES_NOT_EXIST"
        UNREACHABLE = "UNREACHABLE"
        #: A platform operator answered KIND_OR_COUNTRY_UNSURE with "not an
        #: organisation" (the resolution queue, spec 11).
        NOT_AN_ORGANISATION = "NOT_AN_ORGANISATION"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: The display key. Not the only one it answers to -- see OrganisationDomain.
    primary_domain = models.CharField(max_length=253, unique=True)
    name = models.CharField(max_length=300)
    #: Every label a register or Wikidata supplies, in every language. The
    #: resolver scores the union of them; none of them is ever a lookup key.
    names = ArrayField(models.CharField(max_length=300), default=list, blank=True)
    kind = models.CharField(max_length=24, choices=KIND_CHOICES)
    #: Where this body is. NOT where it funds.
    country_code = models.CharField(max_length=2, blank=True, default="")
    official_website = models.URLField(max_length=2048, blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CANDIDATE)
    rejected_reason = models.CharField(
        max_length=24, choices=RejectedReason.choices, blank=True, default=""
    )
    #: Route tags (section 6.4), appended on every route that reaches this body
    #: again -- a list rather than a value so the per-route tally can say which
    #: route found what.
    found_via = ArrayField(models.CharField(max_length=120), default=list, blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_verified = models.DateTimeField(null=True, blank=True)
    #: A faculty under its institution. Both are kind INSTITUTION.
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )

    #: The classifier's verdict (spec 6.6). `funds_students` is the one fact the
    #: whole ladder exists to establish and no register carries reliably;
    #: `classified_by` names the rung that answered -- SUFFIX (a registry-verified
    #: second-level domain), FRONTIER (the OpenAI path), JEV (TypeSafe, when a key
    #: exists) -- so the gate can score each rung on its own. NULL `classified_at`
    #: means never classified OR abstained: both are "ask again", which is why
    #: an abstention writes the confidence and not the timestamp.
    funds_students = models.BooleanField(null=True, blank=True)
    classified_at = models.DateTimeField(null=True, blank=True)
    classified_by = models.CharField(max_length=16, blank=True, default="")
    classifier_confidence = models.FloatField(null=True, blank=True)

    # ponytail: latest state, not a history table. Upgrade path is an
    # OrganisationRead row per read, and the trigger is someone needing "what did
    # we read last month" (section 18) -- until then these three answer every
    # question the sweep asks.
    last_read_at = models.DateTimeField(null=True, blank=True)
    pages_read = models.PositiveIntegerField(default=0)
    pages_unreadable = models.PositiveIntegerField(default=0)

    #: Curated, sourced and expiring (section 9.3). All nullable: a body whose
    #: cadence nobody has established has no cadence, which is not the same as a
    #: monthly one.
    cadence = models.CharField(max_length=20, null=True, blank=True)
    cadence_open_month = models.PositiveSmallIntegerField(null=True, blank=True)
    cadence_deadline_month = models.PositiveSmallIntegerField(null=True, blank=True)
    cadence_source = models.URLField(max_length=2048, null=True, blank=True)
    cadence_verified_for_cycle = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=_HOLDER_VALUES), name="organisation_kind_valid"
            ),
            # A reason only ever states why a REJECTED row was rejected. Carried
            # by a CANDIDATE it means nothing, and the sweep's whole saving is
            # reading it to skip a host it already refused.
            models.CheckConstraint(
                condition=Q(status="REJECTED") | Q(rejected_reason=""),
                name="organisation_rejected_reason_shape",
            ),
        ]


class OrganisationDomain(models.Model):
    """One organisation, several domains -- the lookup key, plural.

    ROR returns `bwstiftung.de` for the foundation whose scholarship lives on
    `bw-stipendium.de` (measured 2026-09-19). Under a one-domain key those never
    join, so the award's holder and the register's row stay different objects.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, related_name="domains"
    )
    #: On the Public Suffix List (`apps.research.hosts.registrable_domain`).
    #: Unique across the register: a domain belongs to one body, so a collision
    #: is a merge question a human answers, never a second row.
    registrable_domain = models.CharField(max_length=253, unique=True)
    found_via = ArrayField(models.CharField(max_length=120), default=list, blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)


#: The pre-2026-09-14 `InstitutionIdentifier` vocabulary (that model was deleted
#: with the institution-safety screen; its scheme list survives in
#: `funding/migrations/0028`) plus the three this engine actually joins on.
_IDENTIFIER_SCHEMES = (
    "ROR",
    "WIKIDATA",
    "EACEA_PIC",
    "UKPRN",
    "CRICOS",
    "DLI",
    "NZQA",
    "IPEDS",
    "DEQARINST",
    "ETER",
    "WHED",
    #: A binding a platform operator made in the resolution queue, value
    #: "<register>:<external_key>". The (scheme, value) uniqueness below is what
    #: makes a person's answer the one answer for that register row.
    "HUMAN",
)


class OrganisationIdentifier(models.Model):
    """The join across sources, and the only evidence that merges two rows.

    A matching name is not evidence -- adjacent organisations share them
    (Carl-Zeiss-Stiftung vs ZEISS; Inönü Vakfi vs Inönü Üniversitesi).
    """

    SCHEMES = _IDENTIFIER_SCHEMES

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, related_name="identifiers"
    )
    scheme = models.CharField(
        max_length=20, choices=tuple((value, value) for value in _IDENTIFIER_SCHEMES)
    )
    value = models.CharField(max_length=200)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("scheme", "value"), name="organisation_identifier_scheme_value_uniq"
            ),
            models.CheckConstraint(
                condition=Q(scheme__in=_IDENTIFIER_SCHEMES),
                name="organisation_identifier_scheme_valid",
            ),
        ]


class ClosedList(models.Model):
    """One closed list, as a sourced row (spec 6.2's closed-list engine).

    A list is data, never code (spec 3, principle 7 and "country is data"):
    where it is published, who keeps it, what it covers, its reuse terms, and
    when a person last checked it. Loaded from docs/research/closed-lists.csv
    by `manage.py load_closed_lists`, never inserted by a migration. The rows
    it names are `RegisterEntry` rows with `register = slug`. That is a plain
    slug rather than a foreign key because `vgm_tr` rows predate this table,
    and a constraint added over them would need a registry row written in
    code.
    """

    class ReadPolicy(models.TextChoices):
        #: Each entry's `page_url` goes through the funding reader.
        FUNDING_READ = "FUNDING_READ"
        #: The body's homepage goes through the classifier (spec 6.6):
        #: institutions, whose awards are read by the per-HEI pass (6.4a).
        CLASSIFY = "CLASSIFY"
        #: The owner's read gate for professional bodies and banks (spec 6.3,
        #: 2026-09-23): the list is the denominator, never the reading queue.
        SIGNAL_ONLY = "SIGNAL_ONLY"
        #: The list routes other work and nothing here reads it (EACEA's
        #: projects; Wikidata's and ROR's enumerations).
        ENUMERATE_ONLY = "ENUMERATE_ONLY"

    class Terms(models.TextChoices):
        """Recorded, never a gate: owner decision 2026-09-27, "allow
        everything, as we are using external services". Any list, whatever
        its terms, may be read by code."""

        #: CC0, PDDL, Licence Ouverte, KOGL, the Europa reuse notice.
        OPEN = "OPEN"
        #: Published, but nobody has read the terms (VGM, spec 19).
        UNREAD = "UNREAD"
        #: Read, and they restrict reuse (HRK Hochschulkompass: personal use
        #: only without the Stiftung's permission).
        RESTRICTED = "RESTRICTED"
        #: We compiled the list from each body's own page.
        OWN_COMPILATION = "OWN_COMPILATION"

    slug = models.CharField(max_length=40, primary_key=True)
    title = models.CharField(max_length=200)
    #: "" for a list that belongs to no country -- the intergovernmental list.
    country_code = models.CharField(max_length=2, blank=True, default="")
    holder_kinds = ArrayField(models.CharField(max_length=24), default=list, blank=True)
    #: 1-4 = spec 6.2's register ladder; 0 = an enumerator that is no rung.
    rung = models.PositiveSmallIntegerField()
    source_url = models.URLField(max_length=2048)
    maintainer = models.CharField(max_length=200)
    carries_purpose = models.BooleanField()
    carries_website = models.BooleanField()
    reuse_terms = models.CharField(max_length=16, choices=Terms.choices)
    reuse_terms_url = models.URLField(max_length=2048, blank=True, default="")
    #: Whether `listed` is a completeness claim. False for Wikidata and ROR:
    #: a count from one register is not a denominator for another (spec 6.2).
    is_denominator = models.BooleanField()
    read_policy = models.CharField(max_length=16, choices=ReadPolicy.choices)
    #: The count the publisher prints, when it prints one. "100% enumerated"
    #: means entries == this number, where it exists.
    printed_size = models.PositiveIntegerField(null=True, blank=True)
    verified_on = models.DateField()
    #: When code last read this list into RegisterEntry rows (a register loader,
    #: spec §5.1). Null for a list only ever read by hand or never loaded; a
    #: body in a country whose register has no `loaded_at` is
    #: UNCONFIRMED(register_not_loaded), never absent from it.
    loaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(rung__lte=4), name="closed_list_rung_range"),
            models.CheckConstraint(
                condition=Q(holder_kinds__contained_by=list(_HOLDER_VALUES)),
                name="closed_list_holder_kinds_valid",
            ),
        ]


class ResolvedVia(models.TextChoices):
    """Which route bound the host (spec 6.5). HUMAN is written by the resolution
    queue (item 12), never by the resolver."""

    EMAIL = "EMAIL"
    #: The list itself carries the key: a curated list's website, a Wikidata
    #: enumeration's P856, EACEA's PIC/website. Written by the list's own
    #: writer, and undone by that writer when the list stops carrying it.
    LISTED = "LISTED"
    WIKIDATA = "WIKIDATA"
    #: Initials or full slug (tier 3): shipped without a title check, measured
    #: to save reachable-by-nobody true sites (tskgv.org.tr, ttgv.org.tr).
    SEARCH_SLUG = "SEARCH_SLUG"
    SEARCH_TITLE = "SEARCH_TITLE"
    DIFFBOT = "DIFFBOT"
    HUMAN = "HUMAN"


#: The routes that bound a host the LIST never carried -- the resolver's rungs
#: and a person. A re-read of the list must never undo one: the list's silence
#: is why the resolver ran, so it is no evidence against what the resolver found.
RESOLVER_ROUTES = frozenset({
    ResolvedVia.WIKIDATA, ResolvedVia.SEARCH_SLUG, ResolvedVia.SEARCH_TITLE,
    ResolvedVia.DIFFBOT, ResolvedVia.HUMAN,
})


def resolver_decided(resolution: str, resolved_via: str) -> bool:
    """Whether a row's state is the resolver's (or a person's) and not its list's.

    A re-read of a list that carries no key for the row keeps such a row as it
    is -- resolution, route and organisation: the list's silence is why the
    resolver ran, so it is no evidence against what the resolver found. That
    covers a route in RESOLVER_ROUTES and a CONFLICT, which on a row the list
    carries no key for can only be the resolver's IDENTIFIER_CONFLICT awaiting
    a person (item 12).
    """
    return resolved_via in RESOLVER_ROUTES or resolution in ("CONFLICT", "REFUSED")


def person_decided(resolution: str, resolved_via: str) -> bool:
    """Whether a person answered this row in the resolution queue (item 12):
    bound it (HUMAN) or refused it (REFUSED).

    Stronger than `resolver_decided`: a list re-read keeps such a row as it is
    even when the list now carries its own key for it -- the person answered
    the question the list's own data could not, and a re-read that undid it
    would re-file the same question (the gate's third criterion)."""
    return resolved_via == ResolvedVia.HUMAN or resolution == "REFUSED"


class UnresolvedReason(models.TextChoices):
    """Why a name stayed unresolved -- the build plan's table. "" = never tried.

    IDENTIFIER_CONFLICT is written beside `Resolution.CONFLICT`, not
    UNRESOLVED: item 7 already reads CONFLICT as "a Wikidata id already on a
    different body", and the resolution queue (item 12) takes it from there.
    """

    #: "Token" is a word of the name, not a credential (Bandit reads the name).
    ONE_TOKEN_NAME = "ONE_TOKEN_NAME"  # nosec B105
    NO_CANDIDATE = "NO_CANDIDATE"
    DIRECTORY = "DIRECTORY"
    TITLE_MISMATCH = "TITLE_MISMATCH"
    FETCH_FAILED = "FETCH_FAILED"
    IDENTIFIER_CONFLICT = "IDENTIFIER_CONFLICT"


class RegisterEntry(models.Model):
    """One row of a closed list, as the list publishes it (spec 6.2).

    The denominator. `count(register=X)` is the list's size and the count of
    DISTINCT organisations bound to a row is `bodies known` -- two entries can
    bind to the same body (a branch office, a second e-mail), so the coverage
    line is arithmetic over this table and never a number someone typed. Shared
    catalog, written by `runtime_engine` only (RLS in migration 0007, repointed
    from `catalog_ingestion` by funding/0049; `runtime_web` holds no grant). What a
    register prints about a body is stored; **its e-mail address is not** --
    only the registrable domain derived from it (`contact_domain`), which is
    all rung 0 needs and the only part that is not a mailbox.
    """

    class Resolution(models.TextChoices):
        #: Rung 0 (own-domain e-mail) or the resolver bound a host.
        RESOLVED = "RESOLVED"
        #: Free-mail or no e-mail: the resolver's queue (spec 6.5), counted in the
        #: denominator and not in `bodies known`.
        UNRESOLVED = "UNRESOLVED"
        #: Two keys named two different bodies (an EU-PIC held by one
        #: organisation, a website held by another; a Wikidata id already on a
        #: different body). Bound to neither: a person decides (spec 11, the
        #: resolution queue of build item 12), and guessing either way silently
        #: joins or splits a body.
        CONFLICT = "CONFLICT"
        #: A platform operator answered the row's SITE_UNKNOWN question with
        #: "not a funder" or "does not exist" (`refused_reason`). Bound to
        #: nothing, and never asked again: every re-read keeps it
        #: (`person_decided`).
        REFUSED = "REFUSED"

    class RefusedReason(models.TextChoices):
        NOT_A_FUNDER = "NOT_A_FUNDER"
        DOES_NOT_EXIST = "DOES_NOT_EXIST"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: Which list: "vgm_tr" today; one slug per register row of spec 6.2.
    register = models.CharField(max_length=40)
    #: The list's own identifier for the row (VGM: the e-tebligat id), else the name.
    external_key = models.CharField(max_length=120)
    name = models.CharField(max_length=300)
    city = models.CharField(max_length=120, blank=True, default="")
    #: `email_domain()` of the row's address, "" when free-mail or absent.
    contact_domain = models.CharField(max_length=253, blank=True, default="")
    #: The names store (spec 6.1/6.5 rule 4): the register's own name first, then
    #: every variant Wikidata supplies once the name matched one item. Scored as a
    #: union; never a lookup key. Carried onto Organisation.names on resolution.
    names = ArrayField(models.CharField(max_length=300), default=list, blank=True)
    #: Set exactly when `resolution` is RESOLVED (register_entry_resolution_shape).
    resolved_via = models.CharField(
        max_length=12, choices=ResolvedVia.choices, blank=True, default=""
    )
    #: The resolver's last verdict on an unbound row; never beside RESOLVED.
    unresolved_reason = models.CharField(
        max_length=20, choices=UnresolvedReason.choices, blank=True, default=""
    )
    resolution_attempted_at = models.DateTimeField(null=True, blank=True)
    #: Diffbot is 25 credits an entity against 400 a month; this column is both
    #: the monthly meter and the "never ask twice in 90 days" rule.
    diffbot_asked_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(max_length=12, choices=Resolution.choices)
    #: Set exactly when `resolution` is REFUSED (register_entry_resolution_shape).
    refused_reason = models.CharField(
        max_length=16, choices=RefusedReason.choices, blank=True, default=""
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="register_entries",
    )
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField()
    #: What the list asserts about the row. `kind` is "" when the list asserts
    #: no kind (Wikidata's class is a claim and does go here; an EACEA project
    #: is not a body and has none).
    country_code = models.CharField(max_length=2, blank=True, default="")
    kind = models.CharField(max_length=24, blank=True, default="")
    #: The scheme page on the body's own site, for a FUNDING_READ list. The
    #: reader reads this; the list itself is never provenance (spec 3.2).
    page_url = models.URLField(max_length=2048, blank=True, default="")
    #: Cell tags (spec 5): ISO 3166-1 alpha-2, an `apps.funding.regions.REGIONS`
    #: key, or ANY. A tag selects a pool and never decides eligibility -- the
    #: reader's conditions do -- so a tag may be wider than the truth, never
    #: narrower. Expanded at read time, never copied, so a region's membership
    #: is one edit.
    home_cells = ArrayField(models.CharField(max_length=24), default=list, blank=True)
    host_cells = ArrayField(models.CharField(max_length=24), default=list, blank=True)
    #: The period the list says this row is live -- an EMJM project's funded
    #: period. Null when the list states none.
    listed_from = models.DateField(null=True, blank=True)
    listed_until = models.DateField(null=True, blank=True)
    #: `read_state.ReadState`, derived and stored by `record_read_states`; ""
    #: until the first coverage run. Never typed by a person.
    read_state = models.CharField(max_length=20, blank=True, default="")
    read_state_detail = models.CharField(max_length=120, blank=True, default="")
    read_state_at = models.DateTimeField(null=True, blank=True)
    #: The registrable domain of the website the list printed for this row --
    #: the domain `record_list` bound it by, and a verdict's `bound_domain`.
    website_domain = models.CharField(max_length=253, blank=True, default="")
    #: The website exactly as the list printed it (www or not): what origin
    #: verification fetches first. Its registrable domain is `website_domain`.
    website_url = models.URLField(max_length=2048, blank=True, default="")
    #: A reviewed row's website counts as evidence only once its origin was
    #: fetched and named the institution (spec §13.8, `verify_list_origins`).
    #: Equal to `website_domain` when verified; a changed website voids it.
    origin_verified_domain = models.CharField(max_length=253, blank=True, default="")
    origin_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("register", "external_key"), name="register_entry_key_uniq"
            ),
            models.CheckConstraint(
                condition=Q(kind="") | Q(kind__in=_HOLDER_VALUES),
                name="register_entry_kind_valid",
            ),
            # A bound row says how it was bound and carries no failure; an
            # unbound one (UNRESOLVED, or CONFLICT awaiting a person) carries no
            # route; a REFUSED one carries a person's reason and nothing else.
            # So every writer that sets `resolution` sets `resolved_via` in the
            # same write, or this fires.
            models.CheckConstraint(
                condition=(
                    (
                        Q(resolution="RESOLVED", unresolved_reason="", refused_reason="")
                        & ~Q(resolved_via="")
                    )
                    | Q(resolution__in=("UNRESOLVED", "CONFLICT"), resolved_via="",
                        refused_reason="")
                    | Q(resolution="REFUSED", resolved_via="", unresolved_reason="",
                        refused_reason__in=("NOT_A_FUNDER", "DOES_NOT_EXIST"))
                ),
                name="register_entry_resolution_shape",
            ),
        ]
        indexes = [models.Index(fields=("register", "resolution"), name="register_entry_res_idx")]


#: The two dispositions that bind no organisation.
_UNBOUND_DISPOSITIONS = ("CONFLICT", "NO_KEY")


def refreshed_resolution(
    stored: tuple[str, str, str] | None, name: str, domain: str, via: str
) -> tuple[dict[str, object], bool]:
    """A list/register row's evidence-precedence rule (shared by every
    per-register writer, e.g. `closed_lists.record_list`, `vgm.record_vgm`):
    a person's own answer (item 12) is kept whole; else the list's own
    evidence -- a website, an own-domain e-mail -- outranks whatever the
    resolver found; else the resolver's earlier binding stands; else, for a
    row nothing above accounts for (new, renamed, or never resolved), the
    binding is withdrawn.

    Returns the fields to merge onto the row's `defaults`, and whether it was
    `kept` -- callers use `kept` (with their own `renamed` check) to decide
    whether to also reset `names`/`unresolved_reason` for a rename.
    """
    renamed = stored is not None and stored[0] != name
    if stored is not None and person_decided(stored[1], stored[2]):
        return {}, True
    if domain:
        return {
            "resolution": RegisterEntry.Resolution.RESOLVED,
            "resolved_via": via,
            "unresolved_reason": "",
        }, False
    if stored is None or renamed or not resolver_decided(stored[1], stored[2]):
        return {
            "resolution": RegisterEntry.Resolution.UNRESOLVED,
            "resolved_via": "",
            "organisation": None,
        }, False
    return {}, False


class RegisterEntryPartner(models.Model):
    """A body a list names as a partner of one of its rows -- an EMJM
    consortium member (spec 6.2's EACEA row, the 2026-09-14 partner design).

    Stores what the list printed (name, identifier, domain) beside what we
    bound it to, so every one of the 09-14 design's dispositions is a count
    over this table rather than a log line. Shared catalog; an organisation's
    PIC and website are not a person.
    """

    class Disposition(models.TextChoices):
        #: EU-PIC and website both reached the same body we already held.
        BOUND_BOTH = "BOUND_BOTH"
        #: The PIC reached a body; the website was absent or new to us, and is
        #: now attached to that body.
        BOUND_PIC = "BOUND_PIC"
        #: The website reached a body; the PIC is now attached to it.
        BOUND_DOMAIN = "BOUND_DOMAIN"
        #: Neither key was held; a new CANDIDATE was keyed on the website.
        NEW = "NEW"
        #: The PIC reached one body and the website another (EDEX, 09-14 4.3).
        CONFLICT = "CONFLICT"
        #: No website and a PIC no body carries. Silence, counted.
        NO_KEY = "NO_KEY"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    entry = models.ForeignKey(RegisterEntry, on_delete=models.PROTECT, related_name="partners")
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, null=True, blank=True,
        related_name="listed_partnerships",
    )
    #: As the list prints it -- EACEA: COORDINATOR or PARTNER.
    role = models.CharField(max_length=12)
    listed_name = models.CharField(max_length=300)
    #: EACEA: the EU-PIC.
    listed_identifier = models.CharField(max_length=120)
    listed_domain = models.CharField(max_length=253, blank=True, default="")
    country_code = models.CharField(max_length=2, blank=True, default="")
    disposition = models.CharField(max_length=14, choices=Disposition.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("entry", "listed_identifier"), name="register_partner_uniq"
            ),
            models.CheckConstraint(
                condition=(
                    Q(disposition__in=_UNBOUND_DISPOSITIONS, organisation__isnull=True)
                    | (
                        ~Q(disposition__in=_UNBOUND_DISPOSITIONS)
                        & Q(organisation__isnull=False)
                    )
                ),
                name="register_partner_bound_shape",
            ),
        ]


class HostProfile(models.Model):
    """What worked on this host last time, so the ladder need not rediscover it.

    Shared catalog on purpose (spec §5, §11): which rung reads a ministry's
    website is the same fact for every tenant, and it describes the web rather
    than a person.

    Only EXPENSIVE rungs are remembered. A success at rung 1 or 2 resets
    start_rung to 1, so the memory can only ever save money, never entrench a
    cost -- and a host that got easier is found by the re-probe below rather
    than paying rung-4 prices forever.

    Keyed on the full lowercased hostname (``urlsplit(url).hostname``), NOT on
    ``apps.research.hosts.registrable_domain``. Everything remembered here is a
    property of one SERVER -- its robots.txt, its TLS, its WAF, whether it needs
    a render -- and ai.study.fau.eu needing one says nothing about www.fau.eu.
    The registrable domain answers "is this the same organisation", which is the
    register's question and cross-sweep dedupe's, never this table's.
    """

    host = models.CharField(max_length=253, primary_key=True)
    start_rung = models.PositiveSmallIntegerField(default=1)
    geo_code = models.CharField(max_length=2, blank=True, default="")
    languages = models.JSONField(default=list, blank=True)
    wait_selector = models.CharField(max_length=200, blank=True, default="")
    custom_wait_ms = models.PositiveIntegerField(default=0)
    #: A per-host OVERRIDE, hence 0 rather than a copy of the setting's number:
    #: both providers read `profile.timeout_ms or settings.FETCH_DEFAULT_TIMEOUT_MS`,
    #: so a non-zero default makes the setting unreachable for every host that
    #: has a profile row -- i.e. every host after its first fetch -- and the
    #: operator's env override silently does nothing.
    timeout_ms = models.PositiveIntegerField(default=0)
    last_success_rung = models.PositiveSmallIntegerField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_probe_at = models.DateTimeField(null=True, blank=True)
    #: Set on `fetch_page`'s POST-ARCHIVE final BLOCKED refusal only -- an
    #: in-ladder BLOCKED verdict is not terminal (`BLOCKED` is not in
    #: `_TERMINAL`, fetch/__init__.py) and continues the walk, so this is
    #: written after `FETCH_MAX_RETRIES` RETRY_SCHEDULED rounds *and* an
    #: archive miss, not on every block. `consecutive_blocks` therefore counts
    #: fully-exhausted URLs, roughly a quarter of the rate "set by a BLOCKED
    #: outcome" alone would suggest, and the +6h-doubling schedule advances
    #: about 4x slower in wall-clock time than that reading implies.
    #: +6h, doubling per consecutive block, capped at 7 days. Read (and
    #: honoured) by `manage.py retry_due_fetches`: a due retry inside this
    #: window is rescheduled, not spent.
    blocked_until = models.DateTimeField(null=True, blank=True)
    consecutive_blocks = models.PositiveSmallIntegerField(default=0)
    #: A platform operator said this host is closed (HOST_UNREACHABLE, the
    #: resolution queue). A dead host is then a known answer, not a question to
    #: pay a vendor to ask again.
    retired_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # The docstring above promises a lowercased key; `remember()`
            # (fetch/__init__.py) is the one writer and lowercases before
            # get_or_create, but this closes the door for any future writer --
            # Example.test and example.test must not become two rows.
            models.CheckConstraint(
                condition=Q(host=Lower("host")), name="hostprofile_host_lowercase"
            ),
        ]


class MovedPage(models.Model):
    """A page a platform operator found at a new address (HOST_UNREACHABLE,
    "paste"), after the fetch ladder opened the new one.

    Shared catalog: which page replaced which is the same fact for every
    tenant, and not a person. `from_url` and `to_url` are both
    `discovery.canonicalize_url` output, so a lookup by a canonical URL finds
    it. Written only by the resolution applier (`resolution/apply.py`), as
    `runtime_engine` or the owner. RLS: research/0015_moved_page_rls.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    from_url = models.URLField(max_length=2048, unique=True)
    to_url = models.URLField(max_length=2048)
    created_at = models.DateTimeField(auto_now_add=True)


class FetchAttempt(models.Model):
    """One vendor call, and what it cost.

    This said the id doubles as Firecrawl's `x-request-id`, so a retry after a
    client-side timeout is answered 409 rather than charged twice (spec §9.3).
    **It does not.** `fetch/__init__.py::_call` sends a fresh `uuid4()` per call
    and the row is created afterwards, so nothing links the two -- and a false
    claim about money is worse than no claim. Making it true means minting the
    id before the call and threading it through `_call`; until someone does,
    assume a timed-out retry is billed twice.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    url = models.URLField(max_length=2048)
    host = models.CharField(max_length=253)
    purpose = models.CharField(max_length=10, default="read")
    rung = models.PositiveSmallIntegerField()
    vendor = models.CharField(max_length=20)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True, default="")
    byte_size = models.PositiveBigIntegerField(default=0)
    credits = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    outcome = models.CharField(max_length=20)
    reason = models.CharField(max_length=300, blank=True, default="")
    final_url = models.URLField(max_length=2048, blank=True, default="")
    change_status = models.CharField(max_length=10, blank=True, default="")
    captured_at = models.CharField(max_length=32, blank=True, default="")
    page_count = models.PositiveIntegerField(null=True, blank=True)
    total_pages = models.PositiveIntegerField(null=True, blank=True)
    retry_after = models.DateTimeField(null=True, blank=True)
    attempt_no = models.PositiveSmallIntegerField(default=1)
    sweep_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Named for what reads them, in the repo's own short form
        # (deletion_lock_idx, fact_scope_idx): Django caps an index name at 30
        # characters, and "research_fetchattempt_retry_idx" is 31.
        indexes = [
            #: The latest attempt for a URL -- the unchanged-page short-circuit
            #: and every "what happened to this page" question.
            models.Index(fields=("url", "-created_at"), name="fetch_attempt_url_idx"),
            #: The retry sweep scans (outcome, retry_after); without this it is a
            #: sequential scan over every fetch ever made.
            models.Index(fields=("outcome", "retry_after"), name="fetch_attempt_retry_idx"),
        ]


class SiteJobRecord(models.Model):
    """What the funnel searched for one programme, and how it ended.

    Shared catalog, not tenant data: which pages a university publishes about
    a programme is the same fact for every agency, and no student data is ever
    in one of these rows.

    **A ledger, not a queue** (owner decision 2026-09-23). There is no state,
    no assignee and no resolution, because nothing waits on it. A `state`
    column here is how a person grows back into the pipeline.

    `program_id` is a plain UUID, not a ForeignKey. `research` has no
    migration-graph edge to `funding` today, and adding one between two apps
    that both carry hand-written RLS SQL is the merge hazard this repo has
    already paid for once (CLAUDE.md, the 2026-09-15 renumber). Programme rows
    are never deleted, so the integrity an FK would add is integrity nothing
    threatens.
    """

    class Outcome(models.TextChoices):
        FOUND = "found"
        NO_CV_REQUIRED = "no_cv_required"
        BLOCKED = "blocked"
        NOT_FOUND = "not_found"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    program_id = models.UUIDField(db_index=True)
    source_url = models.URLField(max_length=2048)
    admissions_cycle = models.CharField(max_length=50)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    #: Which funnel stage it stopped at (1-5). With `outcome`, this is the
    #: corpus's per-stage score: a stage that never stops a job it should have
    #: is a stage that can be removed.
    stopped_at_stage = models.PositiveSmallIntegerField()
    #: {"map": 76, "crawl": 25, "guided_map": 50, "navigator": 4} -- the
    #: EVIDENCE half of spec 7.6's `not found`. Counts, not URL lists, except
    #: for `leads`: a full crawl listing per programme is a table that grows
    #: with the catalog and answers a question the FetchAttempt trail answers
    #: better.
    searched = models.JSONField(default=dict)
    #: The URLs that were actually read, so a person reading this row can open
    #: what the engine opened.
    leads = models.JSONField(default=list)
    credits = models.JSONField(default=dict)
    reason = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=("program_id", "admissions_cycle"))]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stopped_at_stage__gte=1, stopped_at_stage__lte=5),
                name="site_job_stage_in_range",
            )
        ]


class DecisionRecord(models.Model):
    """One answer from the decision layer, with everything needed to re-judge it.

    Three jobs, and the third is why it is a table rather than a log line:

    1. **The calibration audit** (spec §11.4) reads confidence against outcome
       monthly. Drift or a steered page shows up as a calibration break, which
       is measurable, rather than as a wrong CV, which is not. It reads
       `refused=False` rows only.
    2. **`rederive_rules`** (spec §6.5) re-asks the slot questions over stored
       sentences when the grammar grows, without refetching a page.
    3. **The cache.** The same `(state_digest, question_digest, model, question_id)`
       is answered from here. A faculty-wide requirements page linked by thirty
       programmes is decided once, not thirty times -- and a state the provider
       refused is refused from here, never asked again (addendum §5.1).

    Shared catalog: no student data is ever in a state (spec §9a), and which
    sentence a page states is the same fact for every agency. Written and read
    by `runtime_engine` only; `runtime_web` holds no grant (research/0022).
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: sha256 of the canonical JSON of the state the question was asked against.
    state_digest = models.CharField(max_length=64)
    #: sha256 of the canonical JSON of the WHOLE question map, so a reworded
    #: question never reads a stale answer out of the cache.
    question_digest = models.CharField(max_length=64)
    decision = models.CharField(max_length=40)
    question_id = models.CharField(max_length=120)
    #: The chosen option, or "true"/"false" for a Noul; "" on a refusal. Always a
    #: string so one column holds both and a query never has to know which.
    value = models.CharField(max_length=200)
    confidence = models.FloatField()
    probabilities = models.JSONField(default=dict)
    #: The id we pinned and asked for -- the cache key (`typesafe/jev-1.13`).
    model = models.CharField(max_length=60)
    #: The snapshot the provider says answered (`typesafe/jev-1.13-20260917`).
    #: The pin can move under an alias-like id; this is where it shows.
    served_model = models.CharField(max_length=80, blank=True, default="")
    provider = models.CharField(max_length=30)
    language = models.CharField(max_length=12, blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    #: The provider declined this state. Kept so it is never asked again under
    #: this model and question set; excluded from calibration.
    refused = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("state_digest", "question_digest", "model", "question_id"),
                name="decision_record_cache_key_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=("decision", "created_at")),
            models.Index(fields=("created_at",)),
        ]


_RECOGNISED_REASONS = (
    "register", "curated_list", "funder_list", "vouched_by_link", "government_zone",
)
_UNCONFIRMED_REASONS = (
    "not_evaluated", "register_not_loaded", "absent_from_register", "no_domain_binding",
    "unmapped_list_row", "domain_registered_after_listing", "veto_conflict",
    "evidence_off_domain", "lookup_failed", "no_holder_body", "vouch_link_missing",
    "no_register",
)
_BLOCKED_REASONS = (
    "mill_list", "accreditation_mill", "fee_to_release_award", "degree_for_payment",
)


class ProvenanceVerdict(models.Model):
    """Whether a body, on one of its domains, may reach a student (provenance gate spec §4, §8).

    Shared catalogue: every tenant reads it, only `runtime_engine` writes it
    (research/0019's RLS block), `runtime_web` holds no grant. No row means
    `not_evaluated` -- the table starts empty and the absence is read that way
    everywhere (spec §7.7). Written only by `apps.research.provenance.record_verdict`.
    """

    class Verdict(models.TextChoices):
        RECOGNISED = "RECOGNISED"
        UNCONFIRMED = "UNCONFIRMED"
        BLOCKED = "BLOCKED"

    class Reason(models.TextChoices):
        REGISTER = "register"
        CURATED_LIST = "curated_list"
        FUNDER_LIST = "funder_list"
        VOUCHED_BY_LINK = "vouched_by_link"
        GOVERNMENT_ZONE = "government_zone"
        NOT_EVALUATED = "not_evaluated"
        REGISTER_NOT_LOADED = "register_not_loaded"
        ABSENT_FROM_REGISTER = "absent_from_register"
        NO_DOMAIN_BINDING = "no_domain_binding"
        UNMAPPED_LIST_ROW = "unmapped_list_row"
        DOMAIN_REGISTERED_AFTER_LISTING = "domain_registered_after_listing"
        VETO_CONFLICT = "veto_conflict"
        EVIDENCE_OFF_DOMAIN = "evidence_off_domain"
        LOOKUP_FAILED = "lookup_failed"
        NO_HOLDER_BODY = "no_holder_body"
        VOUCH_LINK_MISSING = "vouch_link_missing"
        #: No register is shipped for the body's country, or it has no country
        #: at all (2026-09-28). Not a waiting reason: nothing is about to load.
        NO_REGISTER = "no_register"
        MILL_LIST = "mill_list"
        ACCREDITATION_MILL = "accreditation_mill"
        FEE_TO_RELEASE_AWARD = "fee_to_release_award"
        DEGREE_FOR_PAYMENT = "degree_for_payment"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: A verdict is for one (body, domain) pair, never for a body: a register
    #: row recognises the body of its own website, so a body's domains A and B
    #: can stand differently (2026-09-28 ruling). Programmes join on their
    #: `evidence_domain`, HOLDER awards on their `holder_domain`.
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="provenance_verdicts"
    )
    #: The registrable domain judged, and the one the recognising evidence binds.
    domain = models.CharField(max_length=253, unique=True)
    verdict = models.CharField(max_length=12, choices=Verdict.choices)
    reason_code = models.CharField(max_length=32, choices=Reason.choices)
    #: source_slug, source_url, list_date, identifier {scheme, value}, vouch_url,
    #: admitted_via, rdap {status, date, detail}, content_checks, content_checks_detail,
    #: mill, content_hits.
    evidence = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField()
    #: Null for BLOCKED, which is never retried.
    next_check_at = models.DateTimeField(null=True, blank=True)
    #: When OUR records first saw this domain RECOGNISED -- the only date a
    #: registration date can be compared with (spec §5.5). Kept through
    #: re-checks and downgrades of the same row.
    first_bound_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("next_check_at",), name="provenance_due_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(verdict="RECOGNISED", reason_code__in=_RECOGNISED_REASONS)
                    | Q(verdict="UNCONFIRMED", reason_code__in=_UNCONFIRMED_REASONS)
                    | Q(verdict="BLOCKED", reason_code__in=_BLOCKED_REASONS)
                ),
                name="provenance_verdict_reason_shape",
            ),
        ]


class ProvenanceVerdictChange(models.Model):
    """History of verdicts (spec §8): drives pack notes and shows a body whose
    verdict keeps flipping. Append-only by convention -- record_verdict never
    updates or deletes a row, it only ever creates one."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="provenance_changes"
    )
    domain = models.CharField(max_length=253)
    #: "" for the first verdict a body ever got.
    old = models.CharField(max_length=12, blank=True, default="")
    new = models.CharField(max_length=12, choices=ProvenanceVerdict.Verdict.choices)
    reason_code = models.CharField(max_length=32, choices=ProvenanceVerdict.Reason.choices)
    at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=("organisation", "-at"), name="provenance_change_idx")]


#: The families a sweep pass may run for (spec 6.3). Every other family has a
#: closed list or a register and no open-web sweep; `angles.PASS_SHAPES` holds
#: the shape of each and a test pins the two to one set.
SWEEP_FAMILIES = (
    "PRIVATE_FOUNDATION",
    "INDUSTRIAL_SPONSORSHIP",
    "AFFINITY_OR_DIASPORA",
    "GOVERNMENT_SCHOLARSHIP",
)

#: Decision 37: a diaspora pass is keyed (host country, home language), and
#: nothing else has a home language.
_HOME_LANGUAGE_IFF_DIASPORA = (Q(family="AFFINITY_OR_DIASPORA") & ~Q(home_language="")) | (
    ~Q(family="AFFINITY_OR_DIASPORA") & Q(home_language="")
)

#: The organisation angles of spec 6.3 -- one target page each. The canonical
#: order; a pass shuffles each batch from it, seeded by the run (harness._batches).
ANGLE_KINDS = ("APPLICATION", "ELIGIBILITY", "SEASON", "ABOUT", "FAQ", "PDF_CALL")


class SweepAngle(models.Model):
    """One page-voiced query, stored as data (spec 6.3: "its output is data,
    not a prompt").

    Keyed `(country, family, home_language, language, angle, sample)` and
    versioned: a regeneration writes a new version and the old rows stay, so a
    past run is reproducible and an operator can read exactly what was asked.
    For a diaspora pass `country_code` is the HOST country and `home_language`
    the pass's key (decision 37); `language` is the home language or English.
    Shared catalog: never a person -- the generator's input has no student
    field.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    country_code = models.CharField(max_length=2)
    family = models.CharField(max_length=40)
    #: A diaspora pass's home language; "" for every other family.
    home_language = models.CharField(max_length=12, blank=True, default="")
    language = models.CharField(max_length=12)
    angle = models.CharField(max_length=16)
    #: Which phrasing of this angle kind (0-based). Exa: "genuinely different
    #: angles, not synonym swaps"; each sample is its own query.
    sample = models.PositiveSmallIntegerField()
    version = models.PositiveIntegerField()
    #: The admissions cycle the angle's time words name ("2026-2027"). A new
    #: cycle is a regeneration, never an edit (lever 6).
    cycle = models.CharField(max_length=9)
    #: The sentence, as the target page writes itself -- sent to Exa.
    query = models.CharField(max_length=400)
    #: The same angle as terms with operators -- sent to Brave.
    brave_terms = models.CharField(max_length=400, blank=True, default="")
    #: The model id that wrote it, or "STEERING" for the one hand-written
    #: interim angle.
    written_by = models.CharField(max_length=60)
    written_at = models.DateTimeField(auto_now_add=True)
    #: Set by `tally.retire_dead_angles`, with the tally that justified it.
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "country_code", "family", "home_language", "language", "angle", "sample",
                    "version",
                ),
                name="sweep_angle_key_uniq",
            ),
            models.CheckConstraint(
                condition=Q(family__in=SWEEP_FAMILIES), name="sweep_angle_family_valid"
            ),
            models.CheckConstraint(
                condition=Q(angle__in=ANGLE_KINDS), name="sweep_angle_kind_valid"
            ),
            models.CheckConstraint(
                condition=_HOME_LANGUAGE_IFF_DIASPORA, name="sweep_angle_home_language_iff_diaspora"
            ),
        ]
        indexes = [
            models.Index(fields=("country_code", "family", "home_language", "language", "version"))
        ]


class SweepRun(models.Model):
    """One pass over one `(host country, family)` -- the curve it produced and
    why it stopped (spec 6.7: "swept to N queries, plateau R per batch at
    precision P, spend S"). A row with `finished_at` NULL did not finish; it
    is an error, never a partial result."""

    class StopReason(models.TextChoices):
        #: No new verified host for three consecutive batches.
        PLATEAU = "PLATEAU"
        #: Cost per new verified award above what the option is worth.
        ECONOMIC = "ECONOMIC"
        #: Every active angle was asked before either rule fired -- the angle
        #: set was too small to find the plateau, which is a finding.
        EXHAUSTED = "EXHAUSTED"
        BUDGET = "BUDGET"
        #: The classifier's per-run limit fired, so new hosts could no longer
        #: be verified and the plateau rule could no longer be read.
        CLASSIFIER_LIMIT = "CLASSIFIER_LIMIT"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    country_code = models.CharField(max_length=2)
    family = models.CharField(max_length=40)
    #: A diaspora pass's home language; "" for every other family.
    home_language = models.CharField(max_length=12, blank=True, default="")
    languages = ArrayField(models.CharField(max_length=12), default=list)
    #: The register-ladder rung the pass ran after (spec 6.2), and the
    #: register it was diffed against; "" for rung 4, search only.
    rung = models.PositiveSmallIntegerField()
    register = models.CharField(max_length=40, blank=True, default="")
    cycle = models.CharField(max_length=9)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    stop_reason = models.CharField(
        max_length=16, choices=StopReason.choices, blank=True, default=""
    )
    batches = models.PositiveIntegerField(default=0)
    search_usd = models.FloatField(default=0.0)
    fetch_usd = models.FloatField(default=0.0)
    #: Distinct register-bound bodies the search returned -- the recapture
    #: count against `register` (spec 15).
    recaptured = models.PositiveIntegerField(default=0)
    #: Providers dropped mid-pass by the decay rule, in drop order.
    dropped_providers = ArrayField(models.CharField(max_length=40), default=list, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(rung__gte=1, rung__lte=4), name="sweep_run_rung_valid"
            ),
            models.CheckConstraint(
                condition=Q(rung=4) | ~Q(register=""), name="sweep_run_register_below_rung_4"
            ),
            models.CheckConstraint(
                condition=_HOME_LANGUAGE_IFF_DIASPORA, name="sweep_run_home_language_iff_diaspora"
            ),
        ]


class SweepQuery(models.Model):
    """One angle asked of one provider in one batch -- the per-angle and
    per-provider denominator."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.ForeignKey(SweepRun, on_delete=models.PROTECT, related_name="queries")
    batch_number = models.PositiveIntegerField()
    angle = models.ForeignKey(SweepAngle, on_delete=models.PROTECT, related_name="queries")
    provider = models.CharField(max_length=40)
    seen = models.PositiveIntegerField(default=0)
    denied = models.PositiveIntegerField(default=0)
    novel = models.PositiveIntegerField(default=0)
    cost_usd = models.FloatField(default=0.0)

    class Meta:
        indexes = [models.Index(fields=("run", "batch_number"))]


class SweepDiscovery(models.Model):
    """A registrable domain no route held before this run, owned by the query
    that returned it first. The provider tally counts these once per provider
    in `returned_by`, grouped by the host's CLASSIFIED family (spec 6.7) --
    read live from the Organisation row, so a host classified after the run
    still lands in the right family."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.ForeignKey(SweepRun, on_delete=models.PROTECT, related_name="discoveries")
    query = models.ForeignKey(SweepQuery, on_delete=models.PROTECT, related_name="discoveries")
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, related_name="sweep_discoveries"
    )
    #: Every provider that returned the host in this run, the owning query's
    #: first. Credit reads this, not `query.provider`: who asked first is
    #: position, not yield.
    returned_by = ArrayField(models.CharField(max_length=40), default=list)
    #: Whether the host counted as a new verified host FOR THIS PASS when the
    #: stop rule read it -- funds students, classified, and of the pass's
    #: family. Kept because the stop decision must be reproducible from the
    #: rows even after a later reclassification moves the live tally.
    verified_in_pass = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("run", "organisation"), name="sweep_discovery_once")
        ]


class PlatformAgency(models.Model):
    """The one agency that is the platform itself (spec 2026-09-22 section 11).

    Its PLATFORM_ADMIN members are the only people who may see or answer the
    resolution queue, and research_resolutionitem's policies read this table.
    At most one row: `singleton` is unique and CHECKed True, so a second row is
    refused by the database, not by the command.

    A research-side table rather than a column on `tenancy.Agency`, for its
    grant surface: both runtime roles keep SELECT (the queue's policy subquery
    runs with the caller's privileges, so the web role must read it) and hold
    no INSERT, UPDATE or DELETE -- research/0013 revokes them. So neither
    runtime role can move the platform; only the owner can, through
    `manage.py set_platform_agency` run as the migration role. No RLS: it
    holds one agency id and no person.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    singleton = models.BooleanField(default=True, unique=True, editable=False)
    agency = models.OneToOneField(
        "tenancy.Agency", on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(singleton=True), name="platform_agency_singleton")
        ]


#: Every kind's subject is keyed by one prefix. The prefix IS the dedupe rule of
#: spec 11: a register row for a body with no known site, the canonical_key for
#: awards, the full hostname for reachability, the primary domain for an
#: organisation. One question per subject, whichever tenants' runs met it.
_RESOLUTION_PREFIXES = {
    "SITE_UNKNOWN": "register:",
    "AWARD_DISPUTED": "award:",
    "HOST_UNREACHABLE": "host:",
    "KIND_OR_COUNTRY_UNSURE": "organisation:",
}


class ResolutionItem(models.Model):
    """One live question about the shared catalog, for the platform only.

    Platform-only (the third RLS case -- see research/0013_resolution_item_rls
    and CLAUDE.md): no tenant, no person, invisible to every agency. A queue,
    not a ledger. A row exists only while its question is live and is DELETED
    when answered, expired or withdrawn. The answer lives in the catalog it was
    written back to, and who answered lives in AuditEvent under the platform
    agency. Nothing here points at an operator, because an operator is a
    Membership.

    `country_code` and `registered` are facts about the SUBJECT, stamped by the
    writer at filing (it runs as runtime_engine, which can read the catalogue)
    and refreshed on every re-file while OPEN. The console runs as runtime_web,
    which holds no grant on any catalogue table, so it sorts and buckets by
    these two columns instead of looking the organisation up. No priority is
    stored: the sort is computed at read time.

    Plan: docs/superpowers/plans/2026-09-25-human-resolution-queue.md.
    Spec: 2026-09-22-funding-search-engine-master-design.md section 11.
    """

    class Kind(models.TextChoices):
        SITE_UNKNOWN = "SITE_UNKNOWN"
        AWARD_DISPUTED = "AWARD_DISPUTED"
        HOST_UNREACHABLE = "HOST_UNREACHABLE"
        KIND_OR_COUNTRY_UNSURE = "KIND_OR_COUNTRY_UNSURE"

    class State(models.TextChoices):
        OPEN = "OPEN"
        #: An operator said "I don't know". Only a different operator may decide it.
        PARKED = "PARKED"
        #: Decided in the console; waiting for `apply_resolutions`.
        DECIDED = "DECIDED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    subject_key = models.CharField(max_length=300)
    #: Validated by the kind's evidence model (resolution/kinds.py, extra=forbid).
    evidence = models.JSONField()
    #: The one closed question, rendered once at filing so the console and the
    #: CLI show the same words.
    ask = models.CharField(max_length=300)
    options = models.JSONField(default=list)
    state = models.CharField(max_length=8, choices=State.choices, default=State.OPEN)
    #: Validated by the kind's resolution model. Set only with DECIDED.
    resolution = models.JSONField(null=True, blank=True)
    #: Why the applier sent a decision back (evidence changed, write-back refused).
    apply_error = models.CharField(max_length=200, blank=True, default="")
    #: The subject's country (ISO 3166 alpha-2), "" when unknown. Writer-stamped.
    country_code = models.CharField(max_length=2, blank=True, default="")
    #: Whether the subject is a REGISTERED organisation. Writer-stamped.
    registered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    refreshed_at = models.DateTimeField()
    opened_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    #: created_at + RESOLUTION_EXPIRY_DAYS. Honoured only while never opened.
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "subject_key"), name="resolution_one_per_subject"
            ),
            models.CheckConstraint(
                condition=Q(kind__in=list(_RESOLUTION_PREFIXES)), name="resolution_kind_valid"
            ),
            models.CheckConstraint(
                condition=functools.reduce(
                    operator.or_,
                    (
                        Q(kind=kind, subject_key__startswith=prefix)
                        for kind, prefix in _RESOLUTION_PREFIXES.items()
                    ),
                ),
                name="resolution_subject_prefix",
            ),
            models.CheckConstraint(
                condition=Q(state__in=("OPEN", "PARKED", "DECIDED")),
                name="resolution_state_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="DECIDED", resolution__isnull=False, decided_at__isnull=False)
                    | (~Q(state="DECIDED") & Q(resolution__isnull=True))
                ),
                name="resolution_decided_shape",
            ),
        ]
        indexes = [models.Index(fields=("state", "created_at"), name="resolution_state_idx")]


# --- Demand cells, the cycle wallet and coverage (build item 14) -------------
#
# Five tenant tables (ENABLE + FORCE, tenant_isolation, composite tenant guards
# in research/0014) and one shared-catalogue queue, AreaSweep (the research/0012
# shape: runtime_engine writes, runtime_web holds no grant). Plan:
# docs/superpowers/plans/2026-09-25-demand-cells-and-coverage.md.


class ProfileCellSelection(TenantScopedModel):
    """The discipline bucket one profile version was read into (spec 10.6).

    Tenant data: derived from the student's own words. Keyed by profile version
    so a republish never re-asks, and an edited profile is read afresh. Written
    only by profile_cells.select_bucket; an off-schema or rate-limited read
    writes nothing, so the next call asks again.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey("tenancy.Membership", on_delete=models.CASCADE)
    profile_version = models.OneToOneField(
        "accounts.StudentProfileVersion", on_delete=models.CASCADE
    )
    discipline_bucket = models.CharField(max_length=60, blank=True, default="")
    #: The model id that read it -- the one place a model reads the profile.
    model = models.CharField(max_length=80, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="profilecell_tenant_id_uniq")
        ]


class SearchWallet(TenantScopedModel):
    """One student's search budget for one admission cycle (spec 10.5, decision 28).

    A depleting balance keyed (student, intended_intake) -- never a per-tap
    ceiling. `spent_usd` only ever grows, and only through wallet.charge, which
    locks this row.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey("tenancy.Membership", on_delete=models.CASCADE)
    intended_intake = models.DateField()
    budget_usd = models.DecimalField(max_digits=8, decimal_places=4)
    spent_usd = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="searchwallet_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "student", "intended_intake"), name="searchwallet_cycle_uniq"
            ),
            models.CheckConstraint(
                condition=Q(spent_usd__gte=0) & Q(budget_usd__gte=0),
                name="searchwallet_non_negative",
            ),
            # wallet.charge caps the column at the budget when a call already
            # billed more than was left, and logs the overshoot: the column
            # records what the wallet paid for, never a negative balance.
            models.CheckConstraint(
                condition=Q(spent_usd__lte=models.F("budget_usd")),
                name="searchwallet_spent_within_budget",
            ),
        ]


class SearchTap(TenantScopedModel):
    """One tap: what it asked, what it spent, how it ended (spec 10.5).

    The durable count behind "two taps a day" -- apps/ratelimit.py is a
    per-process cache and would reset on every worker restart.

    `run_id` and `pack_version_id` are plain UUID columns, not Django foreign
    keys: research migrations may not depend on funding (research/0003's
    docstring -- InvalidMigrationPlan in tests/migrations). The database still
    holds both edges, as tenant-guarded composite FKs added by
    funding/0054_pack_coverage (the funding -> research direction funding/0044
    already uses): `(tenant_id, run_id)` -> funding_recommendationrun ON DELETE
    CASCADE and `(tenant_id, pack_version_id)` -> funding_packversion ON DELETE
    SET NULL (pack_version_id).
    """

    class State(models.TextChoices):
        QUEUED = "QUEUED"
        STAGE1 = "STAGE1"
        STAGE2 = "STAGE2"
        DONE = "DONE"

    class Ending(models.TextChoices):
        COMPLETE = "COMPLETE"
        WALLET_SPENT = "WALLET_SPENT"
        TAP_SHARE_SPENT = "TAP_SHARE_SPENT"
        CALL_CAP = "CALL_CAP"
        TIME_CAP = "TIME_CAP"
        NO_ANGLES = "NO_ANGLES"
        STAGE2_UNAVAILABLE = "STAGE2_UNAVAILABLE"
        TENANT_CEILING = "TENANT_CEILING"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey("tenancy.Membership", on_delete=models.CASCADE)
    wallet = models.ForeignKey(SearchWallet, on_delete=models.CASCADE)
    run_id = models.UUIDField()
    pack_version_id = models.UUIDField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.QUEUED)
    ending = models.CharField(max_length=20, choices=Ending.choices, blank=True, default="")
    recency_only = models.BooleanField(default=False)
    allowance_usd = models.DecimalField(max_digits=8, decimal_places=4)
    provider_calls = models.PositiveIntegerField(default=0)
    pages_fetched = models.PositiveIntegerField(default=0)
    hosts_seen = models.PositiveIntegerField(default=0)
    hosts_new = models.PositiveIntegerField(default=0)
    awards_served = models.PositiveIntegerField(default=0)
    requested_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="searchtap_tenant_id_uniq"),
            models.CheckConstraint(
                condition=Q(allowance_usd__gte=0), name="searchtap_allowance_non_negative"
            ),
        ]
        indexes = [models.Index(fields=("student", "requested_at"))]


class WalletCharge(TenantScopedModel):
    """One billed call against a wallet, with the provider's own figure."""

    class Kind(models.TextChoices):
        SEARCH = "SEARCH"
        FETCH = "FETCH"
        CLASSIFY = "CLASSIFY"
        READ = "READ"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    wallet = models.ForeignKey(SearchWallet, on_delete=models.CASCADE)
    tap = models.ForeignKey(SearchTap, on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    provider = models.CharField(max_length=20)
    usd = models.DecimalField(max_digits=8, decimal_places=5)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="walletcharge_tenant_id_uniq"),
            models.CheckConstraint(condition=Q(usd__gte=0), name="walletcharge_non_negative"),
        ]
        indexes = [models.Index(fields=("tenant", "created_at"))]


class CellCoverage(TenantScopedModel):
    """Per cell x discipline bucket, over this tenant's ACTIVE students (spec 10.6).

    **Recomputed, never incremented** (coverage.refresh_cell_coverage): a count
    that is only ever added to cannot forget an erased student, and a counter
    cell of 1 is a person (CLAUDE.md, derived data). Rebuilt on every published
    pack and on the EXECUTED erasure path. It has no student relation at all,
    so the erasure classification walk never reaches it (and must not list it):
    an erased student leaves it by recomputation, not by redaction.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    holder = models.CharField(max_length=24)
    host_country = models.CharField(max_length=3)
    home_country = models.CharField(max_length=3)
    level = models.CharField(max_length=10, default="MASTER")
    discipline_bucket = models.CharField(max_length=60)
    active_students = models.PositiveIntegerField(default=0)
    students_no_floor = models.PositiveIntegerField(default=0)
    students_budget_unspent = models.PositiveIntegerField(default=0)
    found_served = models.PositiveIntegerField(default=0)
    verified_for_intake = models.PositiveIntegerField(default=0)
    refreshed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="cellcoverage_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=(
                    "tenant", "holder", "host_country", "home_country", "level",
                    "discipline_bucket",
                ),
                name="cellcoverage_cell_uniq",
            ),
        ]

    @property
    def thinness(self) -> float:
        return self.students_no_floor / self.active_students if self.active_students else 0.0

    @property
    def aiming_priority(self) -> float:
        return self.active_students * self.thinness


class AreaSweep(models.Model):
    """The queue of bounded cell sweeps (spec 10.5 step 5). SHARED CATALOGUE.

    About the catalogue, never a person: no tenant, no student, no count below
    the area. `demand` is how many taps asked for this area; it orders the
    queue across tenants without any tenant's data being read across the
    boundary. Platform-paid -- a per-student wallet cannot close a per-cell gap.

    Only a family with a sweep pass (`angles.PASS_SHAPES`, the same four
    SWEEP_FAMILIES a SweepAngle may carry) can be queued: an area of any other
    family can never be swept, so a row for it would wait for ever.
    `sweep_run` points a DONE row at the curve its pass produced.
    """

    class State(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        DONE = "DONE"
        UNAVAILABLE = "UNAVAILABLE"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    country_code = models.CharField(max_length=2)
    family = models.CharField(max_length=40)
    state = models.CharField(max_length=12, choices=State.choices, default=State.QUEUED)
    demand = models.PositiveIntegerField(default=1)
    requested_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    provider_calls = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0"))
    new_hosts = models.PositiveIntegerField(default=0)
    #: A SweepRun.StopReason on DONE; on UNAVAILABLE, why no pass ran (the
    #: harness's own refusal, truncated) -- never blank on a finished row.
    stop_reason = models.CharField(max_length=200, blank=True, default="")
    sweep_run = models.ForeignKey(
        SweepRun, on_delete=models.PROTECT, null=True, blank=True, related_name="area_sweeps"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("country_code", "family"),
                condition=Q(state__in=("QUEUED", "RUNNING")),
                name="areasweep_one_open_per_area",
            ),
            models.CheckConstraint(
                condition=Q(family__in=SWEEP_FAMILIES), name="areasweep_family_has_a_pass"
            ),
        ]
        indexes = [models.Index(fields=("state", "demand"))]


class GoldItem(models.Model):
    """One fact a reader accepted, for the platform owner to check (correct / wrong / not on page).

    The truth anchor of certification (verified-catalog section 5.5): a model-built key certifies
    only agreement with its referee. Platform-only, like ResolutionItem (research/0013): readable
    and updatable only on the platform agency's host, written by runtime_engine, never deleted --
    rows are kept as regression data. Nothing here points at an operator, for ResolutionItem's
    reason: a PROTECT FK on Membership would block a platform admin's erasure. Who labelled
    lives in AuditEvent.
    """

    class Kind(models.TextChoices):
        DEADLINE = "deadline"
        ELIGIBILITY = "eligibility"
        DOCUMENTS = "documents"
        MONEY = "money"
        #: A synthetic or published-template decision letter (decision_eval), never a
        #: student's mail.
        DECISION_MAIL = "decision_mail"

    class Purpose(models.TextChoices):
        IMPROVEMENT = "improvement"
        CERTIFICATION = "certification"

    class Verdict(models.TextChoices):
        UNCHECKED = ""
        CORRECT = "correct"
        WRONG = "wrong"
        NOT_ON_PAGE = "not_on_page"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    question = models.CharField(max_length=40)
    language = models.CharField(max_length=12)
    page_url = models.URLField(max_length=2000)
    line_text = models.TextField()
    #: Set by save(). The unique index hashes this, not line_text: a btree entry over a long
    #: line fails above ~2,704 bytes.
    line_sha256 = models.CharField(max_length=64, editable=False)
    heading = models.TextField(blank=True)
    claim = models.TextField()
    round = models.PositiveSmallIntegerField()
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    verdict = models.CharField(max_length=16, choices=Verdict.choices, blank=True, default="")
    fix = models.TextField(blank=True)
    labelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "purpose", "round", "question", "page_url", "line_sha256"],
                name="gold_item_once_per_round",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.line_sha256 = hashlib.sha256(self.line_text.encode()).hexdigest()
        super().save(*args, **kwargs)
