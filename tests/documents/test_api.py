"""The door. Every test here is about a boundary -- who may call, what a
refusal reveals, and what a call is allowed to touch -- because the engine
behind it has its own tests and does not need re-testing through HTTP.

Asserts no markup, by design: this surface is JSON, and the presentation
layer that consumes it is deliberately undecided.
"""

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.concierge.documents import apply_scan_result, register
from apps.documents import document_worker, generation, storage
from apps.documents.drafts import create_draft
from apps.documents.letter_schemas import ClaimKind, LetterClaim, LetterContent, LetterUnit
from apps.documents.models import DocumentDraft, VerifiedFact
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.documents.storage import store_document
from apps.documents.verification import fact_payload
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.conftest import reads_no_catalogue

pytestmark = pytest.mark.django_db

LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"


@pytest.fixture
def credentialed_user(db):
    return get_user_model().objects.create_user(
        username="student-login", password="correct-horse-battery"
    )


@pytest.fixture
def credentialed_membership(agency_a, credentialed_user):
    with tenant_scope(agency_a.id):
        return Membership.objects.create(
            tenant=agency_a, user=credentialed_user, role=Membership.Role.STUDENT
        )


def _post(client, url, payload, host):
    return client.post(url, json.dumps(payload), content_type="application/json",
                       HTTP_HOST=host)


def test_login_authenticates_and_starts_a_session(
    client, domain_a, credentialed_user, credentialed_membership
):
    response = _post(
        client,
        LOGIN,
        {"username": "student-login", "password": "correct-horse-battery"},
        domain_a.host,
    )

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert client.session.get("_auth_user_id") == str(credentialed_user.pk)


@pytest.mark.parametrize("typed", ["aysel@example.com", "Aysel@Example.com"])
def test_login_matches_a_signup_address_in_any_case(client, domain_a, agency_a, typed):
    """Signup stores the address lowercased; the student types it as they wrote it."""
    user = get_user_model().objects.create_user(
        username="aysel@example.com", password="correct-horse-battery"
    )
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.STUDENT)
    response = _post(
        client, LOGIN, {"username": typed, "password": "correct-horse-battery"}, domain_a.host
    )
    assert response.status_code == 200
    assert client.session.get("_auth_user_id") == str(user.pk)


def test_a_mixed_case_staff_username_still_logs_in_exactly(client, domain_a):
    user = get_user_model().objects.create_user(
        username="Staff.Member", password="correct-horse-battery"
    )
    response = _post(
        client,
        LOGIN,
        {"username": "Staff.Member", "password": "correct-horse-battery"},
        domain_a.host,
    )
    assert response.status_code == 200
    assert client.session.get("_auth_user_id") == str(user.pk)


def test_a_wrong_password_is_401_and_starts_no_session(
    client, domain_a, credentialed_user, credentialed_membership
):
    response = _post(
        client, LOGIN, {"username": "student-login", "password": "wrong"}, domain_a.host
    )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_credentials"}
    assert "_auth_user_id" not in client.session


def test_a_missing_user_is_the_same_401_as_a_wrong_password(client, domain_a):
    """Same status, same body: a different answer here is a username oracle."""
    response = _post(
        client, LOGIN, {"username": "nobody", "password": "wrong"}, domain_a.host
    )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_credentials"}


def test_login_attempts_are_rate_limited(
    client, domain_a, credentialed_user, credentialed_membership
):
    """There is no actor id before authentication, so the limiter keys on a
    stable integer derived from the submitted username -- keying on the
    client address would limit a whole university's NAT together."""
    for _ in range(10):
        _post(client, LOGIN, {"username": "student-login", "password": "wrong"},
              domain_a.host)

    response = _post(
        client, LOGIN, {"username": "student-login", "password": "wrong"}, domain_a.host
    )

    assert response.status_code == 429


def test_a_unicode_case_variant_shares_the_accounts_login_bucket(client, domain_a, agency_a):
    """Postgres UPPER folds dotless 'ı' to 'I', so username__iexact resolves
    `alıce.smıth@...` to alice's account while Python's .lower() keeps it
    distinct. Keyed on the typed string, every such variant was ten fresh
    guesses at the same password."""
    user = get_user_model().objects.create_user(
        username="alice.smith@example.com", password="correct-horse-battery"
    )
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.STUDENT)
    for _ in range(10):
        _post(client, LOGIN, {"username": "alice.smith@example.com", "password": "wrong"},
              domain_a.host)
    assert _post(client, LOGIN, {"username": "alice.smith@example.com", "password": "wrong"},
                 domain_a.host).status_code == 429

    variant = "alıce.smıth@example.com"
    assert _post(client, LOGIN, {"username": variant, "password": "wrong"},
                 domain_a.host).status_code == 429
    response = _post(client, LOGIN, {"username": variant, "password": "correct-horse-battery"},
                     domain_a.host)
    assert response.status_code == 429
    assert "_auth_user_id" not in client.session


def test_get_issues_the_csrf_cookie_a_post_needs(domain_a):
    """The reason GET exists. With CSRF enforced, a client that has never made
    a request has no token to send, so a POST-only login route is unusable
    from a browser."""
    strict = Client(enforce_csrf_checks=True)

    seeded = strict.get(LOGIN, HTTP_HOST=domain_a.host)

    assert seeded.status_code == 200
    assert "csrftoken" in strict.cookies


