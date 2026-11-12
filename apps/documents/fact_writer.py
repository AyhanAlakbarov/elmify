"""A reading's values into the fact ledger (spec 2026-10-12 §6.2), and the
student's own correction of one. Called inside the caller's tenant transaction.

Precedence per key: the student's own entry, then the newest proven read, then an
older one. A read never overwrites a student entry and never silently changes a
name, a citizenship or a date of birth: those differences wait as a detail to
check. A proven value is confirmed by no click -- the audit trail says AGENT --
while `confirmed_by` names the student whose own document it is, the precedent
evidence/facts.write_publication_fact set."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from uuid import UUID

from django.utils import timezone

from apps.concierge.models import DocumentVersion
from apps.tenancy.models import Membership

from .audit import record_event
from .confirmation import FactNotFound
from .degree_match import same_name as _equal
from .hygiene import normalize_text
from .id_reading import OWNER_UNCHECKED, ReadValue, raise_identity_mismatch_alert
from .models import DocumentReading, VerifiedFact
from .text_reading import TESTS
from .verification import (
    disowned_refs,
    document_number,
    latest_whys,
    payload_keys,
    retired_refs,
    unsuperseded_facts,
)

PROTECTED_KEYS = frozenset(
    {"identity.given_names", "identity.surname", "identity.citizenship", "identity.date_of_birth"}
)
_SEXES = frozenset({"M", "F", "X"})
_MAX_VALUE = 200


def _agent_read(fact: VerifiedFact) -> None:
    record_event(actor=None, actor_kind="AGENT", event="fact.read_from_document",
                 object_id=fact.id)


def _student_row(
    student: Membership, base: VerifiedFact, payload: dict[str, object], *,
    supersedes: VerifiedFact | None, ref: str | None = None,
    tier: str | None = None, confirmed_by: Membership | None = None,
) -> VerifiedFact:
    """A row confirmed now, built on `base` (its category, tier, ref and confirmer
    unless given)."""
    return VerifiedFact.objects.create(
        student=student, category=base.category, payload=payload,
        source_tier=tier or base.source_tier, source_ref=ref or base.source_ref,
        confirmed_by=confirmed_by, confirmed_at=timezone.now(),
        supersedes=supersedes, created_by=student)


def _split(key: str) -> tuple[str, str]:
    prefix, _, field = key.partition(".")
    return prefix.upper(), field


def _same(a: object, b: object) -> bool:
    return normalize_text(str(a)).casefold() == normalize_text(str(b)).casefold()


def _filled(fact: VerifiedFact, field: str) -> bool:
    """A key counts only when it holds a value: a CV's IDENTITY row carries every
    key, the ones it does not know as None."""
    value = fact.payload.get(field)
    return value is not None and str(value).strip() != ""


def _tips(student: Membership, category: str, field: str) -> list[VerifiedFact]:
    qs = unsuperseded_facts(student).filter(category=category, payload__has_key=field)
    return [f for f in qs if _filled(f, field)]


def _own_row(fact: VerifiedFact) -> bool:
    """A one-key row a document read wrote, safe to supersede; a CV's multi-key
    row is not, or its other keys would vanish from the current rows."""
    return (
        len(fact.payload) == 1
        and fact.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
    )


def _document_age(student: Membership, ref: str) -> str | None:
    """When a document was issued, known only from its confirmed issue_date. A
    doubtful date, a reading's unconfirmed value or the upload day would let a
    misread decide which passport is newer, so those leave the age unknown."""
    for fact in reversed(
        list(
            unsuperseded_facts(student).filter(
                category=VerifiedFact.Category.ID_DOCUMENT,
                source_ref=ref,
                confirmed_at__isnull=False,
                payload__has_key="issue_date",
            )
        )
    ):
        if _filled(fact, "issue_date"):
            return str(fact.payload["issue_date"])
    return None


def write_facts(reading: DocumentReading) -> None:
    student = reading.student
    ref = f"document:{reading.document_id}"
    values = [ReadValue.from_dict(v) for v in reading.values]
    if any(v.why == "owner_mismatch" for v in values):
        # Someone else's passport (a parent's, say): nothing of it enters this
        # student's ledger, so no Use, Correct or confirm can make it theirs. The
        # reading's values stay, for the "doesn't look like yours" problem line.
        raise_identity_mismatch_alert(
            student,
            message=(
                f"Uploaded document ({reading.kind}) for document {reading.document_id} "
                "does not match the student's identity."
            ),
        )
        reading.facts_written = True
        reading.save(update_fields=["facts_written", "updated_at"])
        return
    # The ID document first: its confirmed issue date is how a person value is
    # placed against an older or newer document.
    ids = _write_id_document(student, ref, [v for v in values if v.key.startswith("id_document.")])
    # Plan 2 (spec §4.3-4.4): a certificate is one sitting, a diploma fills its degree.
    sitting = _write_certificate(
        student, ref, [v for v in values if v.key.startswith("language.")])
    degree = _write_diploma(student, ref, [v for v in values if v.key.startswith("education.")])
    person = [_write_person_value(student, ref, v) for v in values
              if v.key.startswith("identity.")]
    reading.values = [v.as_dict() for v in _answered(reading, person + ids + sitting + degree)]
    reading.facts_written = True
    reading.save(update_fields=["values", "facts_written", "updated_at"])
    if sitting or degree:
        from .profile_bridge import sync_facts_to_profile

        sync_facts_to_profile(student)


def _write_person_value(student: Membership, ref: str, value: ReadValue) -> ReadValue:
    category, field = _split(value.key)
    tips = _tips(student, category, field)
    confirmed = [f for f in tips if f.confirmed_at is not None]
    current = confirmed[-1] if confirmed else None
    if current is not None and _same(current.payload[field], value.value):
        return value
    proven, why = value.proven, value.why
    if current is not None and proven:
        if current.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT:
            proven, why = False, "student_entry_differs"
        elif value.key in PROTECTED_KEYS:
            proven, why = False, "document_differs"
        elif (
            current.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
            and current.source_ref.startswith("document:")
            and current.source_ref != ref
        ):
            # Another document's value is replaced only by a strictly newer or
            # equally old one whose age is known; anything else waits as a detail.
            new_age = _document_age(student, ref)
            current_age = _document_age(student, current.source_ref)
            if new_age is None or current_age is None:
                proven, why = False, "document_differs"
            elif new_age < current_age:
                proven, why = False, "older_document"
    # Never against a replaced upload's waiting row: it is hidden, so deduping to it
    # would leave a clearer scan's doubtful value unoffered.
    retired = retired_refs(student)
    waiting = next(
        (f for f in tips if f.confirmed_at is None and f.source_ref not in retired
         and _same(f.payload[field], value.value)),
        None,
    )
    supersedes = (
        current
        if proven and current is not None and len(current.payload) == 1
        and current.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
        else None
    )
    if waiting is not None and not (proven and current is not None):
        if proven:
            # Doubtful before, proven now, nothing contradicting it: the proof is
            # its own row, carrying the proving document, superseding the waiting one.
            fact = _create(
                student, category, {field: value.value}, ref, True,
                waiting if _own_row(waiting) else None,
            )
            _agent_read(fact)
        return ReadValue(value.key, value.value, value.snippet, proven, why)
    fact = _create(student, category, {field: value.value}, ref, proven, supersedes)
    if proven:
        _agent_read(fact)
    return ReadValue(value.key, value.value, value.snippet, proven, why)


def _write_id_document(student: Membership, ref: str, values: list[ReadValue]) -> list[ReadValue]:
    if not values:
        return []
    category = VerifiedFact.Category.ID_DOCUMENT
    tips = list(unsuperseded_facts(student).filter(category=category, source_ref=ref))
    confirmed = [f for f in tips if f.confirmed_at is not None]
    # What the student typed is theirs: a re-read never replaces it.
    owned: dict[str, object] = {}
    owned_at: dict[str, datetime] = {}
    for f in confirmed:
        if f.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT:
            for k, v in f.payload.items():
                if _filled(f, k):
                    owned[k], owned_at[k] = v, f.created_at
    final: list[ReadValue] = []
    for v in values:
        field = _split(v.key)[1]
        if v.proven and field in owned and not _same(owned[field], v.value):
            v = ReadValue(v.key, v.value, v.snippet, False, "student_entry_differs")
        final.append(v)
    proven = {
        _split(v.key)[1]: v.value
        for v in final
        if v.proven and _split(v.key)[1] not in owned
    }
    authoritative = [f for f in confirmed
                     if f.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT]
    existing = authoritative[-1] if authoritative else None
    # A key the student typed after `existing` was written is theirs, not
    # existing's; one `existing` was confirmed after (a "Use" tap) stays.
    kept = (
        {
            k: v for k, v in existing.payload.items()
            if k not in owned or existing.created_at > owned_at[k]
        }
        if existing is not None else {}
    )
    merged = {**kept, **proven}
    changed = existing is None or any(existing.payload.get(k) != v for k, v in proven.items())
    if proven and changed:
        fact = _create(student, category, merged, ref, True, existing)
        _agent_read(fact)
        expiry = proven.get("expiry_date")
        if expiry:
            DocumentVersion.objects.filter(
                id=ref.removeprefix("document:"), expires_on__isnull=True
            ).update(expires_on=expiry)
    waiting = [f for f in tips if f.confirmed_at is None]
    for v in final:
        if v.proven:
            continue
        field = _split(v.key)[1]
        if any(f.payload.get(field) == v.value for f in waiting):
            continue
        _create(student, category, {field: v.value}, ref, False, None)
    return final


#: Without these proven, a document anchors nothing and becomes one row the student
#: confirms whole (spec §6.2).
_ANCHORS = {"language": ("test_name", "language"), "education": ("institution_original",)}
#: One row is one sitting or one degree (verified_values counts EDUCATION per row):
#: these rows are never split into one-key rows.
PER_ROW = frozenset({VerifiedFact.Category.EDUCATION, VerifiedFact.Category.LANGUAGE})


def _waiting(
    values: list[ReadValue], target: VerifiedFact, why: str | None = None
) -> list[ReadValue]:
    return [ReadValue(v.key, v.value, v.snippet, False, why or v.why, target=str(target.id))
            for v in values]


#: Why a whole-document row waits: the student says whether it is a new one.
_NEW: dict[str, str] = {
    VerifiedFact.Category.EDUCATION: "new_degree", VerifiedFact.Category.LANGUAGE: "new_result"
}
#: The student's answers to a waiting value (`_settle`).
_SETTLED = frozenset({"adopted", "kept"})


def _whole_unconfirmed(student: Membership, category: str, ref: str,
                       values: list[ReadValue]) -> list[ReadValue]:
    """One unconfirmed row the student confirms whole, as a CV's facts are: no proven
    anchor, or a document that may or may not be a degree or a sitting we already hold.
    Never a second one for the same document. A value the readers proved says why it
    waits (`new_degree`/`new_result`); a doubtful one keeps the reader's why."""
    # ponytail: a re-read that loses its anchor after an earlier read of this document
    # wrote a row leaves its values on the reading only, with no target; add one if
    # re-reads become routine.
    # A value the ledger cannot hold as printed (a date the code could not read) is never
    # in the row, or "Yes, add it" would confirm it: it waits on the row, for the student
    # to type once the row is theirs (final review I3).
    typed = [v for v in values if needs_typing(v.key, v.value)]
    kept = [v for v in values if not needs_typing(v.key, v.value)]
    row = unsuperseded_facts(student).filter(category=category, source_ref=ref).last()
    if row is None:
        row = _create(student, category, {_split(v.key)[1]: v.value for v in kept}, ref, False,
                      None)
    # Plan 1: the reading's values carry the final proven flag, and nothing here is confirmed.
    return [ReadValue(v.key, v.value, v.snippet, False, _NEW[category] if v.proven else v.why)
            for v in kept] + _waiting(typed, row)


