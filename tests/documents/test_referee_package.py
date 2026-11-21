"""The request package (lanes spec §11.3): the student sends it; we never email anyone."""

import pytest
from django.utils import timezone

from apps.concierge.models import DocumentVersion
from apps.documents.models import DocumentDraft, Referee, RefereeRequest, VerifiedFact
from apps.documents.referee_package import package_cv
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db
pack = dashboard_conftest.pack  # the fixture, shared with the dashboard tests
_SNAPSHOT = {"source": "CATALOGUE", "steps": [{
    "position": 1, "purpose": "APPLY", "channel": "PORTAL",
    "portal_url": "https://apply.tum.de/start", "portal_system": "TUMonline",
    "dates": [{"role": "FINAL", "date": "2027-01-15", "timezone": "Europe/Berlin"}],
}]}


@pytest.fixture
def asked(agency_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(
            agency_a, membership_a, programme, route_snapshot=_SNAPSHOT,
            kit_requirements=["Two letters from academic referees who know your research."],
        )
        referee = Referee.objects.create(
            tenant=agency_a, student=membership_a, name="Rauf Aliyev", title="Prof.",
            relationship="Algorithms (A), and my thesis on graph search.",
        )
        request = RefereeRequest.objects.create(
            tenant=agency_a, referee=referee, application=card, mode="PORTAL_INVITE",
            state="AGREED",
        )
        VerifiedFact.objects.create(
            student=membership_a, category=VerifiedFact.Category.EDUCATION,
            payload={"degree_english": "BSc Computer Science", "institution_english": "ADA",
                     "grade_native": "91/100"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT, source_ref="cv",
            confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a,
        )
    return referee, request


def test_the_package_lists_deadline_portal_senders_and_what_the_programme_wants(
    client, agency_a, domain_a, user_a, membership_a, asked, mailoutbox
) -> None:
    referee, _request = asked
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get(
            f"/student/referees/{referee.id}/package/", HTTP_HOST=domain_a.host
        ).content.decode()
    assert "What to send Prof. Rauf Aliyev" in body
    assert "15 Jan, 23:59 Berlin time" in body
    assert "TUMonline" in body
    assert "campus.tum.de, apply.tum.de" in body
    assert "Two letters from academic referees who know your research." in body
    assert "BSc Computer Science, ADA, grade 91/100" in body
    assert "Algorithms (A), and my thesis on graph search." in body
    assert "Dear Prof. Rauf Aliyev," in body
    assert "- M.Sc. Informatics: due 15 Jan, 23:59 Berlin time; the portal will email you" in body
    assert "No CV yet." in body
    assert mailoutbox == []


def test_a_withdrawn_application_leaves_the_package(
    client, agency_a, domain_a, user_a, membership_a, asked
) -> None:
    from apps.portals.models import Application

    referee, request = asked
    with tenant_scope(agency_a.id):
        Application.objects.filter(id=request.application_id).update(outcome="WITHDRAWN")
    client.force_login(user_a)
    body = client.get(
        f"/student/referees/{referee.id}/package/", HTTP_HOST=domain_a.host
    ).content.decode()
    assert "M.Sc. Informatics" not in body
    assert "No applications for Prof. Rauf Aliyev yet." in body


def test_marking_a_request_changes_its_state_and_sends_nothing(
    client, agency_a, domain_a, user_a, membership_a, asked, mailoutbox
) -> None:
    _referee, request = asked
    client.force_login(user_a)
    for state in ("SUBMITTED", "PROPOSED"):
        client.post(
            f"/student/referees/requests/{request.id}/state/", {"state": state},
            HTTP_HOST=domain_a.host,
        )
    with tenant_scope(agency_a.id):
        request.refresh_from_db()
        assert AuditEvent.objects.filter(event="referee.request_state").count() == 1
    assert request.state == "SUBMITTED"
    assert mailoutbox == []


def test_another_students_package_and_request_are_404(
    client, agency_a, domain_a, user_b, asked
) -> None:
    from apps.tenancy.models import Membership

    referee, request = asked
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
    client.force_login(user_b)
    assert client.get(
        f"/student/referees/{referee.id}/package/", HTTP_HOST=domain_a.host
    ).status_code == 404
    assert client.post(
        f"/student/referees/requests/{request.id}/state/", {"state": "ASKED"},
        HTTP_HOST=domain_a.host,
    ).status_code == 404


def test_the_cv_is_the_newest_approved_draft_else_an_upload(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        assert package_cv(membership_a) is None
        DocumentVersion.objects.create(
            student=membership_a, object_key="k", kind="CV", state="AVAILABLE"
        )
        assert package_cv(membership_a).url == ""
        assert package_cv(membership_a).label.startswith("The CV you uploaded on ")
        for version in (1, 2):
            draft = DocumentDraft.objects.create(
                student=membership_a, kind="CV", version=version, content={},
                status="APPROVED", rendered_filename="cv-standard.pdf",
            )
        cv = package_cv(membership_a)
    assert cv.url == f"/documents/{draft.id}/cv-standard.pdf"
    assert cv.label == "Your CV (version 2)"


def test_a_request_a_swap_removed_in_another_tab_is_a_redirect_not_a_500(
    client, agency_a, domain_a, user_a, membership_a, asked, monkeypatch
) -> None:
    """Final review M1: the mark takes the student's lock and writes by id, so a row
    another tab deleted first changes nothing and records nothing."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    referee, request = asked
    client.force_login(user_a)
    with CaptureQueriesContext(connection) as queries:
        client.post(
            f"/student/referees/requests/{request.id}/state/", {"state": "ASKED"},
            HTTP_HOST=domain_a.host,
        )
    assert any(
        "FOR UPDATE" in q["sql"] and "tenancy_membership" in q["sql"]
        for q in queries.captured_queries
    )

    def swapped_in_another_tab(_request, _student) -> bool:
        RefereeRequest.objects.filter(id=request.id).delete()
        return False

    monkeypatch.setattr("apps.documents.referee_package._limited", swapped_in_another_tab)
    response = client.post(
        f"/student/referees/requests/{request.id}/state/", {"state": "SUBMITTED"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 302
    assert response["Location"] == f"/student/referees/{referee.id}/package/"
    with tenant_scope(agency_a.id):
        assert not RefereeRequest.objects.exists()
        assert AuditEvent.objects.filter(event="referee.request_state").count() == 1


def test_package_includes_shared_work_from_cv_github_and_transcript_courses(
    client, agency_a, domain_a, user_a, membership_a, asked
) -> None:
    from apps.documents.evidence import facts as evidence_facts

    referee, _request = asked
    with tenant_scope(agency_a.id):
        now = timezone.now()
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.RESEARCH,
            payload={
                "thesis_title": "Heuristic Graph Search on Road Networks",
                "supervisor": "Prof. Rauf Aliyev",
                "institution": "ADA University",
                "outcomes": "Reduced query expansions by 38%.",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.PUBLICATION,
            payload={
                "authors": ["Student A", "R. Aliyev"],
                "title": "Bidirectional A* With Landmarks",
                "venue": "WG",
                "year": 2026,
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        evidence_facts.save_reading(
            membership_a,
            source_kind="github",
            changed_at=timezone.now(),
            reader_version=1,
            repo="aliyevlab/graph-search",
            reading={
                "url": "https://github.com/aliyevlab/graph-search",
                "summary": "C++ implementation of landmark-guided shortest paths.",
                "kind": "research",
                "names": ["Heuristic Graph Search on Road Networks"],
                "origin": {"owner_type": "Organization", "owner_name": "Aliyev Lab", "commits": 19},
                "bullets": [
                    {
                        "text": "Implemented ALT landmark selection in C++20.",
                        "evidence": ["src/alt.cpp"],
                        "verdict": "supported",
                    }
                ],
            },
            skills=(),
        )

    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get(
            f"/student/referees/{referee.id}/package/", HTTP_HOST=domain_a.host
        ).content.decode()
    assert "What we worked on together" in body
    assert "Research / thesis: Heuristic Graph Search on Road Networks" in body
    assert "Co-authored paper: Bidirectional A* With Landmarks" in body
    assert "GitHub repository: aliyevlab/graph-search — 19 commits" in body
    assert "Implemented ALT landmark selection in C++20." in body


def test_package_shows_co_referees_and_recommended_focus_when_multiple_referees_assigned(
    client, agency_a, domain_a, user_a, membership_a, asked
) -> None:
    referee, request = asked
    with tenant_scope(agency_a.id):
        co_ref = Referee.objects.create(
            tenant=agency_a,
            student=membership_a,
            name="Farid Mammadov",
            title="Mr.",
            institution="PASHA Bank",
            kind=Referee.Kind.PROFESSIONAL,
        )
        RefereeRequest.objects.create(
            tenant=agency_a,
            referee=co_ref,
            application=request.application,
            mode="PORTAL_INVITE",
            state="AGREED",
        )
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get(
            f"/student/referees/{referee.id}/package/", HTTP_HOST=domain_a.host
        ).content.decode()
    assert "Also writing for this application" in body
    assert "Mr. Farid Mammadov (professional, PASHA Bank)" in body
    assert "Recommended focus for your letter:" in body