def test_a_post_without_a_csrf_token_is_refused(domain_a, credentialed_user):
    strict = Client(enforce_csrf_checks=True)

    response = strict.post(
        LOGIN,
        json.dumps({"username": "student-login", "password": "correct-horse-battery"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == 403


def test_a_body_that_is_not_json_is_a_400(client, domain_a):
    response = client.post(
        LOGIN, "not json", content_type="application/json", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_json"}


def test_logout_ends_the_session(client, domain_a, user_a, membership_a):
    client.force_login(user_a)

    response = client.post(LOGOUT, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_logout_refuses_a_get(client, domain_a, user_a, membership_a):
    """A GET that logs you out is a CSRF hole dressed as a convenience."""
    client.force_login(user_a)

    assert client.get(LOGOUT, HTTP_HOST=domain_a.host).status_code == 405


UPLOADS = "/api/documents/uploads"


def test_an_upload_returns_a_form_scoped_to_a_new_document(
    client, domain_a, user_a, membership_a, monkeypatch
):
    import apps.documents.api as api

    monkeypatch.setattr(
        api,
        "presigned_upload",
        lambda document: {
            "url": "https://s3.example.test/bucket",
            "fields": {"key": document.object_key},
        },
    )
    client.force_login(user_a)

    response = _post(client, UPLOADS, {}, domain_a.host)

    assert response.status_code == 201
    body = response.json()
    assert body["fields"]["key"].startswith(f"quarantine/{domain_a.agency_id}/")
    assert body["fields"]["key"].endswith(body["document_id"])


def test_a_transcript_upload_needs_a_paid_cycle(client, user_a, membership_a, domain_a):
    client.force_login(user_a)

    response = _post(client, UPLOADS, {"kind": "TRANSCRIPT", "role": "ORIGINAL"}, domain_a.host)

    assert response.status_code == 402
    assert response.json() == {"error": "cycle_unpaid"}


def test_a_cycle_without_paid_at_is_unpaid(client, user_a, membership_a, agency_a, domain_a):
    from apps.concierge.models import StudentCycle
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        StudentCycle.objects.create(student=membership_a, academic_year="2026-2027")
    client.force_login(user_a)

    response = _post(client, UPLOADS, {"kind": "TRANSCRIPT", "role": "ORIGINAL"}, domain_a.host)

    assert response.status_code == 402
    assert response.json() == {"error": "cycle_unpaid"}


def test_a_cv_upload_is_not_gated_on_payment(client, user_a, membership_a, domain_a, monkeypatch):
    import apps.documents.api as api

    monkeypatch.setattr(api, "presigned_upload", lambda document: {"url": "", "fields": {}})
    client.force_login(user_a)

    assert _post(client, UPLOADS, {"kind": "CV"}, domain_a.host).status_code == 201


def _tpost(client, domain, **body):
    return client.post(
        UPLOADS, {"kind": "TRANSCRIPT", **body}, content_type="application/json",
        HTTP_HOST=domain.host,
    )


@pytest.fixture
def _no_presign(monkeypatch):
    import apps.documents.api as api

    monkeypatch.setattr(api, "presigned_upload", lambda document: {"url": "", "fields": {}})


def test_a_transcript_upload_records_its_role_and_language(
    client, user_a, membership_a, domain_a, paid_cycle_a, agency_a, _no_presign
):
    from apps.documents.models import TranscriptUpload

    client.force_login(user_a)
    response = _tpost(client, domain_a, role="ORIGINAL", language="az")
    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        upload = TranscriptUpload.objects.get(document_id=response.json()["document_id"])
    assert (upload.role, upload.language, upload.mode, upload.retake_slot, upload.cycle_id) == (
        "ORIGINAL", "az", "ADD", None, paid_cycle_a.id,
    )


@pytest.mark.parametrize(("body", "error"), [
    ({}, "invalid_role"),
    ({"role": "COPY"}, "invalid_role"),
    ({"role": "ORIGINAL", "mode": "APPEND"}, "invalid_mode"),
    ({"role": "ORIGINAL", "mode": "RETAKE"}, "invalid_slot"),
    ({"role": "ORIGINAL", "mode": "RETAKE", "slot": True}, "invalid_slot"),
    ({"role": "ORIGINAL", "slot": 1}, "invalid_slot"),
    ({"role": "TRANSLATION", "language": "az"}, "invalid_language"),
    ({"role": "ORIGINAL", "language": "de"}, "invalid_language"),
    ({"role": "ORIGINAL", "language": ["az"]}, "invalid_language"),
])
def test_a_malformed_transcript_upload_is_refused(
    client, user_a, membership_a, domain_a, paid_cycle_a, body, error, _no_presign
):
    client.force_login(user_a)
    response = _tpost(client, domain_a, **body)
    assert (response.status_code, response.json()) == (400, {"error": error})


def test_a_retake_needs_a_live_page_in_that_slot(
    client, user_a, membership_a, domain_a, paid_cycle_a, _no_presign
):
    client.force_login(user_a)
    response = _tpost(client, domain_a, role="ORIGINAL", mode="RETAKE", slot=3)
    assert (response.status_code, response.json()) == (404, {"error": "slot_not_found"})


def _page(agency_a, membership_a, cycle, upload_doc_id, **fields):
    from apps.documents.models import TranscriptPage, TranscriptUpload

    with tenant_scope(agency_a.id):
        upload = TranscriptUpload.objects.get(document_id=upload_doc_id)
        return TranscriptPage.objects.create(
            student=membership_a, cycle=cycle, upload=upload, number=1, slot=1,
            source="azure", **fields,
        )


def test_a_third_retake_is_refused(
    client, user_a, membership_a, domain_a, paid_cycle_a, agency_a, _no_presign
):
    client.force_login(user_a)
    first = _tpost(client, domain_a, role="ORIGINAL").json()["document_id"]
    _page(agency_a, membership_a, paid_cycle_a, first,
          state="REFUSED", refusal="unreadable", retakes=2)
    response = _tpost(client, domain_a, role="ORIGINAL", mode="RETAKE", slot=1)
    assert (response.status_code, response.json()) == (409, {"error": "retakes_used"})


def test_the_transcript_view_lists_live_pages_and_pages_left(
    client, user_a, membership_a, domain_a, paid_cycle_a, agency_a, _no_presign
):
    client.force_login(user_a)
    first = _tpost(client, domain_a, role="ORIGINAL").json()["document_id"]
    _page(agency_a, membership_a, paid_cycle_a, first,
          state="REFUSED", refusal="cut_off", retakes=1)
    with tenant_scope(agency_a.id):
        paid_cycle_a.pages_used = 7
        paid_cycle_a.save(update_fields=["pages_used"])
    body = client.get("/api/documents/transcript", HTTP_HOST=domain_a.host).json()
    assert body["pages_left"] == 43
    assert body["pages"] == [
        {"slot": 1, "state": "REFUSED", "refusal": "cut_off", "skipped_because": "",
         "retakes_left": 1}
    ]
    assert (body["waiting"], body["delayed"], body["reading_id"]) == (False, False, None)


def test_the_transcript_view_needs_a_paid_cycle(client, user_a, membership_a, domain_a):
    client.force_login(user_a)
    response = client.get("/api/documents/transcript", HTTP_HOST=domain_a.host)
    assert (response.status_code, response.json()) == (402, {"error": "cycle_unpaid"})


def test_an_upload_needs_a_student_session(client, domain_a, counselor_user,
                                           counselor_membership):
    """There is no staff surface behind this door."""
    from tests.conftest import verify_mfa_session

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)

    response = client.post(UPLOADS, HTTP_HOST=domain_a.host)

    assert response.status_code == 403


def test_an_anonymous_upload_is_401(client, domain_a):
    assert client.post(UPLOADS, HTTP_HOST=domain_a.host).status_code == 401


def test_upload_issuance_is_rate_limited(client, domain_a, user_a, membership_a,
                                         monkeypatch):
    """A signed form is a write capability into the evidence bucket. Issuing
    them without a ceiling is issuing unlimited ones."""
    import apps.documents.api as api

    monkeypatch.setattr(api, "presigned_upload", lambda document: {"url": "", "fields": {}})
    client.force_login(user_a)
    for _ in range(10):
        assert _post(client, UPLOADS, {}, domain_a.host).status_code == 201

    assert client.post(UPLOADS, HTTP_HOST=domain_a.host).status_code == 429


def test_the_poll_reports_the_scan_verdict(client, domain_a, user_a, membership_a):
    """BLOCKED must be distinguishable from 'nothing was extracted':
    ingest_uploaded_cv returns () for both, and a student whose file carried
    malware has to be told."""
    document = register(domain_a.agency_id, membership_a.id)
    apply_scan_result(document, "THREATS_FOUND")
    client.force_login(user_a)

    response = client.get(f"{UPLOADS}/{document.id}", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert response.json() == {"state": "BLOCKED", "scan_result": "THREATS_FOUND"}


def test_another_students_upload_is_404(
    client, domain_a, user_a, membership_a, agency_a, django_user_model
):
    """404, not 403: a 403 confirms the document exists."""
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a,
            user=django_user_model.objects.create_user(username="other-student"),
            role=Membership.Role.STUDENT,
        )
    document = register(agency_a.id, other.id)
    client.force_login(user_a)

    response = client.get(f"{UPLOADS}/{document.id}", HTTP_HOST=domain_a.host)

    assert response.status_code == 404


def test_another_tenants_upload_is_404(
    client, domain_a, domain_b, user_a, membership_a, agency_b, membership_b
):
    document = register(agency_b.id, membership_b.id)
    client.force_login(user_a)

    response = client.get(f"{UPLOADS}/{document.id}", HTTP_HOST=domain_a.host)

    assert response.status_code == 404


CANDIDATES = "/api/documents/facts/candidates"
CONFIRM = "/api/documents/facts/confirm"


def _candidate(student, name="Jane Doe"):
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": name},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:test",
        confirmed_by=None,
        created_by=student,
    )


def test_the_candidate_list_is_unconfirmed_facts_only(
    client, domain_a, user_a, membership_a
):
    """A confirmed fact is not a candidate: showing it again invites a second
    click that means nothing."""
    with tenant_scope(domain_a.agency_id):
        pending = _candidate(membership_a)
        settled = _candidate(membership_a, name="Already Confirmed")
        settled.confirmed_by = membership_a
        settled.confirmed_at = pending.created_at
        settled.save(update_fields=["confirmed_by", "confirmed_at"])
    client.force_login(user_a)

    response = client.get(CANDIDATES, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert [fact["id"] for fact in response.json()["facts"]] == [str(pending.id)]


def test_the_candidate_list_is_the_callers_ledger_only(
    client, domain_a, domain_b, user_a, membership_a, agency_b, membership_b
):
    with tenant_scope(agency_b.id):
        _candidate(membership_b, name="Someone Else")
    with tenant_scope(domain_a.agency_id):
        mine = _candidate(membership_a)
    client.force_login(user_a)

    response = client.get(CANDIDATES, HTTP_HOST=domain_a.host)

    assert [fact["id"] for fact in response.json()["facts"]] == [str(mine.id)]


def test_confirming_reports_how_many_changed(client, domain_a, user_a, membership_a):
    with tenant_scope(domain_a.agency_id):
        fact = _candidate(membership_a)
    client.force_login(user_a)

    response = _post(client, CONFIRM, {"fact_ids": [str(fact.id)]}, domain_a.host)

    assert response.status_code == 200
    assert response.json() == {"confirmed": 1}
    fact.refresh_from_db()
    assert fact.confirmed_by_id == membership_a.id


def test_confirming_another_students_fact_is_404(
    client, domain_a, user_a, membership_a, agency_b, membership_b
):
    """404, not 403 -- a 403 confirms the fact exists."""
    with tenant_scope(agency_b.id):
        theirs = _candidate(membership_b, name="Someone Else")
    client.force_login(user_a)

    response = _post(client, CONFIRM, {"fact_ids": [str(theirs.id)]}, domain_a.host)

    assert response.status_code == 404


def test_candidate_list_filters_by_student_within_tenant(
    client, domain_a, user_a, membership_a, django_user_model
):
    """The candidates list filters by student=, not just by RLS. A same-tenant
    sibling student's fact must not appear. This pins the refusal to the
    endpoint's own student= guard, not to row-level security."""
    with tenant_scope(domain_a.agency_id):
        my_fact = _candidate(membership_a)
        sibling_user = django_user_model.objects.create_user(username="sibling-student")
        sibling = Membership.objects.create(
            tenant=domain_a.agency, user=sibling_user, role=Membership.Role.STUDENT, active=True
        )
        _candidate(sibling)
    client.force_login(user_a)

    response = client.get(CANDIDATES, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert [fact["id"] for fact in response.json()["facts"]] == [str(my_fact.id)]


def test_confirm_filters_by_student_within_tenant(
    client, domain_a, user_a, membership_a, django_user_model
):
    """The confirm endpoint filters by student=, not just by RLS. Attempting
    to confirm a same-tenant sibling student's fact must return 404, not 200.
    This pins the refusal to the endpoint's own student= guard, not to
    row-level security."""
    with tenant_scope(domain_a.agency_id):
        sibling_user = django_user_model.objects.create_user(username="sibling-student")
        sibling = Membership.objects.create(
            tenant=domain_a.agency, user=sibling_user, role=Membership.Role.STUDENT, active=True
        )
        sibling_fact = _candidate(sibling)
    client.force_login(user_a)

    response = _post(
        client, CONFIRM, {"fact_ids": [str(sibling_fact.id)]}, domain_a.host
    )

    assert response.status_code == 404
    sibling_fact.refresh_from_db()
    assert sibling_fact.confirmed_by is None


def test_a_malformed_fact_id_is_a_400(client, domain_a, user_a, membership_a):
    client.force_login(user_a)

    response = _post(client, CONFIRM, {"fact_ids": ["not-a-uuid"]}, domain_a.host)

    assert response.status_code == 400
    assert response.json() == {"error": "fact_ids_invalid"}


def test_an_empty_or_missing_fact_id_list_is_a_400(client, domain_a, user_a, membership_a):
    client.force_login(user_a)

    assert _post(client, CONFIRM, {"fact_ids": []}, domain_a.host).status_code == 400
    assert _post(client, CONFIRM, {}, domain_a.host).status_code == 400


def test_an_oversized_batch_is_refused_before_the_query(
    client, domain_a, user_a, membership_a
):
    """A cap on the list length, not on what it costs to find out it was
    wrong: 10,000 ids is one request that becomes one enormous IN clause."""
    from uuid import uuid4

    client.force_login(user_a)

    response = _post(
        client, CONFIRM, {"fact_ids": [str(uuid4()) for _ in range(201)]}, domain_a.host
    )

    assert response.status_code == 400
    assert response.json() == {"error": "too_many_fact_ids"}


GENERATE = "/api/documents/generate"


@pytest.fixture
def queued(monkeypatch):
    """Captures enqueued work instead of calling SQS."""
    import apps.documents.api as api

    messages = []
    monkeypatch.setattr(
        api, "enqueue_document_work", lambda message, **kw: messages.append(message)
    )
    return messages


def _generatable_student(agency_a, membership_a):
    """A student who passes all three pre-flight checks."""
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        fact.confirmed_by = membership_a
        fact.confirmed_at = fact.created_at
        fact.save(update_fields=["confirmed_by", "confirmed_at"])
        membership_a.application_email = "student@mail.example.test"
        membership_a.save(update_fields=["application_email"])
    return membership_a


def test_generate_enqueues_exactly_one_message(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)

    response = _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    assert response.status_code == 202
    assert len(queued) == 1
    assert queued[0].action == "generate"
    assert queued[0].student_id == membership_a.id
    assert queued[0].tenant_id == agency_a.id


def _pack_with(agency, student, program):
    """A published pack for ``student`` holding one candidate for ``program``."""
    from apps.funding.models import RecommendationCandidate
    from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

    run = make_run(agency, student)
    candidate = make_db_candidate(agency, run)
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(program_id=program.id)
    return make_published_pack(agency, run, (candidate,))


def test_generate_carries_a_programme_through_to_the_queue(
    client, domain_a, user_a, membership_a, agency_a, queued, program_factory
):
    """The id travels, never the Program: tailoring runs in the worker, which
    reads the catalog row itself. The door checks pack membership only, on
    tenant rows, and so reads no catalogue table."""
    programme = program_factory()
    _pack_with(agency_a, membership_a, programme)
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)

    with reads_no_catalogue():
        response = _post(
            client, GENERATE, {"kind": "CV", "programme_id": str(programme.id)}, domain_a.host
        )

    assert response.status_code == 202
    assert queued[0].programme_id == programme.id


def test_a_programme_the_student_applies_to_counts_as_in_the_pack(
    client, domain_a, user_a, membership_a, agency_a, queued, program_factory
):
    from tests.portals.test_kit_view import _application

    programme = program_factory()
    _generatable_student(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        application.program_id = programme.id
        application.save(update_fields=["program_id"])
    client.force_login(user_a)

    response = _post(
        client, GENERATE, {"kind": "CV", "programme_id": str(programme.id)}, domain_a.host
    )

    assert response.status_code == 202
    assert queued[0].programme_id == programme.id


def test_an_existing_programme_outside_the_pack_is_400_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued, program_factory
):
    """Existence in the corpus buys nothing: the answer is about the
    student's own pack, so it is no oracle over which catalogue ids exist."""
    in_pack, elsewhere = program_factory(), program_factory()
    _pack_with(agency_a, membership_a, in_pack)
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)

    for programme_id in (elsewhere.id, uuid4()):
        response = _post(
            client, GENERATE, {"kind": "CV", "programme_id": str(programme_id)}, domain_a.host
        )
        assert response.status_code == 400
        assert response.json() == {"error": "programme_not_in_pack"}
    assert queued == []


def test_another_tenants_pack_programme_is_400(
    client, domain_a, user_a, membership_a, agency_a, agency_b, membership_b, queued,
    program_factory,
):
    programme = program_factory()
    _pack_with(agency_b, membership_b, programme)
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)

    response = _post(
        client, GENERATE, {"kind": "CV", "programme_id": str(programme.id)}, domain_a.host
    )

    assert response.status_code == 400
    assert response.json() == {"error": "programme_not_in_pack"}
    assert queued == []


def test_a_malformed_programme_id_is_400_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)

    response = _post(
        client, GENERATE, {"kind": "CV", "programme_id": "not-a-uuid"}, domain_a.host
    )

    assert response.status_code == 400
    assert response.json() == {"error": "unknown_programme"}
    assert queued == []


def test_the_door_cannot_queue_enough_work_to_trip_the_skill_match_limit():
    """The one predictable failure this endpoint does NOT check, because it
    cannot happen: tailoring's limiter lives in the worker, so a SkillMatchRateLimited
    would surface as a dead-letter entry instead of a 429. It stays unreachable only
    while the door's own ceiling is the lower of the two over the same window."""
    from apps.documents import tailoring

    assert generation._CV_GENERATION_RATE_WINDOW_SECONDS == tailoring._RATE_LIMIT_WINDOW_SECONDS
    assert generation._CV_GENERATION_RATE_LIMIT < tailoring._RATE_LIMIT


def test_an_unconfirmed_identity_is_409_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    """The predictable failure a job table was going to report asynchronously.
    Every check here is cheap, so the student is told at request time."""
    with tenant_scope(agency_a.id):
        _candidate(membership_a)
        membership_a.application_email = "student@mail.example.test"
        membership_a.save(update_fields=["application_email"])
    client.force_login(user_a)

    response = _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    assert response.status_code == 409
    assert response.json() == {"error": "identity_not_confirmed"}
    assert queued == []


def test_a_missing_application_email_is_409_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        fact.confirmed_by = membership_a
        fact.confirmed_at = fact.created_at
        fact.save(update_fields=["confirmed_by", "confirmed_at"])
    client.force_login(user_a)

    response = _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    assert response.status_code == 409
    assert response.json() == {"error": "application_email_missing"}
    assert queued == []


def test_generation_is_rate_limited_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)
    for _ in range(10):
        _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    response = _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    assert response.status_code == 429
    assert len(queued) == 10