def _attach(
    student: Membership, ref: str, row: VerifiedFact, fields: dict[str, ReadValue]
) -> list[ReadValue]:
    """A document's values against the one CONFIRMED row they belong to (spec §5.3.6,
    §6.2). A key the row lacks is filled from a proven value; an equal one stands; a
    differing one waits on the reading with the row as its target. What the row holds
    wins (D5), and a re-read never carries back a key the student owns (plan 1). A
    filled row takes this document's ref, so it can be corrected and names its source.
    Callers pass a confirmed row only: an unconfirmed CV claim is never built on."""
    own = (row.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT
           and row.source_ref.startswith("document:"))  # typed or adopted on the dashboard
    differs = "student_entry_differs" if own else "document_differs"
    filled = {f: v.value for f, v in fields.items() if v.proven and not _filled(row, f)}
    if filled:
        row = _student_row(student, row, {**row.payload, **filled}, ref=ref,
                           confirmed_by=row.confirmed_by, supersedes=row)
        _agent_read(row)
    out: list[ReadValue] = []
    for field, value in fields.items():
        # Only the institution is compared folded; a diploma number or a grade
        # differing in one character is a different value.
        same = _equal if field.startswith("institution_") else _same
        if field in filled or (_filled(row, field) and same(row.payload[field], value.value)):
            out.append(value)
        elif _filled(row, field):
            out.extend(_waiting([value], row, differs if value.proven else None))
        else:
            out.extend(_waiting([value], row))
    return out


