"""Verified facts, in the vocabulary a FieldMap entry uses.

A FieldMap entry names "personal.given_name". A VerifiedFact holds a category
and a payload dict. Nothing else in the codebase needs that translation, so it
lives here rather than in apps/documents, and it is deliberately one-way:
nothing writes facts from a portal page.
"""

import re
from datetime import date, datetime
from typing import Literal, NamedTuple
from uuid import UUID

from django.utils import timezone

from apps.documents.fact_writer import is_one_tap_row, needs_typing
from apps.documents.id_reading import OWNER_UNCHECKED
from apps.documents.models import DocumentDraft, DocumentReading, NarrativeInput, VerifiedFact
from apps.documents.verification import (
    TRANSCRIPT_ONLY_EDUCATION_KEYS,
    disowned_refs,
    id_document_groups,
    id_documents,
    latest_whys,
    live_retired_refs,
    payload_keys,
    retired_hides,
    retired_refs,
    unsuperseded_facts,
)
from apps.tenancy.models import Membership

#: What every snapshot is learned against: every canonical payload key of every
#: fact category, as "category.key". Fixed rather than the learning student's
#: own keys: a tenant map learned from the first student's facts would never
#: ask about a field only the second student holds, and the map serves both.
#: Values never come from here -- they are still the forbidden list.
#: Repeated degree sections a map may address ("Degree 1".."Degree 3"). A form
#: asking for a fourth is rare enough to leave to the student.
INDEXED_DEGREES = 3
INDEXED_EXPERIENCES = 3
INDEXED_REFERENCES = 3
INDEXED_TIMELINES = 3

NARRATIVE_FIELDS: tuple[str, ...] = (
    "narrative.motivation_letter",
    "narrative.why_programme",
    "narrative.why_country",
    "narrative.academic_preparation",
    "narrative.research_plan",
    "narrative.career_plan",
    "narrative.home_country_contribution",
    "narrative.leadership_example",
    "narrative.personal_background",
    "narrative.language_plan",
    "narrative.relationship_community",
    "narrative.opening",
    "narrative.closing",
)

_ARCHETYPE_TO_FIELD: dict[str, str] = {
    "OPENING": "narrative.opening",
    "WHY_PROGRAMME": "narrative.why_programme",
    "WHY_COUNTRY": "narrative.why_country",
    "ACADEMIC_PREPARATION": "narrative.academic_preparation",
    "RESEARCH_PLAN": "narrative.research_plan",
    "CAREER_PLAN_RETURN": "narrative.career_plan",
    "HOME_COUNTRY_CONTRIBUTION": "narrative.home_country_contribution",
    "LEADERSHIP_EXAMPLE": "narrative.leadership_example",
    "PERSONAL_BACKGROUND": "narrative.personal_background",
    "LANGUAGE_PLAN": "narrative.language_plan",
    "RELATIONSHIP_COMMUNITY": "narrative.relationship_community",
    "CLOSING": "narrative.closing",
}

_INPUT_KIND_TO_FIELD: dict[str, str] = {
    NarrativeInput.Kind.RESEARCH_PLAN: "narrative.research_plan",
    NarrativeInput.Kind.LANGUAGE_PLAN: "narrative.language_plan",
    NarrativeInput.Kind.PERSONAL_BACKGROUND: "narrative.personal_background",
    NarrativeInput.Kind.HOME_COUNTRY_CIRCUMSTANCES: "narrative.home_country_contribution",
    NarrativeInput.Kind.DEVELOPMENT_IMPACT: "narrative.home_country_contribution",
}

_INDEX = re.compile(r"\.\d+\.")


def field_class(profile_field: str) -> str:
    """"education.2.end_date" -> "education.end_date"; anything else unchanged.
    Two degrees' boxes share a label, so anything comparing by meaning compares
    classes; which degree a box belongs to is the map's to say."""
    return _INDEX.sub(".", profile_field, count=1)