def test_an_unsupported_kind_is_400(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    """DocumentDraft.Kind already carries MOTIVATION_LETTER and CORE_NARRATIVE.
    The letter engine widens _SUPPORTED_KINDS -- until it does, this door does
    not pretend to build one."""
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)

    response = _post(client, GENERATE, {"kind": "MOTIVATION_LETTER"}, domain_a.host)

    assert response.status_code == 400
    assert queued == []


DRAFTS = "/api/documents/drafts"

#: Kept as its own EducationEntry (not inlined in _cv_content) so
#: _education_candidate can build its VerifiedFact payload from the exact
#: same instance via fact_payload -- see that function's docstring.
_DRAFT_EDUCATION = EducationEntry(
    degree_as_awarded="BSc",
    institution_original="Example U",
    city="Berlin",
    country="DE",
    start_date="2020-09-01",
)


def _cv_content(name="Jane Doe"):
    return CVContent(
        personal_information=PersonalInformation(full_name=name, email="jane@example.com"),
        education=(_DRAFT_EDUCATION,),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )


def _education_candidate(student):
    """A confirmable EDUCATION fact backing _cv_content's education entry.

    education has min_length=1 on CVContent, so every draft built from
    _cv_content carries a claim in that category. verify_against_facts
    treats a category with no matching VerifiedFact at all as UNSUPPORTED
    (test_approval.py::test_unsupported_claim_blocks_even_when_the_caller_says_otherwise
    pins the same case), and UNSUPPORTED blocks mark_ready. A test that wants
    an approvable draft needs this alongside _candidate's IDENTITY fact.
    """
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload=fact_payload(_DRAFT_EDUCATION, category=VerifiedFact.Category.EDUCATION),
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:test",
        confirmed_by=None,
        created_by=student,
    )