def _proven_row(student: Membership, category: str, ref: str, values: list[ReadValue],
                waiting_row: VerifiedFact | None) -> list[ReadValue]:
    """The document's own confirmed row. A proof never confirms a waiting row in place
    (plan 1): it supersedes this document's earlier whole unconfirmed row instead."""
    proven = {_split(v.key)[1]: v.value for v in values if v.proven}
    row = _create(student, category, proven, ref, True, waiting_row)
    _agent_read(row)
    return [v for v in values if v.proven] + _waiting([v for v in values if not v.proven], row)


def _write_certificate(student: Membership, ref: str, values: list[ReadValue]) -> list[ReadValue]:
    if not values:
        return []
    proven = {_split(v.key)[1]: v.value for v in values if v.proven}
    # A test that names no one language (YDS: any of several) anchors on its name alone,
    # or every result of it would wait whole (final review M6).
    anchors = (("test_name",) if TESTS.get(str(proven.get("test_name"))) == ""
               else _ANCHORS["language"])
    if not all(key in proven for key in anchors):
        return _whole_unconfirmed(student, VerifiedFact.Category.LANGUAGE, ref, values)
    rows = list(unsuperseded_facts(student).filter(category=VerifiedFact.Category.LANGUAGE))
    sitting = next((r for r in reversed(rows) if r.source_ref == ref), None)
    if sitting is None:
        # The same sitting uploaded again as another document is still one sitting:
        # generation reads every LANGUAGE row as a language.
        # Same test and the same proven date or proven certificate number.

        def same_sitting(row: VerifiedFact) -> bool:
            return (_filled(row, "test_name")
                    and _same(row.payload["test_name"], proven["test_name"])
                    and any(key in proven and _filled(row, key)
                            and _same(row.payload[key], proven[key])
                            for key in ("test_date", "certificate_number")))

        sitting = next(
            (r for r in reversed(rows)
             if r.confirmed_at and r.source_ref.startswith("document:") and same_sitting(r)),
            None,
        )
    if sitting is None or sitting.confirmed_at is None:
        return _proven_row(student, VerifiedFact.Category.LANGUAGE, ref, values, sitting)
    return _attach(student, ref, sitting, {_split(v.key)[1]: v for v in values})


