"""Read a programme's page, then conclude what the catalog needs from it.

Lives in documents, not research, because the import direction in this
codebase is documents -> research (tailoring, generation, ingestion all import
apps.research) and never the reverse. The reader stays free of documents
concerns; this module is the one place the two meet.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.funding.models import OfficialSource, OfficialSourceSnapshot, Program
from apps.research.decisions import DecisionBudget, DecisionBudgetExhausted, DecisionsUnavailable
from apps.research.discovery import retrieve_official_source
from apps.research.egress import FetchResult
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.models import DecisionRecord
from apps.research.reader import ReadResult, read_program_page
from apps.research.snapshot import ObjectStore

from .derive import derive_page_rules

logger = logging.getLogger(__name__)

_READABLE = OfficialSourceSnapshot.Readability.OK

#: What a page read's decisions can raise after some of them were answered.
_DECISIONS_STOPPED = (DecisionsUnavailable, DecisionBudgetExhausted)


@contextmanager
def _atomic_keeping_decisions(source_url: str = "") -> Iterator[None]:
    """transaction.atomic(), except that the DecisionRecord rows the block
    wrote survive a decision layer that stops mid-page.

    A refused or failed decision rolls the page's own writes back (its
    statements, its rules), so the page's previous rows stand. The rows
    ask() wrote on the way are a different kind of fact: a refusal row is what
    makes a refusal "recorded once, never retried" (addendum §5.1), and an
    answered row is tokens actually spent, which month_tokens_spent must keep
    seeing. So they are read before the rollback and put back after it --
    outside the rolled-back block, in the caller's transaction or in
    autocommit. Only on a decision-layer stop: any other error may have left
    the transaction unusable, and its rows go with it.

    Rows are found by created_at, which auto_now_add stamps from this
    process's clock. A row another worker committed in the same window is
    caught too, and `ignore_conflicts` skips it (same primary key, same
    cache key). The recovery read is ordered by (state_digest, question_digest,
    model, question_id) -- the row's own cache key -- so a re-insert is
    reproducible rather than in whatever order the database happened to
    return (fix round 1, finding 4).

    Fix round 1, finding 4: the recovery read and the re-insert are each a
    second database access made AFTER the caller's own decision exception
    already exists. A DatabaseError from either -- a dropped connection, a
    deadlock -- is logged and swallowed, never left to replace the caller's
    DecisionsUnavailable / DecisionBudgetExhausted: `read_and_derive`'s
    callers match on that exception's type and `.kind`, and an opaque
    DatabaseError in its place would be a worse answer than losing the kept
    rows this call exists to save.
    """
    # ponytail: selects by a wall-clock mark; a backwards clock step during a
    # page read would miss rows. Tag rows with a read id if that ever matters.
    since = timezone.now()
    kept: list[DecisionRecord] = []
    try:
        with transaction.atomic():
            try:
                yield
            except _DECISIONS_STOPPED as error:
                try:
                    kept = list(
                        DecisionRecord.objects.filter(created_at__gte=since).order_by(
                            "state_digest", "question_digest", "model", "question_id"
                        )
                    )
                except DatabaseError:
                    logger.exception(
                        "derive: could not read back DecisionRecord rows to keep, on %s",
                        source_url,
                    )
                raise error
    except _DECISIONS_STOPPED as error:
        try:
            DecisionRecord.objects.bulk_create(kept, ignore_conflicts=True)
        except DatabaseError:
            logger.exception(
                "derive: could not re-insert kept DecisionRecord rows, on %s", source_url,
            )
        raise error


def read_and_derive(
    *,
    program: Program,
    source: OfficialSource,
    store: ObjectStore,
    parser: ResponsesAPI,
    claude: MessagesAPI,
    admissions_cycle: str,
    retrieve: Callable[[str], FetchResult] = retrieve_official_source,
    budget: DecisionBudget | None = None,
) -> ReadResult:
    """One read, one derivation, one transaction.

    Derivation runs on every read that persisted a readable snapshot --
    not only when the statement read wrote -- because recall no longer
    depends on which sentences the read selected (derive_page_rules finds
    its own candidates over the whole page). An unchanged page (no
    snapshot) and an unreadable one (result.snapshot.readability) derive
    nothing: there is nothing new to read, or nothing readable to read it
    from.

    derive_page_rules raises DerivationFailure (never caught here) when its
    model call is refused, empty, or off-schema. Letting it propagate is
    the point: read and derive share this one transaction.atomic(), so the
    raise rolls the statement write back too, and a programme's statements
    and its derived rules can never end up at different versions of the page.
    A validated-but-empty derivation still writes [] and does not raise --
    that is a real result meaning "this page states no CV constraint".

    `retrieve=` is passed straight through to `read_program_page` and binds
    the same rule reader.py states for it: it may only ever be bound from
    code in this repo or a test double, never from settings, a task kwarg, or
    a dotted path.

    Derivation reads through the decision layer when a provider is
    configured and through the frontier judge otherwise (derive_page_rules).
    `parser` still serves read_program_page's statement read, which plan 2
    replaces. A decision that fails or is refused raises DecisionsUnavailable
    the same way DerivationFailure does -- statements and rules roll back
    together -- but the DecisionRecord rows the read wrote are kept
    (_atomic_keeping_decisions).

    Fix round 1, finding 1 (unfixed here, recorded): this one transaction now
    holds open across the fetch AND back-to-back grammar requests (packed
    slots, then values, then the page-level facts), each an uncommitted
    DecisionRecord insert against the cache's unique key. Two workers reading
    the same shared page inside the same window both pay for the same
    answers -- record=True's cache read cannot see the other's uncommitted
    row -- and whichever commits second then waits on that row's unique-key
    lock until the first's transaction ends. The structural fix -- decision
    writes on their own autocommit connection, outside this transaction --
    is plan 2's; this docstring only names the cost plan 2 removes.
    """
    with _atomic_keeping_decisions(source_url=source.canonical_url):
        result = read_program_page(
            program=program,
            source=source,
            store=store,
            parser=parser,
            admissions_cycle=admissions_cycle,
            retrieve=retrieve,
        )
        if result.snapshot is not None and result.snapshot.readability == _READABLE:
            derive_page_rules(
                program, parser=parser, claude=claude, budget=budget,
                page_text=result.page_text, snapshot=result.snapshot,
                admissions_cycle=admissions_cycle, page_language=result.page_language,
            )
    return result