def _draft_for(agency, student, name="Jane Doe"):
    with tenant_scope(agency.id):
        return create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_cv_content(name)
        )


def test_the_draft_list_is_newest_first(client, domain_a, user_a, membership_a, agency_a):
    """This is how the client learns a generation finished -- there is no job
    row to poll, by design."""
    _draft_for(agency_a, membership_a)
    second = _draft_for(agency_a, membership_a)
    client.force_login(user_a)

    response = client.get(DRAFTS, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    versions = [draft["version"] for draft in response.json()["drafts"]]
    assert versions == [2, 1]
    assert response.json()["drafts"][0]["id"] == str(second.id)


def test_a_draft_reads_back_with_its_verdicts(
    client, domain_a, user_a, membership_a, agency_a
):
    """Verdicts are computed against the live ledger, not stored: the review
    overlay must show what mark_ready will find, not what was true when the
    draft was written."""
    with tenant_scope(agency_a.id):
        identity = _candidate(membership_a)
        identity.confirmed_by = membership_a
        identity.confirmed_at = identity.created_at
        identity.save(update_fields=["confirmed_by", "confirmed_at"])
    draft = _draft_for(agency_a, membership_a)
    client.force_login(user_a)

    response = client.get(f"{DRAFTS}/{draft.id}", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    body = response.json()
    assert body["content"]["personal_information"]["full_name"] == "Jane Doe"
    assert {verdict["claim_path"] for verdict in body["verdicts"]}


def test_another_students_draft_is_404(
    client, domain_a, user_a, membership_a, agency_b, membership_b
):
    draft = _draft_for(agency_b, membership_b)
    client.force_login(user_a)

    assert client.get(f"{DRAFTS}/{draft.id}", HTTP_HOST=domain_a.host).status_code == 404


def test_draft_detail_filters_by_student_within_tenant(
    client, domain_a, user_a, membership_a, agency_a, django_user_model
):
    """The endpoint's own boundary is its student= filter. A second TENANT
    proves nothing about it -- row-level security hides that row either way --
    so the case that pins it is a sibling student in the SAME tenant. Same
    call as Rulings R4 and R10 made for the service layer and for the
    candidates and confirm endpoints."""
    with tenant_scope(agency_a.id):
        sibling_user = django_user_model.objects.create_user(username="sibling-draft")
        sibling = Membership.objects.create(
            tenant=agency_a, user=sibling_user, role=Membership.Role.STUDENT, active=True
        )
    draft = _draft_for(agency_a, sibling)
    client.force_login(user_a)

    assert client.get(f"{DRAFTS}/{draft.id}", HTTP_HOST=domain_a.host).status_code == 404


def test_a_draft_names_its_artefact_only_once_one_is_stored(
    client, domain_a, user_a, membership_a, agency_a, queued, fake_store
):
    """The journey's last hand-off, and what a client polls. Null before
    approval, still null after approval until the worker has stored the
    artefact, then the name store_document actually wrote -- never a name
    resolved live on the web, which named a missing object whenever the
    programme or funder changed after rendering."""
    with tenant_scope(agency_a.id):
        identity = _candidate(membership_a)
        identity.confirmed_by = membership_a
        identity.confirmed_at = identity.created_at
        identity.save(update_fields=["confirmed_by", "confirmed_at"])
        education = _education_candidate(membership_a)
        education.confirmed_by = membership_a
        education.confirmed_at = education.created_at
        education.save(update_fields=["confirmed_by", "confirmed_at"])
    draft = _draft_for(agency_a, membership_a)
    client.force_login(user_a)

    before = client.get(f"{DRAFTS}/{draft.id}", HTTP_HOST=domain_a.host).json()
    assert before["download_path"] is None

    _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)
    approved = client.get(f"{DRAFTS}/{draft.id}", HTTP_HOST=domain_a.host).json()
    assert approved["download_path"] is None

    draft.refresh_from_db()
    with tenant_scope(agency_a.id):
        store_document(
            draft=draft, filename="cv-german-tabular.pdf", content=b"%PDF", store=fake_store
        )
    with reads_no_catalogue():
        rendered = client.get(f"{DRAFTS}/{draft.id}", HTTP_HOST=domain_a.host).json()
    assert rendered["download_path"] == f"/documents/{draft.id}/cv-german-tabular.pdf"


def test_approve_marks_ready_and_enqueues_one_render(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    with tenant_scope(agency_a.id):
        identity = _candidate(membership_a)
        identity.confirmed_by = membership_a
        identity.confirmed_at = identity.created_at
        identity.save(update_fields=["confirmed_by", "confirmed_at"])
        education = _education_candidate(membership_a)
        education.confirmed_by = membership_a
        education.confirmed_at = education.created_at
        education.save(update_fields=["confirmed_by", "confirmed_at"])
    draft = _draft_for(agency_a, membership_a)
    client.force_login(user_a)

    response = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)
    assert response.status_code == 202
    draft.refresh_from_db()
    assert draft.status == DocumentDraft.Status.APPROVED
    assert [message.action for message in queued] == ["render"]
    assert queued[0].draft_id == draft.id


def test_approving_an_already_approved_draft_enqueues_no_second_render(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    """mark_ready is idempotent on an already-APPROVED draft -- it returns the
    row unchanged rather than raising -- so the render it triggers must be
    idempotent too: a double-click or a retried request must not cost a
    second render for the same draft."""
    with tenant_scope(agency_a.id):
        identity = _candidate(membership_a)
        identity.confirmed_by = membership_a
        identity.confirmed_at = identity.created_at
        identity.save(update_fields=["confirmed_by", "confirmed_at"])
        education = _education_candidate(membership_a)
        education.confirmed_by = membership_a
        education.confirmed_at = education.created_at
        education.save(update_fields=["confirmed_by", "confirmed_at"])
    draft = _draft_for(agency_a, membership_a)
    client.force_login(user_a)

    first = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)
    draft.refresh_from_db()
    approved_at_after_first = draft.approved_at
    second = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)

    assert first.status_code == 202
    assert second.status_code == 202
    assert [message.action for message in queued] == ["render"]
    draft.refresh_from_db()
    assert draft.approved_at == approved_at_after_first


