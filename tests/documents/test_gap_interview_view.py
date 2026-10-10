"""The gap interview's view: the trust boundary the intake module does not have.

``gap_intake.submit_answers`` takes ``student`` on trust and says so. This is
where that trust is earned, so the authorisation tests here are the whole
point of the file, not a formality.

Deliberately asserts no markup. ``tests/templates/README.md`` draws the line:
a test that needs specific rendering belongs with the frontend, and the ~40
tests that do are quarantined behind the ``frontend`` marker. What is asserted
here is contract -- that a field carries the name ``field_name`` produced, that
no field is required, that a failure is a 4xx -- all of which any presentation
layer must honour.
"""

import pytest

from apps.documents.gap_intake import field_name
from apps.documents.gaps import Kind, gap_questions
from apps.documents.models import VerifiedFact
from apps.documents.schemas import TIMELINE_STATEMENT_MAX
from apps.documents.verification import unsuperseded_facts
from apps.tenancy.context import tenant_scope
from tests.conftest import verify_mfa_session

from .conftest import make_fact

URL = "/student/gap-interview/"

pytestmark = pytest.mark.django_db(transaction=True)


def _degree_without_a_grade(student, **kwargs):
    return make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {"degree_as_awarded": "MSc Chemistry", "institution_original": "EPFL"},
        **kwargs,
    )


