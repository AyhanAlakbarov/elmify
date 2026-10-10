"""One Jev reading of a mail about an application, that abstains (spec §4).

TypeSafe's Jev through OpenRouter (apps.research.decisions.ask, decision
"mail_decision"), owner decision 2026-10-04 (docs/legal/2026-09-provider-terms.md).
The mitigation is in this module: the student's name words, every email address
and every phone number are replaced before the state is built, and ask() runs
with record=False so no student text reaches the shared DecisionRecord.
Jev generates no text; the classifier's quotes are kept only when code finds
them in the email (rule 14).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings

from apps.documents.transcript import _fold, _nfc, personal_names
from apps.mailbox import decision_bars as bars
from apps.mailbox.classify import MailVerdict
from apps.mailbox.providers import MAX_BODY_CHARS
from apps.ratelimit import rate_limited
from apps.research.decisions import Answer, Client, ask, provider_for

from .decision_questions import DECISION, FUNDING_TO_OUTCOME, questions

if TYPE_CHECKING:
    from apps.mailbox.models import MailSignal

logger = logging.getLogger(__name__)

#: Forty an hour per student, the classifier's own ceiling: one reading per message.
READ_LIMIT = 40
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
#: "/" is a separator too: 0176/12345678 is how a German number is written.
_PHONE_RE = re.compile(r"(?<![\w-])\+?\d[\d\s()./-]{6,}\d(?![\w-])")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


@dataclass(frozen=True)
class DecisionReading:
    is_decision: bool | None
    outcome: str
    funding_outcome: str
    other_programme_offered: bool | None
    p: Mapping[str, float] = field(default_factory=dict)
    #: The bars were learned; only then is an outcome recorded automatically.
    measured: bool = False
    unavailable: bool = False

    def as_json(self) -> dict[str, Any]:
        return {**asdict(self), "p": dict(self.p)}


UNAVAILABLE = DecisionReading(None, "", "", None, unavailable=True)


def strip_identifiers(text: str, *, names: frozenset[str], addresses: Iterable[str] = ()) -> str:
    """The student's name words, every email address and every phone number, replaced.

    A run of nine or more digits is a phone number; an ISO date (eight digits) is not.
    Composed to NFC first, as personal_names composed the names: a decomposed İ
    would otherwise split a name word in two before it is folded.
    """
    text = _nfc(text)
    for address in addresses:
        if address:
            text = re.sub(re.escape(address), "[email]", text, flags=re.IGNORECASE)
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub(
        lambda m: "[phone]" if sum(c.isdigit() for c in m.group()) >= 9 else m.group(), text
    )
    return re.sub(r"\w+", lambda m: "[name]" if _fold(m.group()) in names else m.group(), text)


def _norm(text: str) -> str:
    return " ".join(text.translate(_QUOTES).split()).casefold()


def verified(phrase: str, body: str) -> bool:
    """Rule 14: a quote is checked by code, never by a model."""
    return bool(phrase.strip()) and _norm(phrase) in _norm(body)


def keep_verified(verdict: MailVerdict, body: str) -> MailVerdict:
    return verdict.model_copy(update={
        "document_name": verdict.document_name if verified(verdict.document_name, body) else "",
        "offered_programme": (
            verdict.offered_programme if verified(verdict.offered_programme, body) else ""
        ),
        "outcome_conditions": tuple(c for c in verdict.outcome_conditions if verified(c, body)),
    })


def _p_yes(answer: Answer) -> float:
    return float(answer.probabilities.get("true", 0.0))


def _decide(answers: Mapping[str, Answer], qid: str) -> bool | None:
    if qid not in answers:
        return None
    p, cut = _p_yes(answers[qid]), bars.bar(qid)
    if p >= cut:
        return True
    return False if p <= 1 - cut else None


def _gated(answers: Mapping[str, Answer], choice: str, prefix: str) -> str:
    """The Choice's top option, only when that option's own gate cleared its bar."""
    answer = answers.get(choice)
    if answer is None:
        return ""
    gate = answers.get(f"{prefix}{answer.value}")
    if gate is None or _p_yes(gate) < bars.bar(f"{prefix}{answer.value}"):
        return ""
    return str(answer.value)


def reading_from_answers(answers: Mapping[str, Answer], *, funding: bool) -> DecisionReading:
    is_decision = _decide(answers, "is_decision")
    outcome = _gated(answers, "outcome", "gate:") if is_decision else ""
    funding_top = _gated(answers, "funding", "fgate:") if is_decision and funding else ""
    return DecisionReading(
        is_decision=is_decision,
        outcome=outcome,
        funding_outcome=FUNDING_TO_OUTCOME.get(funding_top, ""),
        other_programme_offered=_decide(answers, "other_programme"),
        p={qid: (_p_yes(a) if "true" in a.probabilities else float(a.confidence))
           for qid, a in answers.items()},
        measured=bars.measured(),
    )


#: Where the owner's permission for student mail holds (2026-10-04): TypeSafe's
#: Jev, through OpenRouter or TypeSafe's own host. Anything else abstains.
_JEV_HOSTS = frozenset({"openrouter.ai", "api.typesafe.ai"})


def jev_configured() -> bool:
    """The routed provider for this decision is TypeSafe's Jev, nothing else."""
    return (
        provider_for(DECISION) == "typesafe"
        and "jev" in settings.TYPESAFE_MODEL.casefold()
        and urlsplit(settings.DECISIONS_BASE_URL).hostname in _JEV_HOSTS
    )