def test_a_blocked_approval_is_409_with_its_verdicts_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    """A name nothing in the ledger supports blocks release. The student is
    shown which claims blocked it -- that list is the only actionable part of
    the refusal -- and no render is queued for a document that never
    approved."""
    draft = _draft_for(agency_a, membership_a, name="Unsupported Name")
    client.force_login(user_a)

    response = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)

    assert response.status_code == 409
    assert response.json()["error"] == "approval_blocked"
    assert response.json()["verdicts"]
    assert queued == []
    draft.refresh_from_db()
    assert draft.status == DocumentDraft.Status.DRAFT


def test_approving_another_students_draft_is_404(
    client, domain_a, user_a, membership_a, agency_b, membership_b, queued
):
    draft = _draft_for(agency_b, membership_b)
    client.force_login(user_a)

    response = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)

    assert response.status_code == 404
    assert queued == []


def test_approve_filters_by_student_within_tenant(
    client, domain_a, user_a, membership_a, agency_a, django_user_model, queued
):
    """Approval is consent, so this is the endpoint where a missing student=
    filter would be worst: one student approving another's document. The
    cross-tenant case above is satisfied by RLS alone and cannot pin it."""
    with tenant_scope(agency_a.id):
        sibling_user = django_user_model.objects.create_user(username="sibling-approve")
        sibling = Membership.objects.create(
            tenant=agency_a, user=sibling_user, role=Membership.Role.STUDENT, active=True
        )
    draft = _draft_for(agency_a, sibling)
    client.force_login(user_a)

    response = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)

    assert response.status_code == 404
    draft.refresh_from_db()
    assert draft.status == DocumentDraft.Status.DRAFT
    assert queued == []


