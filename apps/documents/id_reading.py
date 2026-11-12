"""What a passport or ID card read proves (spec 2026-10-12 §5.2). Pure: an Azure
prebuilt-idDocument answer in, values with their proof out. No model reads a
passport; the proof is the strip's own check digits and agreement between the
strip and the printed page, or Azure's confidence where the strip is silent."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from typing import TYPE_CHECKING

from . import mrz
from .azure_layout import AzureField, AzureIdResult

if TYPE_CHECKING:
    from apps.portals.models import Application
    from apps.tenancy.models import Membership

ID_TYPES = {
    "idDocument.passport": "passport",
    "idDocument.nationalIdentityCard": "national_id",
    "idDocument.residencePermit": "residence_permit",
}
_SNIPPET = 200
#: Why-codes of a reading that could not tie the document to this student: its values
#: are offered on no surface.
OWNER_UNCHECKED = frozenset({"owner_unknown", "owner_mismatch"})


@dataclass(frozen=True)
class ReadValue:
    key: str
    value: str
    snippet: str
    proven: bool
    why: str
    #: The fact id a doubtful value would change (plan 2: a diploma value for a CV
    #: degree row). Empty for a value that stands alone.
    target: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ReadValue:
        return cls(key=str(data["key"]), value=str(data["value"]), snippet=str(data["snippet"]),
                   proven=bool(data["proven"]), why=str(data["why"]),
                   target=str(data.get("target", "")))


class NotRead(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _confident(field: AzureField, result: AzureIdResult, threshold: float) -> bool:
    if field.confidence < threshold:
        return False
    spans = [(span.offset, span.offset + span.length) for span in field.spans]
    words = [word for page in result.pages for word in page.words
             if any(start <= word.span.offset < end for start, end in spans)]
    return bool(words) and all(word.confidence >= threshold for word in words)


def _iso(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def read_id(
    result: AzureIdResult,
    *,
    known_names: list[str],
    threshold: float,
    today: date,
    known_birth_date: str | None = None,
) -> list[ReadValue]:
    candidates = [d for d in result.documents if d.docType in ID_TYPES]
    if not candidates:
        raise NotRead("not_an_id_document" if result.documents else "no_data_page")

    def parsed(doc: object) -> mrz.Strip | None:
        zone_field = getattr(doc, "fields", {}).get("MachineReadableZone")
        return mrz.parse(zone_field.content) if zone_field is not None else None

    # With several identity documents, prefer the one whose strip is sound.
    document = next((d for d in candidates if (st := parsed(d)) and st.composite_ok),
                    candidates[0])
    fields = document.fields
    zone = fields.get("MachineReadableZone")
    strip = parsed(document)
    sound = strip is not None and strip.composite_ok
    values: list[ReadValue] = []

    def printed(name: str) -> AzureField | None:
        found = fields.get(name)
        return found if found is not None and found.text() else None

    def add(key: str, value: str, snippet: str, proven: bool, why: str) -> None:
        if value:
            if proven and len(value) > _SNIPPET:
                proven, why = False, "low_confidence"
            values.append(ReadValue(key, value, snippet[:_SNIPPET], proven, why))

    def strip_why(agrees: bool) -> str:
        if strip is None:
            return "no_strip"
        return "check_digit" if sound and agrees else "strip_disagrees"

    # Values a check digit covers: proven by the digit AND the printed page.
    number = printed("DocumentNumber")
    if number is not None:
        text = number.text().replace(" ", "")
        agrees = sound and strip is not None and strip.number == text
        add("id_document.number", text, number.content, agrees, strip_why(agrees))
    for key, name, attr, birth in (
        ("identity.date_of_birth", "DateOfBirth", "birth", True),
        ("id_document.expiry_date", "DateOfExpiration", "expiry", False),
    ):
        page = printed(name)
        yymmdd = getattr(strip, attr) if strip is not None else None
        on_page = _iso(page.text()) if page is not None else None
        if on_page is not None:
            agrees = sound and yymmdd is not None and mrz.printed_agrees(yymmdd, on_page)
            why = strip_why(agrees)
            if agrees and not _plausible(key, on_page, today):
                agrees, why = False, "implausible"
            add(key, on_page.isoformat(), page.content if page else "", agrees, why)
        elif yymmdd is not None:
            from_strip = mrz.date_from_strip(yymmdd, birth=birth, today=today)
            if from_strip is not None:
                add(key, from_strip.isoformat(), zone.content if zone else "", False,
                    "low_confidence")

    # Values outside every digit: proven only by the strip and the page agreeing.
    sex = printed("Sex")
    if sex is not None:
        page_sex = sex.text()[:1].upper()
        strip_sex = strip.sex if strip is not None else ""
        agrees = (sound and strip_sex in ("M", "F", "<", "X") and page_sex in ("M", "F", "X")
                  and page_sex == strip_sex.replace("<", "X"))
        add("identity.sex", page_sex, sex.content, agrees,
            "strip_agrees" if agrees else ("no_strip" if strip is None else "strip_disagrees"))
    for key, name, attr in (
        ("identity.citizenship", "Nationality", "nationality"),
        ("id_document.issuing_country", "CountryRegion", "issuing_state"),
    ):
        page = printed(name)
        if page is None:
            continue
        code = page.text().upper()
        name_text = mrz.country_name_for(code)
        stripped = getattr(strip, attr) if strip is not None else ""
        if code in mrz.NO_CITIZENSHIP or stripped in mrz.NO_CITIZENSHIP:
            add(key, code, page.content, False, "no_citizenship")
            continue
        if name_text is None:
            add(key, code, page.content, False, "unknown_country")
            continue
        strip_name = mrz.country_name_for(getattr(strip, attr)) if strip is not None else None
        agrees = sound and strip_name == name_text
        add(key, name_text, page.content, agrees,
            "strip_agrees" if agrees else ("no_strip" if strip is None else "strip_disagrees"))
    for key, name, attr in (
        ("identity.surname", "LastName", "surname"),
        ("identity.given_names", "FirstName", "given_names"),
    ):
        page = printed(name)
        if page is None:
            continue
        truncated = strip.names_truncated if strip is not None else False
        if attr == "surname" and strip is not None:
            # A surname is cut only when the field ran out before "<<" ever came.
            truncated = truncated and strip.given_names == ""
        agrees = sound and strip is not None and mrz.names_agree(
            page.text(), getattr(strip, attr), truncated=truncated
        )
        add(key, page.text(), page.content, agrees,
            "strip_agrees" if agrees else ("no_strip" if strip is None else "strip_disagrees"))
    document_type = ID_TYPES[document.docType]
    strip_type = {"TD3": "passport"}.get(strip.format, "card") if strip is not None else ""
    type_agrees = sound and (strip_type == document_type
                             or (strip_type == "card" and document_type != "passport"))
    add("id_document.document_type", document_type, document.docType, type_agrees,
        "strip_agrees" if type_agrees else ("no_strip" if strip is None else "strip_disagrees"))

    # Values the strip does not carry: proven only by Azure's confidence.
    for key, name in (
        ("identity.place_of_birth", "PlaceOfBirth"),
        ("id_document.issue_date", "DateOfIssue"),
        ("id_document.issuing_authority", "IssuingAuthority"),
    ):
        page = printed(name)
        if page is None:
            continue
        value = page.text()
        parsed_date = None
        if key.endswith("_date"):
            parsed_date = _iso(value)
            if parsed_date is None:
                continue
            value = parsed_date.isoformat()
        confident = _confident(page, result, threshold)
        why = "confident" if confident else "low_confidence"
        if confident and parsed_date is not None and not _plausible(key, parsed_date, today):
            confident, why = False, "implausible"
        add(key, value, page.content, confident, why)

    dob_value = next(
        (v.value for v in values if v.key == "identity.date_of_birth" and v.proven), None
    )
    dob_mismatch = bool(
        known_birth_date and dob_value and dob_value != known_birth_date.strip()
    )
    named = [n for n in known_names if n.strip()]
    if not named:
        # No name to check it against (an account made without one): nothing is
        # proven, or the first passport uploaded -- anyone's -- would be.
        values = [replace(v, proven=False, why="owner_unknown") for v in values]
    elif dob_mismatch or not _owner_matches(values, named, strip if sound else None):
        values = [replace(v, proven=False, why="owner_mismatch") for v in values]
    return values


def _plausible(key: str, value: date, today: date) -> bool:
    """A date the document could really carry; an implausible one is never proven."""
    def years(n: int) -> date:
        return today.replace(year=today.year + n, day=min(today.day, 28))
    if key == "identity.date_of_birth":
        return years(-120) < value <= today
    if key == "id_document.expiry_date":
        return years(-10) < value <= years(20)
    return value <= today  # issue date


def _words(text: str) -> list[str]:
    return text.replace("-", " ").split()


#: "<father> qızı/oğlu": the marker and the father's name before it.
_PATRONYMIC_MARKERS = frozenset({"QIZI", "OGLU", "KIZI", "OGLY", "KYZY", "UULU", "GIZI",
                                 "GYZY"})
#: Russian and Ukrainian patronymics. Note the H: Balkan -ović/-ević surnames
#: fold to -OVIC/-EVIC and are never dropped.
_PATRONYMIC_ENDINGS = ("OVICH", "EVICH", "OVNA", "EVNA", "ICHNA", "OVYCH", "IVNA")


def _known_words(name: str) -> tuple[list[str], int]:
    """A known name's words without its patronymic, and how many words it had.
    An ending marks a patronymic only in a name of three or more words and never
    in the first word, so "Roman Abramovich" keeps its surname and "Ivna Marija
    Horvat" her given name."""
    words = _words(name)
    folded = [mrz.fold_tokens(word) for word in words]
    dropped: set[int] = set()
    for index, forms in enumerate(folded):
        if forms & _PATRONYMIC_MARKERS:
            dropped |= {index, index - 1}
        elif index and len(words) >= 3 and any(
                f.endswith(_PATRONYMIC_ENDINGS) for f in forms):
            dropped.add(index)
    return [w for index, w in enumerate(words) if index not in dropped], len(words)


