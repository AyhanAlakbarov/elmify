"""What a CV for one programme keeps, decided at generation so the draft the
student approves is the CV that prints.

Two deciders, both only ever keep or leave out WHOLE items (coverage.items_of)
and never rewrite or add one: the programme page's coverage rules (this
module) and the relevance engine (relevance.py, 4d). Everything left out is
listed with its reason on the draft (Stage 3's applied_fixes), and the student
can put it back.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from django.conf import settings

from apps.funding.models import Program
from apps.research.decisions import Client
from apps.tenancy.models import Membership

from .constraints import ConstraintRule, Enforcement, resolve_rules
from .coverage import Coverage, Item, coverage_of, items_of
from .relevance import Verdict, judge
from .render import binding_content_failures, render_cv_with_warnings, select_render_variant
from .requirement_list import RequirementList
from .schemas import CVContent

logger = logging.getLogger(__name__)

#: The sections a cv_start window may thin. Paid experience, research and
#: publications stay whatever their age (plan decision 6).
_WINDOW_REACH = frozenset({"awards", "certifications", "volunteering"})
#: On a funder template these sections have a named home (SISGP, Rhodes), so
#: the engine never empties them (plan decision 17).
_FUNDER_PROTECTED = frozenset({"awards", "volunteering"})
_ORDERED_FIELDS = ("awards", "certifications")


@dataclass(frozen=True)
class LeftOut:
    section: str
    text: str
    digest: str
    reason: str

    def record(self) -> dict[str, str]:
        """One entry of the draft's change list (Stage 3's applied_fixes). The
        item text is the student's own, so the list is REDACT on erasure."""
        return {
            "kind": "left_out",
            "section": self.section,
            "item": self.text,
            "item_digest": self.digest,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Selection:
    content: CVContent
    left_out: tuple[LeftOut, ...] = ()


def without(content: CVContent, items: Iterable[Item]) -> CVContent:
    drop: dict[str, set[int]] = defaultdict(set)
    for item in items:
        drop[item.field].add(item.index)
    return content.model_copy(
        update={
            field: tuple(e for n, e in enumerate(getattr(content, field)) if n not in indices)
            for field, indices in drop.items()
        }
    )


def _newest_first(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda i: (i.when is not None, i.when or date.min), reverse=True)


def apply_coverage(
    content: CVContent, coverage: Coverage, *, kept: frozenset[str], today: date
) -> Selection:
    """The page's caps and window. `kept` is the digests the student put back:
    the student decides over the page, and the render check then reports the
    cap the CV exceeds (render._check_cv_item_cap)."""
    items = items_of(content)
    leaving: dict[str, tuple[Item, str]] = {}
    for section, limit in coverage.caps:
        in_section = _newest_first([i for i in items if i.section == section])
        for item in in_section[limit:]:
            if item.digest not in kept:
                leaving[item.digest] = (item, f"the programme lists at most {limit} {section}")
    cutoff: date | None = None
    if coverage.start == "last_n_years":
        cutoff = date(today.year - coverage.years, today.month, min(today.day, 28))
    elif coverage.start == "first_degree":
        starts = [e.start_date for e in content.education if e.start_date is not None]
        cutoff = min(starts) if starts else None
    if cutoff is not None:
        for item in items:
            if (
                item.section in _WINDOW_REACH
                and item.when is not None
                and item.when < cutoff
                and item.digest not in kept
            ):
                leaving.setdefault(
                    item.digest, (item, "before the period the programme asks for")
                )
    if not leaving:
        return Selection(content)
    gone = [item for item, _ in leaving.values()]
    return Selection(
        without(content, gone),
        tuple(
            LeftOut(item.section, item.text, item.digest, reason)
            for item, reason in leaving.values()
        ),
    )


def _guarded(
    original: CVContent, chosen: Selection, constraints: tuple[ConstraintRule, ...]
) -> Selection:
    """Plan decision 18: a leave-out may never make a BINDING rule fail."""
    if not chosen.left_out:
        return chosen
    before = binding_content_failures(original, constraints)
    if binding_content_failures(chosen.content, constraints) - before:
        return Selection(original)
    return chosen


def _put_back(student: Membership, programme: Program) -> frozenset[str]:
    """Digests the student put back for this programme: never left out again."""
    from .models import CVItemChoice

    return frozenset(
        CVItemChoice.objects.filter(student=student, program_id=programme.id).values_list(
            "item_digest", flat=True
        )
    )


def _over_pages(
    content: CVContent, variant: str, constraints: tuple[ConstraintRule, ...]
) -> bool:
    """Does a local, non-compact render of this content break a resolved
    max_pages rule? EUROPASS_API renders its look-alike here
    (allow_network=False). Downgrades BINDING max_pages rules for this probe so
    general-merit items are dropped before Stage 1's compact retry."""
    probe_rules = tuple(
        rule.model_copy(update={"enforcement": Enforcement.ADVISORY_HIGH_RISK})
        if rule.key == "max_pages" and rule.enforcement == Enforcement.BINDING
        else rule
        for rule in constraints
    )
    _, violations = render_cv_with_warnings(content, variant=variant, constraints=probe_rules)
    return any(v.rule.key == "max_pages" for v in violations)


def _asked_first(content: CVContent, asked: set[str]) -> CVContent:
    """Question doc: an item the requirements name prints first in its section.
    Only where order is the content's own -- awards, certifications; dated
    sections are re-sorted at render (render.reverse_chronological)."""
    update: dict[str, object] = {}
    for field in _ORDERED_FIELDS:
        positions = {i.index: i.digest in asked for i in items_of(content) if i.field == field}
        entries = getattr(content, field)
        update[field] = tuple(
            entry
            for _, entry in sorted(
                enumerate(entries), key=lambda pair: not positions.get(pair[0], False)
            )
        )
    return content.model_copy(update=update)


def _fit_general_merit(
    content: CVContent,
    merit: set[str],
    constraints: tuple[ConstraintRule, ...],
    variant: str,
    *,
    kept: frozenset[str] = frozenset(),
) -> tuple[CVContent, list[LeftOut]]:
    """Spec §7.2 & CV evidence spec §10.5: for a programme, side projects and
    general-merit items stay while the CV fits its page target and go oldest
    first (projects before general-merit items) while it does not. No page
    rule, or a layout we cannot measure locally, keeps them all."""
    if variant in ("FUNDER_TEMPLATE", "FIELD_MAPPED") or not any(
        rule.key == "max_pages" for rule in constraints
    ):
        return content, []
    left: list[LeftOut] = []
    while True:
        items = items_of(content)
        project_candidates = [
            i for i in items if i.section == "projects" and i.digest not in kept
        ]
        candidates = (
            project_candidates
            if project_candidates
            else [i for i in items if i.digest in merit]
        )
        if not candidates or not _over_pages(content, variant, constraints):
            break
        # Oldest dated first; undated last, since their age is unknown.
        oldest = min(candidates, key=lambda i: (i.when is None, i.when or date.max))
        content = without(content, [oldest])
        merit.discard(oldest.digest)
        left.append(
            LeftOut(
                oldest.section,
                oldest.text,
                oldest.digest,
                "left out to keep the CV within the programme's page limit",
            )
        )
    return content, left


def _relevance(
    chosen: Selection,
    *,
    student: Membership,
    programme: Program,
    constraints: tuple[ConstraintRule, ...],
    kept: frozenset[str],
    client: Client | None,
) -> Selection:
    items = items_of(chosen.content)
    verdicts: dict[str, Verdict] = judge(
        items, student=student, programme=programme, client=client
    )
    variant = select_render_variant(programme)
    if not verdicts:
        if not chosen.content.projects:
            return chosen
        content, squeezed = _fit_general_merit(
            chosen.content, set(), constraints, variant, kept=kept
        )
        return Selection(content, (*chosen.left_out, *squeezed))
    protected = _FUNDER_PROTECTED if variant == "FUNDER_TEMPLATE" else frozenset()
    bar: float = settings.CV_RELEVANCE_BAR
    leaving: list[Item] = []
    merit: set[str] = set()
    asked: set[str] = set()
    for item in items:
        verdict = verdicts.get(item.digest)
        if verdict is None or item.digest in kept:
            continue
        if item.section == "skills":
            # Logged, never applied, until Jev beats tailor_skills on the same
            # CVs (question doc, "Skills"). The label only -- never the line.
            logger.info("CVRelevanceSkill answer=%s chance=%.2f", verdict.answer, verdict.chance)
            continue
        if item.section in protected:
            continue
        if verdict.answer == "unrelated" and verdict.chance >= bar:
            leaving.append(item)
        elif verdict.answer == "general_merit":
            merit.add(item.digest)
        elif verdict.answer == "asked_for":
            asked.add(item.digest)
    content = _asked_first(without(chosen.content, leaving), asked)
    left = [
        *chosen.left_out,
        *(
            LeftOut(i.section, i.text, i.digest, "not related to this programme")
            for i in leaving
        ),
    ]
    content, squeezed = _fit_general_merit(
        content, merit, constraints, variant, kept=kept
    )
    return Selection(content, tuple(left + squeezed))


def select_for_programme(
    content: CVContent,
    *,
    student: Membership,
    programme: Program | None,
    requirements: RequirementList | None = None,
    today: date | None = None,
    client: Client | None = None,
) -> Selection:
    if programme is None and requirements is None:
        return Selection(content)
    constraints = (
        requirements.cv_rules()
        if requirements is not None
        else resolve_rules(programme, None, content=content)
    )
    coverage = coverage_of(constraints)
    kept = _put_back(student, programme) if programme is not None else frozenset()
    chosen = apply_coverage(content, coverage, kept=kept, today=today or date.today())
    if programme is not None and not coverage.complete:
        chosen = _relevance(
            chosen,
            student=student,
            programme=programme,
            constraints=constraints,
            kept=kept,
            client=client,
        )
    elif chosen.content.projects:
        variant = (
            select_render_variant(programme) if programme is not None else "STANDARD"
        )
        fitted, squeezed = _fit_general_merit(
            chosen.content, set(), constraints, variant, kept=kept
        )
        chosen = Selection(fitted, (*chosen.left_out, *squeezed))
    return _guarded(content, chosen, constraints)