def _letter_draft_for(agency, student):
    """A MOTIVATION_LETTER draft this generic CV door must never see.

    approval.verdicts_for became kind-aware for letter drafts (Task 14): a
    LetterContent-shaped draft now validates cleanly instead of always
    failing closed on "malformed content", so draft_detail/approve's own
    id/student-only filter is no longer enough to keep a letter draft out --
    that used to be an accidental side effect of the old bug. The claim
    doesn't need to resolve to a real fact; these endpoints must 404 before
    ever computing a verdict.
    """
    content = LetterContent(
        language="en",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                text="I want to study here.",
                claims=(
                    LetterClaim(
                        text="study here",
                        span_start=2,
                        span_end=12,
                        kind=ClaimKind.FACTUAL,
                        fact_id=uuid4(),
                    ),
                ),
            ),
        ),
    )
    with tenant_scope(agency.id):
        return create_draft(
            student=student, kind=DocumentDraft.Kind.MOTIVATION_LETTER, content=content
        )


def test_draft_detail_of_a_letter_draft_is_404(
    client, domain_a, user_a, membership_a, agency_a
):
    """The exact scenario apps.documents.api's kind__in=_SUPPORTED_KINDS
    filter exists to close: a MOTIVATION_LETTER draft hitting the generic CV
    detail endpoint must read as not-found, not leak a LetterContent-shaped
    body through claim_path/fact_id keys this view was never taught to
    render, and not 500 trying."""
    draft = _letter_draft_for(agency_a, membership_a)
    client.force_login(user_a)

    response = client.get(f"{DRAFTS}/{draft.id}", HTTP_HOST=domain_a.host)

    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


