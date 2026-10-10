import pytest
from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.audit.redaction import RedactionIncomplete, redact_student
from apps.concierge.models import RoadmapItem
from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency,
        user=user,
        role=Membership.Role.STUDENT,
        active=True,
        application_email=f"{name}@example.test",
        academic_email=f"{name}@uni.example.test",
    )


def test_redaction_empties_personal_fields_and_keeps_structure(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        fact = VerifiedFact.objects.create(
            tenant=agency_a,
            student=student,
            category="EXPERIENCE",
            payload={"employer": "Acme GmbH", "name": "Amina Yusuf"},
            source_tier="AUTHORITATIVE_DOCUMENT",
            source_ref="s3://evidence/cv.pdf",
            created_by=student,
        )
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=student,
            stage=RoadmapItem.Stage.DOCUMENTS,
            owner_kind="AGENT",
            deadline=timezone.now(),
            result="Amina's passport scan is blurred; ask her to resend.",
        )

        redact_student(tenant_id=agency_a.id, student_id=student.id)

        fact.refresh_from_db()
        item.refresh_from_db()
        student.refresh_from_db()

        # REDACT: emptied, not deleted, not NULL.
        assert fact.payload == {}
        assert fact.source_ref == ""
        assert item.result == ""
        assert student.application_email == ""
        assert student.academic_email == ""
        # KEEP: the structured residue the models need survives untouched.
        assert fact.category == "EXPERIENCE"
        assert fact.source_tier == "AUTHORITATIVE_DOCUMENT"
        assert item.stage == RoadmapItem.Stage.DOCUMENTS
        assert item.owner_kind == "AGENT"
        assert student.role == Membership.Role.STUDENT
        # The rows themselves survive: nothing was deleted.
        assert VerifiedFact.objects.filter(pk=fact.pk).exists()
        assert Membership.objects.filter(pk=student.pk).exists()


def test_an_interview_items_deadline_does_not_survive_the_erasure(agency_a, django_user_model):
    """Final review M2: the mailbox writes MailSignal.interview_at (REDACT) into
    an INTERVIEW item's deadline (actions._alert_student). Only the mailbox
    writes that stage; the deadline falls back to the row's own created_at
    (NOT NULL). Other stages' deadlines are the programme's, and stay."""
    from datetime import timedelta

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        interview_at = timezone.now() + timedelta(days=12, hours=3)
        programme_deadline = timezone.now() + timedelta(days=40)
        interview, documents = (
            RoadmapItem.objects.create(
                tenant=agency_a, student=student, stage=stage, owner=student, deadline=deadline
            )
            for stage, deadline in (
                (RoadmapItem.Stage.INTERVIEW, interview_at),
                (RoadmapItem.Stage.DOCUMENTS, programme_deadline),
            )
        )

        redact_student(tenant_id=agency_a.id, student_id=student.id)

        interview.refresh_from_db()
        documents.refresh_from_db()
    assert interview.deadline == interview.created_at
    assert documents.deadline == programme_deadline


def test_redaction_touches_only_the_named_student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        erased = _student(agency_a, django_user_model, "amina")
        bystander = _student(agency_a, django_user_model, "kwame")
        keep = VerifiedFact.objects.create(
            tenant=agency_a,
            student=bystander,
            category="EDUCATION",
            payload={"degree": "BSc"},
            source_tier="AUTHORITATIVE_DOCUMENT",
            source_ref="s3://evidence/kwame.pdf",
            created_by=bystander,
        )

        redact_student(tenant_id=agency_a.id, student_id=erased.id)

        keep.refresh_from_db()
        bystander.refresh_from_db()

    assert keep.payload == {"degree": "BSc"}
    assert keep.source_ref == "s3://evidence/kwame.pdf"
    assert bystander.application_email == "kwame@example.test"


