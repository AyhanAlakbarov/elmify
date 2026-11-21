"""Gap notes: read-only notes surfaced to the counsellor/student for unanswerable gaps."""

from __future__ import annotations

from apps.documents.gaps.models import GapNote, _current, _cv_on_file
from apps.documents.models import VerifiedFact
from apps.tenancy.models import Membership

#: Sections the catalog wants and this ledger cannot hold.
#:
#: Certificates and training (S-036, from Queensland, Toronto, Berkeley and
#: German guidance) is a real gap and an unanswerable question: there is no
#: VerifiedFact category for a certificate, no CVContent entry and no
#: template section. That absence IS S-036's complaint -- the real CV filed a
#: summer school under Awards because there was nowhere else -- and it is why
#: this is a note. A CERTIFICATE category is its own change: a model choice,
#: a _CategorySpec, a schema entry, _PAYLOAD_KEYS, an ingestion sentence, a
#: render section and a Europass mapping.
_CERTIFICATES_NOTE = GapNote(
    text=(
        "Certificates, licences, professional registration and short courses "
        "belong in their own section, and this CV has nowhere to put them yet. "
        "If you hold any, keep the paperwork -- we will ask once there is a "
        "place for it."
    ),
    evidence=(
        "Queensland, Toronto, Berkeley and German guidance all list a "
        "certificates or training section; nothing on file holds one."
    ),
)


def gap_notes(student: Membership) -> tuple[GapNote, ...]:
    """Everything worth showing that nobody is asked to answer.

    One detector left. Timeline gaps were the other, until the TIMELINE
    category gave their answer somewhere to live.
    """
    if _cv_on_file(student) and not _current(student, VerifiedFact.Category.CERTIFICATION):
        return (_CERTIFICATES_NOTE,)
    return ()