def test_approve_of_a_letter_draft_is_404_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    """The same scenario for approve: a letter draft must never reach
    mark_ready through this door, since that would auto-approve it without
    ever running is_letter_blocked's gates (those only run inside
    mark_letter_ready)."""
    draft = _letter_draft_for(agency_a, membership_a)
    client.force_login(user_a)

    response = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)

    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}
    draft.refresh_from_db()
    assert draft.status == DocumentDraft.Status.DRAFT
    assert queued == []


def test_the_journey_joins_up_across_the_tier_boundary(
    client, domain_a, user_a, membership_a, agency_a, queued, fake_store, monkeypatch
):
    """The one test that crosses the boundary this branch is entirely about.

    Every other worker test monkeypatches the expensive call and every other
    API test asserts on a captured enqueue, so no test had ever taken a
    DocumentWorkMessage that api.generate actually produced and handed it to
    handle_document_work. The branch's whole claim is end-to-end reachability,
    and the joins were the one thing unexercised.

    Stubbed: the model client, and the object store. Everything else -- the
    ledger reads, verification, the variant resolution, weasyprint, the key
    derivation -- runs for real, and the artefact is fetched back through the
    download route the API pointed at rather than through a re-derived key.
    """
    with tenant_scope(agency_a.id):
        identity = _candidate(membership_a)
        education = _education_candidate(membership_a)
        membership_a.application_email = "journey@mail.example.test"
        membership_a.save(update_fields=["application_email"])
    monkeypatch.setattr(generation, "OpenAI", lambda *a, **kw: _journey_model())
    client.force_login(user_a)

    confirmed = _post(
        client, CONFIRM, {"fact_ids": [str(identity.id), str(education.id)]}, domain_a.host
    )
    assert confirmed.json() == {"confirmed": 2}

    assert _post(client, GENERATE, {"kind": "CV"}, domain_a.host).status_code == 202
    (generate_message,) = queued
    document_worker.handle_document_work(generate_message)

    listed = client.get(DRAFTS, HTTP_HOST=domain_a.host).json()["drafts"]
    assert [row["status"] for row in listed] == ["DRAFT"]
    draft_id = listed[0]["id"]
    detail = client.get(f"{DRAFTS}/{draft_id}", HTTP_HOST=domain_a.host).json()
    assert detail["download_path"] is None

    assert _post(client, f"{DRAFTS}/{draft_id}/approve", {}, domain_a.host).status_code == 202
    render_message = queued[1]
    assert render_message.action == "render"
    monkeypatch.setattr(document_worker, "_object_store", lambda: fake_store)
    document_worker.handle_document_work(render_message)

    approved = client.get(f"{DRAFTS}/{draft_id}", HTTP_HOST=domain_a.host).json()
    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    download = client.get(approved["download_path"], HTTP_HOST=domain_a.host)

    assert download.status_code == 200
    assert download["Content-Type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")