def test_redaction_refuses_a_tenant_that_does_not_match_the_ambient_scope(
    agency_a, agency_b, django_user_model
):
    """The tenant-scoped manager reads the contextvar, not the argument, so a
    mismatch would otherwise redact under the wrong scope in silence."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        with pytest.raises(RedactionIncomplete):
            redact_student(tenant_id=agency_b.id, student_id=student.id)


def test_redaction_refuses_to_run_while_a_field_is_undecided(
    agency_a, django_user_model, monkeypatch
):
    """A partial erasure must not be reachable by forgetting a decision."""
    monkeypatch.setattr(
        "apps.audit.redaction.UNDECIDED", {"concierge.Receipt": ("object_key",)}
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        version = StudentProfileVersion.objects.create(
            tenant=agency_a, student=student, version=1, schema_version=1,
            snapshot={"name": "Amina Yusuf"},
        )
        with pytest.raises(RedactionIncomplete):
            redact_student(tenant_id=agency_a.id, student_id=student.id)
        version.refresh_from_db()

    # Refused before touching anything, not halfway through.
    assert version.snapshot == {"name": "Amina Yusuf"}


def test_evaluation_example_holds_no_identifier(agency_a):
    """Owed by the spec: EvaluationExample is KEEP by constraint, not inspection.

    Nothing writes it today, so there is no content to assert against. When a
    writer exists, replace this with an assertion that what it persists
    contains no value drawn from a REDACT field.

    EvaluationExample.objects is tenant-scoped (TenantManager), so even this
    existence check needs a tenant context -- there is no unscoped manager.
    """
    from apps.funding.models import EvaluationExample

    with tenant_scope(agency_a.id):
        assert not EvaluationExample.objects.exists(), (
            "EvaluationExample now has rows: this test must be replaced with a real "
            "assertion that its contents carry no identifier. See the spec's "
            "'Owed' section."
        )


def test_executed_redacts_and_is_written_only_after_redaction_succeeds(
    agency_a, django_user_model, monkeypatch
):
    from django.utils import timezone

    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_documents", lambda **kw: 0
    )
    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0
    )
    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_mailbox_tokens", lambda **kw: 0
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        fact = VerifiedFact.objects.create(
            tenant=agency_a, student=student, category="IDENTITY",
            payload={"name": "Amina Yusuf"}, source_tier="AUTHORITATIVE_DOCUMENT",
            source_ref="s3://evidence/cv.pdf",
            created_by=student,
        )
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")

        request.refresh_from_db()
        fact.refresh_from_db()

    assert request.state == "EXECUTED"
    assert fact.payload == {}


def test_a_failed_redaction_leaves_the_request_approved(
    agency_a, django_user_model, monkeypatch
):
    """The whole point: EXECUTED must never outrun the redaction it claims."""
    from django.utils import timezone

    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0
    )
    monkeypatch.setattr(
        "apps.audit.deletion.delete_student_mailbox_tokens", lambda **kw: 0
    )

    def boom(**kwargs):
        raise RedactionIncomplete("simulated failure")

    monkeypatch.setattr("apps.audit.deletion.redact_student", boom)

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        fact = VerifiedFact.objects.create(
            tenant=agency_a, student=student, category="IDENTITY",
            payload={"name": "Amina Yusuf"}, source_tier="AUTHORITATIVE_DOCUMENT",
            source_ref="s3://evidence/cv.pdf",
            created_by=student,
        )
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")

        with pytest.raises(RedactionIncomplete):
            advance_deletion(request, "EXECUTED")

        request.refresh_from_db()
        fact.refresh_from_db()

    assert request.state == "APPROVED"
    assert fact.payload == {"name": "Amina Yusuf"}


def test_executed_sets_the_tenant_guc_in_a_transaction_before_redacting(
    agency_a, django_user_model, monkeypatch
):
    """Pins the mechanism, not the outcome.

    Several redacted tables are FORCE ROW LEVEL SECURITY keyed on the Postgres
    app.tenant_id GUC. tenant_scope is only a contextvar and never reaches
    Postgres, so without set_local_tenant the UPDATEs are legal SQL matching
    zero rows -- the erasure "succeeds", EXECUTED is written, and nothing was
    redacted. The test role enforces no RLS, so only the mechanism is provable
    here: that the GUC is set, with the right tenant, inside an open
    transaction, before redact_student runs.
    """
    from django.db import connection
    from django.utils import timezone

    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)

    order: list[tuple[str, object, bool]] = []
    real_set_local_tenant = deletion.set_local_tenant
    real_redact = deletion.redact_student

    def _spy_guc(tenant_id):
        order.append(("guc", tenant_id, connection.in_atomic_block))
        return real_set_local_tenant(tenant_id)

    def _spy_redact(**kwargs):
        order.append(("redact", kwargs["tenant_id"], connection.in_atomic_block))
        return real_redact(**kwargs)

    monkeypatch.setattr(deletion, "set_local_tenant", _spy_guc)
    monkeypatch.setattr(deletion, "redact_student", _spy_redact)

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "guc")
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")

    assert order == [
        ("guc", agency_a.id, True),
        ("redact", agency_a.id, True),
    ]


def test_receipt_has_no_writer_yet(agency_a):
    """Receipt.object_key is KEEP by constraint. This fails when that stops being safe.

    Nothing creates a Receipt today, so the classification is a promise about a
    writer that does not exist. When one is built, this test fails and whoever
    built it must read the four rules in the spec and replace this assertion:

      1. object_key stays opaque -- no payer name in a field we keep forever.
      2. Retained means access-restricted after erasure (GDPR Art. 18), not
         merely kept. apps/audit/services.py already serves receipts into the
         student dossier via ledger_entry__student_id.
      3. Destroyed when the statutory period expires (§147 AO: 8 years from the
         end of the calendar year). Retention is a floor, not a licence.
      4. The exemption covers the receipt and nothing else.

    Receipt is TenantScopedModel, so the existence check needs a tenant context
    like test_evaluation_example_holds_no_identifier's -- there is no unscoped
    manager to fall back on.
    """
    from apps.concierge.models import Receipt

    with tenant_scope(agency_a.id):
        assert not Receipt.objects.exists(), (
            "Receipt now has a writer. Read the four constraints in "
            "docs/superpowers/specs/2026-09-08-erasure-by-redaction-design.md and replace "
            "this assertion with a real one -- KEEP was a promise, not an observation."
        )


def test_masked_card_reference_has_no_writer_yet(agency_a):
    """The third KEEP-by-constraint field, and the one with no stated constraint.

    ApplicationFeeLedgerEntry has no writer at all, so `masked_card_reference`
    is KEEP on the strength of its NAME implying the value arrives already
    masked. Nothing enforces that. A writer that stores a full PAN, or a
    cardholder name, puts unerasable payment data in a field this design
    promises is safe to keep -- and unlike Receipt and EvaluationExample, that
    promise was never written down until now.

    The constraint on whoever builds the writer: this column may hold a masked
    reference only -- last four digits or a processor token -- never a full
    card number, never a cardholder name, never anything that identifies the
    payer. If a fuller reference is genuinely needed, it is REDACT, not KEEP,
    and belongs in the map with a subject path of `student_id`.

    ApplicationFeeLedgerEntry is TenantScopedModel too, so this needs the same
    tenant context as the Receipt tripwire above.
    """
    from apps.concierge.models import ApplicationFeeLedgerEntry

    with tenant_scope(agency_a.id):
        assert not ApplicationFeeLedgerEntry.objects.exists(), (
            "ApplicationFeeLedgerEntry now has a writer. Confirm masked_card_reference "
            "holds only a masked reference, then replace this assertion with one that "
            "checks it -- or move the field to REDACT."
        )


def test_the_s3_purge_runs_before_redaction_empties_the_keys(
    agency_a, django_user_model, monkeypatch
):
    """Order is load-bearing, and nothing else pins it.

    delete_student_documents finds objects BY object_key, and redaction empties
    object_key. Reversed, the purge enumerates nothing, every document survives
    in S3, and the request still reads EXECUTED. The S3 purge is idempotent, so
    this order is also the safely retryable one.
    """
    from django.utils import timezone

    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    order: list[str] = []
    real_redact = deletion.redact_student

    monkeypatch.setattr(
        deletion, "delete_student_documents", lambda **kw: order.append("s3") or 0
    )
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)

    def _spy_redact(**kwargs):
        order.append("redact")
        return real_redact(**kwargs)

    monkeypatch.setattr(deletion, "redact_student", _spy_redact)

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "order")
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")

    assert order == ["s3", "redact"]


def test_a_write_time_failure_on_a_later_model_rolls_back_an_earlier_ones_update(
    agency_a, django_user_model, monkeypatch
):
    """redact_student now builds every model's empty values BEFORE writing any
    of them (Fix 2), so an unsupported field type refuses up front. But a
    genuine failure while performing the UPDATE itself -- unrelated to
    _empty_value -- can still happen after an earlier model already wrote.
    That case still depends on the caller's transaction.atomic() for
    correctness, and nothing pinned it: the existing fail-closed test
    (test_redaction_refuses_to_run_while_a_field_is_undecided) monkeypatches
    UNDECIDED, which raises before the write pass even starts, so no write
    ever happens there. This one proves the write that DID happen is undone.
    """
    from django.core.exceptions import FieldError
    from django.db import transaction

    from apps.audit.redaction import RedactSpec

    fake_redact = {
        # Applied first, successfully -- application_email really is emptied
        # in the database, inside the still-open outer transaction.
        "tenancy.Membership": RedactSpec("id", ("application_email",)),
        # Applied second: "no_such_field" does not exist on Membership, so
        # this model's own .filter() raises FieldError while attempting its
        # update -- after the first model's write already happened.
        "documents.VerifiedFact": RedactSpec("student__no_such_field", ("payload",)),
    }
    monkeypatch.setattr("apps.audit.redaction.REDACT", fake_redact)

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "amina")
        with pytest.raises(FieldError):
            with transaction.atomic():
                redact_student(tenant_id=agency_a.id, student_id=student.id)
        student.refresh_from_db()

    # The caller's atomic() rolled back the whole block, so the first model's
    # write did not survive -- proving redact_student still needs that
    # wrapper and is not "safe enough" without it.
    assert student.application_email == "amina@example.test"