def _owner_matches(values: list[ReadValue], known_names: list[str],
                   strip: mrz.Strip | None = None) -> bool:
    """Spec §5.2.4: the read belongs to the student we hold names for. One known
    name must vouch for both halves: its first or last word equals the first
    given name up to spelling (surname-first order works), and a surname word
    matches another of its words -- never one that equals the given name, so
    Marko Marković does not own MARKO MARKOV. Given name alone fails a namesake;
    surname alone fails a parent; two halves from two different known names fail
    both. Only when every known name is one word does the given name decide
    alone. A strip fills in what the page lacks."""
    def printed(key: str) -> str:
        return next((v.value for v in values if v.key == key), "")

    given_words = _words(printed("identity.given_names") or (strip.given_names if strip else ""))
    surname_words = _words(printed("identity.surname") or (strip.surname if strip else ""))
    if not given_words:
        return False
    first = given_words[0]

    def given_ok(words: list[str]) -> bool:
        return bool(words) and any(mrz.same_given_name(first, words[j]) for j in (0, -1))

    known = [_known_words(name) for name in known_names]
    full = [words for words, count in known if count > 1]
    if not full:
        return any(given_ok(words) for words, _ in known)
    return any(
        mrz.same_name_token(surname, word)
        for words in full if given_ok(words)
        for word in words if not mrz.same_given_name(first, word)
        for surname in surname_words
    )