def test_a_question_is_rendered_under_the_name_field_name_produces(
    client, domain_a, user_a, membership_a
) -> None:
    """The renderer never invents a field name.

    ``field_name`` is the contract between the form and ``submit_answers``:
    the submit side looks answers up by it, so a page that names its inputs
    anything else posts a form whose every answer is dropped in silence.
    """
    with tenant_scope(domain_a.agency_id):
        degree = _degree_without_a_grade(membership_a)
        (question,) = [q for q in gap_questions(membership_a) if q.fact_id == degree.id]
    client.force_login(user_a)

    response = client.get(URL, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert field_name(question) in response.content.decode()


def test_no_field_is_required(client, domain_a, user_a, membership_a) -> None:
    """Every question is skippable, so a blank is an ordinary skip.

    A ``required`` attribute would make the browser refuse a submission that
    the server treats as entirely valid -- the student cannot answer three
    questions and leave the fourth for when they have found the document.
    """
    with tenant_scope(domain_a.agency_id):
        _degree_without_a_grade(membership_a)
        make_fact(membership_a, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    client.force_login(user_a)

    response = client.get(URL, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert "required" not in response.content.decode()


def test_an_answer_is_written_and_the_response_redirects(
    client, domain_a, user_a, membership_a
) -> None:
    """Post/Redirect/Get: a reload must not re-post the answers."""
    with tenant_scope(domain_a.agency_id):
        degree = _degree_without_a_grade(membership_a)

    client.force_login(user_a)
    response = client.post(
        URL, {f"{degree.id}:grade_native": "16.45/20.0"}, HTTP_HOST=domain_a.host
    )

    assert response.status_code == 302
    assert response.headers["Location"] == URL
    with tenant_scope(domain_a.agency_id):
        (written,) = VerifiedFact.objects.filter(source_ref="gap-interview")
        assert written.payload["grade_native"] == "16.45/20.0"
        assert written.supersedes_id == degree.id


def test_an_answered_question_is_gone_from_the_page_that_follows(
    client, domain_a, user_a, membership_a
) -> None:
    """The form empties itself. Nothing tracks 'answered' -- the ledger now
    carries a grade, so the detector that asked stops asking.
    """
    with tenant_scope(domain_a.agency_id):
        degree = _degree_without_a_grade(membership_a)
    client.force_login(user_a)

    client.post(URL, {f"{degree.id}:grade_native": "16.45/20.0"}, HTTP_HOST=domain_a.host)
    response = client.get(URL, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert f"{degree.id}:grade_native" not in response.content.decode()


def test_a_blank_answer_is_a_skip_and_not_an_error(
    client, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(domain_a.agency_id):
        degree = _degree_without_a_grade(membership_a)
    client.force_login(user_a)

    response = client.post(URL, {f"{degree.id}:grade_native": "   "}, HTTP_HOST=domain_a.host)

    assert response.status_code == 302
    with tenant_scope(domain_a.agency_id):
        assert not VerifiedFact.objects.filter(source_ref="gap-interview").exists()


def test_a_submission_naming_another_students_fact_writes_nothing(
    client, domain_a, user_a, membership_a, user_b, membership_b, agency_b
) -> None:
    """The trust boundary, stated as a test.

    ``submit_answers`` re-derives the questions and reads only its own field
    names, so a hand-edited fact id belonging to someone else matches no
    question and is never looked at. This is the only thing standing between a
    submission and another student's ledger.
    """
    with tenant_scope(agency_b.id):
        theirs = _degree_without_a_grade(membership_b)
    client.force_login(user_a)

    response = client.post(
        URL, {f"{theirs.id}:grade_native": "20.0/20.0"}, HTTP_HOST=domain_a.host
    )

    assert response.status_code == 302
    with tenant_scope(agency_b.id):
        assert not VerifiedFact.objects.filter(source_ref="gap-interview").exists()
        assert not theirs.superseded_by.exists()


def test_an_unanswerable_question_is_a_client_error_and_not_a_crash(
    client, domain_a, user_a, membership_a
) -> None:
    """Reachable the day an authoritative EDUCATION fact exists.

    ``missing_grade`` asks about every degree with no grade regardless of
    tier, but ``answer_questions`` refuses to let a typed sentence overwrite a
    transcript. The student can act on that; a 500 tells them nothing and
    pages someone.
    """
    with tenant_scope(domain_a.agency_id):
        degree = _degree_without_a_grade(
            membership_a, tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
        )
    client.force_login(user_a)

    response = client.post(
        URL, {f"{degree.id}:grade_native": "16.45/20.0"}, HTTP_HOST=domain_a.host
    )

    assert response.status_code == 400
    with tenant_scope(domain_a.agency_id):
        assert not VerifiedFact.objects.filter(source_ref="gap-interview").exists()


def test_an_anonymous_visitor_never_reaches_the_form(client, domain_a) -> None:
    response = client.get(URL, HTTP_HOST=domain_a.host)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_a_counselor_is_refused(
    client, domain_a, counselor_user, counselor_membership
) -> None:
    """``current_membership(request, STUDENT)`` is the authorisation check.

    A counsellor operating this form on a student's behalf is a different
    surface with a different ``student`` argument; it is not this one, and
    falling through to the counsellor's own (nonexistent) ledger would be the
    silent version of the same mistake.
    """
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)

    response = client.get(URL, HTTP_HOST=domain_a.host)

    assert response.status_code == 403


def test_two_concurrent_submits_do_not_fork_the_supersession_chain(
    agency_a, membership_a, monkeypatch
) -> None:
    """The race the row lock exists to stop, run for real on two connections.

    Deterministic rather than hopeful. ``payload_keys`` is called between the
    locking SELECT and the INSERT, so patching it lets thread A hold the lock
    at exactly that point while thread B's own SELECT is provably in flight --
    the interleaving that forks the chain, rather than two threads started
    together and a hope that they collide.

    The invariant is one tip per logical fact. Two tips mean every reader
    downstream of ``unsuperseded_facts`` -- ``generatable_facts`` and the
    detectors here -- sees one degree twice.
    """
    import threading
    import time

    from django.db import connections

    from apps.documents import gaps as gaps_module

    with tenant_scope(agency_a.id):
        make_fact(
            membership_a,
            VerifiedFact.Category.EDUCATION,
            {"degree_as_awarded": "MSc Chemistry", "institution_original": "EPFL"},
        )
        question = gaps_module.missing_grade(membership_a)[0]

    a_holds_lock = threading.Event()
    b_has_started = threading.Event()
    real_payload_keys = gaps_module.payload_keys

    def payload_keys_that_lets_b_catch_up(category):
        if threading.current_thread().name == "A":
            a_holds_lock.set()
            b_has_started.wait(timeout=10)
            # B's SELECT ... FOR UPDATE is now either blocked on A's lock or
            # already past it. Either way it has reached the server, which is
            # what makes the snapshot question decidable.
            time.sleep(1.0)
        return real_payload_keys(category)

    monkeypatch.setattr(gaps_module, "payload_keys", payload_keys_that_lets_b_catch_up)

    outcomes: list[str] = []

    def submit(name: str, answer: str) -> None:
        if name == "B":
            a_holds_lock.wait(timeout=10)
            b_has_started.set()
        try:
            with tenant_scope(agency_a.id):
                gaps_module.answer_questions([(question, answer)], student=membership_a)
            outcomes.append(f"{name}:written")
        except gaps_module.UnanswerableQuestion:
            outcomes.append(f"{name}:refused")
        except Exception as error:  # noqa: BLE001 - diagnostic, reported below
            outcomes.append(f"{name}:{type(error).__name__}")
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=submit, args=("A", "16.45/20.0"), name="A"),
        threading.Thread(target=submit, args=("B", "18.0/20.0"), name="B"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    with tenant_scope(agency_a.id):
        tips = list(unsuperseded_facts(membership_a).filter(category="EDUCATION"))
    assert len(tips) == 1, f"chain forked into {len(tips)} tips; outcomes={outcomes}"
    # And the loser learns why in the vocabulary the view already handles: an
    # IntegrityError escaping raw would be a 500 on an ordinary double-click.
    # Which thread wins is the scheduler's business; that exactly one does,
    # and that the loser hears it as UnanswerableQuestion, is not. A raw
    # IntegrityError escaping here would be a 500 on an ordinary double-click.
    assert sorted(outcome.split(":")[1] for outcome in outcomes) == ["refused", "written"], outcomes


def test_the_certificates_note_is_rendered_and_has_no_input(
    client, domain_a, user_a, membership_a
) -> None:
    """A GapNote is read by the student and answered by nobody. It must show
    up on the page and it must not grow the form -- a note is a <li>, never an
    <input>. The certificates note is the one detector left that emits one.
    """
    with tenant_scope(domain_a.agency_id):
        # Undated, so the timeline detector skips it and no gap question exists.
        make_fact(
            membership_a,
            VerifiedFact.Category.EDUCATION,
            {"degree_as_awarded": "BSc", "institution_original": "ADA University"},
        )
        assert not [q for q in gap_questions(membership_a) if q.kind == Kind.TIMELINE_GAP]
        expected_inputs = len(gap_questions(membership_a))
    client.force_login(user_a)

    response = client.get(URL, HTTP_HOST=domain_a.host)
    body = response.content.decode()

    assert response.status_code == 200
    assert "Certificates, licences" in body
    assert body.count('<input type="text"') == expected_inputs


def test_a_gap_question_offers_the_statements(client, domain_a, user_a, membership_a) -> None:
    with tenant_scope(domain_a.agency_id):
        make_fact(
            membership_a,
            VerifiedFact.Category.EDUCATION,
            {
                "degree_as_awarded": "BSc",
                "institution_original": "ADA University",
                "start_date": "2019-09-01",
                "end_date": "2023-06-30",
            },
        )
    client.force_login(user_a)

    html = client.get(URL, HTTP_HOST=domain_a.host).content.decode()

    assert 'list="gap-statements"' in html
    assert f'maxlength="{TIMELINE_STATEMENT_MAX}"' in html
    assert "Personal reasons." in html


def test_the_gap_interview_sits_inside_the_page_chrome(client, domain_a, user_a, membership_a):
    client.force_login(user_a)
    body = client.get(URL, HTTP_HOST=domain_a.host).content.decode()
    assert "Skip to content" in body
    assert 'href="/student/documents/"' in body
