"""Write one motivation letter for one student and one programme, and stop.

    POSTGRES_DB=... uv run python manage.py draft_letter \
        --tenant <agency-uuid> --student <membership-uuid> \
        --programme <program-uuid> --cycle 2027 [--render letter.pdf]

**The letter engine's first caller.** Everything the engine measures -- the
page's stated bounds, the naming gate, the written-requirement judge, the
shape the renderer applies -- was arithmetic about output nothing produced
until this command existed. A console entry point on purpose, and the same
choice `ingest_evidence` made: `phased requirements.md` section 10 still gates
the interaction surface, and a management command opens none.

What it deliberately does NOT do:

* **It does not approve.** It writes a `DocumentDraft` in `DRAFT` and prints
  what a human must weigh. `mark_letter_ready` takes an `accepted_by` for a
  reason -- a person accepts a letter, and nothing here is a person.
* **It does not submit anything anywhere**, and it does not touch a portal.
* **It renders only when asked**, to a path you name, and never into the
  evidence bucket.

Generation reads CONFIRMED facts only (`generatable_facts`): a fact a model
proposed and nobody accepted is invisible here, which is the whole design of
the ledger. `--forbid` is the one thing this command cannot work out for
itself -- the institutions the letter must not name are a property of the
student's pack, and passing none leaves `check_wrong_institution` inert, so
the command says so out loud rather than implying a check it did not make.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.documents.letter_render import render_letter
from apps.documents.letter_shape import NotGeneratable, constraints_from_shape, shape_from_prompt
from apps.documents.letters import (
    LetterGenerationError,
    LetterGenerationResult,
    generate_letter,
    is_letter_blocked,
)
from apps.documents.models import DocumentDraft, NarrativeInput, VerifiedFact
from apps.documents.verification import generatable_facts
from apps.funding.models import ApplicationPrompt
from apps.research.provenance import WORDING, Verdict, programme_verdict
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership


class Command(BaseCommand):
    help = "Generate one motivation letter draft for a student and programme."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Agency (tenant) UUID.")
        parser.add_argument("--student", required=True, help="Membership UUID.")
        parser.add_argument("--programme", required=True, help="Program UUID.")
        parser.add_argument("--cycle", required=True, help="Admissions cycle, e.g. 2027.")
        parser.add_argument(
            "--forbid",
            action="append",
            default=[],
            help="An institution name the letter must not mention. Repeatable.",
        )
        parser.add_argument(
            "--render", default="", help="Write the rendered letter to this path."
        )

    def handle(self, *args: object, **options: object) -> None:
        tenant = UUID(str(options["tenant"]))
        with tenant_scope(tenant):
            student = self._student(UUID(str(options["student"])))
            prompt = self._prompt(UUID(str(options["programme"])), str(options["cycle"]))
            verdict, code = programme_verdict(prompt.programme)
            self.stdout.write(f"provenance: {verdict} ({code})")
            if verdict == Verdict.BLOCKED:
                raise CommandError(
                    f"programme {prompt.programme_id} is BLOCKED ({code}): {WORDING[code][0]}"
                )
            facts = {fact.id: fact for fact in generatable_facts(student)}
            inputs = {
                entry.id: entry for entry in NarrativeInput.objects.filter(student=student)
            }
            forbidden = frozenset(str(name) for name in cast(list[str], options["forbid"]))
            if not forbidden:
                self.stdout.write(
                    "no --forbid names given: the wrong-institution gate checks nothing"
                )
            try:
                result = generate_letter(
                    student=student,
                    prompt=prompt,
                    facts=facts,
                    inputs=inputs,
                    forbidden_institution_names=forbidden,
                )
            except (NotGeneratable, LetterGenerationError) as error:
                # Refusals are the engine working, not the command failing:
                # a shape no letter can satisfy, a page that forbids naming
                # with no confirmed fit, a requirement every reading says the
                # letter still breaks. Each names its own reason.
                raise CommandError(f"{type(error).__name__}: {error}") from None

            draft = DocumentDraft.objects.create(
                tenant_id=tenant,
                student=student,
                kind=DocumentDraft.Kind.MOTIVATION_LETTER,
                version=self._next_version(student, prompt),
                content=result.content.model_dump(mode="json"),
                programme=prompt.programme,
                status=DocumentDraft.Status.DRAFT,
            )
            self._report(result, draft, prompt)
            if options["render"]:
                self._render(
                    result,
                    prompt,
                    Path(str(options["render"])),
                    applicant_name=_applicant_name(facts),
                )

    def _student(self, student_id: UUID) -> Membership:
        student = Membership.objects.filter(id=student_id).first()
        if student is None:
            raise CommandError(f"no membership {student_id} in this tenant")
        return student

    def _prompt(self, programme_id: UUID, cycle: str) -> ApplicationPrompt:
        prompt = ApplicationPrompt.objects.filter(
            programme_id=programme_id, cycle=cycle
        ).first()
        if prompt is None:
            raise CommandError(
                f"no application prompt for programme {programme_id} and cycle {cycle} -- "
                "resolve one first (apps/documents/prompt_resolution.py)"
            )
        return prompt

    def _next_version(self, student: Membership, prompt: ApplicationPrompt) -> int:
        previous = DocumentDraft.objects.filter(
            student=student,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            programme=prompt.programme,
        ).count()
        return previous + 1

    def _report(
        self, result: LetterGenerationResult, draft: DocumentDraft, prompt: ApplicationPrompt
    ) -> None:
        blocked = is_letter_blocked(
            result.claim_verdicts, result.gate_violations, immigration=prompt.immigration
        )
        self.stdout.write(f"draft {draft.id} (version {draft.version}) written as DRAFT")
        self.stdout.write(f"  retried: {result.retried}")
        self.stdout.write(
            f"  claims: {len(result.claim_verdicts)}, "
            f"gate violations: {len(result.gate_violations)}"
        )
        for violation in result.gate_violations:
            self.stdout.write(f"    {violation.code} ({violation.unit_archetype})")
        self.stdout.write(f"  blocked: {blocked}")
        self.stdout.write("  nothing is approved: a person does that, not this command")

    def _render(
        self,
        result: LetterGenerationResult,
        prompt: ApplicationPrompt,
        path: Path,
        *,
        applicant_name: str,
    ) -> None:
        shape = shape_from_prompt(prompt)
        artifact = render_letter(
            result.content,
            structure=prompt.structure,
            constraints=constraints_from_shape(shape, document_language=prompt.document_language),
            questions=prompt.questions,
            shape=shape,
            funder_kind=prompt.funder_kind,
            addressee=_addressee(prompt),
            applicant_name=applicant_name,
            # `place_and_date` is deliberately unfilled: the two rows whose
            # rule mandates a dateline (es/M-034, pt/M-101) have no sourced
            # salutation and render as essays, and no field of the ledger holds
            # the town a student writes from. Pinned by
            # test_the_head_and_foot_of_a_formal_letter_are_filled.
        )
        if artifact.pdf_bytes is None:
            # SHORT_ANSWER_SET renders no document: it is text typed into a
            # portal's own boxes, so there is nothing to write to a path.
            self.stdout.write(f"  {artifact.variant}: no document, {artifact.field_mapped}")
            return
        path.write_bytes(artifact.pdf_bytes)
        self.stdout.write(f"  rendered {artifact.variant} to {path} ({artifact.byte_size} bytes)")


def _addressee(prompt: ApplicationPrompt) -> str:
    """The recipient block: the institution and where it is.

    Read off the shared catalog, never composed: an addressee is the
    recipient's own identity, unlike a salutation, which is a convention a
    sourced rule has to state (`docs/research/letter-formalities.csv`).
    A programme with no institution row yields "", and the template omits the
    block rather than printing a half one.
    """
    programme = prompt.programme
    institution = programme.institution
    where = ", ".join(part for part in (programme.city, programme.country_code) if part)
    return "\n".join(part for part in (institution.name if institution else "", where) if part)


def _applicant_name(facts: dict[UUID, VerifiedFact]) -> str:
    """The name that signs the letter, from the confirmed ledger only.

    `facts` is already `generatable_facts`, so a name a model proposed and
    nobody accepted cannot reach the signature. The last IDENTITY fact wins,
    matching `gaps.missing_contact`; no confirmed one means no signature line,
    which the template treats as absent rather than blank.
    """
    for fact in reversed(facts.values()):
        if fact.category == VerifiedFact.Category.IDENTITY:
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            return str(payload.get("full_name") or "")
    return ""
