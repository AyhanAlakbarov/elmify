from uuid import uuid4

import pytest

from apps.funding.models import PackCandidate, PackVersion, RecommendationCandidate
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import verify_mfa_session
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run


@pytest.fixture
def run(agency_a, membership_a):
    return make_run(agency_a, membership_a)


@pytest.fixture
def candidate_a(agency_a, run):
    return make_db_candidate(agency_a, run, program_name="MSc Chemistry", funding_gap="500.00")


@pytest.fixture
def candidate_b(agency_a, run):
    return make_db_candidate(agency_a, run, program_name="MSc Physics", funding_gap="300.00")


@pytest.fixture
def pack(agency_a, run, candidate_a, candidate_b):
    return make_published_pack(agency_a, run, (candidate_a, candidate_b))


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_dashboard_renders_complete_evidence_for_every_visible_candidate(
    client, domain_a, user_a, membership_a, pack, candidate_a
) -> None:
    client.force_login(user_a)

    response = client.get("/student/recommendation/", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    body = response.content.decode()
    assert "MSc Chemistry" in body
    assert "Official source" in body
    assert "Last checked" in body
    assert "Eligible" in body
    assert "Funding gap" in body
    assert "500.00 EUR" in body
    assert "Approved v" in body  # approval badge
    assert "Total funding gap" in body
    assert "800.00 EUR" in body


@pytest.mark.django_db(transaction=True)
def test_reject_command_creates_a_new_version_and_redirects(
    client, domain_a, user_a, membership_a, pack, candidate_a
) -> None:
    client.force_login(user_a)

    response = client.post(
        f"/student/recommendation/candidates/{candidate_a.id}/reject/", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 302
    with tenant_scope(domain_a.agency_id):
        candidate_a.refresh_from_db()
        assert candidate_a.state == RecommendationCandidate.State.REJECTED
        assert (
            not PackCandidate.objects.filter(candidate_id=candidate_a.id)
            .exclude(pack_version=pack)
            .exists()
        )


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_reject_command_htmx_returns_updated_partial(
    client, domain_a, user_a, membership_a, pack, candidate_a, candidate_b
) -> None:
    client.force_login(user_a)

    response = client.post(
        f"/student/recommendation/candidates/{candidate_a.id}/reject/",
        HTTP_HOST=domain_a.host,
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "MSc Chemistry" not in body
    assert "MSc Physics" in body


@pytest.mark.django_db(transaction=True)
def test_replace_requires_a_reviewed_candidate_id(
    client, domain_a, user_a, membership_a, pack, candidate_a
) -> None:
    client.force_login(user_a)

    missing = client.post(
        f"/student/recommendation/candidates/{candidate_a.id}/replace/", HTTP_HOST=domain_a.host
    )
    assert missing.status_code == 400

    with tenant_scope(domain_a.agency_id):
        checking = make_db_candidate(
            domain_a.agency,
            pack.run,
            program_name="Unreviewed",
            state=RecommendationCandidate.State.CHECKING,
        )
    unreviewed = client.post(
        f"/student/recommendation/candidates/{candidate_a.id}/replace/",
        {"replacement_candidate_id": str(checking.id)},
        HTTP_HOST=domain_a.host,
    )
    assert unreviewed.status_code == 400


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_consider_named_program_requires_a_name_and_queues_review(
    client, domain_a, user_a, membership_a, pack
) -> None:
    client.force_login(user_a)

    empty = client.post("/student/recommendation/named-program/", HTTP_HOST=domain_a.host)
    assert empty.status_code == 400

    response = client.post(
        "/student/recommendation/named-program/",
        {"program_name": "Named Erasmus Mundus Program"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 302

    dashboard = client.get("/student/recommendation/", HTTP_HOST=domain_a.host)
    body = dashboard.content.decode()
    assert "Under review" in body
    assert "Named Erasmus Mundus Program" in body


@pytest.mark.django_db(transaction=True)
def test_commands_404_when_student_has_no_published_pack(
    client, domain_a, user_a, membership_a
) -> None:
    client.force_login(user_a)

    response = client.post(
        f"/student/recommendation/candidates/{uuid4()}/reject/", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_a_students_command_cannot_touch_another_tenants_candidate(
    client, domain_b, user_b, membership_b, pack, candidate_a
) -> None:
    client.force_login(user_b)

    response = client.post(
        f"/student/recommendation/candidates/{candidate_a.id}/reject/", HTTP_HOST=domain_b.host
    )

    assert response.status_code in (400, 404)
    with tenant_scope(pack.tenant_id):
        candidate_a.refresh_from_db()
        assert candidate_a.state == RecommendationCandidate.State.VISIBLE


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_resolve_validation_failure_rerenders_review_with_inline_error(
    client, domain_a, user_a, membership_a, counselor_user, counselor_membership, pack
) -> None:
    # design-lint-baseline defect 5: a failed privileged action must return the
    # review page with an inline alert and the submitted values, not a bare 400.
    client.force_login(user_a)
    client.post(
        "/student/recommendation/named-program/",
        {"program_name": "Named Erasmus Mundus Program"},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(domain_a.agency_id):
        candidate = RecommendationCandidate.objects.get(
            run=pack.run, state=RecommendationCandidate.State.CHECKING
        )
        CounselorAssignment.objects.create(
            tenant=domain_a.agency, counselor=counselor_membership, student=membership_a
        )

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.post(
        f"/counselor/runs/{pack.run_id}/named-program/{candidate.id}/resolve/",
        {"source_url": "https://official.example.test/erasmus-mundus", "reason": "   "},
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == 400
    body = response.content.decode()
    assert 'role="alert"' in body
    assert "A rationale is required." in body
    # The page came back as the real review screen with the input preserved.
    assert "Named Erasmus Mundus Program" in body
    assert 'value="https://official.example.test/erasmus-mundus"' in body


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_counselor_can_resolve_a_named_program_and_the_placeholder_url_is_replaced(
    client, domain_a, user_a, membership_a, counselor_user, counselor_membership, pack,
    monkeypatch,
) -> None:
    import apps.funding.services as services

    queued = []
    monkeypatch.setattr(
        services, "enqueue_research", lambda message, *, queue_url: queued.append(message)
    )
    client.force_login(user_a)
    client.post(
        "/student/recommendation/named-program/",
        {"program_name": "Named Erasmus Mundus Program"},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(domain_a.agency_id):
        candidate = RecommendationCandidate.objects.get(
            run=pack.run, state=RecommendationCandidate.State.CHECKING
        )
        placeholder_url = candidate.evidence.source_url
        CounselorAssignment.objects.create(
            tenant=domain_a.agency, counselor=counselor_membership, student=membership_a
        )
    assert "research.pending.internal" in placeholder_url

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.post(
        f"/counselor/runs/{pack.run_id}/named-program/{candidate.id}/resolve/",
        {
            "source_url": "https://official.example.test/erasmus-mundus",
            "reason": "Confirmed open and eligible for this cycle.",
            "eligible": "true",
        },
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 302

    with tenant_scope(domain_a.agency_id):
        candidate.refresh_from_db()
        assert candidate.state == RecommendationCandidate.State.VISIBLE
        assert candidate.eligible is True
        assert candidate.evidence.source_url == "https://official.example.test/erasmus-mundus"
    # The commit queued the worker's check of the verified site, and nothing else.
    assert [(m.kind, m.candidate_id) for m in queued] == [("check_named_program", candidate.id)]

    client.force_login(user_a)
    dashboard = client.get("/student/recommendation/", HTTP_HOST=domain_a.host)
    body = dashboard.content.decode()
    assert "research.pending.internal" not in body
    assert "https://official.example.test/erasmus-mundus" in body


def _named_candidate(client, domain_a, user_a, pack) -> RecommendationCandidate:
    client.force_login(user_a)
    client.post(
        "/student/recommendation/named-program/",
        {"program_name": "Named Erasmus Mundus Program"},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(domain_a.agency_id):
        return RecommendationCandidate.objects.get(
            run=pack.run, state=RecommendationCandidate.State.CHECKING
        )


@pytest.mark.django_db(transaction=True)
def test_an_unassigned_counselor_cannot_resolve_or_see_the_review(
    client, domain_a, user_a, membership_a, counselor_user, counselor_membership, pack
) -> None:
    """The validation-failure path re-renders the student's whole review page,
    so the assignment check must come before it -- and before the rate limit."""
    candidate = _named_candidate(client, domain_a, user_a, pack)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    url = f"/counselor/runs/{pack.run_id}/named-program/{candidate.id}/resolve/"
    for data in (
        {"source_url": "https://official.example.test/x", "reason": "   "},
        {"source_url": "https://official.example.test/x", "reason": "Fine.", "eligible": "true"},
    ):
        response = client.post(url, data, HTTP_HOST=domain_a.host)
        assert response.status_code == 404
        body = response.content.decode()
        assert "Named Erasmus Mundus Program" not in body
        assert "MSc" not in body
    with tenant_scope(domain_a.agency_id):
        candidate.refresh_from_db()
        assert candidate.state == RecommendationCandidate.State.CHECKING


@pytest.mark.parametrize("lock", ["deletion", "objection"])
@pytest.mark.django_db(transaction=True)
def test_a_paused_students_named_program_is_not_resolved(
    client, domain_a, user_a, membership_a, counselor_user, counselor_membership, pack, lock
) -> None:
    from datetime import timedelta

    from django.utils import timezone

    from apps.audit.models import DeletionRequest
    from apps.funding.models import AuditEvent
    from apps.privacy.models import PrivacyRequest

    candidate = _named_candidate(client, domain_a, user_a, pack)
    now = timezone.now()
    with tenant_scope(domain_a.agency_id):
        CounselorAssignment.objects.create(
            tenant=domain_a.agency, counselor=counselor_membership, student=membership_a
        )
        if lock == "deletion":
            DeletionRequest.objects.create(
                tenant=domain_a.agency, student=membership_a, state="REQUESTED", reason="OTHER"
            )
        else:
            PrivacyRequest.objects.create(
                tenant_id=domain_a.agency_id, student=membership_a, kind="objection",
                channel="email", received_at=now, due_at=now + timedelta(days=9),
            )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.post(
        f"/counselor/runs/{pack.run_id}/named-program/{candidate.id}/resolve/",
        {"source_url": "https://official.example.test/x", "reason": "Fine.", "eligible": "true"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 409
    with tenant_scope(domain_a.agency_id):
        candidate.refresh_from_db()
        assert candidate.state == RecommendationCandidate.State.CHECKING
        assert not AuditEvent.objects.filter(actor=counselor_membership).exists()


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_counselor_review_survives_repeated_student_edits(
    client, domain_a, user_a, membership_a, counselor_user, counselor_membership, pack, candidate_b
) -> None:
    client.force_login(user_a)
    with tenant_scope(domain_a.agency_id):
        replacement_one = make_db_candidate(domain_a.agency, pack.run, program_name="MSc Biology")
        replacement_two = make_db_candidate(domain_a.agency, pack.run, program_name="MSc Geology")
    client.post(
        f"/student/recommendation/candidates/{candidate_b.id}/replace/",
        {"replacement_candidate_id": str(replacement_one.id)},
        HTTP_HOST=domain_a.host,
    )
    client.post(
        f"/student/recommendation/candidates/{replacement_one.id}/replace/",
        {"replacement_candidate_id": str(replacement_two.id)},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(domain_a.agency_id):
        # Each replace auto-publishes its new version now that nothing else
        # ever will (Important #2, remove-counselor-pack-approval-gate final
        # review): three versions total (the original plus two replaces),
        # every one of them published.
        assert PackVersion.objects.filter(run=pack.run, published_at__isnull=True).count() == 0
        assert PackVersion.objects.filter(run=pack.run).count() == 3
        CounselorAssignment.objects.create(
            tenant=domain_a.agency, counselor=counselor_membership, student=membership_a
        )

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.get(f"/counselor/runs/{pack.run_id}/approve/", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert "MSc Geology" in response.content.decode()


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_dashboard_shows_the_most_recent_run_not_the_highest_version_number(
    client, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(domain_a.agency_id):
        old_run = make_run(domain_a.agency, membership_a)
        old_candidate = make_db_candidate(domain_a.agency, old_run, program_name="Old Program")
        old_pack = make_published_pack(domain_a.agency, old_run, (old_candidate,))
        for _ in range(4):
            old_pack = PackVersion.objects.create(
                run=old_run, version=old_pack.version + 1, published_at=None
            )
    new_run = make_run(domain_a.agency, membership_a)
    new_candidate = make_db_candidate(domain_a.agency, new_run, program_name="New Program")
    make_published_pack(domain_a.agency, new_run, (new_candidate,))

    client.force_login(user_a)
    response = client.get("/student/recommendation/", HTTP_HOST=domain_a.host)

    body = response.content.decode()
    assert "New Program" in body
    assert "Old Program" not in body


@pytest.mark.django_db(transaction=True)
def test_consider_named_program_rejects_an_overlong_name(
    client, domain_a, user_a, membership_a, pack
) -> None:
    client.force_login(user_a)

    response = client.post(
        "/student/recommendation/named-program/",
        {"program_name": "x" * 151},
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == 400
    with tenant_scope(domain_a.agency_id):
        assert not RecommendationCandidate.objects.filter(
            run=pack.run, state=RecommendationCandidate.State.CHECKING
        ).exists()


@pytest.mark.django_db(transaction=True)
def test_resolve_named_program_rejects_an_unsafe_or_non_https_source_url(
    client, domain_a, user_a, membership_a, counselor_user, counselor_membership, pack
) -> None:
    client.force_login(user_a)
    client.post(
        "/student/recommendation/named-program/",
        {"program_name": "Named Erasmus Mundus Program"},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(domain_a.agency_id):
        candidate = RecommendationCandidate.objects.get(
            run=pack.run, state=RecommendationCandidate.State.CHECKING
        )
        CounselorAssignment.objects.create(
            tenant=domain_a.agency, counselor=counselor_membership, student=membership_a
        )

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    for unsafe_url in ("javascript:alert(1)", "http://official.example.test/plain", "not-a-url"):
        response = client.post(
            f"/counselor/runs/{pack.run_id}/named-program/{candidate.id}/resolve/",
            {"source_url": unsafe_url, "reason": "x", "eligible": "true"},
            HTTP_HOST=domain_a.host,
        )
        assert response.status_code == 400

    with tenant_scope(domain_a.agency_id):
        candidate.refresh_from_db()
        assert candidate.state == RecommendationCandidate.State.CHECKING


@pytest.mark.django_db(transaction=True)
def test_reject_command_refuses_to_empty_the_pool(
    client, domain_a, user_a, membership_a, run
) -> None:
    with tenant_scope(domain_a.agency_id):
        solo_candidate = make_db_candidate(domain_a.agency, run, program_name="Only Option")
        solo_pack = make_published_pack(domain_a.agency, run, (solo_candidate,))
    client.force_login(user_a)

    response = client.post(
        f"/student/recommendation/candidates/{solo_candidate.id}/reject/", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 400
    with tenant_scope(domain_a.agency_id):
        assert PackCandidate.objects.filter(pack_version=solo_pack).count() == 1


@pytest.mark.django_db(transaction=True)
def test_pack_commands_are_rate_limited_per_student(
    client, domain_a, user_a, membership_a, pack
) -> None:
    from django.core.cache import cache

    cache.clear()
    client.force_login(user_a)

    for _ in range(20):
        response = client.post(
            "/student/recommendation/named-program/",
            {"program_name": "Filler Program"},
            HTTP_HOST=domain_a.host,
        )
        assert response.status_code == 302

    blocked = client.post(
        "/student/recommendation/named-program/",
        {"program_name": "One Too Many"},
        HTTP_HOST=domain_a.host,
    )

    assert blocked.status_code == 429


# --- Inline error re-renders (design-lint-baseline defect 5, student side) ---


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_named_program_failures_re_render_the_page_with_inline_errors(
    client, domain_a, user_a, membership_a, pack
) -> None:
    client.force_login(user_a)

    empty = client.post("/student/recommendation/named-program/", HTTP_HOST=domain_a.host)
    assert empty.status_code == 400
    body = empty.content.decode()
    assert 'role="alert"' in body
    assert "A program name is required." in body
    # The real page came back, not a bare error body.
    assert "<h1>Programmes &amp; funding</h1>" in body

    overlong = client.post(
        "/student/recommendation/named-program/",
        {"program_name": "x" * 151},
        HTTP_HOST=domain_a.host,
    )
    assert overlong.status_code == 400
    body = overlong.content.decode()
    assert "150 characters or fewer" in body
    # The typed name is preserved for correction.
    assert f'value="{"x" * 151}"' in body


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_reject_refusal_re_renders_with_the_service_error_inline(
    client, domain_a, user_a, membership_a, run
) -> None:
    with tenant_scope(domain_a.agency_id):
        solo_candidate = make_db_candidate(domain_a.agency, run, program_name="Only Option")
        make_published_pack(domain_a.agency, run, (solo_candidate,))
    client.force_login(user_a)

    response = client.post(
        f"/student/recommendation/candidates/{solo_candidate.id}/reject/", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 400
    body = response.content.decode()
    assert 'role="alert"' in body
    assert "cannot reject the last remaining candidate in the pack" in body
    assert "Only Option" in body


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_htmx_fragment_error_returns_the_partial_with_the_alert(
    client, domain_a, user_a, membership_a, run
) -> None:
    with tenant_scope(domain_a.agency_id):
        solo_candidate = make_db_candidate(domain_a.agency, run, program_name="Only Option")
        make_published_pack(domain_a.agency, run, (solo_candidate,))
    client.force_login(user_a)

    response = client.post(
        f"/student/recommendation/candidates/{solo_candidate.id}/reject/",
        HTTP_HOST=domain_a.host,
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 400
    body = response.content.decode()
    assert 'role="alert"' in body
    # Fragment, not the full document.
    assert "<h1>" not in body


@pytest.mark.django_db(transaction=True)
def test_boosted_command_is_treated_as_navigation_not_a_fragment_request(
    client, domain_a, user_a, membership_a, pack, candidate_a
) -> None:
    # hx-boost sends HX-Request too; a boosted form must get the redirect (and
    # on failure the full page), never the bare partial swapped into <body>.
    client.force_login(user_a)
    response = client.post(
        f"/student/recommendation/candidates/{candidate_a.id}/reject/",
        HTTP_HOST=domain_a.host,
        HTTP_HX_REQUEST="true",
        HTTP_HX_BOOSTED="true",
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/student/recommendation/"
