"""Re-review of the passport fact reader (2026-10-13): each test is one probe
that showed a wrong value reaching a portal, end to end through process_document."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.concierge.documents import register, upload_prefix
from apps.concierge.models import DocumentVersion
from apps.documents import document_reading
from apps.documents.confirmation import confirm_facts
from apps.documents.fact_writer import correct_fact
from apps.documents.gaps import answer_questions, programme_required
from apps.documents.models import DocumentReading, VerifiedFact
from apps.documents.views import page_context
from apps.portals.profile import verified_values
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.documents.id_fixtures import field, passport

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _on(settings):
    settings.FACT_READING_ENABLED = True
    settings.TRANSCRIPT_AZURE_ENABLED = True


class _Store:
    def __init__(self, body):
        self.body = body

    def get(self, key):
        return self.body


@pytest.fixture
def named(membership_a):
    membership_a.user.first_name, membership_a.user.last_name = "Nərmin", "Əliyeva"
    membership_a.user.save()
    return membership_a


def upload(agency, student):
    # ADD: several passports held at once; the default REPLACE refuses "replace_which".
    document = register(agency.id, student.id, kind="PASSPORT", mode="ADD")
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        DocumentVersion.objects.filter(id=document.id).update(
            state="AVAILABLE", promoted_key=upload_prefix(
                tenant_id=agency.id, student_id=student.id, document_id=document.id
            ) + "scan.pdf", content_type="application/pdf")
    return document


def run(agency, document, answer, body=None):
    document_reading.process_document(agency.id, document.id,
                                      store=_Store(body or str(document.id).encode()),
                                      analyze=lambda c, *, pages: answer)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return DocumentReading.objects.get(document_id=document.id)


def values(agency, student):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return verified_values(student)


def ctx(agency, student):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return page_context(student, counselor_view=False)


def turkish():
    return passport(fields={"DocumentNumber": field("U12345678"),
                            "Nationality": field("TUR", kind="countryRegion"),
                            "CountryRegion": field("TUR", kind="countryRegion"),
                            "DateOfExpiration": field("2033-01-01", kind="date")},
                    strip_args={"number": "U12345678", "nationality": "TUR", "issuing": "TUR",
                                "expiry": "330101"})


def _row(agency, student, category, ref, key):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return VerifiedFact.objects.filter(
            student=student, category=category, source_ref=ref, payload__has_key=key,
            superseded_by__isnull=True,
        ).last()


def _correct(agency, student, row, key, value):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return correct_fact(student=student, fact_id=row.id, key=key, value=value)


def _choose(agency, document):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        DocumentReading.objects.filter(document=document).update(primary_chosen_at=timezone.now())


# -- B1/B2: whose citizenship a portal gets ---------------------------------------


def test_p1_a_corrected_citizenship_is_served(agency_a, named):
    document = upload(agency_a, named)
    run(agency_a, document, passport())
    row = _row(agency_a, named, "IDENTITY", f"document:{document.id}", "citizenship")
    _correct(agency_a, named, row, "citizenship", "Azerbaijani Republic")
    assert values(agency_a, named)["identity.citizenship"] == "Azerbaijani Republic"


def test_p2_a_dual_nationals_corrected_citizenship_is_served(agency_a, named):
    run(agency_a, upload(agency_a, named), passport())
    second = upload(agency_a, named)
    run(agency_a, second, turkish())
    _choose(agency_a, second)
    row = _row(agency_a, named, "IDENTITY", f"document:{second.id}", "citizenship")
    _correct(agency_a, named, row, "citizenship", "Türkiye")
    served = values(agency_a, named)
    assert (served["id_document.number"], served["identity.citizenship"]) == (
        "U12345678", "Türkiye")


def test_p4_number_and_citizenship_come_from_the_same_passport(agency_a, named):
    """The chosen passport is a re-upload whose citizenship equalled the held one,
    so the writer wrote no row under it; the Turkish row confirmed later must not
    ride along with the Azerbaijani number."""
    run(agency_a, upload(agency_a, named), passport(), body=b"az-photo-1")
    again = upload(agency_a, named)
    run(agency_a, again, passport(), body=b"az-photo-2")
    tr = upload(agency_a, named)
    run(agency_a, tr, turkish())
    row = _row(agency_a, named, "IDENTITY", f"document:{tr.id}", "citizenship")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        VerifiedFact.objects.filter(id=row.id).update(confirmed_by=named,
                                                      confirmed_at=timezone.now())
    _choose(agency_a, again)
    served = values(agency_a, named)
    assert (served["id_document.number"], served["identity.citizenship"]) == (
        "C01X00T47", "Azerbaijan")


def test_p5_the_students_own_citizenship_outranks_a_passport(agency_a, named, program_factory):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        VerifiedFact.objects.create(
            student=named, category="IDENTITY", payload={"full_name": "Nərmin Əliyeva"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv",
            confirmed_by=named, confirmed_at=timezone.now(), created_by=named)
        programme = program_factory(cv_directives=[{
            "action": "include", "target": "personal.citizenship", "value": None,
            "rule_text": "State citizenship.", "source_url": "https://x.example/"}])
        [question] = programme_required(named, programme)
        [answer] = answer_questions([(question, "Georgian")], student=named)
        VerifiedFact.objects.filter(id=answer.id).update(confirmed_by=named,
                                                         confirmed_at=timezone.now())
    run(agency_a, upload(agency_a, named), passport())
    assert values(agency_a, named)["identity.citizenship"] == "Georgian"
    to_check = [(row["label"], row["value"]) for row in ctx(agency_a, named)["to_check"]]
    assert ("Citizenship", "Azerbaijan") in to_check


# -- B3/B4: the same passport uploaded again ---------------------------------------


def test_p3_the_choice_survives_a_reupload_of_the_chosen_passport(agency_a, named):
    az = upload(agency_a, named)
    run(agency_a, az, passport(), body=b"az-photo-1")
    run(agency_a, upload(agency_a, named), turkish())
    _choose(agency_a, az)
    run(agency_a, upload(agency_a, named), passport(), body=b"az-photo-2")
    served = values(agency_a, named)
    assert (served["id_document.number"], served["identity.citizenship"]) == (
        "C01X00T47", "Azerbaijan")


def test_p9_a_correction_survives_a_reupload_of_the_same_passport(agency_a, named):
    first = upload(agency_a, named)
    run(agency_a, first, passport(), body=b"p1")
    row = _row(agency_a, named, "ID_DOCUMENT", f"document:{first.id}", "issuing_authority")
    _correct(agency_a, named, row, "issuing_authority", "DMX 123")
    run(agency_a, upload(agency_a, named), passport(), body=b"p2")
    assert values(agency_a, named)["id_document.issuing_authority"] == "DMX 123"
    shown = [(r["label"], r["value"]) for r in ctx(agency_a, named)["details"]
             if r["label"] == "Issuing authority"]
    assert shown == [("Issuing authority", "DMX 123")]


def test_the_later_read_wins_where_no_student_entry_holds_the_key(agency_a, named):
    run(agency_a, upload(agency_a, named), passport(), body=b"p1")
    run(agency_a, upload(agency_a, named), passport(fields={"IssuingAuthority": field("DMX 9")}),
        body=b"p2")
    assert values(agency_a, named)["id_document.issuing_authority"] == "DMX 9"


# -- B7: a document number compares without spacing or case -----------------------


def test_p7_a_corrected_number_is_stored_without_spaces_and_still_one_document(agency_a, named):
    first = upload(agency_a, named)
    run(agency_a, first, passport(), body=b"p1")
    row = _row(agency_a, named, "ID_DOCUMENT", f"document:{first.id}", "number")
    corrected = _correct(agency_a, named, row, "number", "c01 x00t47")
    assert corrected.payload["number"] == "C01X00T47"
    run(agency_a, upload(agency_a, named), passport(), body=b"p2")
    assert ctx(agency_a, named)["passport_choices"] == []


def test_the_dedup_key_ignores_spacing_and_case():
    from apps.documents.verification import id_documents

    now = timezone.now()
    facts = [
        VerifiedFact(category="ID_DOCUMENT", source_ref=ref, confirmed_at=now, created_at=now,
                     source_tier="AUTHORITATIVE_DOCUMENT",
                     payload={"document_type": "passport", "number": number})
        for ref, number in (("document:a", "C01 X00T47"), ("document:b", "c01x00t47"))
    ]
    assert list(id_documents(facts)) == ["document:b"]


# -- programme_required never asks for what a portal already gets ----------------


def test_p6_a_passport_proven_date_of_birth_is_not_asked_again(agency_a, named, program_factory):
    run(agency_a, upload(agency_a, named), passport())
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        VerifiedFact.objects.create(
            student=named, category="IDENTITY", payload={"full_name": "Nərmin Əliyeva"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv",
            confirmed_by=named, confirmed_at=timezone.now(), created_by=named)
        programme = program_factory(cv_directives=[
            {"action": "include", "target": f"personal.{key}", "value": None,
             "rule_text": "State it.", "source_url": "https://x.example/"}
            for key in ("date_of_birth", "phone")])
        asked = [q.payload_key for q in programme_required(named, programme)]
    assert asked == ["phone"]


# -- owner_unknown is not a dead end -----------------------------------------------


def test_p8_naming_the_account_then_uploading_the_same_file_reads_it_again(
    agency_a, membership_a
):
    run(agency_a, upload(agency_a, membership_a), passport(), body=b"same")
    problems = [p["text"] for p in ctx(agency_a, membership_a)["problems"]]
    assert problems == ["Add your name to your account, then upload the passport again."]
    membership_a.user.first_name, membership_a.user.last_name = "Nərmin", "Əliyeva"
    membership_a.user.save()
    reading = run(agency_a, upload(agency_a, membership_a), passport(), body=b"same")
    assert reading.azure_pages > 0
    assert {v["why"] for v in reading.values} & {"owner_unknown"} == set()
    assert values(agency_a, membership_a)["id_document.number"] == "C01X00T47"
    assert ctx(agency_a, membership_a)["problems"] == []


# -- Round 2 (2026-10-13): number, expiry and citizenship travel together ------------


def mother():
    return passport(fields={"LastName": field("PETROVA"), "FirstName": field("ANNA"),
                            "DocumentNumber": field("M77777777"),
                            "Nationality": field("RUS", kind="countryRegion"),
                            "CountryRegion": field("RUS", kind="countryRegion")},
                    strip_args={"surname": "PETROVA", "given": "ANNA", "number": "M77777777",
                                "nationality": "RUS", "issuing": "RUS"})


def test_n1_a_parents_passport_offers_nothing_to_confirm(agency_a, named):
    """Someone else's passport writes no fact at all, so no Use, no Correct and no
    confirm call can ever make its values the student's; it shows only as a problem."""
    run(agency_a, upload(agency_a, named), passport())
    mum = upload(agency_a, named)
    reading = run(agency_a, mum, mother())
    assert {v["why"] for v in reading.values} == {"owner_mismatch"} and reading.facts_written
    page = ctx(agency_a, named)
    rows = page["details"] + page["to_check"]
    assert "Russia" not in [r["value"] for r in rows]
    assert [r["source"] for r in rows if r["value"] == "M77777777"] == []
    assert "This passport doesn't look like yours" in [p["text"] for p in page["problems"]]
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert not VerifiedFact.objects.filter(source_ref=f"document:{mum.id}").exists()
    assert values(agency_a, named)["identity.citizenship"] == "Azerbaijan"