def _degree_match(row: VerifiedFact, institution: str, year: str) -> int:
    """2: same institution and graduation year; 1: same institution, one side has no
    year; 0: not this degree."""
    names = [row.payload.get("institution_original"), row.payload.get("institution_english")]
    if not any(isinstance(n, str) and n.strip() and _equal(n, institution) for n in names):
        return 0
    end = str(row.payload.get("end_date") or "")
    if year and end:
        return 2 if end.startswith(year) else 0
    return 1


def _write_diploma(student: Membership, ref: str, values: list[ReadValue]) -> list[ReadValue]:
    if not values:
        return []
    fields = {_split(v.key)[1]: v for v in values}
    anchor = fields.get("institution_original") or fields.get("institution_english")
    if anchor is None or not anchor.proven:
        return _whole_unconfirmed(student, VerifiedFact.Category.EDUCATION, ref, values)
    # Only a proven graduation date places a diploma: a misread year must not pick
    # the wrong degree.
    end = fields.get("end_date")
    year = end.value[:4] if end is not None and end.proven else ""
    rows = list(unsuperseded_facts(student).filter(category=VerifiedFact.Category.EDUCATION))
    waiting_row = next(
        (r for r in reversed(rows) if r.source_ref == ref and r.confirmed_at is None), None)
    # This document's own confirmed row is its degree, however a re-read or the
    # student's correction now spells the institution.
    own = next((r for r in reversed(rows) if r.source_ref == ref and r.confirmed_at), None)
    if own is not None:
        return _attach(student, ref, own, fields)
    # ponytail: when this document's whole unconfirmed row exists AND a CV degree matches,
    # the whole row stays beside it as a second, unconfirmed degree; supersede it here if
    # that case is ever seen.
    others = [r for r in rows if r is not waiting_row]
    scored = [(_degree_match(r, anchor.value, year), r) for r in others]
    best = max((score for score, _ in scored), default=0)
    matches = [r for score, r in scored if score and score == best]
    if len(matches) == 1 and matches[0].confirmed_at is not None:
        return _attach(student, ref, matches[0], fields)
    if not others:
        # The student's first degree: nothing it could duplicate.
        return _proven_row(student, VerifiedFact.Category.EDUCATION, ref, values, waiting_row)
    # A degree is already held, and this diploma is not proven to be it: two it could
    # be (a bachelor's and a master's at one university, undated), an unconfirmed CV
    # degree (never built on), or none by name (a translation, "BSU" on the CV). A
    # confirmed row here would be a second degree on every portal, so the student says.
    return _whole_unconfirmed(student, VerifiedFact.Category.EDUCATION, ref, values)