_ALPHA_WORD = re.compile(r"[^\W\d_]+")


def owner_matches_full_name(candidate_name: str, known_names: Iterable[str]) -> bool:
    """Whether `candidate_name` (a full name from a CV or transcript label) matches
    at least one known owner name on both given name and surname."""
    cand_words, _ = _known_words(candidate_name)
    if len(cand_words) < 2:
        return False
    known = [
        words
        for name in known_names
        if name.strip()
        for words, count in (_known_words(name),)
        if count > 1 and len(words) >= 2
    ]
    if not known:
        return True
    for words in known:
        for cand_given in (cand_words[0], cand_words[-1]):
            if not any(mrz.same_given_name(cand_given, words[j]) for j in (0, -1)):
                continue
            if any(
                mrz.same_name_token(cand_surname, word)
                for word in words
                if not mrz.same_given_name(cand_given, word)
                for cand_surname in cand_words
                if not mrz.same_given_name(cand_given, cand_surname)
            ):
                return True
    return False


def owner_matches_document_text(text: str, known_names: Iterable[str]) -> bool:
    """Whether `text` (unstripped OCR text of a certificate, diploma, or transcript)
    contains both a given-name token and a surname token from at least one 2+ word
    known owner name."""
    known = [
        words
        for name in known_names
        if name.strip()
        for words, count in (_known_words(name),)
        if count > 1 and len(words) >= 2
    ]
    if not known:
        return True
    doc_words = _ALPHA_WORD.findall(text)
    if not doc_words:
        return False
    for words in known:
        for g_idx in (0, -1):
            given = words[g_idx]
            if not any(mrz.same_given_name(dw, given) for dw in doc_words):
                continue
            if any(
                mrz.same_name_token(dw, s_word)
                for s_word in words
                if not mrz.same_given_name(given, s_word)
                for dw in doc_words
                if not mrz.same_given_name(dw, given)
            ):
                return True
    return False


