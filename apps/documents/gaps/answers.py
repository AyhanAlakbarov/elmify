"""Answer ingestion: processes and writes student responses to gap questions as verified facts."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from django.db import IntegrityError, transaction
from pydantic import ValidationError

from apps.documents.cv_fixes import ABBREVIATED_NAME, TITLE_MAX, remember_revert, subject_of
from apps.documents.gaps.detectors.profile import _NAME_PART_KEYS, NAME_PART_MAX
from apps.documents.gaps.models import GapQuestion, Kind, UnanswerableQuestion
from apps.documents.models import VerifiedFact
from apps.documents.schemas import TIMELINE_STATEMENT_MAX, TimelineEntry
from apps.documents.verification import payload_keys, unsuperseded_facts
from apps.tenancy.models import Membership

#: Payload keys whose schema type is a sequence, so a typed answer is stored
#: as a one-element list rather than a bare string. Without this a voluntary
#: role's bullet reached the ledger as a string while every ingested
#: experience carries a list (verification.fact_payload builds it from
#: ExperienceEntry.bullets, a tuple), and generation._facts_payload puts both
#: shapes in front of the model under one key.
_LIST_KEYS = frozenset({"bullets"})


@transaction.atomic
def answer_questions(
    answers: Sequence[tuple[GapQuestion, str]], *, student: Membership
) -> tuple[VerifiedFact, ...]:
    """Write a form's worth of answers as superseding candidate facts.

    One row per fact, carrying every answer for that fact. Written one at a
    time instead, the first answer would supersede the fact the second names
    and the second would be refused as stale -- a post missing both its
    supervisor and its end date produces exactly that pair.

    A correction is a new row with supersedes set: the ledger is append-only
    (see VerifiedFact's docstring), so this never mutates the row it answers.
    Everything written is a candidate -- confirmed_by=None, exactly as
    ingest_uploaded_cv writes -- and generation reads generatable_facts, so an
    answer cannot reach a document until a counsellor accepts it.

    Blank answers are dropped: a skipped question is not an empty fact, and a
    form of blanks writes nothing at all. Everything else that fails raises,
    and the whole batch is one transaction -- a student who answered three
    questions and tripped a guard on the fourth must not find two of them
    landed. All three guards read values that arrived from a form, which makes
    them a trust boundary rather than a hint.

    A double submit cannot fork the chain, and the guard is the
    ``verifiedfact_one_superseder`` index rather than anything here. Two
    concurrent batches both read the tip as current -- a row lock does not stop
    that, because the fork comes from INSERTing a sibling rather than modifying
    the locked row, so under READ COMMITTED the loser's anti-join never sees
    the winner (measured, not argued: see that constraint's comment). The
    index refuses the second write, and the loser is told its answers did not
    land, which is true and is what the form re-renders.
    """
    updates: dict[UUID, dict[str, object]] = {}
    # slug -> (one question of that group, the answers given). A new entry
    # takes several answers -- an EducationEntry needs an institution AND a
    # degree, an ExperienceEntry an employer, a title and a bullet -- so the
    # group is the unit of creation, not the question. The question is kept
    # because it carries the group's category, its full key list and its
    # defaults; all three are server-built and identical across the group.
    creations: dict[str, tuple[GapQuestion, dict[str, str]]] = {}
    for question, answer in answers:
        value = answer.strip()
        if not value:
            continue
        if question.fact_id is None:
            # A question about something the ledger does not hold: the answer
            # is a new fact, not a correction. `category` comes off the
            # server-built question, never off the form.
            if question.category is None:
                raise UnanswerableQuestion("a question with no fact must name a category")
            # The ledger stores whatever string it is handed, and generation
            # validates TimelineEntry.statement against TIMELINE_STATEMENT_MAX:
            # an over-long answer accepted here is a fact that makes every
            # later CV for this student fail. Refused at the door instead,
            # which the form already shows as an error. The schema also refuses
            # it below; this stays for the message, which a student can act on.
            if (
                question.category == VerifiedFact.Category.TIMELINE
                and len(value) > TIMELINE_STATEMENT_MAX
            ):
                raise UnanswerableQuestion(
                    f"keep it to {TIMELINE_STATEMENT_MAX} characters"
                )
            slug = question.slug
            assert slug is not None  # GapQuestion.__post_init__ guarantees it
            first, fields = creations.setdefault(slug, (question, {}))
            if first.category != question.category:
                raise UnanswerableQuestion(f"{slug} names two categories")
            if first.group_keys != question.group_keys:
                raise UnanswerableQuestion(f"{slug} declares two key sets")
            fields[question.payload_key] = value
            continue
        if question.kind == Kind.ABBREVIATED_NAME:
            limit = TITLE_MAX[question.payload_key]
            if len(value) > limit:
                # No input in the message: it is the student's own data.
                raise UnanswerableQuestion(f"keep it to {limit} characters")
            current = unsuperseded_facts(student).filter(id=question.fact_id).first()
            stated = (
                current.payload.get(question.payload_key)
                if current and isinstance(current.payload, dict)
                else None
            )
            if stated == value:
                # Retyped unchanged: the diploma prints it so. Remembered, not
                # written, so the question stops instead of re-asking forever.
                remember_revert(student, ABBREVIATED_NAME, subject_of(ABBREVIATED_NAME, value))
                continue
        if question.payload_key in _NAME_PART_KEYS and len(value) > NAME_PART_MAX:
            # No input in the message or the cause: it is the student's own data.
            raise UnanswerableQuestion(f"keep it to {NAME_PART_MAX} characters") from None
        stored_value: object = value
        if question.payload_key == "self_author_index" and value.isdigit():
            parsed_idx = int(value)
            stored_value = parsed_idx - 1 if parsed_idx >= 1 else 0
        updates.setdefault(question.fact_id, {})[question.payload_key] = stored_value
    if not updates and not creations:
        return ()

    written: list[VerifiedFact] = []
    named = False
    for slug, (question, fields) in creations.items():
        # All or nothing. A half-answered group writes a fact no reader can use
        # -- an EDUCATION row holding an institution and no degree gives
        # generation nothing to build an entry from, and the model's only legal
        # move is to invent the other half. A dropped partial answer costs one
        # re-ask, which the interview does on its own because the detector
        # still fires.
        if set(fields) != set(question.group_keys):
            continue
        category = question.category
        assert category is not None  # checked when the answer was read
        # Merged after the completeness check above: a default is not
        # something the student answered, and must not count toward it.
        full_fields: dict[str, object] = {**fields, **dict(question.defaults)}
        unknown = sorted(set(full_fields) - set(payload_keys(category)))
        if unknown:
            raise UnanswerableQuestion(f"{category} facts do not carry {', '.join(unknown)}")
        if category == VerifiedFact.Category.TIMELINE:
            # Through the entry generation builds from it, so the ledger holds
            # what the CV prints: the statement tidied as the schema tidies it,
            # the dates as the schema writes them, and no end_date at all for
            # the trailing gap. Stored raw, a tidied CV line disagrees with its
            # own fact.
            try:
                entry = TimelineEntry.model_validate(full_fields)
            except ValidationError:
                # `from None`, not `from error`: a ValidationError carries the
                # rejected input, and a gap answer is health or family data
                # more often than not (approval.py, same choice, same reason).
                raise UnanswerableQuestion(
                    f"{slug}: that answer cannot be printed on the CV"
                ) from None
            full_fields = entry.model_dump(mode="json", exclude_none=True)
        payload = {
            key: [value] if key in _LIST_KEYS else value
            for key, value in full_fields.items()
        }
        written.append(
            VerifiedFact.objects.create(
                student=student,
                category=category,
                payload=payload,
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                # Prefixed with the slug, unlike the supersede path below: a
                # created fact is otherwise indistinguishable from any other
                # row once it lands (a voluntary role is an EXPERIENCE row
                # with an employer, a title and a bullet, exactly like a job),
                # so this stamp is the only thing that can say "this group was
                # already answered" -- see _already_created. Same mechanism
                # as profile_bridge.py's own source_ref prefix.
                source_ref=f"gap-interview:{slug}",
                confirmed_by=None,
                supersedes=None,
                created_by=student,
            )
        )
    for fact_id, update_fields in updates.items():
        target = unsuperseded_facts(student).filter(id=fact_id).first()
        if target is None:
            raise UnanswerableQuestion(f"no current fact {fact_id} for this student")
        payload = dict(target.payload) if isinstance(target.payload, dict) else {}
        is_author_pick = (
            target.category == VerifiedFact.Category.PUBLICATION
            and set(update_fields) == {"self_author_index"}
            and payload.get("self_author_index") is None
        )
        if (
            target.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
            and not is_author_pick
        ):
            raise UnanswerableQuestion("an authoritative fact cannot be answered over")
        allowed = payload_keys(target.category)
        unknown = sorted(set(update_fields) - set(allowed))
        if unknown:
            raise UnanswerableQuestion(
                f"{target.category} facts do not carry {', '.join(unknown)}"
            )
        # A name part is no reason to confirm the rest of the row: the new row
        # inherits the tip's confirmation, and only when the batch is name
        # parts alone (or picking self_author_index on a registry publication).
        inherit = (
            set(update_fields) <= _NAME_PART_KEYS or is_author_pick
        ) and target.confirmed_at is not None
        try:
            created = VerifiedFact.objects.create(
                student=student,
                category=target.category,
                payload={**payload, **update_fields},
                source_tier=(
                    target.source_tier
                    if is_author_pick
                    else VerifiedFact.SourceTier.STUDENT_STATEMENT
                ),
                source_ref="gap-interview",
                confirmed_by=target.confirmed_by if inherit else None,
                confirmed_at=target.confirmed_at if inherit else None,
                supersedes=target,
                created_by=student,
            )
        except IntegrityError as error:
            # verifiedfact_one_superseder: someone else answered this same
            # question between our read and our write. Their row is the tip
            # now, so ours is not a correction to apply -- it is an answer to
            # a question that no longer exists, which is what this exception
            # already means everywhere else it is raised.
            raise UnanswerableQuestion(f"fact {fact_id} was answered concurrently") from error
        written.append(created)
        named = named or bool(set(update_fields) & _NAME_PART_KEYS)
    if named:
        # Lazy: apps.documents must not import apps.portals at module level.
        from apps.portals.prepare import queue_for_student

        queue_for_student(student.tenant_id, student.id)
    return tuple(written)

