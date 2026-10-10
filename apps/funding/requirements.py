"""What a programme requires, as three read-only panes.

Spec `2026-09-19-letter-shape-tailoring` section 7. Nothing here computes,
fetches or decides: every item is a row the catalog already holds, carried with
the sentence the programme published and an honest statement of what this
system does about it.

The three statuses on the letter pane are section 3b's three paths, and they
are the whole point of the pane. A requirement is either something the engine
enforces, something it writes to and then checks, or something only the
applicant can do -- and a student reading the pane should never have to guess
which.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.documents.letter_shape import shape_from_prompt

from .models import ApplicationPrompt, Program, ProgramStatement

#: A bound or a setting the renderer measures (letter_render, and render.py's
#: own checkers for the artefact keys).
ENFORCED_AT_RENDER = "enforced at render"
#: A gate runs before anything is rendered -- there is no artefact to measure,
#: the letter simply may not say it.
ENFORCED_WHEN_WRITTEN = "enforced when the letter is written"
#: Section 3b path 2: carried into the prompt as data, judged afterwards.
WRITTEN_TO_AND_CHECKED = "written to and checked"
#: Section 3b path 3: nobody but the applicant can do it.
YOUR_ACTION = "your action"
#: Stored from the page and read by nothing yet.
RECORDED_NOT_ACTED_ON = "recorded, nothing acts on it yet"
#: The applicant pane's one label. Spec 3 replaces it with a verdict per item;
#: until it exists, saying nothing is the honest thing to say.
NOT_YET_CHECKED = "Stated by the programme. Not yet checked against your record."

#: Shape fields the applicant performs rather than the engine.
_APPLICANT_FIELDS = {"handwritten", "signed_declaration"}
#: Shape fields a gate enforces before any render. `document_language` is
#: letter_gates.check_language_mismatch, which refuses a letter in another
#: language before anything is rendered.
_GATE_FIELDS = {"naming", "document_language"}
#: Shape fields NOTHING reads yet. `document_required` and `file_bundle` are
#: derived, stored and read back into `LetterShape`, and no gate, renderer or
#: template acts on either (found by the branch's over-engineering pass). The
#: pane said "enforced at render" for them, which was false. Saying what is
#: true costs a label; saying nothing costs a student's trust in the other
#: three labels.
_UNREAD_FIELDS = {"document_required", "file_bundle"}

_APPLICANT_STATEMENT_KINDS = (
    ProgramStatement.Kind.COMPETENCY,
    ProgramStatement.Kind.LANGUAGE,
    ProgramStatement.Kind.OTHER,
)


@dataclass(frozen=True)
class RequirementItem:
    text: str
    #: The page's own URL for this sentence, carried verbatim out of catalog
    #: JSON (`letter_shape_sources`, `letter_student_actions`) -- a model read
    #: it off a third-party page and no field validator ever saw it. Django
    #: escapes it as TEXT, so showing it is safe; a template that renders it as
    #: `<a href="{{ }}">` must check the scheme first, because `javascript:`
    #: survives autoescaping inside an href. No template renders these yet
    #: (`templates/` is deferred), which is the only reason this is a note.
    source_url: str
    requirement: str
    status: str
    statement_id: str = ""


@dataclass(frozen=True)
class Requirements:
    letter: tuple[RequirementItem, ...]
    cv: tuple[RequirementItem, ...]
    applicant: tuple[RequirementItem, ...]


def _shape_items(prompt: ApplicationPrompt) -> list[RequirementItem]:
    shape = shape_from_prompt(prompt)
    items = [
        RequirementItem(
            text=source.get("text", ""),
            source_url=source.get("source_url", ""),
            requirement="REQUIRED",
            status=(
                YOUR_ACTION
                if field in _APPLICANT_FIELDS
                else ENFORCED_WHEN_WRITTEN
                if field in _GATE_FIELDS
                else RECORDED_NOT_ACTED_ON
                if field in _UNREAD_FIELDS
                else ENFORCED_AT_RENDER
            ),
        )
        for field, source in sorted(shape.sources.items())
    ]
    items += [
        RequirementItem(
            text=requirement.get("text", ""),
            source_url=requirement.get("source_url", ""),
            requirement="REQUIRED",
            status=WRITTEN_TO_AND_CHECKED,
        )
        for requirement in shape.written_requirements
    ]
    items += [
        RequirementItem(
            text=action.get("text", ""),
            source_url=action.get("source_url", ""),
            requirement="REQUIRED",
            status=YOUR_ACTION,
        )
        for action in shape.student_actions
    ]
    return items


def _cv_items(programme: Program) -> list[RequirementItem]:
    """The CV path's own derivations, shown the same way.

    Read straight off the stored rows rather than through
    `constraints.rules_from_program`, which raises on a malformed one: this is
    a read-only pane, and a rule nobody can parse is better shown as what it
    says than replaced by an exception on a page about something else.
    """
    items = []
    if programme.cv_format_requirement != Program.CVFormatRequirement.ANY:
        items.append(
            RequirementItem(
                text=programme.cv_format_requirement,
                source_url=programme.cv_format_source_url,
                requirement="REQUIRED",
                status=ENFORCED_AT_RENDER,
            )
        )
    for rule in programme.cv_constraints:
        items.append(
            RequirementItem(
                text=str(rule.get("rule_text", "")),
                source_url=str(rule.get("source_url", "")),
                requirement=str(rule.get("enforcement", "")),
                status=ENFORCED_AT_RENDER,
            )
        )
    for directive in programme.cv_directives:
        items.append(
            RequirementItem(
                text=str(directive),
                source_url=programme.cv_format_source_url,
                requirement="REQUIRED",
                status=ENFORCED_AT_RENDER,
            )
        )
    return items


def program_requirements(programme: Program, *, cycle: str) -> Requirements:
    """The three panes, for one programme and one admissions cycle.

    A programme with no prompt for that cycle has no letter pane rather than
    an error: the catalog is read programme by programme and a cycle nobody
    has read yet is an ordinary state, not a failure.
    """
    prompt = programme.application_prompts.filter(cycle=cycle).first()
    statements = list(
        programme.statements.filter(kind__in=_APPLICANT_STATEMENT_KINDS).select_related(
            "snapshot"
        )
    )
    return Requirements(
        letter=tuple(_shape_items(prompt)) if prompt is not None else (),
        cv=tuple(_cv_items(programme)),
        applicant=tuple(
            RequirementItem(
                text=statement.text,
                source_url=statement.snapshot.final_url,
                requirement=statement.requirement,
                status=NOT_YET_CHECKED,
                statement_id=str(statement.id),
            )
            for statement in statements
        ),
    )


def letter_kit_steps(prompt: ApplicationPrompt) -> tuple[RequirementItem, ...]:
    """The steps only the applicant can take, for the Application Kit.

    The same objects the letter pane shows, so a step can never be worded one
    way in the pane and another in the Kit.
    """
    return tuple(item for item in _shape_items(prompt) if item.status == YOUR_ACTION)


# SHOULD BE DONE BY AYKHAN: the window that shows these three panes is the
# presentation layer's, and this service is the one thing it calls.
#
# The Application Kit (2026-09-15 glass-box design) reads letter_kit_steps
# through apps/portals/packets.py::_letter_actions, as this note predicted. It
# has no model and wants none: the spec's own words are that the kit and the
# packet are "one server-side object with two renderings, so they can never
# disagree", and a stored kit is a third rendering that goes stale the moment a
# fact is confirmed, a draft is approved or a field map is superseded.
# Since the 2026-09-25 catalog read split, only the CATALOGUE-derived parts are
# stored (`packets.capture_requirements`, worker-side), because the web tier
# that serves the kit cannot read the catalogue; facts, drafts and field maps
# are still read live. That copy is stale until re-captured, which is the cost.