def known_owner_names(student: Membership, *, exclude_ref: str = "") -> list[str]:
    """Whole names held for `student`: account full name, confirmed IDENTITY full_name,
    and confirmed passport given_names + surname."""
    from .models import VerifiedFact
    from .verification import disowned_refs, unsuperseded_facts

    disowned = disowned_refs(student)
    names = [student.user.get_full_name()]
    parts: dict[str, dict[str, str]] = {}
    qs = (
        unsuperseded_facts(student)
        .filter(category=VerifiedFact.Category.IDENTITY, confirmed_at__isnull=False)
        .exclude(source_ref__in=disowned)
    )
    if exclude_ref:
        qs = qs.exclude(source_ref=exclude_ref)
    for fact in qs:
        full = fact.payload.get("full_name")
        if isinstance(full, str) and full.strip():
            names.append(full)
        if fact.source_ref.startswith("document:"):
            for key in ("given_names", "surname"):
                value = fact.payload.get(key)
                if isinstance(value, str) and value.strip():
                    parts.setdefault(fact.source_ref, {})[key] = value
    for document in parts.values():
        if document.get("given_names") and document.get("surname"):
            names.append(f"{document['given_names']} {document['surname']}")
    result = [name for name in names if name.strip()]
    if not any(len(n.split()) >= 2 for n in result):
        unconfirmed_qs = (
            unsuperseded_facts(student)
            .filter(
                category=VerifiedFact.Category.IDENTITY,
                confirmed_at__isnull=True,
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            )
            .exclude(source_ref__in=disowned)
        )
        if exclude_ref:
            unconfirmed_qs = unconfirmed_qs.exclude(source_ref=exclude_ref)
        for fact in unconfirmed_qs:
            full = fact.payload.get("full_name")
            if isinstance(full, str) and len(full.split()) >= 2:
                result.append(full.strip())
    return result


def owner_birth_date(student: Membership, *, exclude_ref: str = "") -> str | None:
    """The student's locked date of birth (YYYY-MM-DD) from their confirmed IDENTITY
    facts or latest full profile (`schema_version=3`), if any."""
    from apps.accounts.models import StudentProfileVersion

    from .models import VerifiedFact
    from .verification import unsuperseded_facts

    qs = unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.IDENTITY,
        confirmed_at__isnull=False,
        payload__has_key="date_of_birth",
    )
    if exclude_ref:
        qs = qs.exclude(source_ref=exclude_ref)
    for fact in reversed(list(qs)):
        dob = fact.payload.get("date_of_birth")
        if isinstance(dob, str) and dob.strip():
            return dob.strip()
    version = (
        StudentProfileVersion.objects.filter(student=student, schema_version=3)
        .order_by("-version")
        .first()
    )
    if version is not None and isinstance(version.snapshot, dict):
        dob = version.snapshot.get("date_of_birth")
        if isinstance(dob, str) and dob.strip():
            return dob.strip()
    return None


def raise_identity_mismatch_alert(
    student: Membership,
    *,
    message: str,
    stage: str = "DOCUMENTS",
    application: Application | None = None,
) -> None:
    """Notify the student's active counsellor (if any) of an identity mismatch,
    deduped by open message text."""
    from django.utils import timezone

    from apps.concierge.models import Notification
    from apps.tenancy.models import CounselorAssignment

    assignment = (
        CounselorAssignment.objects.filter(student=student, active=True)
        .select_related("counselor")
        .first()
    )
    if assignment is None:
        return
    if Notification.objects.filter(
        roadmap_item__student=student,
        recipient=assignment.counselor,
        acknowledged_at__isnull=True,
        message=message[:500],
    ).exists():
        return
    Notification.raise_card(
        student=student,
        recipient=assignment.counselor,
        owner=assignment.counselor,
        stage=stage,
        deadline=timezone.now() + timedelta(days=2),
        application=application,
        message=message[:500],
    )