def test_n2_a_correction_on_one_passport_stays_with_it(agency_a, named):
    az = upload(agency_a, named)
    run(agency_a, az, passport())
    row = _row(agency_a, named, "IDENTITY", f"document:{az.id}", "citizenship")
    _correct(agency_a, named, row, "citizenship", "Azerbaijani Republic")
    tr = upload(agency_a, named)
    run(agency_a, tr, turkish())
    _choose(agency_a, tr)
    served = values(agency_a, named)
    assert (served["id_document.number"], served["identity.citizenship"]) == (
        "U12345678", "Turkey")


def test_n2b_switching_back_serves_the_other_passports_citizenship(agency_a, named):
    az = upload(agency_a, named)
    run(agency_a, az, passport())
    tr = upload(agency_a, named)
    run(agency_a, tr, turkish())
    _choose(agency_a, tr)
    row = _row(agency_a, named, "IDENTITY", f"document:{tr.id}", "citizenship")
    _correct(agency_a, named, row, "citizenship", "Türkiye")
    _choose(agency_a, az)
    served = values(agency_a, named)
    assert (served["id_document.number"], served["identity.citizenship"]) == (
        "C01X00T47", "Azerbaijan")


def test_n3_use_on_the_passport_after_a_typed_answer_serves_the_passport(
    agency_a, named, program_factory
):
    # The dashboard's Use on a waiting passport row goes through use_document_value
    # (api.confirm's one-tap branch, ruling Q1), never confirm_facts: that skips a
    # nameless IDENTITY row, and every one-key passport IDENTITY row is nameless.
    from apps.documents.fact_writer import use_document_value

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        VerifiedFact.objects.create(
            student=named, category="IDENTITY", payload={"full_name": "Nərmin Əliyeva"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv",
            confirmed_by=named, confirmed_at=timezone.now(), created_by=named)
        programme = program_factory(cv_directives=[{
            "action": "include", "target": "personal.citizenship", "value": None,
            "rule_text": "State citizenship.", "source_url": "https://x.example/"}])
        [question] = programme_required(named, programme)
        [answer] = answer_questions([(question, "Georgian")], student=named)
        VerifiedFact.objects.filter(id=answer.id).update(confirmed_by=named,
                                                         confirmed_at=timezone.now())
    run(agency_a, upload(agency_a, named), passport())
    [row] = [x for x in ctx(agency_a, named)["to_check"] if x["label"] == "Citizenship"]
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        use_document_value(student=named, fact_id=row["fact_id"])
    assert values(agency_a, named)["identity.citizenship"] == "Azerbaijan"
    shown = [x["value"] for x in ctx(agency_a, named)["details"] if x["label"] == "Citizenship"]
    assert "Azerbaijan" in shown


def test_n4_a_same_number_renewal_after_a_correction_serves_its_new_dates(agency_a, named):
    first = upload(agency_a, named)
    run(agency_a, first, passport(), body=b"old")
    row = _row(agency_a, named, "ID_DOCUMENT", f"document:{first.id}", "issuing_authority")
    corrected = _correct(agency_a, named, row, "issuing_authority", "DMX 123")
    assert corrected.payload == {"issuing_authority": "DMX 123"}
    renewed = passport(fields={"DateOfIssue": field("2026-01-10", kind="date"),
                               "DateOfExpiration": field("2036-01-09", kind="date")},
                       strip_args={"expiry": "360109"})
    run(agency_a, upload(agency_a, named), renewed, body=b"new")
    served = values(agency_a, named)
    assert (served["id_document.expiry_date"], served["id_document.issue_date"],
            served["id_document.issuing_authority"]) == ("2036-01-09", "2026-01-10", "DMX 123")


def test_n8_a_file_read_as_someone_elses_is_read_again_after_a_name_fix(agency_a, membership_a):
    membership_a.user.first_name, membership_a.user.last_name = "Rauf", "Əliyev"
    membership_a.user.save()
    first = run(agency_a, upload(agency_a, membership_a), passport(), body=b"same")
    assert {v["why"] for v in first.values} == {"owner_mismatch"}
    membership_a.user.first_name = "Nərmin"
    membership_a.user.last_name = "Əliyeva"
    membership_a.user.save()
    again = run(agency_a, upload(agency_a, membership_a), passport(), body=b"same")
    assert again.azure_pages > 0 and "owner_mismatch" not in {v["why"] for v in again.values}
    assert ctx(agency_a, membership_a)["problems"] == []


# -- Round 3 (Q2): a passport proven not the student's serves nothing -----------------


def _name(membership, first, last):
    membership.user.first_name, membership.user.last_name = first, last
    membership.user.save()


def test_q2_a_mothers_passport_read_before_the_name_serves_nothing_after_it(
    agency_a, membership_a
):
    first = upload(agency_a, membership_a)
    assert {v["why"] for v in run(agency_a, first, mother(), body=b"mum").values} == {
        "owner_unknown"
    }
    _name(membership_a, "Nərmin", "Əliyeva")
    again = run(agency_a, upload(agency_a, membership_a), mother(), body=b"mum")
    assert {v["why"] for v in again.values} == {"owner_mismatch"}
    page = ctx(agency_a, membership_a)
    assert page["to_check"] == [] and page["details"] == []
    assert "This passport doesn't look like yours" in [p["text"] for p in page["problems"]]
    served = values(agency_a, membership_a)
    assert not [k for k in served if k.startswith("id_document.")]
    assert "identity.citizenship" not in served and "identity.surname" not in served
    # Even a confirm call that names a waiting row serves nothing under that ref.
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        waiting = list(VerifiedFact.objects.filter(source_ref=f"document:{first.id}"))
        assert waiting
        confirm_facts(student=membership_a, fact_ids=[f.id for f in waiting],
                      actor=membership_a)
    assert "M77777777" not in values(agency_a, membership_a).values()
    assert not [k for k in values(agency_a, membership_a) if k.startswith("id_document.")]


def test_q2_choosing_a_disowned_document_is_a_404(client, domain_a, user_a, agency_a,
                                                  membership_a):
    first = upload(agency_a, membership_a)
    run(agency_a, first, mother(), body=b"mum")
    _name(membership_a, "Nərmin", "Əliyeva")
    run(agency_a, upload(agency_a, membership_a), mother(), body=b"mum")
    from apps.documents.verification import disowned_refs
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert f"document:{first.id}" in disowned_refs(membership_a)
    client.force_login(user_a)
    url = reverse("student-id-document-primary", args=[first.id])
    assert client.post(url, HTTP_HOST=domain_a.host).status_code == 404


def test_q1_a_rename_then_a_mismatching_reread_withdraws_the_earlier_clean_facts(
    agency_a, membership_a, monkeypatch
):
    _name(membership_a, "Anna", "Petrova")
    doc = upload(agency_a, membership_a)
    run(agency_a, doc, mother(), body=b"mum")
    assert values(agency_a, membership_a)["id_document.number"] == "M77777777"
    _name(membership_a, "Nərmin", "Əliyeva")
    monkeypatch.setitem(document_reading.READER_VERSION, "PASSPORT", "id-2")
    document_reading.process_document(agency_a.id, doc.id, store=_Store(b"mum"),
                                      analyze=lambda c, *, pages: mother())
    served = values(agency_a, membership_a)
    assert not [k for k in served if k.startswith("id_document.")]
    assert "identity.citizenship" not in served
    page = ctx(agency_a, membership_a)
    assert page["details"] == [] and page["to_check"] == []


def test_a_genuine_passport_with_a_clean_latest_read_is_unaffected(agency_a, named, monkeypatch):
    doc = upload(agency_a, named)
    run(agency_a, doc, passport(), body=b"mine")
    monkeypatch.setitem(document_reading.READER_VERSION, "PASSPORT", "id-2")
    document_reading.process_document(agency_a.id, doc.id, store=_Store(b"mine"),
                                      analyze=lambda c, *, pages: passport())
    assert values(agency_a, named)["id_document.number"] == "C01X00T47"
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        from apps.documents.verification import disowned_refs
        assert disowned_refs(named) == set()


def test_t1_a_clean_twin_after_the_name_fix_is_not_swept_in_by_the_old_mismatch(
    agency_a, membership_a
):
    _name(membership_a, "Wrong", "Name")
    a = upload(agency_a, membership_a)
    assert {v["why"] for v in run(agency_a, a, passport(), body=b"mine").values} == {
        "owner_mismatch"
    }
    _name(membership_a, "Nərmin", "Əliyeva")
    b = upload(agency_a, membership_a)
    assert {v["why"] for v in run(agency_a, b, passport(), body=b"mine").values} & {
        "owner_mismatch", "owner_unknown"
    } == set()
    from apps.documents.verification import disowned_refs
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert disowned_refs(membership_a) == set()
    assert values(agency_a, membership_a)["id_document.number"] == "C01X00T47"
    assert ctx(agency_a, membership_a)["problems"] == []