def tip_of(fact: VerifiedFact) -> VerifiedFact:
    """The current row of `fact`'s supersession chain."""
    while (nxt := VerifiedFact.objects.filter(supersedes=fact).first()) is not None:
        fact = nxt
    return fact


class AlreadySettled(FactNotFound):
    """The student's answer was already given (a repeated tap, a stale page): nothing to
    act on, as FactNotFound says, but the view answers 409, as for a racing write."""


def placed_whole_rows(student: Membership, facts: Iterable[VerifiedFact]) -> set[UUID]:
    """The ids among `facts` of whole-document rows already placed: unconfirmed EDUCATION
    or LANGUAGE rows of a document a confirmed current row of the same category already
    carries (a merge, a proof, an attach). The append-only ledger keeps them, so every
    door that could confirm or offer one asks here -- confirming one would be a second
    degree or sitting for one document (build ruling 1, fix round 1)."""
    carried = set(
        unsuperseded_facts(student)
        .filter(category__in=PER_ROW, confirmed_at__isnull=False,
                source_ref__startswith="document:")
        .values_list("category", "source_ref")
    )
    return {f.id for f in facts
            if f.category in PER_ROW and f.confirmed_at is None
            and (f.category, f.source_ref) in carried}


def _latest_reading(student: Membership, document_id: UUID) -> DocumentReading | None:
    """The document's latest READ reading: the one the dashboard shows and answers."""
    return DocumentReading.objects.filter(
        student=student, document_id=document_id, state=DocumentReading.State.READ,
    ).order_by("created_at").last()


def _waiting_entry(
    student: Membership, reading_id: UUID, key: str
) -> tuple[DocumentReading, dict[str, object]]:
    # Locked: `_settle` rewrites the whole values list, and two answers on one reading
    # (two tabs) would otherwise drop the earlier one's mark (final review M3).
    reading = DocumentReading.objects.select_for_update().filter(
        id=reading_id, student=student).first()
    if reading is None or _latest_reading(student, reading.document_id) != reading:
        # An older reading's value is not on the page (fix round 1, p8).
        raise FactNotFound("not the latest reading of this student's document")
    waiting = [v for v in reading.values or []
               if v.get("key") == key and not v.get("proven") and v.get("target")]
    entry = next((v for v in waiting if v.get("why") not in _SETTLED), None)
    if entry is None:
        if waiting:
            raise AlreadySettled(key)
        raise FactNotFound("no waiting value of this student's reading")
    return reading, entry


def needs_typing(key: str, value: object) -> bool:
    """A value no tap may write: one the ledger cannot hold as printed (a date the code
    could not normalise). The student types it instead (final review I3)."""
    try:
        _valid(_split(key)[1], str(value))
    except ValueError:
        return True
    return False


def adopt_document_value(
    *, student: Membership, reading_id: UUID, key: str, value: str | None = None
) -> VerifiedFact:
    """Use the document's value for one key of the row it targets (spec §3 "Use"): the
    student's own superseding row on the CURRENT tip of that row. A racing write on the
    same tip raises IntegrityError (one superseder per row); the view answers 409. With
    `value`, the student's typed value instead, taken only for a `date_unclear` entry --
    the only way to answer a value `needs_typing`; either is checked as `correct_fact`
    checks it (ValueError)."""
    reading, entry = _waiting_entry(student, reading_id, key)
    target = VerifiedFact.objects.filter(id=str(entry["target"]), student=student).first()
    if target is None:
        raise FactNotFound("the targeted row is gone")
    tip = tip_of(target)
    if tip.confirmed_at is None:
        # Superseding it would confirm every claim it holds by one tap on one value.
        raise FactNotFound("the targeted row is not confirmed")
    field = _split(key)[1]
    if value is not None and entry.get("why") != "date_unclear":
        # Concern ruling 3: elsewhere a typed value is a correction, with its own path.
        raise ValueError("invalid_value")
    chosen = _valid(field, str(entry["value"]) if value is None else value)
    adopted = _student_row(
        student, tip, {**tip.payload, field: chosen}, supersedes=tip, confirmed_by=student,
        tier=VerifiedFact.SourceTier.STUDENT_STATEMENT)
    record_event(actor=student, event="fact.adopted", object_id=adopted.id)
    _settle(reading, key, "adopted")
    if adopted.category in PER_ROW:
        from .profile_bridge import sync_facts_to_profile

        sync_facts_to_profile(student)
    return adopted