def read_decision(
    email_text: str,
    sender_domain: str,
    programme: str,
    university: str,
    funding_name: str,
    *,
    student_id: UUID,
    subject: str = "",
    names: frozenset[str] = frozenset(),
    addresses: Iterable[str] = (),
    client: Client | None = None,
    wording: str = "a",
) -> DecisionReading:
    """One request; any failure is an abstention, never another reader."""
    if not jev_configured():
        logger.warning("mail decision abstained: the decision provider is not TypeSafe's Jev")
        return UNAVAILABLE
    if rate_limited("mailbox-decision", student_id, limit=READ_LIMIT, window_seconds=3600):
        return UNAVAILABLE
    listed = tuple(addresses)
    email: dict[str, str] = {
        "from_domain": sender_domain,
        "body": strip_identifiers(email_text[:MAX_BODY_CHARS], names=names, addresses=listed),
    }
    if subject:
        email["subject"] = strip_identifiers(subject, names=names, addresses=listed)
    application = {"programme": programme, "university": university}
    if funding_name:
        application["funding"] = funding_name
    try:
        answers = ask(
            {"email": email, "application": application},
            questions(wording, funding=bool(funding_name)),
            decision=DECISION,
            record=False,
            client=client,
        )
    except Exception as error:
        # DecisionsUnavailable, DecisionBudgetExhausted and StateTooLarge are the
        # designed ones; anything else is a bug that must still cost one mail's
        # reading, never the sync batch. Which party and the type, never the
        # message: an error can quote the state, and the state is student mail.
        logger.info(
            "mail decision abstained: Jev %s %s",
            type(error).__name__, getattr(error, "kind", ""),
        )
        return UNAVAILABLE
    return reading_from_answers(answers, funding=bool(funding_name))


@dataclass(frozen=True)
class MailContext:
    programme: str
    university: str
    funding: str
    names: frozenset[str]
    addresses: tuple[str, ...]


def mail_context(signal: MailSignal) -> MailContext | None:
    """What the reader needs about the card the mail belongs to. Inside a tenant
    transaction: every row read here is tenant-scoped.

    A scholarship card asks its own name as both programme and funding, and its
    outcome is the funding answer (portals/outcome.py)."""
    from apps.funding.grouping import funds
    from apps.funding.services import pack_awards
    from apps.mailbox.models import MailboxConnection
    from apps.portals.models import PortalAccount
    from apps.portals.outcome import is_funding_application

    application = signal.application
    if application is None:
        return None
    candidate, student = application.candidate, application.student
    funding = ""
    if is_funding_application(application):
        funding = application.title
    elif candidate is not None:
        awards = pack_awards(student)
        funded = sorted(
            (a for a in awards if funds(a, candidate)),
            key=lambda a: (a.funding_card or {}).get("route") != "AUTOMATIC_ON_ADMISSION",
        )
        funding = funded[0].program_name if funded else ""
    addresses = (
        student.application_email, student.academic_email, student.user.email,
        *MailboxConnection.objects.filter(membership=student).values_list("address", flat=True),
        *PortalAccount.objects.filter(student=student).values_list("address", flat=True),
    )
    return MailContext(
        programme=application.title,
        university=candidate.institution_name if candidate is not None else "",
        funding=funding,
        names=personal_names(student),
        addresses=tuple(a for a in addresses if a),
    )