LEARNABLE_FIELDS: tuple[str, ...] = (
    tuple(
        f"{category.lower()}.{key}"
        for category in VerifiedFact.Category.values
        for key in payload_keys(category)
        if key not in TRANSCRIPT_ONLY_EDUCATION_KEYS
    )
    + tuple(
        f"education.{number}.{key}"
        for number in range(1, INDEXED_DEGREES + 1)
        for key in payload_keys(VerifiedFact.Category.EDUCATION)
        # Owner decision 2026-10-15: autofill never uses a transcript's courses or the matcher's
        # bookkeeping (.claude/rules/cv-and-letters.md, "One ledger, every consumer").
        if key not in TRANSCRIPT_ONLY_EDUCATION_KEYS
    )
    + tuple(
        f"experience.{number}.{key}"
        for number in range(1, INDEXED_EXPERIENCES + 1)
        for key in payload_keys(VerifiedFact.Category.EXPERIENCE)
    )
    + tuple(
        f"reference.{number}.{key}"
        for number in range(1, INDEXED_REFERENCES + 1)
        for key in payload_keys(VerifiedFact.Category.REFERENCE)
    )
    + tuple(
        f"timeline.{number}.{key}"
        for number in range(1, INDEXED_TIMELINES + 1)
        for key in payload_keys(VerifiedFact.Category.TIMELINE)
    )
    + NARRATIVE_FIELDS
)


def _degree_order(payload: dict[str, object]) -> tuple[str, str]:
    return str(payload.get("start_date") or ""), str(payload.get("end_date") or "")


