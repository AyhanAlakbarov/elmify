# tests/documents/test_documents_page_details.py
"""Spec 2026-10-12 §3: what the dashboard shows after a passport read."""

from html import unescape

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.models import DocumentReading, VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _fact(student, document, payload, confirmed=True, category="IDENTITY"):
    return VerifiedFact.objects.create(
        student=student, category=category, payload=payload,
        source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None, created_by=student,
    )


class _Page:
    """The student's own browser, as tests/documents/test_documents_page.py drives it."""

    def __init__(self, client, host):
        self.client, self.host = client, host

    def get(self, path):
        return self.client.get(path, HTTP_HOST=self.host)

    def post(self, path, data=None):
        return self.client.post(path, data or {}, HTTP_HOST=self.host)


@pytest.fixture
def page(client, domain_a, user_a, membership_a):
    client.force_login(user_a)
    return _Page(client, domain_a.host)


def test_details_and_details_to_check_are_shown_apart_from_cv_facts(page, agency_a,
                                                                     membership_a):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _fact(membership_a, document, {"date_of_birth": "1998-03-14"})
        doubtful = _fact(membership_a, document, {"place_of_birth": "BAKI"}, confirmed=False)
        DocumentReading.objects.create(
            student=membership_a, document=document, kind="PASSPORT", reader_version="id-1",
            state="READ", values=[{"key": "identity.place_of_birth", "value": "BAKI",
                                   "snippet": "PLACE OF BIRTH BAKI", "proven": False,
                                   "why": "low_confidence"}],
        )
    html = page.get(reverse("student-documents")).content.decode()
    assert "Your details" in html and "Date of birth" in html and "1998-03-14" in html
    assert "1 detail to check" in html and "PLACE OF BIRTH BAKI" in html
    assert str(doubtful.id) in html  # the Use button's body
    cv_section = html.split('id="facts"')[1].split("</section>")[0]
    assert "BAKI" not in cv_section  # never in the CV's confirm-all list


def test_a_failed_read_and_a_foreign_passport_say_so(page, agency_a, membership_a):
    failed = register(agency_a.id, membership_a.id, kind="PASSPORT")
    foreign = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.create(student=membership_a, document=failed, kind="PASSPORT",
                                       reader_version="id-1", state="FAILED",
                                       failure="unreadable")
        DocumentReading.objects.create(
            student=membership_a, document=foreign, kind="PASSPORT", reader_version="id-1",
            state="READ", values=[{"key": "identity.surname", "value": "X", "snippet": "X",
                                   "proven": False, "why": "owner_mismatch"}],
        )
    html = unescape(page.get(reverse("student-documents")).content.decode())
    assert "We couldn't read this — upload a clearer photo" in html
    assert "This passport doesn't look like yours" in html
    # Spec §6.4: each problem line links to the upload form on the same page.
    assert html.count('<a href="#upload">Upload again</a>') == 2
    assert 'id="upload"' in html