def dismiss_document_value(*, student: Membership, reading_id: UUID, key: str) -> None:
    reading, _entry = _waiting_entry(student, reading_id, key)
    _settle(reading, key, "kept")


def _may_be(whole: VerifiedFact, row: VerifiedFact) -> bool:
    """Whether `row` could be the sitting (same test) or the degree (same institution by
    name) a whole-document row is."""
    if whole.category == VerifiedFact.Category.LANGUAGE:
        test = whole.payload.get("test_name")
        return (_filled(row, "test_name") and test is not None
                and _same(row.payload["test_name"], test))
    return any(isinstance(name, str) and name.strip() and _degree_match(row, name, "") > 0
               for name in (whole.payload.get("institution_original"),
                            whole.payload.get("institution_english")))


def _unconfirmed_claims(student: Membership, whole: VerifiedFact) -> list[VerifiedFact]:
    """A CV's unconfirmed degrees or sittings a whole-document row may be (final review
    I2). Never a merge target: a diploma attaches only to a confirmed row."""
    return [r for r in unsuperseded_facts(student)
            .filter(category=whole.category, confirmed_at__isnull=True)
            .exclude(source_ref__startswith="document:") if _may_be(whole, r)]


def held_whole_rows(student: Membership, facts: Iterable[VerifiedFact]) -> set[UUID]:
    """The ids among `facts` of whole-document rows that an unconfirmed CV degree or sitting
    may be. Confirming one now would be a second degree the moment the student confirms
    that CV row, so `confirm_facts` skips them and the page does not show them: the line
    waits until the CV row is confirmed, then asks "Is this a new degree?" with "No --
    it's my <degree>" onto that confirmed row (final review I2, concern ruling 1)."""
    return {f.id for f in facts
            if f.category in PER_ROW and f.confirmed_at is None
            and f.source_ref.startswith("document:") and _unconfirmed_claims(student, f)}


def merge_targets(student: Membership, whole: VerifiedFact) -> list[VerifiedFact]:
    """The confirmed degrees (or sittings of the same test) a whole-document row may be
    one of (build ruling 1). Confirmed only: a merge never confirms a CV claim."""
    rows = [r for r in unsuperseded_facts(student).filter(
        category=whole.category, confirmed_at__isnull=False) if r.id != whole.id]
    if whole.category == VerifiedFact.Category.LANGUAGE:
        rows = [r for r in rows if _may_be(whole, r)]
    return rows


