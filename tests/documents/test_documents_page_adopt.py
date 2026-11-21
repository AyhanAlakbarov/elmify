# tests/documents/test_documents_page_adopt.py
"""Plan 2 Task 7: the dashboard's choices on a diploma's or certificate's values."""

from html import unescape

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.fact_labels import WHY_TEXT
from apps.documents.models import DocumentReading, VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.documents import test_documents_page_details

pytestmark = pytest.mark.django_db
page = test_documents_page_details.page  # the student's own browser, as a fixture


def _waiting(agency, student):
    document = register(agency.id, student.id, kind="DIPLOMA")
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        degree = VerifiedFact.objects.create(
            student=student, category="EDUCATION", payload={"degree_as_awarded": "Bachelor"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", confirmed_by=student,
            confirmed_at=timezone.now(), created_by=student)
        reading = DocumentReading.objects.create(
            student=student, document=document, kind="DIPLOMA", reader_version="doc-1",
            state="READ", values=[{"key": "education.degree_as_awarded", "value": "Bakalavr",
                                   "snippet": "BAKALAVR", "proven": False,
                                   "why": "document_differs", "target": str(degree.id)}])
    return reading


def _details(html):
    return html.split('id="details"')[1].split("</section>")[0]


def test_a_differing_diploma_value_shows_both_and_can_be_used(page, agency_a, membership_a):
    reading = _waiting(agency_a, membership_a)
    html = page.get(reverse("student-documents")).content.decode()
    assert "Bakalavr" in _details(html) and "Bachelor" in _details(html)
    assert "1 detail to check" in html
    assert "from your diploma" in _details(html)
    response = page.post(reverse("student-document-value-adopt", args=[reading.id]),
                         {"key": "education.degree_as_awarded"})
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        tip = VerifiedFact.objects.get(category="EDUCATION", superseded_by__isnull=True)
        assert tip.payload["degree_as_awarded"] == "Bakalavr"
    # Settled: the choice is no longer offered.
    assert "Bakalavr</strong>" not in _details(page.get(reverse("student-documents"))
                                               .content.decode())


def test_keep_mine_clears_the_row(page, agency_a, membership_a):
    reading = _waiting(agency_a, membership_a)
    page.post(reverse("student-document-value-keep", args=[reading.id]),
              {"key": "education.degree_as_awarded"})
    html = page.get(reverse("student-documents")).content.decode()
    assert "Bakalavr" not in _details(html)


def test_a_choice_the_row_already_holds_is_not_offered(page, agency_a, membership_a):
    """The student settled it another way (an Edit of the same value): nothing to choose."""
    _waiting(agency_a, membership_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        degree = VerifiedFact.objects.get(category="EDUCATION")
        VerifiedFact.objects.create(
            student=membership_a, category="EDUCATION", payload={"degree_as_awarded": "Bakalavr"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", confirmed_by=membership_a,
            confirmed_at=timezone.now(), supersedes=degree, created_by=membership_a)
    html = page.get(reverse("student-documents")).content.decode()
    assert "detail to check" not in html


def _whole(agency, student, payload, values, kind="DIPLOMA", category="EDUCATION"):
    document = register(agency.id, student.id, kind=kind)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        whole = VerifiedFact.objects.create(
            student=student, category=category, payload=payload,
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
            created_by=student)
        DocumentReading.objects.create(
            student=student, document=document, kind=kind, reader_version="doc-1",
            state="READ", values=values)
    return whole


def test_a_whole_document_row_is_one_line_with_use_and_no_correct(page, agency_a, membership_a):
    whole = _whole(agency_a, membership_a,
                   {"institution_original": "ADA University", "end_date": "2024-06-15"}, [])
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "1 detail to check" in html and "from your diploma" in html
    assert "Institution: ADA University; Graduation date: 2024-06-15" in html
    assert reverse("student-fact-correct", args=[whole.id]) not in html
    assert "Yes, add it" in html
    assert "it's my" not in html  # no confirmed degree to be


def _cv_degree(student, **payload):
    return VerifiedFact.objects.create(
        student=student, category="EDUCATION", payload=payload,
        source_tier="STUDENT_STATEMENT", source_ref="upload:cv", confirmed_by=student,
        confirmed_at=timezone.now(), created_by=student)


def test_no_its_my_degree_merges_the_diploma_into_that_degree(page, agency_a, membership_a):
    """Build ruling 1: confirming a CV degree and its diploma never yields two degrees."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        degree = _cv_degree(membership_a, institution_original="ADA University",
                            degree_as_awarded="Bachelor", end_date=None)
    whole = _whole(
        agency_a, membership_a,
        {"institution_original": "ADA University", "end_date": "2024-06-15",
         "degree_as_awarded": "Bakalavr", "grade_native": "4.0"},
        [{"key": "education.institution_original", "value": "ADA University",
          "snippet": "ADA UNIVERSITY",
          "proven": False, "why": "new_degree"},
         {"key": "education.end_date", "value": "2024-06-15", "snippet": "15.06.2024",
          "proven": False, "why": "new_degree"},
         {"key": "education.degree_as_awarded", "value": "Bakalavr", "snippet": "BAKALAVR",
          "proven": False, "why": "new_degree"},
         {"key": "education.grade_native", "value": "4.0", "snippet": "4.0",
          "proven": False, "why": "low_confidence"}])
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "No — it's my Bachelor, ADA University" in html
    response = page.post(reverse("student-document-merge", args=[whole.id]),
                         {"into": str(degree.id)})
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        confirmed = list(VerifiedFact.objects.filter(
            category="EDUCATION", superseded_by__isnull=True, confirmed_at__isnull=False))
        assert len(confirmed) == 1  # one degree, never two
        tip = confirmed[0]
        # The proven, empty key is filled; what the row held stands; a doubtful one waits.
        assert tip.payload == {"institution_original": "ADA University",
                               "degree_as_awarded": "Bachelor", "end_date": "2024-06-15"}
        assert tip.source_ref == whole.source_ref
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "Yes, add it" not in html  # the whole row is gone
    # Disagreements become details to check, against the student's degree.
    assert "Bakalavr" in html and "4.0" in html and "2 details to check" in html


def test_merge_targets_only_the_students_confirmed_rows(page, agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        unconfirmed = VerifiedFact.objects.create(
            student=membership_a, category="EDUCATION", payload={"institution_original": "X"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", created_by=membership_a)
    whole = _whole(agency_a, membership_a, {"institution_original": "ADA"}, [])
    response = page.post(reverse("student-document-merge", args=[whole.id]),
                         {"into": str(unconfirmed.id)})
    assert response.status_code == 404
    response = page.post(reverse("student-document-merge", args=[whole.id]), {"into": "nope"})
    assert response.status_code == 404


def test_a_certificate_offers_only_sittings_of_the_same_test(page, agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        for test, when in (("IELTS", "2023-01-10"), ("TOEFL", "2023-02-10")):
            VerifiedFact.objects.create(
                student=membership_a, category="LANGUAGE",
                payload={"test_name": test, "test_date": when},
                source_tier="STUDENT_STATEMENT", source_ref="upload:cv",
                confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a)
    _whole(agency_a, membership_a, {"test_name": "IELTS", "test_score": "7.0"},
           [{"key": "language.test_name", "value": "IELTS", "snippet": "IELTS",
             "proven": False, "why": "new_result"}],
           kind="LANGUAGE_CERTIFICATE", category="LANGUAGE")
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "from your language certificate" in html
    assert "No — it's my IELTS, 2023-01-10" in html
    assert "TOEFL" not in html


def test_values_of_an_unchecked_owner_are_offered_nowhere(page, agency_a, membership_a):
    """Build ruling 2: owner_unknown values carry no Use, Correct or Keep."""
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        fact = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"surname": "ALIYEV"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
            created_by=membership_a)
        DocumentReading.objects.create(
            student=membership_a, document=document, kind="PASSPORT", reader_version="id-1",
            state="READ", values=[{"key": "identity.surname", "value": "ALIYEV",
                                   "snippet": "ALIYEV", "proven": False,
                                   "why": "owner_unknown"}])
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "Add your name to your account" in html  # the problem line stays
    assert str(fact.id) not in html and "ALIYEV" not in html
    assert "detail to check" not in html


def test_a_crafted_confirm_of_an_unchecked_owner_value_is_refused(page, agency_a,
                                                                  membership_a):
    """owner_unknown is offered on no surface: the page hides the row, and a POST that
    names it anyway is a 404 from the writer, leaving the row waiting."""
    from apps.documents.confirmation import FactNotFound
    from apps.documents.fact_writer import use_document_value

    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        fact = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"surname": "ALIYEV"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{document.id}",
            created_by=membership_a)
        DocumentReading.objects.create(
            student=membership_a, document=document, kind="PASSPORT", reader_version="id-1",
            state="READ", values=[{"key": "identity.surname", "value": "ALIYEV",
                                   "snippet": "ALIYEV", "proven": False,
                                   "why": "owner_unknown"}])
        with pytest.raises(FactNotFound):
            use_document_value(student=membership_a, fact_id=fact.id)
    assert _confirm_api(page, [fact.id]).status_code == 404
    with tenant_scope(agency_a.id):
        fact.refresh_from_db()
        assert fact.confirmed_at is None
        assert not VerifiedFact.objects.filter(supersedes=fact).exists()


def test_every_why_a_writer_can_leave_waiting_has_text():
    """Build ruling 4: each code a doubtful value can carry is explained. The proven
    codes (check_digit, confident, readers_agree) and the answers (adopted, kept) are
    never shown as something to check."""
    doubtful = {
        "low_confidence", "strip_disagrees", "no_strip", "no_citizenship", "unknown_country",
        "owner_mismatch", "owner_unknown", "student_entry_differs", "document_differs",
        "implausible", "older_document", "readers_disagree", "not_on_page",
        "text_layer_differs", "unknown_test", "ambiguous_date", "date_unclear",
        "new_degree", "new_result",
    }
    assert {code for code in doubtful if not WHY_TEXT.get(code, "").strip()} == set()


def test_a_racing_use_answers_409(page, agency_a, membership_a, monkeypatch):
    from django.db import IntegrityError

    from apps.documents import views

    def boom(**kwargs):
        raise IntegrityError

    monkeypatch.setattr(views, "adopt_document_value", boom)
    reading = _waiting(agency_a, membership_a)
    response = page.post(reverse("student-document-value-adopt", args=[reading.id]),
                         {"key": "education.degree_as_awarded"})
    assert response.status_code == 409
    assert "That changed — refresh and try again." in response.content.decode()


def test_a_racing_merge_answers_409(page, agency_a, membership_a, monkeypatch):
    from django.db import IntegrityError

    from apps.documents import views

    def boom(**kwargs):
        raise IntegrityError

    monkeypatch.setattr(views, "merge_whole_document", boom)
    whole = _whole(agency_a, membership_a, {"institution_original": "ADA"}, [])
    response = page.post(reverse("student-document-merge", args=[whole.id]),
                         {"into": str(whole.id)})
    assert response.status_code == 409


def test_the_choices_are_rate_limited(page, agency_a, membership_a, monkeypatch):
    from apps.documents import views

    monkeypatch.setattr(views, "rate_limited", lambda *a, **k: True)
    reading = _waiting(agency_a, membership_a)
    for name in ("student-document-value-adopt", "student-document-value-keep"):
        assert page.post(reverse(name, args=[reading.id]),
                         {"key": "education.degree_as_awarded"}).status_code == 429
    assert page.post(reverse("student-document-merge", args=[reading.id]),
                     {"into": str(reading.id)}).status_code == 429


def test_another_student_gets_404_and_a_counselor_403(client, agency_a, domain_a, membership_a,
                                                      user_b, counselor_user,
                                                      counselor_membership):
    from apps.tenancy.models import Membership

    reading = _waiting(agency_a, membership_a)
    whole = _whole(agency_a, membership_a, {"institution_original": "ADA"}, [])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        degree = VerifiedFact.objects.get(source_ref="upload:cv")
        Membership.objects.create(tenant=agency_a, user=user_b, role=Membership.Role.STUDENT)
    posts = ((reverse("student-document-value-adopt", args=[reading.id]),
              {"key": "education.degree_as_awarded"}),
             (reverse("student-document-value-keep", args=[reading.id]),
              {"key": "education.degree_as_awarded"}),
             (reverse("student-document-merge", args=[whole.id]), {"into": str(degree.id)}))
    for user, status in ((user_b, 404), (counselor_user, 403)):
        client.force_login(user)
        for url, data in posts:
            assert client.post(url, data, HTTP_HOST=domain_a.host).status_code == status
        for url, data in posts:
            assert client.get(url, HTTP_HOST=domain_a.host).status_code in (403, 405)
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.filter(category="EDUCATION").count() == 2
        assert DocumentReading.objects.get(id=reading.id).values[0]["why"] == "document_differs"


def test_the_counselor_view_shows_the_choices_without_actions(agency_a, membership_a, rf):
    from django.template.loader import render_to_string

    from apps.documents.views import page_context

    _waiting(agency_a, membership_a)
    _whole(agency_a, membership_a, {"institution_original": "ADA"}, [])
    with tenant_scope(agency_a.id):
        html = render_to_string("student/_documents.html",
                                page_context(membership_a, counselor_view=True),
                                request=rf.get("/"))
    details = unescape(_details(html))
    assert "Bakalavr" in details and "ADA" in details
    for action in ("<form", "<button", "Keep mine", "Yes, add it", "it's my"):
        assert action not in details


# Fix round 1: the reviewer's probes (scratchpad dash2), each a confirmed finding.


def _served_degrees(agency, student):
    from apps.portals.profile import verified_values

    with tenant_scope(agency.id):
        values = verified_values(student)
    return sorted(k for k in values if k.startswith("education.")
                  and k.split(".")[1].isdigit() and k.endswith(".institution_original")), values


def _confirm_api(page, ids):
    import json

    return page.client.post("/api/documents/facts/confirm",
                            data=json.dumps({"fact_ids": [str(i) for i in ids]}),
                            content_type="application/json", HTTP_HOST=page.host)


def _v(key, value, why="new_degree"):
    return {"key": f"education.{key}", "value": value, "snippet": value.upper(),
            "proven": False, "why": why}


_ADA = {"institution_original": "ADA University", "end_date": "2024-06-15"}
_ADA_VALUES = [_v("institution_original", "ADA University"), _v("end_date", "2024-06-15")]


def test_a_merged_whole_row_cannot_be_confirmed_into_a_second_degree(page, agency_a,
                                                                     membership_a):
    """p1: confirm_facts skips a whole row whose document a confirmed row already carries."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        degree = _cv_degree(membership_a, institution_original="ADA University",
                            degree_as_awarded="Bachelor")
    whole = _whole(agency_a, membership_a, dict(_ADA), list(_ADA_VALUES))
    assert page.post(reverse("student-document-merge", args=[whole.id]),
                     {"into": str(degree.id)}).status_code == 302
    response = _confirm_api(page, [whole.id])
    assert response.status_code == 200 and response.json() == {"confirmed": 0}
    assert len(_served_degrees(agency_a, membership_a)[0]) == 1


def test_a_whole_row_the_writer_placed_cannot_be_confirmed_either(page, agency_a, membership_a):
    """p1b: placed by a confirmed row of the same document, not by a merge."""
    from apps.documents.confirmation import confirm_facts

    whole = _whole(agency_a, membership_a, {"institution_original": "X"},
                   [_v("institution_original", "X")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a, category="EDUCATION",
            payload={"institution_original": "X", "end_date": "2020-01-01"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=whole.source_ref,
            confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a)
        assert confirm_facts(student=membership_a, fact_ids=[whole.id], actor=membership_a) == 0
    assert _confirm_api(page, [whole.id]).status_code == 200
    assert len(_served_degrees(agency_a, membership_a)[0]) == 1


def test_a_second_merge_is_refused(page, agency_a, membership_a):
    """p2: one diploma goes into one degree, once."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        bachelor = _cv_degree(membership_a, institution_original="ADA University",
                              degree_as_awarded="Bachelor")
        master = _cv_degree(membership_a, institution_original="ADA University",
                            degree_as_awarded="Master")
    whole = _whole(agency_a, membership_a, dict(_ADA), list(_ADA_VALUES))
    assert page.post(reverse("student-document-merge", args=[whole.id]),
                     {"into": str(bachelor.id)}).status_code == 302
    response = page.post(reverse("student-document-merge", args=[whole.id]),
                         {"into": str(master.id)})
    assert response.status_code == 409
    assert "That changed — refresh and try again." in response.content.decode()
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.filter(category="EDUCATION", confirmed_at__isnull=False,
                                           source_ref=whole.source_ref).count() == 1
        assert not VerifiedFact.objects.filter(supersedes=master).exists()


def test_a_merge_acts_on_what_the_student_saw(page, agency_a, membership_a):
    """p3: a re-read that changed a value after the page was shown proves nothing."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        degree = _cv_degree(membership_a, institution_original="ADA University")
    whole = _whole(agency_a, membership_a, dict(_ADA), list(_ADA_VALUES))
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.create(
            student=membership_a, document_id=whole.source_ref.removeprefix("document:"),
            kind="DIPLOMA", reader_version="doc-2", state="READ",
            values=[_v("institution_original", "ADA University"), _v("end_date", "2025-07-01")])
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "2024-06-15" in html and "2025-07-01" not in html
    assert page.post(reverse("student-document-merge", args=[whole.id]),
                     {"into": str(degree.id)}).status_code == 302
    _keys, served = _served_degrees(agency_a, membership_a)
    assert "2025-07-01" not in served.values() and "2024-06-15" not in served.values()
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "Graduation date: you have nothing — <strong>2024-06-15</strong>" in html


def test_a_repeated_answer_is_a_conflict(page, agency_a, membership_a):
    """p7: Use twice, or Keep after Use, says the page is stale."""
    reading = _waiting(agency_a, membership_a)
    url = reverse("student-document-value-adopt", args=[reading.id])
    data = {"key": "education.degree_as_awarded"}
    assert page.post(url, data).status_code == 302
    assert page.post(url, data).status_code == 409
    assert page.post(reverse("student-document-value-keep", args=[reading.id]),
                     data).status_code == 409
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.filter(category="EDUCATION").count() == 2
        assert DocumentReading.objects.get(id=reading.id).values[0]["why"] == "adopted"


def test_an_older_readings_value_cannot_be_applied(page, agency_a, membership_a):
    """p8: only the document's latest reading, the one the page shows, is answerable."""
    reading = _waiting(agency_a, membership_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.create(
            student=membership_a, document_id=reading.document_id, kind="DIPLOMA",
            reader_version="doc-2", state="READ",
            values=[{"key": "education.degree_as_awarded", "value": "Bachelor",
                     "snippet": "B", "proven": True, "why": "readers_agree"}])
    for name in ("student-document-value-adopt", "student-document-value-keep"):
        assert page.post(reverse(name, args=[reading.id]),
                         {"key": "education.degree_as_awarded"}).status_code == 404
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.filter(category="EDUCATION").count() == 1


def test_a_disowned_documents_whole_row_cannot_be_merged(page, agency_a, membership_a):
    """p10: the same file read later as someone else's disowns it."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        degree = _cv_degree(membership_a, institution_original="ADA University")
    whole = _whole(agency_a, membership_a, dict(_ADA), list(_ADA_VALUES))
    document_id = whole.source_ref.removeprefix("document:")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.filter(document_id=document_id).update(file_sha256="f" * 64)
        DocumentReading.objects.create(
            student=membership_a, document_id=document_id, kind="DIPLOMA",
            reader_version="doc-2", state="READ", file_sha256="f" * 64,
            values=[{"key": "identity.surname", "value": "X", "snippet": "X",
                     "proven": False, "why": "owner_mismatch"}])
    assert page.post(reverse("student-document-merge", args=[whole.id]),
                     {"into": str(degree.id)}).status_code == 404
    with tenant_scope(agency_a.id):
        assert not VerifiedFact.objects.filter(supersedes=degree).exists()


# Task 2 ruling: the dashboard's Use on a waiting passport value is the panel's tap.


def _waiting_passport(agency, student):
    from tests.portals.test_packet import _clean_upload

    with tenant_scope(agency.id), tenant_transaction(agency.id):
        passport = _clean_upload(agency, student, "PASSPORT")
        return VerifiedFact.objects.create(
            student=student, category="IDENTITY", payload={"date_of_birth": "1998-03-14"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{passport.id}",
            created_by=student)


def test_a_dashboard_use_on_a_passport_value_serves_the_tapped_value(page, agency_a,
                                                                     membership_a):
    from apps.portals.profile import verified_values

    fact = _waiting_passport(agency_a, membership_a)
    response = _confirm_api(page, [fact.id])
    assert response.status_code == 200 and response.json() == {"confirmed": 1}
    with tenant_scope(agency_a.id):
        used = VerifiedFact.objects.get(supersedes=fact)
        assert used.confirmed_by == membership_a and used.payload == fact.payload
        newest = VerifiedFact.objects.filter(student=membership_a).latest("created_at")
        assert newest.id == used.id
        assert verified_values(membership_a)["identity.date_of_birth"] == "1998-03-14"
        fact.refresh_from_db()
        assert fact.confirmed_at is None  # not confirmed in place


def test_a_second_dashboard_use_answers_as_the_routes_second_tap_does(page, agency_a,
                                                                      membership_a):
    fact = _waiting_passport(agency_a, membership_a)
    assert _confirm_api(page, [fact.id]).status_code == 200
    second = _confirm_api(page, [fact.id])
    assert second.status_code == 409 and second.json()["error"] == "already_used"
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.filter(supersedes=fact).count() == 1


def test_an_unread_passport_date_is_never_confirmed_by_a_dashboard_use(page, agency_a,
                                                                      membership_a):
    from tests.portals.test_packet import _clean_upload

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        fact = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"date_of_birth": "14 Marh 98"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{passport.id}",
            created_by=membership_a)
    response = _confirm_api(page, [fact.id])
    assert response.status_code == 404 and response.json()["error"] == "not_found"
    with tenant_scope(agency_a.id):
        fact.refresh_from_db()
        assert fact.confirmed_at is None
        assert not VerifiedFact.objects.filter(supersedes=fact).exists()
    html = page.get(reverse("student-documents")).content.decode()
    assert "14 Marh 98" in _details(html)  # still shown, with Correct
    assert "Use</button>" not in _details(html)


def test_a_repeated_use_is_409_already_used_and_a_disowned_one_stays_404(
        page, agency_a, membership_a):
    """Final review M3: the dashboard reads only 409 as 'Done.'; a refusal (here a
    passport disowned since the page loaded) must not."""
    from uuid import uuid4

    from tests.portals.test_packet import _clean_upload

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        passport = _clean_upload(agency_a, membership_a, "PASSPORT")
        fact = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"date_of_birth": "1998-03-14"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{passport.id}",
            created_by=membership_a)
        stale = VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY", payload={"place_of_birth": "BAKU"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{passport.id}",
            created_by=membership_a)
    assert _confirm_api(page, [fact.id]).status_code == 200
    again = _confirm_api(page, [fact.id])
    assert again.status_code == 409 and again.json()["error"] == "already_used"
    assert _confirm_api(page, [uuid4()]).status_code == 404
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        from apps.concierge.models import DocumentVersion
        DocumentVersion.objects.filter(id=passport.id).update(retired_at=timezone.now())
    assert _confirm_api(page, [stale.id]).status_code == 404


def test_the_dashboard_use_button_reads_only_409_as_done() -> None:
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[2] / "static/dashboard/documents.js")
    text = js.read_text()
    assert "result.status === 409" in text and "result.status === 404" not in text