def test_a_correction_posts_and_redirects(page, agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        fact = _fact(membership_a, document, {"place_of_birth": "BAKI"}, confirmed=False)
    response = page.post(reverse("student-fact-correct", args=[fact.id]),
                         {"key": "place_of_birth", "value": "Baku"})
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.get(supersedes=fact).payload == {"place_of_birth": "Baku"}


def test_the_passport_question_appears_only_for_two_valid_passports(page, agency_a,
                                                                    membership_a):
    first = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _fact(membership_a, first, {"document_type": "passport", "number": "A1",
                                    "expiry_date": "2031-01-01"}, category="ID_DOCUMENT")
    assert "Which passport should we use?" not in page.get(
        reverse("student-documents")).content.decode()
    second = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _fact(membership_a, second, {"document_type": "passport", "number": "B2",
                                     "expiry_date": "2032-01-01"}, category="ID_DOCUMENT")
        DocumentReading.objects.create(student=membership_a, document=second, kind="PASSPORT",
                                       reader_version="id-1", state="READ")
    html = page.get(reverse("student-documents")).content.decode()
    assert "Which passport should we use?" in html
    response = page.post(reverse("student-id-document-primary", args=[second.id]))
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        assert DocumentReading.objects.get(document=second).primary_chosen_at is not None


def test_a_racing_correction_answers_409(page, agency_a, membership_a, monkeypatch):
    from django.db import IntegrityError

    from apps.documents import views

    def boom(**kwargs):
        raise IntegrityError

    monkeypatch.setattr(views, "correct_fact", boom)
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        fact = _fact(membership_a, document, {"place_of_birth": "BAKI"}, confirmed=False)
    response = page.post(reverse("student-fact-correct", args=[fact.id]),
                         {"key": "place_of_birth", "value": "Baku"})
    assert response.status_code == 409
    assert "That changed — refresh and try again." in response.content.decode()


def test_passports_are_counted_per_document_as_the_portal_serves_them(page, agency_a,
                                                                       membership_a):
    first = register(agency_a.id, membership_a.id, kind="PASSPORT")
    second = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        for doc, number, expiry in ((first, "A1", "2031-01-01"), (second, "B2", "2032-01-01")):
            _fact(membership_a, doc, {"document_type": "passport", "number": number},
                  category="ID_DOCUMENT")
            _fact(membership_a, doc, {"expiry_date": expiry}, category="ID_DOCUMENT")
    html = page.get(reverse("student-documents")).content.decode()
    assert "Which passport should we use?" in html


def test_one_passport_with_two_confirmed_rows_is_listed_once(page, agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    full = {"document_type": "passport", "number": "A1", "expiry_date": "2031-01-01"}
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _fact(membership_a, document, full, category="ID_DOCUMENT")
        _fact(membership_a, document, full, category="ID_DOCUMENT")
    html = page.get(reverse("student-documents")).content.decode()
    assert "Which passport should we use?" not in html


def test_details_name_their_source_and_a_later_good_read_clears_the_failure(
        page, agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.create(student=membership_a, document=document, kind="PASSPORT",
                                       reader_version="id-1", state="FAILED",
                                       failure="document_unavailable")
        _fact(membership_a, document, {"date_of_birth": "1998-03-14"})
        DocumentReading.objects.create(student=membership_a, document=document, kind="PASSPORT",
                                       reader_version="id-2", state="READ")
    html = unescape(page.get(reverse("student-documents")).content.decode())
    assert "from your passport" in html
    assert "upload it again" not in html


def test_another_student_gets_404_and_a_counselor_403(client, agency_a, domain_a, membership_a,
                                                      user_b, counselor_user,
                                                      counselor_membership):
    from apps.tenancy.models import Membership

    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        fact = _fact(membership_a, document, {"place_of_birth": "BAKI"}, confirmed=False)
        DocumentReading.objects.create(student=membership_a, document=document, kind="PASSPORT",
                                       reader_version="id-1", state="READ")
        Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
    urls = (reverse("student-fact-correct", args=[fact.id]),
            reverse("student-id-document-primary", args=[document.id]))
    client.force_login(user_b)
    for url in urls:
        assert client.post(url, {"key": "place_of_birth", "value": "X"},
                           HTTP_HOST=domain_a.host).status_code == 404
    client.force_login(counselor_user)
    for url in urls:
        assert client.post(url, {"key": "place_of_birth", "value": "X"},
                           HTTP_HOST=domain_a.host).status_code == 403
    with tenant_scope(agency_a.id):
        assert not VerifiedFact.objects.filter(supersedes=fact).exists()
        assert DocumentReading.objects.get(document=document).primary_chosen_at is None


def test_a_held_cv_degree_says_why_and_can_be_added_as_a_different_one(
    page, agency_a, membership_a
):
    # Transcript plan 3b final review, finding 6.
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        held = VerifiedFact.objects.create(
            student=membership_a, category="EDUCATION", source_tier="STUDENT_STATEMENT",
            payload={"institution_original": "Bakı Dövlət Universiteti",
                     "degree_as_awarded": "Bakalavr"},
            source_ref="transcript:x", confirmed_by=membership_a, confirmed_at=timezone.now(),
            created_by=membership_a)
        claim = VerifiedFact.objects.create(
            student=membership_a, category="EDUCATION", source_tier="STUDENT_STATEMENT",
            payload={"institution_original": "Baku State University", "degree_as_awarded": "BSc",
                     "possible_duplicate_of": str(held.id)},
            source_ref="upload:cv", created_by=membership_a)
    html = unescape(page.get(reverse("student-documents")).content.decode())
    assert "Baku State University" in html
    assert "may be the same degree as Bakalavr, Bakı Dövlət Universiteti" in html
    response = page.post(reverse("student-different-degree", args=[claim.id]))
    assert response.status_code == 302
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        added = VerifiedFact.objects.get(supersedes=claim)
    assert "possible_duplicate_of" not in added.payload


def test_a_cv_degrees_transcript_courses_are_counted_not_dumped(page, agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a, category="EDUCATION", source_tier="STUDENT_STATEMENT",
            payload={"institution_original": "Baku State University", "degree_as_awarded": "BSc",
                     "courses": [{"title": "Physics", "ects": "6.00", "grade": "B",
                                  "in_progress": False}],
                     "courses_unconfirmed": [], "aliases": ["Bakı Dövlət Universiteti"]},
            source_ref="transcript:x", created_by=membership_a)
    html = unescape(page.get(reverse("student-documents")).content.decode())
    facts = html.split('id="facts-heading"')[1].split("</section>")[0]
    assert "1 course from your transcript" in facts
    assert "'title'" not in facts and "aliases" not in facts