def _payload_str(category: str, key: str, value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if (
        category == VerifiedFact.Category.EXPERIENCE
        and key == "bullets"
        and isinstance(value, list)
    ):
        lines = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if lines:
            return "\n".join(lines)
    return None


def narrative_values(
    student: Membership,
    *,
    program_id: UUID | None = None,
    application_id: UUID | None = None,
    _inputs: list[NarrativeInput] | None = None,
    _drafts: list[DocumentDraft] | None = None,
) -> dict[str, str]:
    """Approved narrative units and confirmed student narrative inputs for portals.

    Reads only tenant-scoped tables (``NarrativeInput`` and ``DocumentDraft``
    via raw UUID columns ``application_id`` and ``programme_id``) so web-tier
    packet and kit endpoints never touch the shared catalogue.
    """
    out: dict[str, str] = {}
    inputs = (
        _inputs
        if _inputs is not None
        else list(NarrativeInput.objects.filter(student=student).order_by("created_at"))
    )
    for entry in inputs:
        text = entry.text.strip() if isinstance(entry.text, str) else ""
        if not text:
            continue
        if entry.kind == NarrativeInput.Kind.RESEARCH_FIT:
            if (
                program_id is not None
                and isinstance(entry.provenance, dict)
                and entry.provenance.get("program_id") == str(program_id)
                and "narrative.research_plan" not in out
            ):
                out["narrative.research_plan"] = text
            continue
        if entry.confirmed_at is not None or entry.proposed_by == NarrativeInput.ProposedBy.STUDENT:
            target = _INPUT_KIND_TO_FIELD.get(entry.kind)
            if target:
                out[target] = text

    drafts = (
        _drafts
        if _drafts is not None
        else list(
            DocumentDraft.objects.filter(
                student=student,
                kind__in=(DocumentDraft.Kind.CORE_NARRATIVE, DocumentDraft.Kind.MOTIVATION_LETTER),
                status=DocumentDraft.Status.APPROVED,
            ).order_by("version", "created_at")
        )
    )
    core_draft = next(
        (d for d in reversed(drafts) if d.kind == DocumentDraft.Kind.CORE_NARRATIVE),
        None,
    )
    letter_draft: DocumentDraft | None = None
    letters = [d for d in drafts if d.kind == DocumentDraft.Kind.MOTIVATION_LETTER]
    if application_id is not None:
        letter_draft = next(
            (d for d in reversed(letters) if d.application_id == application_id),
            None,
        )
    if letter_draft is None and program_id is not None:
        letter_draft = next(
            (
                d
                for d in reversed(letters)
                if d.application_id is None and d.programme_id == program_id
            ),
            None,
        )
    if letter_draft is None:
        letter_draft = next(
            (
                d
                for d in reversed(letters)
                if d.application_id is None
                and (d.programme_id is None or (program_id is None and application_id is None))
            ),
            None,
        )

    for draft in (core_draft, letter_draft):
        if draft is None or not isinstance(draft.content, dict):
            continue
        paragraphs: list[str] = []
        units = draft.content.get("units")
        if isinstance(units, list):
            for unit in units:
                if not isinstance(unit, dict):
                    continue
                unit_text = unit.get("text")
                if not isinstance(unit_text, str) or not unit_text.strip():
                    continue
                clean_text = unit_text.strip()
                paragraphs.append(clean_text)
                archetype = unit.get("archetype")
                if isinstance(archetype, str) and archetype in _ARCHETYPE_TO_FIELD:
                    out[_ARCHETYPE_TO_FIELD[archetype]] = clean_text
        for key, target in _ARCHETYPE_TO_FIELD.items():
            short_key = target.split(".", 1)[1]
            raw_val = (
                draft.content.get(key)
                or draft.content.get(key.lower())
                or draft.content.get(short_key)
            )
            if isinstance(raw_val, str) and raw_val.strip():
                clean_val = raw_val.strip()
                out[target] = clean_val
                if not isinstance(units, list):
                    paragraphs.append(clean_val)
        if paragraphs and (
            draft.kind == DocumentDraft.Kind.MOTIVATION_LETTER
            or "narrative.motivation_letter" not in out
        ):
            out["narrative.motivation_letter"] = "\n\n".join(paragraphs)
    return out


def verified_values(student: Membership) -> dict[str, str]:
    """Confirmed, current facts flattened to ``"category.key" -> value``.

    A repeated category's unindexed key is its last row (maps stored before
    plan 5 ask for those). Education, experience, reference, and timeline are
    also indexed ("education.1.institution_original") for forms with repeated
    sections.
    """
    superseded = set(
        VerifiedFact.objects.filter(student=student, supersedes__isnull=False).values_list(
            "supersedes_id", flat=True
        )
    )
    retired, live = retired_refs(student), live_retired_refs(student)
    facts = [
        f
        for f in VerifiedFact.objects.filter(student=student, confirmed_at__isnull=False)
        .exclude(id__in=superseded)
        .exclude(source_ref__in=disowned_refs(student))
        .order_by("created_at")
        if not retired_hides(f, retired, live)
    ]
    values: dict[str, str] = {}
    # Every confirmed category, TIMELINE included (owner decision 2026-10-06:
    # one ledger, every consumer). Like every multi-row category here, the
    # last row of a key wins, so a student with two gaps offers the later one.
    for fact in facts:
        if fact.category == VerifiedFact.Category.ID_DOCUMENT:
            continue
        for key, value in fact.payload.items():
            # A replaced scan's citizenship travels with its ID-document group.
            if (key == "citizenship" and fact.source_ref in retired - live
                    and fact.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT):
                continue
            # Text only (plus joined experience bullets). A general list or
            # number belongs to document generation; typing its repr into a
            # portal field is worse than leaving the field to the student.
            rendered = _payload_str(fact.category, key, value)
            if rendered is not None:
                values[f"{fact.category.lower()}.{key}"] = rendered
    # Oldest first: on a master's application "Degree 1" is the first degree
    # earned. Ordered by start, then end; an undated degree sorts first.
    for category, prefix, limit, sort_by_dates in (
        (VerifiedFact.Category.EDUCATION, "education", INDEXED_DEGREES, True),
        (VerifiedFact.Category.EXPERIENCE, "experience", INDEXED_EXPERIENCES, True),
        (VerifiedFact.Category.REFERENCE, "reference", INDEXED_REFERENCES, False),
        (VerifiedFact.Category.TIMELINE, "timeline", INDEXED_TIMELINES, True),
    ):
        rows: list[dict[str, object]] = [
            fact.payload
            for fact in facts
            if fact.category == category and isinstance(fact.payload, dict)
        ]
        if sort_by_dates:
            rows.sort(key=_degree_order)
        for number, payload in enumerate(rows[:limit], start=1):
            for key, value in payload.items():
                rendered = _payload_str(category, key, value)
                if rendered is not None:
                    values[f"{prefix}.{number}.{key}"] = rendered
    values = _with_latest_certificate(values, facts)
    documents, served = _id_document_values(student, facts)
    values.update(documents)
    own = _own_citizenship(facts)
    if own is not None and (served is None or own[1] > served):
        values["identity.citizenship"] = own[0]
    values.update(narrative_values(student))
    return values


def _with_latest_certificate(values: dict[str, str], facts: list[VerifiedFact]) -> dict[str, str]:
    """Spec 2026-10-12 §4.3: a portal gets the latest sitting's values, whole. A CV's
    language row never mixes into a certificate's (its level is a self-assessment). A
    sitting's rows share its document ref -- the student's adopted or corrected row
    included -- and the later row wins per key (facts are in created order)."""
    sittings: dict[str, dict[str, str]] = {}
    for fact in facts:
        if (fact.category == VerifiedFact.Category.LANGUAGE
                and fact.source_ref.startswith("document:")):
            for key, value in fact.payload.items():
                if isinstance(value, str) and value.strip():
                    sittings.setdefault(fact.source_ref, {})[key] = value
    if not sittings:
        return values
    latest = max(sittings.values(), key=_sitting_date)
    kept = {k: v for k, v in values.items() if not k.startswith("language.")}
    return kept | {f"language.{key}": value for key, value in latest.items()}


def _sitting_date(sitting: dict[str, str]) -> str:
    """A sitting's ISO test date, or "" (undated): only dates compare, never the text of
    one the code could not read (final review I3)."""
    try:
        return date.fromisoformat(sitting.get("test_date", "")).isoformat()
    except ValueError:
        return ""


def _own_citizenship(facts: list[VerifiedFact]) -> tuple[str, datetime] | None:
    """Spec D5: the student's own entry -- the latest confirmed STUDENT_STATEMENT
    IDENTITY citizenship that is not a document's (a gap answer, say), with when it
    was confirmed. A correction of a passport's value travels with that passport
    instead (_document_citizenship). `facts` is current, confirmed rows only."""
    own = [
        (fact.payload["citizenship"], fact.confirmed_at)
        for fact in facts
        if fact.category == VerifiedFact.Category.IDENTITY
        and fact.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT
        and not fact.source_ref.startswith("document:")
        and fact.confirmed_at is not None
        and isinstance(fact.payload.get("citizenship"), str)
        and fact.payload["citizenship"].strip()
    ]
    return max(own, key=lambda o: o[1]) if own else None


def _picked(
    student: Membership, groups: dict[str, tuple[dict[str, str], frozenset[str]]]
) -> str | None:
    """The ID document portals are served (spec §4.2): the student's chosen one if it
    is valid, else the valid passport with the latest expiry, else the valid document
    of any type with the latest expiry. None when none is valid: an expired document
    is never served."""
    today = timezone.localdate().isoformat()
    valid = {ref: doc for ref, (doc, _) in groups.items() if doc.get("expiry_date", "") >= today}
    if not valid:
        return None
    chosen = (
        DocumentReading.objects.filter(student=student, primary_chosen_at__isnull=False)
        .order_by("-primary_chosen_at")
        .values_list("document_id", flat=True)
        .first()
    )
    # A re-upload of the chosen passport is merged into one document under the
    # later ref: the choice holds for any of the merged refs.
    picked = next(
        (ref for ref in valid if chosen is not None and f"document:{chosen}" in groups[ref][1]),
        None,
    )
    if picked is not None:
        return picked
    passports = {r: d for r, d in valid.items() if d.get("document_type") == "passport"}
    pool = passports or valid
    return max(pool, key=lambda r: pool[r].get("expiry_date", ""))


def _id_document_values(
    student: Membership, facts: list[VerifiedFact]
) -> tuple[dict[str, str], datetime | None]:
    """Spec 2026-10-12 §4.2: one document's keys, never a mix of two. The student's
    chosen one if it is valid, else the valid passport with the latest expiry, else
    the valid document of any type with the latest expiry. An expired document is
    never served: the portal box stays a hint. Also returns when the citizenship
    served with it was confirmed (None: none served, or one still waiting)."""
    groups = id_document_groups(facts)
    ref = _picked(student, groups)
    if ref is None:
        return {}, None
    out = {f"id_document.{key}": value for key, value in groups[ref][0].items()}
    citizenship = _document_citizenship(student, groups[ref][1])
    if citizenship is None:
        return out, None
    out["identity.citizenship"] = citizenship[0]
    return out, citizenship[1]


#: Why-codes a reading's entry carries when the strip proved it and the writer
#: then parked it as a detail to check because another source already held a value.
_PROVED_THEN_PARKED = frozenset({"document_differs", "student_entry_differs", "older_document"})


def _document_citizenship(
    student: Membership, refs: frozenset[str]
) -> tuple[str, datetime | None] | None:
    """Number, expiry and citizenship travel together (owner, 2026-10-13): the
    picked document -- every ref merged into it -- is served with its own
    citizenship, even when a dual national's other passport owns the confirmed
    identity.citizenship fact. With when that value was confirmed: None when it
    still waits, so a gap answer outranks it (verified_values).

    The student's correction under one of `refs` wins (the latest). Else what the
    document proved: a ref's current IDENTITY citizenship row if it is
    confirmed, or it waits and the reading's entry for it was proven (or proven
    then parked) with the same value; with no row at all -- the value equalled
    the one already held, so the writer wrote none -- the proven or parked entry
    itself, as of the reading. The latest of the refs' answers wins. None when
    it proved none: the caller then keeps the ledger's identity.citizenship."""
    rows = [
        fact for fact in unsuperseded_facts(student).filter(
            category=VerifiedFact.Category.IDENTITY, source_ref__in=refs,
            payload__has_key="citizenship",
        )
        if isinstance(fact.payload["citizenship"], str) and fact.payload["citizenship"].strip()
    ]
    corrected = [
        f for f in rows
        if f.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT and f.confirmed_at
    ]
    if corrected:
        last = max(corrected, key=lambda f: f.confirmed_at or f.created_at)
        return last.payload["citizenship"], last.confirmed_at
    proved: list[tuple[datetime, str, datetime | None]] = []
    for reading in DocumentReading.objects.filter(
        student=student, document_id__in=[UUID(r.removeprefix("document:")) for r in refs]
    ):
        ref = f"document:{reading.document_id}"
        entry = next(
            (
                v for v in reading.values or []
                if v.get("key") == "identity.citizenship"
                and (v.get("proven") or v.get("why") in _PROVED_THEN_PARKED)
                and isinstance(v.get("value"), str) and v["value"].strip()
            ),
            None,
        )
        mine = [f for f in rows if f.source_ref == ref]
        if mine:
            row = mine[-1]
            value: str = row.payload["citizenship"]
            if row.confirmed_at is not None:
                proved.append((row.confirmed_at, value, row.confirmed_at))
            elif entry is not None and entry["value"] == value:
                proved.append((row.created_at, value, None))
        elif entry is not None:
            proved.append((reading.created_at, entry["value"], reading.created_at))
    if not proved:
        return None
    _, value, at = max(proved, key=lambda p: p[0])
    return value, at


#: Spec 2026-10-12 §7.4: the upload kind a document-read fact came from, as the
#: co-pilot names it on a mark ("From your passport").
SourceKind = Literal["passport", "diploma", "certificate"]
SOURCE_KINDS: dict[str, SourceKind] = {
    "PASSPORT": "passport",
    "DIPLOMA": "diploma",
    "LANGUAGE_CERTIFICATE": "certificate",
}
_DOCUMENT_REF = "document:"
# OWNER_UNCHECKED: a reading that could not tie the document to this student (spec
# §5.2.4). Its values are never one tap from a portal (plan 1 rulings: a passport proven
# not the student's serves nothing; an owner_unknown one is settled only by a clean re-read).
#: Number, expiry and citizenship travel together (owner, 2026-10-13): these are
#: offered only from the one document portals are served (or would be).
_ONE_DOCUMENT = ("id_document.", "identity.citizenship")


class Offer(NamedTuple):
    fact_id: UUID
    value: str
    source_kind: SourceKind


def _document_kinds(facts: list[VerifiedFact]) -> dict[str, SourceKind]:
    from apps.concierge.models import DocumentVersion

    ids = set()
    for fact in facts:
        if fact.source_ref.startswith(_DOCUMENT_REF):
            try:
                ids.add(UUID(fact.source_ref.removeprefix(_DOCUMENT_REF)))
            except ValueError:
                continue
    return {
        str(document_id): SOURCE_KINDS[kind]
        for document_id, kind in DocumentVersion.objects.filter(id__in=ids).values_list(
            "id", "kind"
        )
        if kind in SOURCE_KINDS
    }


def _owned(student: Membership, disowned: set[str]) -> list[VerifiedFact]:
    """Current rows, minus every document read as someone else's (plan 1: a disowned
    document serves nothing, and is offered nothing)."""
    return [f for f in unsuperseded_facts(student) if f.source_ref not in disowned]


def document_sources(student: Membership, values: dict[str, str]) -> dict[str, str]:
    """Profile field -> source kind, for each value in `values` (what verified_values
    serves) that a document read proved: a current, confirmed AUTHORITATIVE_DOCUMENT row
    of a document the student owns holds exactly that value. Matched on the value, so
    the mark follows whatever verified_values picked -- the chosen passport, the latest
    sitting -- and a student's own correction, which differs from every read, is never
    marked "From your passport"."""
    facts = [
        f for f in _owned(student, disowned_refs(student))
        if f.confirmed_at is not None
        and f.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
        and f.source_ref.startswith(_DOCUMENT_REF)
    ]
    kinds = _document_kinds(facts)
    proved: dict[tuple[str, str], str] = {}
    for fact in facts:
        source = kinds.get(fact.source_ref.removeprefix(_DOCUMENT_REF))
        for key, value in fact.payload.items():
            if source and isinstance(value, str) and value.strip():
                proved[(f"{fact.category.lower()}.{key}", value)] = source
    return {
        field: proved[(field_class(field), value)]
        for field, value in values.items()
        if (field_class(field), value) in proved
    }


def _offer_refs(
    student: Membership, confirmed: list[VerifiedFact], disowned: set[str]
) -> frozenset[str]:
    """The refs of the one ID document an id_document.* or citizenship offer may come
    from: the document portals are served (_picked), else the latest passport read the
    student owns. Never a second document's value beside the first's."""
    groups = id_document_groups(confirmed)
    picked = _picked(student, groups)
    if picked is not None:
        return groups[picked][1]
    latest = next(
        (
            ref
            for ref in (
                f"{_DOCUMENT_REF}{d}"
                for d in DocumentReading.objects.filter(
                    student=student, kind="PASSPORT", state=DocumentReading.State.READ
                ).order_by("-created_at").values_list("document_id", flat=True)
            )
            if ref not in disowned
        ),
        None,
    )
    if latest is None:
        return frozenset()
    return next((refs for _, refs in groups.values() if latest in refs), frozenset({latest}))


def document_offers(student: Membership) -> dict[str, Offer]:
    """"category.key" -> the newest doubtful value a document read left for it
    (spec 2026-10-12 §7.2): unconfirmed, unsuperseded, one value per row, from a
    document the student owns (never disowned; a replaced upload offers nothing).
    Never a value whose latest reading could not tie the document to the student
    (OWNER_UNCHECKED, decided as the dashboard decides it); never one the ledger
    cannot hold as printed (fact_writer.needs_typing: no tap writes an unread
    date); an id_document.* or citizenship value only from the one document
    portals are served (_offer_refs); and no id_document.* value while every ID
    document has expired. mint_packet and ext_api.confirm_offer both ask here, so
    a value offered when the packet was minted and not offered now is refused at
    the tap."""
    disowned = disowned_refs(student)
    retired, live = retired_refs(student), live_retired_refs(student)
    owned = [f for f in _owned(student, disowned) if not retired_hides(f, retired, live)]
    waiting = [
        # One value per row, of an ID document. Plan 2's doubtful diploma and
        # certificate values wait on the DocumentReading (adopt_document_value) or
        # as one whole-document row, and one tap on one box must never confirm
        # values the student did not see. Those are settled on the dashboard.
        f for f in owned if is_one_tap_row(f)
    ]
    if not waiting:
        return {}
    # The latest reading's why per (document, key), later readings winning, as
    # documents/views.py builds its snippets: a clean re-read of the same file
    # lifts an owner_unknown (plan 1), and the panel never offers what the
    # dashboard hides (plan 2: owner_unknown is offered on no surface).
    why = latest_whys(student)
    one_document = _offer_refs(
        student, [f for f in owned if f.confirmed_at], disowned | retired
    )
    # An expired document is never served (spec §4.2), not even through a tap.
    expired = bool(expired_id_document(student))
    kinds = _document_kinds(waiting)
    offers: dict[str, Offer] = {}
    for fact in waiting:
        source = kinds.get(fact.source_ref.removeprefix(_DOCUMENT_REF))
        for key, value in fact.payload.items():
            field = f"{fact.category.lower()}.{key}"
            if (
                not source
                or not (isinstance(value, str) and value.strip())
                or why.get((fact.source_ref, field)) in OWNER_UNCHECKED
                or needs_typing(field, value)
                or (field.startswith(_ONE_DOCUMENT) and fact.source_ref not in one_document)
                or (expired and field.startswith("id_document."))
            ):
                continue
            offers[field] = Offer(fact.id, value, source)
    return offers


def expired_id_document(student: Membership) -> str:
    """The latest expiry among the student's ID documents when every one of them has
    expired, else "" (spec §4.2: an expired document is never served). Documents are
    counted as portals count them -- per document, re-uploads merged
    (verification.id_documents) -- and a disowned one is not the student's."""
    disowned = disowned_refs(student)
    retired, live = retired_refs(student), live_retired_refs(student)
    confirmed = [
        f for f in _owned(student, disowned)
        if f.confirmed_at is not None and not retired_hides(f, retired, live)
    ]
    expiries = [doc.get("expiry_date", "") for doc in id_documents(confirmed).values()]
    expiries = [e for e in expiries if e]
    today = timezone.localdate().isoformat()
    if not expiries or any(e >= today for e in expiries):
        return ""
    # A renewed passport whose expiry is still only waiting (doubtful) is not an
    # expired document: the tap that would confirm it must not be withheld.
    for fact in _owned(student, disowned):
        if (
            fact.source_ref not in retired
            and fact.confirmed_at is None
            and fact.category == VerifiedFact.Category.ID_DOCUMENT
        ):
            waiting = fact.payload.get("expiry_date")
            if isinstance(waiting, str) and waiting >= today:
                return ""
    return max(expiries)