def merge_whole_document(*, student: Membership, fact_id: UUID, into_id: UUID) -> VerifiedFact:
    """"No, it's my <degree>" (build ruling 1): a whole-document row is one the student
    already holds, so its values go into that confirmed row through `_attach` -- a proven
    value fills an empty key, an equal one stands, the rest wait as details to check --
    and never become a second degree. The result carries the document's ref, which binds
    the document to that row: a re-read attaches to it (`_write_diploma`'s own row), and
    the whole row, which an append-only ledger cannot retire, is placed
    (`placed_whole_rows`): never offered, confirmed or merged again."""
    # Locked as confirm_facts locks it: "Yes, add it" and this merge racing on one row
    # would otherwise both pass their checks -- two degrees (final review M4).
    whole = VerifiedFact.objects.select_for_update().filter(
        id=fact_id, student=student, category__in=PER_ROW,
        source_ref__startswith="document:").first()
    if whole is None or whole.source_ref in (disowned_refs(student) | retired_refs(student)):
        raise FactNotFound("not a whole-document row of this student")
    if (whole.confirmed_at is not None
            or VerifiedFact.objects.filter(supersedes=whole).exists()
            or placed_whole_rows(student, [whole])):
        raise AlreadySettled(str(fact_id))  # added, corrected or merged already
    into = next((r for r in merge_targets(student, whole) if r.id == into_id), None)
    reading = _latest_reading(student, UUID(whole.source_ref.removeprefix("document:")))
    if into is None or reading is None:
        raise FactNotFound("not a confirmed row of this student")
    ref, prefix = whole.source_ref, f"{whole.category.lower()}."
    new = _NEW[whole.category]
    read = {str(d.get("key", "")): ReadValue.from_dict(d) for d in reading.values or []}
    # What the student saw is the row's payload. A value is proven only where the latest
    # reading proved that same value (`_whole_unconfirmed` wrote those as `new_degree`/
    # `new_result`); a re-read that changed it since proves nothing and it waits.
    fields: dict[str, ReadValue] = {}
    for field, value in whole.payload.items():
        if not isinstance(value, str) or not value.strip():
            continue
        r = read.get(prefix + field)
        same = r is not None and _same(r.value, value)
        proven = same and r is not None and r.why == new
        why = "readers_agree" if proven else (r.why if same and r is not None
                                              else "readers_disagree")
        fields[field] = ReadValue(prefix + field, value, r.snippet if same and r else "",
                                  proven, why)
    attached = _attach(student, ref, into, fields)
    tip = tip_of(into)
    if tip.source_ref != ref:
        # Nothing filled: the row still takes this document's ref, or it is not bound.
        # ponytail: if the row was bound to another document (a translation), a later
        # re-read of that one no longer finds its own row and can re-ask "Is this a new
        # degree?"; a row bound to several documents is the fix, deferred.
        tip = _student_row(student, tip, tip.payload, ref=ref,
                           confirmed_by=tip.confirmed_by, supersedes=tip)
    record_event(actor=student, event="fact.merged", object_id=tip.id)
    others = [ReadValue.from_dict(d) for d in reading.values or []
              if str(d.get("key", "")) not in {v.key for v in fields.values()}]
    reading.values = [v.as_dict() for v in _answered(reading, others + attached)]
    reading.save(update_fields=["values", "updated_at"])
    from .profile_bridge import sync_facts_to_profile

    sync_facts_to_profile(student)
    return tip


def _settle(reading: DocumentReading, key: str, why: str) -> None:
    """The student's answer to one waiting value. `proven` stays False: a tap is the
    student's choice, never a proof (plan 1: reading.values carry the final proven/why),
    and the ledger row carries the value."""
    reading.values = [
        {**v, "why": why}
        if v.get("key") == key and not v.get("proven") and v.get("target")
        and v.get("why") not in _SETTLED
        else v
        for v in reading.values
    ]
    reading.save(update_fields=["values", "updated_at"])


def _answered(reading: DocumentReading, values: list[ReadValue]) -> list[ReadValue]:
    """A value the student already answered (Use or Keep mine) on an earlier reading,
    for the same row's chain and the same key, is settled again, never re-offered."""
    waiting = [v for v in values if v.target and not v.proven]
    if not waiting:
        return values
    answers: dict[tuple[str, str], list[tuple[object, str]]] = {}
    for earlier in DocumentReading.objects.filter(student=reading.student).exclude(id=reading.id):
        for v in earlier.values or []:
            if v.get("why") in _SETTLED and v.get("target"):
                answers.setdefault((str(v["key"]), str(v["target"])), []).append(
                    (v.get("value"), str(v["why"])))
    if not answers:
        return values
    tips: dict[str, str | None] = {}

    def chain(target: str) -> str | None:
        if target not in tips:
            row = VerifiedFact.objects.filter(id=target, student=reading.student).first()
            tips[target] = str(tip_of(row).id) if row is not None else None
        return tips[target]

    out: list[ReadValue] = []
    for v in values:
        why = next(
            (answer for (key, target), given in answers.items()
             if key == v.key and v.target and not v.proven
             and chain(target) == chain(v.target)
             for value, answer in given if _same(value, v.value)),
            None,
        )
        out.append(ReadValue(v.key, v.value, v.snippet, False, why, target=v.target)
                   if why else v)
    return out


def _create(
    student: Membership,
    category: str,
    payload: dict[str, str],
    ref: str,
    proven: bool,
    supersedes: VerifiedFact | None,
) -> VerifiedFact:
    now = timezone.now()
    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref=ref,
        confirmed_by=student if proven else None,
        confirmed_at=now if proven else None,
        supersedes=supersedes,
        created_by=student,
    )


def _valid(field: str, value: str) -> str:
    value = " ".join(value.split())
    if not value or len(value) > _MAX_VALUE:
        raise ValueError("invalid_value")
    if field.endswith("date") or field == "date_of_birth":
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise ValueError("invalid_value") from None
    if field == "sex":
        if value.upper() not in _SEXES:
            raise ValueError("invalid_value")
        return value.upper()
    return value