def _journey_model():
    """The model call the worker makes, answered with content the confirmed
    ledger actually supports -- an unsupported claim would block approval."""
    client = MagicMock()
    response = MagicMock()
    response.output_parsed = _cv_content()
    response.output = []
    response.usage = None
    response.id = "resp_journey"
    client.responses.parse.return_value = response
    return client


def test_the_poll_reports_the_uploads_reading_state(
    client, user_a, membership_a, domain_a, paid_cycle_a, _no_presign
):
    client.force_login(user_a)
    document_id = _tpost(client, domain_a, role="ORIGINAL").json()["document_id"]
    body = client.get(f"{UPLOADS}/{document_id}", HTTP_HOST=domain_a.host).json()
    assert body["reading"] == {"state": "PENDING", "refusal": "", "refusal_page": None}


def _replace_in_flight(
    client, domain, agency, state, *, doc_state=None, age_minutes=0, lease_minutes=5
):
    """A REPLACE upload made through the API, then put in the given state."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.concierge.models import DocumentVersion
    from apps.documents.models import TranscriptUpload

    doc_id = _tpost(client, domain, role="ORIGINAL", mode="REPLACE").json()["document_id"]
    with tenant_scope(agency.id):
        TranscriptUpload.objects.filter(document_id=doc_id).update(
            state=state,
            created_at=timezone.now() - timedelta(minutes=age_minutes),
            next_attempt_at=timezone.now() + timedelta(minutes=lease_minutes),
        )
        if doc_state:
            DocumentVersion.objects.filter(id=doc_id).update(state=doc_state)


_BLOCKING = [
    ("READING", None, 0),
    ("DELAYED", None, 0),
    ("PENDING", None, 1),
    ("PENDING", "AVAILABLE", 19),
]
_FREE = [
    ("READ", None, 0),
    ("REFUSED", None, 0),
    ("FAILED", None, 0),
    ("PENDING", "QUARANTINED", 21),
    ("PENDING", "AVAILABLE", 25),
    ("PENDING", None, 25),
]
_NEW = [
    {"mode": "ADD"},
    {"mode": "REPLACE"},
    {"mode": "RETAKE", "slot": 1},
]


@pytest.mark.parametrize("new", _NEW)
@pytest.mark.parametrize(("state", "doc_state", "age"), _BLOCKING)
def test_no_transcript_upload_while_a_replace_is_in_flight(
    client, user_a, membership_a, domain_a, paid_cycle_a, agency_a, _no_presign,
    state, doc_state, age, new,
):
    client.force_login(user_a)
    first = _tpost(client, domain_a, role="ORIGINAL").json()["document_id"]
    _page(agency_a, membership_a, paid_cycle_a, first, state="READ")
    _replace_in_flight(client, domain_a, agency_a, state, doc_state=doc_state, age_minutes=age)
    response = _tpost(client, domain_a, role="ORIGINAL", **new)
    assert (response.status_code, response.json()) == (409, {"error": "replace_pending"})
    body = client.get("/api/documents/transcript", HTTP_HOST=domain_a.host).json()
    assert body["replace_pending"] is True


@pytest.mark.parametrize("new", _NEW)
@pytest.mark.parametrize(("state", "doc_state", "age"), _FREE)
def test_a_settled_or_abandoned_replace_does_not_block_uploads(
    client, user_a, membership_a, domain_a, paid_cycle_a, agency_a, _no_presign,
    state, doc_state, age, new,
):
    client.force_login(user_a)
    first = _tpost(client, domain_a, role="ORIGINAL").json()["document_id"]
    _page(agency_a, membership_a, paid_cycle_a, first, state="READ")
    _replace_in_flight(client, domain_a, agency_a, state, doc_state=doc_state, age_minutes=age)
    body = client.get("/api/documents/transcript", HTTP_HOST=domain_a.host).json()
    assert body["replace_pending"] is False
    assert _tpost(client, domain_a, role="ORIGINAL", **new).status_code == 201


def test_a_reading_replace_whose_lease_lapsed_does_not_block_uploads(
    client, user_a, membership_a, domain_a, paid_cycle_a, agency_a, _no_presign,
):
    client.force_login(user_a)
    first = _tpost(client, domain_a, role="ORIGINAL").json()["document_id"]
    _page(agency_a, membership_a, paid_cycle_a, first, state="READ")
    _replace_in_flight(client, domain_a, agency_a, "READING", lease_minutes=-5)
    body = client.get("/api/documents/transcript", HTTP_HOST=domain_a.host).json()
    assert body["replace_pending"] is False
    assert _tpost(client, domain_a, role="ORIGINAL", mode="ADD").status_code == 201


def test_an_upload_may_be_any_document_the_table_lists(
    client, domain_a, user_a, membership_a, monkeypatch
):
    import apps.documents.api as api

    monkeypatch.setattr(
        api, "presigned_upload", lambda document: {"url": "https://s3.test/", "fields": {}}
    )
    client.force_login(user_a)
    for kind in ("PASSPORT", "DIPLOMA", "LANGUAGE_CERTIFICATE", "RECOMMENDATION", "OTHER"):
        response = _post(client, "/api/documents/uploads", {"kind": kind}, domain_a.host)
        assert response.status_code == 201, kind
    refused = _post(client, "/api/documents/uploads", {"kind": "SELFIE"}, domain_a.host)
    assert refused.status_code == 400
