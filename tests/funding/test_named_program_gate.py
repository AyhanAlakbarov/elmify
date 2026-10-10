"""The named-programme path (spec §7.4): the web queues, the worker checks,
the web reads the tenant code. No web path reads the catalogue."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from pydantic import ValidationError

from apps.funding.models import PackCandidate, RecommendationCandidate
from apps.funding.services import (
    PackCommandError,
    consider_named_program,
    replace_candidate,
    resolve_named_program,
)
from apps.funding.views import _pack_context
from apps.research.blocking import read_mill_list
from apps.research.management.commands import run_research_worker
from apps.research.models import Organisation, OrganisationDomain
from apps.research.provenance import WORDING, recognition_note, record_verdict, verdict_of
from apps.research.provenance_job import (
    Deps,
    bodies_in_play,
    check_named_program,
    check_named_url,
)
from apps.research.schemas import ResearchMessage
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment
from tests.conftest import reads_no_catalogue
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run
from tests.research.provenance_helpers import FakeFetch, FakeStore, make_body

pytestmark = pytest.mark.django_db


def _pack(agency, student, *, code: str):
    run = make_run(agency, student)
    first = make_db_candidate(agency, run, program_name="MSc One")
    named = make_db_candidate(agency, run, program_name="MSc Named")
    pack = make_published_pack(agency, run, (first,))
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=named.id).update(provenance_reason_code=code)
    return pack, first, named


def test_a_blocked_named_programme_is_refused_with_its_reason(agency_a, membership_a) -> None:
    pack, first, named = _pack(agency_a, membership_a, code="mill_list")
    with tenant_scope(agency_a.id), reads_no_catalogue(), pytest.raises(
        PackCommandError, match="cannot be added: On a published list of unaccredited institutions"
    ):
        replace_candidate(pack, first.id, named.id, membership_a)


@pytest.mark.parametrize("code", ["", "not_evaluated", "register_not_loaded"])
def test_an_unchecked_programme_waits_while_the_gate_is_enforced(
    agency_a, membership_a, settings, code: str
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    pack, first, named = _pack(agency_a, membership_a, code=code)
    with tenant_scope(agency_a.id), pytest.raises(
        PackCommandError, match="still being checked; try again shortly"
    ):
        replace_candidate(pack, first.id, named.id, membership_a)


def test_before_enforcement_an_unchecked_programme_is_placed_as_before(
    agency_a, membership_a
) -> None:
    pack, first, named = _pack(agency_a, membership_a, code="")
    with tenant_scope(agency_a.id):
        new = replace_candidate(pack, first.id, named.id, membership_a)
        assert PackCandidate.objects.filter(pack_version=new, candidate=named).exists()


def test_an_unconfirmed_programme_is_refused_while_the_gate_is_enforced(
    agency_a, membership_a, settings
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    pack, first, named = _pack(agency_a, membership_a, code="absent_from_register")
    with tenant_scope(agency_a.id), pytest.raises(
        PackCommandError, match="its recognition is not confirmed"
    ):
        replace_candidate(pack, first.id, named.id, membership_a)


@pytest.mark.parametrize("enforced", [True, False])
def test_an_unconfirmed_candidate_is_not_considered_only_while_enforced(
    agency_a, membership_a, settings, enforced: bool
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = enforced
    _pack_, _first, named = _pack(agency_a, membership_a, code="absent_from_register")
    with tenant_scope(agency_a.id), reads_no_catalogue():
        considered = {c.id for c in _pack_context(membership_a)["considered"]}
    assert (named.id in considered) is (not enforced)


def test_a_blocked_or_waiting_candidate_stays_considered_while_enforced(
    agency_a, membership_a, settings
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    for code in ("mill_list", "not_evaluated"):
        _pack_, _first, named = _pack(agency_a, membership_a, code=code)
        with tenant_scope(agency_a.id), reads_no_catalogue():
            considered = {c.id for c in _pack_context(membership_a)["considered"]}
        assert named.id in considered


def test_the_student_never_reads_recognition_not_confirmed(agency_a, membership_a) -> None:
    _pack_, _first, named = _pack(agency_a, membership_a, code="absent_from_register")
    with tenant_scope(agency_a.id), reads_no_catalogue():
        context = _pack_context(membership_a)
    assert named.id not in context["recognition_notes"]


def test_resolving_a_named_programme_queues_its_check_after_commit(
    agency_a, membership_a, counselor_membership, monkeypatch, django_capture_on_commit_callbacks
) -> None:
    sent: list[ResearchMessage] = []
    monkeypatch.setattr(
        "apps.funding.services.enqueue_research", lambda message, **_kw: sent.append(message)
    )
    run = make_run(agency_a, membership_a)
    pack = make_published_pack(agency_a, run, (make_db_candidate(agency_a, run),))
    with tenant_scope(agency_a.id):
        candidate = consider_named_program(pack, "MSc Energy Engineering", membership_a)
        RecommendationCandidate.objects.filter(id=candidate.id).update(
            provenance_reason_code="mill_list"
        )
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with reads_no_catalogue():
                resolve_named_program(
                    candidate, eligible=True, reason="Official page read",
                    source_url="https://www.kentech.ac.kr/msc", actor=counselor_membership,
                )
            assert sent == []  # nothing leaves before the commit
        candidate.refresh_from_db()
    assert len(callbacks) == 1
    # A new verified URL clears any code for an earlier site.
    assert (candidate.provenance_reason_code, candidate.provenance_body_id) == ("", None)
    assert [(m.kind, m.candidate_id, m.run_id, m.tenant_id) for m in sent] == [
        ("check_named_program", candidate.id, run.id, agency_a.id)
    ]


def test_a_queue_failure_is_logged_not_raised(
    agency_a, membership_a, counselor_membership, monkeypatch, caplog,
    django_capture_on_commit_callbacks,
) -> None:
    def down(message, **_kw):
        raise RuntimeError("sqs unavailable")

    monkeypatch.setattr("apps.funding.services.enqueue_research", down)
    run = make_run(agency_a, membership_a)
    pack = make_published_pack(agency_a, run, (make_db_candidate(agency_a, run),))
    with tenant_scope(agency_a.id):
        candidate = consider_named_program(pack, "MSc X", membership_a)
        with django_capture_on_commit_callbacks(execute=True):
            resolve_named_program(
                candidate, eligible=True, reason="r", source_url="https://www.kentech.ac.kr/x",
                actor=counselor_membership,
            )
        candidate.refresh_from_db()
    assert "named-programme check not queued" in caplog.text
    assert candidate.state == RecommendationCandidate.State.VISIBLE


def test_the_message_names_its_candidate() -> None:
    with pytest.raises(ValidationError):
        ResearchMessage(kind="check_named_program", tenant_id=uuid4(), run_id=uuid4())
    with pytest.raises(ValidationError):
        ResearchMessage(
            kind="run_research", tenant_id=uuid4(), run_id=uuid4(), candidate_id=uuid4()
        )


def _deps() -> Deps:
    return Deps(
        fetch=FakeFetch({}), ror_call=lambda url, *, params, headers: {"items": []},
        store=FakeStore(), sources=(), mill_rows=read_mill_list(), bootstrap={},
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.bircham.edu/online-mba", "mill_list"),
        ("https://blogs.tum.de/msc", "evidence_off_domain"),
        ("https://tum-msc.github.io/apply", "no_domain_binding"),
    ],
)
def test_the_worker_check_of_a_named_url(url: str, expected: str) -> None:
    body_id, code = check_named_url(url, "MSc Named", now=timezone.now(), deps=_deps())
    assert code == expected
    if expected == "mill_list":
        body = Organisation.objects.get(id=body_id)
        # Labelled by its domain: a programme's name is not an institution's.
        assert (body.name, body.found_via) == ("bircham.edu", ["NAMED_PROGRAM"])
        assert {(p.organisation_id, p.registrable_domain) for p in bodies_in_play()} == {
            (body.id, "bircham.edu")
        }


def test_a_named_url_on_a_bodys_second_domain_puts_that_domain_in_play() -> None:
    body = make_body("first-uni-fixture.de")
    OrganisationDomain.objects.create(organisation=body, registrable_domain="second-uni-fixture.de")
    body_id, _code = check_named_url(
        "https://www.second-uni-fixture.de/msc", "MSc Named", now=timezone.now(), deps=_deps()
    )
    assert body_id == body.id
    assert {p.registrable_domain for p in bodies_in_play()} == {"second-uni-fixture.de"}


@pytest.fixture
def named_candidate(agency_a, membership_a):
    run = make_run(agency_a, membership_a)
    return make_db_candidate(agency_a, run, program_name="MSc Named")


@pytest.mark.django_db(transaction=True)
def test_the_worker_writes_the_tenant_code_under_rls(
    agency_a, named_candidate, rls_enforced_orm
) -> None:
    body_id = uuid4()
    seen: list[tuple[str, str]] = []

    def check(url: str, name: str):
        seen.append((url, name))
        return body_id, "absent_from_register"

    check_named_program(
        ResearchMessage(kind="check_named_program", tenant_id=agency_a.id,
                        run_id=named_candidate.run_id, candidate_id=named_candidate.id),
        check=check,
    )
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        row = RecommendationCandidate.objects.get(id=named_candidate.id)
    assert (row.provenance_reason_code, row.provenance_body_id) == ("absent_from_register", body_id)
    assert seen == [(named_candidate.evidence.source_url, "MSc Named")]


def test_the_worker_never_checks_an_unresolved_or_catalogue_candidate(
    agency_a, membership_a, named_candidate, program_factory
) -> None:
    """A CHECKING candidate still carries the pending placeholder URL, and a
    catalogue candidate's code is the pipeline's to write."""
    run = named_candidate.run
    checking = make_db_candidate(
        agency_a, run, state=RecommendationCandidate.State.CHECKING
    )
    catalogue = make_db_candidate(agency_a, run)
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=catalogue.id).update(
            program_id=program_factory().id
        )

    def check(url: str, name: str):
        raise AssertionError("checked a candidate it must not")

    for candidate in (checking, catalogue):
        check_named_program(
            ResearchMessage(kind="check_named_program", tenant_id=agency_a.id,
                            run_id=run.id, candidate_id=candidate.id),
            check=check,
        )


def test_the_worker_routes_a_named_check_outside_the_tenant_transaction(monkeypatch) -> None:
    routed: list[str] = []
    monkeypatch.setattr(
        run_research_worker, "check_named_program", lambda m: routed.append("named")
    )
    monkeypatch.setattr(
        run_research_worker, "process_research_message", lambda m, handler: routed.append("run")
    )
    run_research_worker.route(ResearchMessage(
        kind="check_named_program", tenant_id=uuid4(), run_id=uuid4(), candidate_id=uuid4(),
    ))
    run_research_worker.route(
        ResearchMessage(kind="run_research", tenant_id=uuid4(), run_id=uuid4())
    )
    assert routed == ["named", "run"]


@pytest.fixture
def named_world(agency_a, membership_a):
    """Written as the superuser before ``web_role_orm`` swaps the connection."""
    pack, first, blocked = _pack(agency_a, membership_a, code="mill_list")
    unconfirmed = make_db_candidate(agency_a, pack.run, program_name="MSc Unconfirmed")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=unconfirmed.id).update(
            provenance_reason_code="absent_from_register"
        )
    return {"first": first, "blocked": blocked, "unconfirmed": unconfirmed}


@pytest.mark.django_db(transaction=True)
def test_under_the_web_role_placement_and_the_note_need_no_catalogue(
    client, settings, domain_a, user_a, named_world, web_role_orm
) -> None:
    """The student's replace and pack pages, through Django's connection logged
    in as a runtime_web member: a catalogue read is a real `permission denied`."""
    settings.PROVENANCE_GATE_ENFORCED = True
    client.force_login(user_a)
    first = named_world["first"]
    url = f"/student/recommendation/candidates/{first.id}/replace/"

    refused = client.post(
        url, {"replacement_candidate_id": str(named_world["blocked"].id)},
        HTTP_HOST=domain_a.host,
    )
    assert refused.status_code == 400
    assert "cannot be added: On a published list" in refused.context["error"]

    refused_unconfirmed = client.post(
        url, {"replacement_candidate_id": str(named_world["unconfirmed"].id)},
        HTTP_HOST=domain_a.host,
    )
    assert refused_unconfirmed.status_code == 400
    assert "its recognition is not confirmed" in refused_unconfirmed.context["error"]
    page = client.get("/student/recommendation/", HTTP_HOST=domain_a.host)
    assert page.status_code == 200
    notes = page.context["recognition_notes"]
    assert named_world["unconfirmed"].id not in notes
    # Never placed, and the student reads why before trying to.
    assert notes[named_world["blocked"].id].startswith("Cannot be added: On a published list")


# --- Task 14 fix round 1 ---


def test_the_student_sees_why_a_blocked_named_programme_cannot_be_added(
    agency_a, membership_a
) -> None:
    _pack_, _first, named = _pack(agency_a, membership_a, code="mill_list")
    with tenant_scope(agency_a.id), reads_no_catalogue():
        context = _pack_context(membership_a)
    assert context["recognition_notes"][named.id] == (
        f"Cannot be added: {WORDING['mill_list'][0]}"
    )


@pytest.mark.parametrize(
    ("code", "next_check_in"), [("absent_from_register", timedelta(days=3)), ("mill_list", None)]
)
def test_a_named_url_whose_domain_is_not_due_reuses_its_verdict(
    code: str, next_check_in: timedelta | None
) -> None:
    body = make_body("fresh-uni-fixture.de")
    now = timezone.now()
    record_verdict(
        body, "fresh-uni-fixture.de", verdict=verdict_of(code), reason_code=code, evidence={},
        now=now, next_check_at=now + next_check_in if next_check_in else None,
    )

    def no_ror(*_args, **_kwargs):
        raise AssertionError("a verdict not yet due was re-checked")

    deps = _deps()
    deps.ror_call = no_ror
    body_id, reused = check_named_url(
        "https://www.fresh-uni-fixture.de/msc", "MSc Named", now=now, deps=deps
    )
    assert (body_id, reused) == (body.id, code)
    assert deps.fetch.calls == []
    # Still tagged, so the daily recheck owns it from here.
    assert {p.registrable_domain for p in bodies_in_play()} == {"fresh-uni-fixture.de"}


@pytest.fixture
def other_tenants_candidate(agency_b, membership_b):
    """Written as the superuser before ``rls_enforced_orm`` swaps the connection."""
    return make_db_candidate(agency_b, make_run(agency_b, membership_b), program_name="MSc B")


@pytest.mark.django_db(transaction=True)
def test_a_named_check_naming_another_tenants_candidate_writes_nothing(
    agency_a, agency_b, other_tenants_candidate, caplog, rls_enforced_orm
) -> None:
    def check(url: str, name: str):
        raise AssertionError("checked another tenant's candidate")

    check_named_program(
        ResearchMessage(
            kind="check_named_program", tenant_id=agency_a.id,
            run_id=other_tenants_candidate.run_id, candidate_id=other_tenants_candidate.id,
        ),
        check=check,
    )
    assert "no named candidate" in caplog.text
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        row = RecommendationCandidate.objects.get(id=other_tenants_candidate.id)
    assert (row.provenance_reason_code, row.provenance_body_id) == ("", None)


@pytest.fixture
def counsellor_client(client, agency_a, membership_a, counselor_user, counselor_membership):
    """Logged in, MFA-verified and assigned to the student, as the superuser."""
    from tests.conftest import verify_mfa_session

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    return client


@pytest.mark.django_db(transaction=True)
def test_the_counsellor_sees_each_named_verdict_under_the_web_role(
    agency_a, domain_a, named_world, counsellor_client, web_role_orm
) -> None:
    """Spec §7.4: resolve shows the code to the counsellor -- from the tenant
    copy, through a connection that holds no catalogue grant."""
    run_id = named_world["first"].run_id
    response = counsellor_client.get(f"/counselor/runs/{run_id}/approve/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    notes = {c.program_name: note for c, note in response.context["named"]}
    assert notes == {
        "MSc One": "Still being checked.",
        "MSc Named": f"Cannot be added: {WORDING['mill_list'][0]}",
        "MSc Unconfirmed": recognition_note("absent_from_register"),
    }


def test_a_waiting_code_reads_as_still_being_checked_and_unresolved_is_not_listed(
    agency_a, domain_a, membership_a, counsellor_client
) -> None:
    pack, _first, _named = _pack(agency_a, membership_a, code="register_not_loaded")
    make_db_candidate(
        agency_a, pack.run, program_name="MSc Pending", state=RecommendationCandidate.State.CHECKING
    )
    with reads_no_catalogue():
        response = counsellor_client.get(
            f"/counselor/runs/{pack.run_id}/approve/", HTTP_HOST=domain_a.host
        )
    assert {c.program_name: note for c, note in response.context["named"]} == {
        "MSc One": "Still being checked.",
        "MSc Named": "Still being checked.",
    }


def test_resolving_named_programmes_is_rate_limited_per_counsellor(
    agency_a, domain_a, membership_a, counsellor_client
) -> None:
    from django.core.cache import cache

    cache.clear()
    pack, _first, named = _pack(agency_a, membership_a, code="")
    url = f"/counselor/runs/{pack.run_id}/named-program/{named.id}/resolve/"
    for _ in range(30):
        # Refused on its missing rationale, but still a resolve attempt.
        assert counsellor_client.post(url, {}, HTTP_HOST=domain_a.host).status_code == 400
    blocked = counsellor_client.post(url, {}, HTTP_HOST=domain_a.host)
    assert blocked.status_code == 429
    assert blocked.context["error"] == "Too many requests. Try again shortly."