def correct_fact(*, student: Membership, fact_id: UUID, key: str, value: str) -> VerifiedFact:
    """The student's own value for one key of a document-read fact: a one-key
    STUDENT_STATEMENT row, confirmed by them, keeping the document's source_ref so
    an ID document's keys stay together. It supersedes a one-key row; a multi-key
    row (an ID document's merged read) stays, and the per-key merge
    (verification.id_document_groups) serves the typed key from the student's row
    and the rest from the reads -- so a later read of the same passport still
    renews the keys the student never typed. An EDUCATION or LANGUAGE row is one
    degree or one sitting, so it is superseded with the merged payload instead, as
    `adopt_document_value` does."""
    fact = (
        unsuperseded_facts(student)
        .filter(id=fact_id, source_ref__startswith="document:")
        .first()
    )
    if fact is None or key not in fact.payload or key not in payload_keys(fact.category):
        raise FactNotFound("not a document-read fact of this student")
    if fact.category in PER_ROW and fact.confirmed_at is None:
        # A whole-document row: a correction would confirm every value in it and skip
        # "Is this a new degree?" (final review I1). The page offers no Correct on it.
        raise FactNotFound("a whole-document row is answered whole")
    valid = _valid(key, value)
    if fact.category == VerifiedFact.Category.ID_DOCUMENT and key == "number":
        valid = document_number(valid)
    corrected = _student_row(
        student, fact,
        {**fact.payload, key: valid} if fact.category in PER_ROW else {key: valid},
        tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, confirmed_by=student,
        supersedes=fact if fact.category in PER_ROW or len(fact.payload) == 1 else None)
    record_event(actor=student, event="fact.corrected", object_id=corrected.id)
    if corrected.category in PER_ROW:
        from .profile_bridge import sync_facts_to_profile

        sync_facts_to_profile(student)
    return corrected


#: What the panel's one tap may confirm: one waiting value of the student's ID
#: document. A diploma's or certificate's doubtful values are answered on the
#: dashboard (adopt_document_value, or the whole row), never by one tap on one box,
#: so a whole-document row (placed_whole_rows, held_whole_rows) cannot reach here.
ONE_TAP = frozenset({VerifiedFact.Category.IDENTITY, VerifiedFact.Category.ID_DOCUMENT})


def is_one_tap_row(fact: VerifiedFact) -> bool:
    """A waiting one-value ID-category row read from a document. This routes a Use;
    it does not say the tap may write it (use_document_value also refuses a value
    that needs_typing, so such a Use is refused, never confirmed in place)."""
    return (
        fact.confirmed_at is None
        and fact.category in ONE_TAP
        and fact.source_ref.startswith("document:")
        and len(fact.payload) == 1
    )


def use_document_value(*, student: Membership, fact_id: UUID) -> VerifiedFact:
    """The student's Use on a waiting document-read row (spec 2026-10-12 §7.3, the
    panel's one tap and the dashboard's Use on a passport value): a new confirmed row
    carrying it, superseding the waiting one. Never confirmed in place:
    verified_values and id_document_groups let the newest row win, and a row confirmed
    in place keeps its old created_at, so it could lose to a row written after it
    (plan 1 final review; plan 2 ruling). The tier and the document ref are the
    read's: the value is still the document's, and is marked so. Only this student's
    own waiting row of a document neither disowned (owner_mismatch) nor replaced
    (retired); it does not itself re-check owner_unknown, which the panel route gets
    from document_offers and the dashboard from hiding the row. A racing second Use
    raises
    IntegrityError (one superseder per row)."""
    fact = (
        unsuperseded_facts(student)
        .filter(id=fact_id)
        .exclude(source_ref__in=disowned_refs(student) | retired_refs(student))
        .first()
    )
    if (
        fact is None
        or not is_one_tap_row(fact)
        or any(needs_typing(f"{fact.category.lower()}.{k}", v) for k, v in fact.payload.items())
    ):
        raise FactNotFound("no waiting document value of this student")
    whys = latest_whys(student)
    if any(whys.get((fact.source_ref, f"{fact.category.lower()}.{k}")) in OWNER_UNCHECKED
           for k in fact.payload):
        raise FactNotFound("a value of an unchecked owner is offered nowhere")
    used = _student_row(student, fact, fact.payload, confirmed_by=student, supersedes=fact)
    record_event(actor=student, event="fact.confirmed", object_id=used.id)
    return used
