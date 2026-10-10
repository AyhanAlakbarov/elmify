"""Verdict changes inside published packs, and resolved checks (spec §7.1, §7.3).

Proven under rls_enforced_orm: without tenant_scope AND set_local_tenant per
tenant the sweep is legal SQL that finds nothing. Fixtures write as the
superuser before the fixture swaps the connection, so it is listed last.
Verdicts join candidates on DOMAIN: a programme's evidence_domain, a named
programme's verified URL."""

from collections import Counter
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.funding.models import (
    AuditEvent,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.services import PackCommandError, replace_candidate
from apps.research.provenance import record_verdict
from apps.research.provenance_sweep import SweepReport, sweep
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run
from tests.research.provenance_helpers import evidence_program, make_body, recognise

NOW = timezone.now()


def _candidate(agency, run, name, *, code="register", program=None, url=None, body=None):
    """A catalogue candidate (`program`) or a named one (`url`, the verified site)."""
    candidate = make_db_candidate(agency, run, program_name=name)
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(
            program_id=program.id if program else None, provenance_reason_code=code,
            provenance_body_id=body.id if body else None,
        )
        if url:
            type(candidate.evidence).objects.filter(id=candidate.evidence_id).update(
                source_url=url
            )
    candidate.refresh_from_db()
    return candidate


def _downgrade(body, domain, reason, at) -> None:
    record_verdict(body, domain, verdict="UNCONFIRMED", reason_code=reason, evidence={}, now=at,
                   next_check_at=None)


def _block(body, domain, at) -> None:
    record_verdict(body, domain, verdict="BLOCKED", reason_code="mill_list", evidence={}, now=at,
                   next_check_at=None)


@pytest.fixture
def world(agency_a, agency_b, membership_a, membership_b):
    blocked = make_body("bircham.edu")
    recognise(blocked, "bircham.edu", now=NOW - timedelta(days=90))
    _block(blocked, "bircham.edu", NOW)
    downgraded = make_body("downgraded-uni-fixture.de")
    recognise(downgraded, "downgraded-uni-fixture.de", now=NOW - timedelta(days=90))
    _downgrade(downgraded, "downgraded-uni-fixture.de", "lookup_failed", NOW)
    steady = make_body("tum.de")
    recognise(steady, "tum.de")
    on_blocked = evidence_program("https://www.bircham.edu/msc", name="MSc Blocked")
    on_downgraded = evidence_program("https://downgraded-uni-fixture.de/msc", name="MSc Down")
    on_steady = evidence_program("https://www.tum.de/msc", name="MSc Steady")

    run_a = make_run(agency_a, membership_a)
    pack_a = (
        _candidate(agency_a, run_a, "MSc Blocked", program=on_blocked, body=blocked),
        _candidate(agency_a, run_a, "MSc Downgraded", program=on_downgraded, body=downgraded),
        _candidate(agency_a, run_a, "MSc Steady", program=on_steady, body=steady),
    )
    make_published_pack(agency_a, run_a, pack_a)
    run_b = make_run(agency_b, membership_b)
    pack_b = (
        # Named, on the blocked domain: joined by its verified URL's domain.
        _candidate(agency_b, run_b, "MSc Blocked B", url="https://www.bircham.edu/named"),
        _candidate(agency_b, run_b, "MSc Steady B", program=on_steady, body=steady),
    )
    make_published_pack(agency_b, run_b, pack_b)
    return {"blocked": blocked, "downgraded": downgraded}


def _current(agency) -> PackVersion:
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return PackVersion.objects.filter(superseded_at__isnull=True).order_by("-version").first()


def _names(agency, pack) -> set[str]:
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return set(
            PackCandidate.objects.filter(pack_version=pack).values_list(
                "candidate__program_name", flat=True
            )
        )


def _no_dispatch(**_kwargs) -> bool:
    raise AssertionError("no re-run expected")


def _no_enqueue(message) -> None:
    raise AssertionError(f"nothing to queue, got {message}")


@pytest.mark.django_db(transaction=True)
def test_blocked_is_removed_and_downgraded_is_kept_with_a_note_in_every_tenant(
    world, agency_a, agency_b, rls_enforced_orm
) -> None:
    report = sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert (report.revised, report.removed, report.kept, report.errors) == (2, 2, 1, 0)
    pack_a = _current(agency_a)
    assert pack_a.version == 2 and pack_a.published_at is not None
    assert _names(agency_a, pack_a) == {"MSc Downgraded", "MSc Steady"}
    assert [(n["candidate_name"], n["reason_code"], n["action"]) for n in pack_a.change_notes] == [
        ("MSc Blocked", "mill_list", "removed"),
        ("MSc Downgraded", "lookup_failed", "kept"),
    ]
    pack_b = _current(agency_b)
    assert _names(agency_b, pack_b) == {"MSc Steady B"}
    assert [(n["candidate_name"], n["action"]) for n in pack_b.change_notes] == [
        ("MSc Blocked B", "removed")
    ]
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        withdrawn = RecommendationCandidate.objects.get(program_name="MSc Blocked")
        assert withdrawn.state == RecommendationCandidate.State.REJECTED
        withdrawals = AuditEvent.objects.filter(event="candidate.withdrawn")
        assert withdrawals.filter(object_id=withdrawn.id).exists()
        kept = RecommendationCandidate.objects.get(program_name="MSc Downgraded")
        assert (kept.provenance_reason_code, kept.provenance_body_id) == (
            "lookup_failed", world["downgraded"].id,
        )


@pytest.mark.django_db(transaction=True)
def test_a_second_sweep_changes_nothing(world, agency_a, rls_enforced_orm) -> None:
    sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    report = sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert (report.revised, report.removed, report.kept) == (0, 0, 0)
    assert _current(agency_a).version == 2


@pytest.mark.django_db(transaction=True)
def test_still_unconfirmed_two_cycles_after_its_note_a_catalogue_candidate_is_removed(
    world, agency_a, settings, rls_enforced_orm
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    one_cycle = sweep(now=NOW + timedelta(days=31), dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert one_cycle.removed == 0
    report = sweep(now=NOW + timedelta(days=61), dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert report.removed == 1
    pack = _current(agency_a)
    assert _names(agency_a, pack) == {"MSc Steady"}
    assert [(n["candidate_name"], n["action"]) for n in pack.change_notes] == [
        ("MSc Downgraded", "removed")
    ]


@pytest.mark.django_db(transaction=True)
def test_with_the_gate_off_an_unconfirmed_candidate_is_never_timed_out(
    world, agency_a, settings, rls_enforced_orm
) -> None:
    """The pool re-admits UNCONFIRMED while the gate is off, so timing one out
    of the pack would contradict the next run."""
    settings.PROVENANCE_GATE_ENFORCED = False
    sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    report = sweep(now=NOW + timedelta(days=61), dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert report.removed == 0
    assert _names(agency_a, _current(agency_a)) == {"MSc Downgraded", "MSc Steady"}


@pytest.fixture
def stranded(agency_a, membership_a):
    """A pack whose only member sits on a domain that is now BLOCKED."""
    blocked = make_body("bircham.edu")
    recognise(blocked, "bircham.edu", now=NOW - timedelta(days=90))
    _block(blocked, "bircham.edu", NOW)
    run = make_run(agency_a, membership_a)
    only = _candidate(agency_a, run, "MSc Only", url="https://www.bircham.edu/msc")
    make_published_pack(agency_a, run, (only,))
    return run


@pytest.mark.django_db(transaction=True)
def test_a_sweep_that_empties_a_pack_re_runs_the_student_once(
    stranded, agency_a, rls_enforced_orm
) -> None:
    """An empty pack strands the student: reject refuses the last member and
    replace needs one. A fresh run is the only way out."""
    dispatched: list[tuple] = []

    def dispatch(*, tenant_id, run_id):
        dispatched.append((tenant_id, run_id))
        return True

    report = sweep(now=NOW, dispatch=dispatch, enqueue=_no_enqueue)
    assert (report.removed, report.reruns, report.errors) == (1, 1, 0)
    pack = _current(agency_a)
    assert _names(agency_a, pack) == set()
    assert [(n["candidate_name"], n["action"]) for n in pack.change_notes] == [
        ("MSc Only", "removed")
    ]
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        new_run = RecommendationRun.objects.get(id=dispatched[0][1])
    assert dispatched[0][0] == agency_a.id
    assert new_run.profile_version_id == stranded.profile_version_id
    again = sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert (again.revised, again.reruns) == (0, 0)


@pytest.mark.django_db(transaction=True)
def test_a_tenant_whose_listing_fails_is_counted_and_the_next_tenant_is_swept(
    world, agency_a, agency_b, monkeypatch, rls_enforced_orm
) -> None:
    from apps.research import provenance_sweep

    real = provenance_sweep._listing

    def listing(tenant_id):
        if tenant_id == agency_a.id:
            raise RuntimeError("listing failed")
        return real(tenant_id)

    monkeypatch.setattr(provenance_sweep, "_listing", listing)
    report = sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert (report.errors, report.revised) == (1, 1)
    assert _current(agency_a).version == 1
    assert _current(agency_b).version == 2


@pytest.fixture
def superseded(world, agency_a, membership_a):
    """The student's newer published run, holding only the steady programme."""
    with tenant_scope(agency_a.id):
        old_run = RecommendationRun.objects.get()
        steady = RecommendationCandidate.objects.get(program_name="MSc Steady")
    newer = make_run(agency_a, membership_a)
    make_published_pack(
        agency_a, newer, (_candidate(agency_a, newer, "MSc Steady", program=steady.program),)
    )
    return old_run


@pytest.mark.django_db(transaction=True)
def test_only_the_current_pack_is_revised(superseded, agency_a, rls_enforced_orm) -> None:
    """A superseded run's versions are never shown, so never revised (preflight m9)."""
    report = sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert report.revised == 1  # agency B's pack only
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert PackVersion.objects.filter(run=superseded).count() == 1
        assert PackVersion.objects.exclude(run=superseded).get().version == 1


@pytest.fixture
def named_world(agency_a, membership_a):
    body = make_body("little-known-college.edu")
    recognise(body, "little-known-college.edu", now=NOW - timedelta(days=400))
    _downgrade(body, "little-known-college.edu", "lookup_failed", NOW - timedelta(days=300))
    run = make_run(agency_a, membership_a)
    make_published_pack(agency_a, run, (
        _candidate(agency_a, run, "MSc Counsellor Added", body=body,
                   url="https://www.little-known-college.edu/msc"),
        _candidate(agency_a, run, "MSc Other", url="https://www.tum.de/named"),
    ))


@pytest.mark.django_db(transaction=True)
def test_a_counsellor_added_programme_is_kept_then_timed_out_while_enforced(
    named_world, agency_a, settings, rls_enforced_orm
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    first = sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert (first.kept, first.removed) == (1, 0)
    assert _names(agency_a, _current(agency_a)) == {"MSc Counsellor Added", "MSc Other"}
    later = sweep(now=NOW + timedelta(days=365), dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert later.removed == 1
    assert _names(agency_a, _current(agency_a)) == {"MSc Other"}


@pytest.mark.django_db(transaction=True)
def test_a_counsellor_added_programme_is_never_timed_out_with_the_gate_off(
    named_world, agency_a, settings, rls_enforced_orm
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = False
    sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    later = sweep(now=NOW + timedelta(days=365), dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert later.removed == 0
    assert _names(agency_a, _current(agency_a)) == {"MSc Counsellor Added", "MSc Other"}


@pytest.fixture
def finding_world(agency_a, membership_a):
    """A catalogue member and a counsellor-added member, each on a body that
    now carries a finding (not a transient code), plus one steady member."""
    registered = make_body("registered-late.edu")
    recognise(registered, "registered-late.edu", now=NOW - timedelta(days=90))
    _downgrade(registered, "registered-late.edu", "domain_registered_after_listing", NOW)
    vetoed = make_body("vetoed-college.edu")
    recognise(vetoed, "vetoed-college.edu", now=NOW - timedelta(days=90))
    _downgrade(vetoed, "vetoed-college.edu", "veto_conflict", NOW)
    steady = make_body("tum.de")
    recognise(steady, "tum.de")
    on_registered = evidence_program("https://registered-late.edu/msc", name="MSc Late")
    run = make_run(agency_a, membership_a)
    make_published_pack(agency_a, run, (
        _candidate(agency_a, run, "MSc Late", program=on_registered, body=registered),
        _candidate(agency_a, run, "MSc Vetoed Named", body=vetoed,
                   url="https://www.vetoed-college.edu/msc"),
        _candidate(agency_a, run, "MSc Other", url="https://www.tum.de/named"),
    ))


@pytest.mark.django_db(transaction=True)
def test_a_finding_removes_catalogue_and_counsellor_members_on_the_first_sweep(
    finding_world, agency_a, settings, rls_enforced_orm
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = True
    report = sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert (report.kept, report.removed) == (0, 2)
    pack = _current(agency_a)
    assert _names(agency_a, pack) == {"MSc Other"}
    assert sorted((n["candidate_name"], n["action"]) for n in pack.change_notes) == [
        ("MSc Late", "removed"), ("MSc Vetoed Named", "removed"),
    ]


@pytest.mark.django_db(transaction=True)
def test_with_the_gate_off_a_finding_is_kept_never_removed(
    finding_world, agency_a, settings, rls_enforced_orm
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = False
    sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    later = sweep(now=NOW + timedelta(days=365), dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert later.removed == 0
    assert _names(agency_a, _current(agency_a)) == {
        "MSc Late", "MSc Vetoed Named", "MSc Other",
    }


@pytest.fixture
def unplaced_world(agency_a, membership_a):
    blocked = make_body("bircham.edu")
    _block(blocked, "bircham.edu", NOW)
    recognised = make_body("tum.de")
    recognise(recognised, "tum.de")
    run = make_run(agency_a, membership_a)
    member = _candidate(agency_a, run, "MSc Member", url="https://www.example-member.edu/x")
    make_published_pack(agency_a, run, (member,))
    return {
        "member": member,
        "blocked": _candidate(agency_a, run, "MSc Unplaced", url="https://www.bircham.edu/x"),
        "waiting": _candidate(agency_a, run, "MSc Waiting", code="register_not_loaded",
                              url="https://www.tum.de/named"),
        "body": blocked,
    }


@pytest.mark.django_db(transaction=True)
def test_an_unplaced_named_candidate_takes_its_domains_new_code_and_cannot_be_placed(
    unplaced_world, agency_a, membership_a, rls_enforced_orm
) -> None:
    # MSc Member's domain has no verdict and it carries a settled code: left alone.
    report = sweep(now=NOW, dispatch=_no_dispatch, enqueue=_no_enqueue)
    assert report.revised == 0
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        blocked = RecommendationCandidate.objects.get(id=unplaced_world["blocked"].id)
        waiting = RecommendationCandidate.objects.get(id=unplaced_world["waiting"].id)
        assert (blocked.provenance_reason_code, blocked.provenance_body_id) == (
            "mill_list", unplaced_world["body"].id,
        )
        assert waiting.provenance_reason_code == "register"
    pack = _current(agency_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        with pytest.raises(PackCommandError, match="cannot be added"):
            replace_candidate(pack, unplaced_world["member"].id, blocked.id, membership_a)


@pytest.fixture
def unchecked_named(agency_a, membership_a):
    run = make_run(agency_a, membership_a)
    member = _candidate(agency_a, run, "MSc Member", code="", url="https://www.new-college.edu/a")
    make_published_pack(agency_a, run, (member,))
    return {
        "member": member,
        "waiting": _candidate(agency_a, run, "MSc Waiting", code="not_evaluated",
                              url="https://www.other-college.edu/b"),
        # A hosting platform: nothing will ever be checked, so nothing is queued.
        "platform": _candidate(agency_a, run, "MSc Platform", code="no_domain_binding",
                               url="https://someone.netlify.app/c"),
    }


@pytest.mark.django_db(transaction=True)
def test_a_named_programme_whose_check_never_ran_is_re_queued(
    unchecked_named, agency_a, rls_enforced_orm
) -> None:
    seen = []
    report = sweep(now=NOW, dispatch=_no_dispatch, enqueue=seen.append)
    assert report.named == 2
    assert sorted((m.kind, m.tenant_id, m.candidate_id) for m in seen) == sorted([
        ("check_named_program", agency_a.id, unchecked_named["member"].id),
        ("check_named_program", agency_a.id, unchecked_named["waiting"].id),
    ])


@pytest.fixture
def pending_world(agency_a, membership_a):
    def body_with_programme(domain):
        evidence_program(f"https://www.{domain}/msc", name=f"MSc at {domain}")
        return make_body(domain)

    resolved = body_with_programme("resolved-uni-fixture.de")
    recognise(resolved, "resolved-uni-fixture.de")
    absent = body_with_programme("absent-uni-fixture.de")
    _downgrade(absent, "absent-uni-fixture.de", "absent_from_register", NOW)
    waiting = body_with_programme("waiting-uni-fixture.de")
    _downgrade(waiting, "waiting-uni-fixture.de", "register_not_loaded", NOW)
    unchecked = body_with_programme("unchecked-uni-fixture.de")

    other_user = get_user_model().objects.create_user(username="student-a2")
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=other_user, role=Membership.Role.STUDENT
        )
    stale = make_run(agency_a, membership_a)
    rerun = make_run(agency_a, membership_a)
    cleared = make_run(agency_a, other)
    with tenant_scope(agency_a.id):
        RecommendationRun.objects.filter(id=stale.id).update(pending_bodies=[resolved.id])
        RecommendationRun.objects.filter(id=rerun.id).update(
            pending_bodies=[resolved.id, waiting.id], state=RecommendationRun.State.PUBLISHED
        )
        RecommendationRun.objects.filter(id=cleared.id).update(
            pending_bodies=[absent.id, waiting.id, unchecked.id]
        )
    return {"stale": stale, "rerun": rerun, "cleared": cleared, "waiting": waiting,
            "unchecked": unchecked, "resolved": resolved}


@pytest.mark.django_db(transaction=True)
def test_a_body_resolving_recognised_re_runs_its_student(
    pending_world, agency_a, rls_enforced_orm
) -> None:
    dispatched: list[tuple] = []
    queued = []

    def dispatch(*, tenant_id, run_id):
        dispatched.append((tenant_id, run_id))
        return True

    report = sweep(now=NOW, dispatch=dispatch, enqueue=queued.append)
    assert report.reruns == 1
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        runs = {
            key: RecommendationRun.objects.get(id=pending_world[key].id)
            for key in ("stale", "rerun", "cleared")
        }
        new_run = RecommendationRun.objects.get(id=dispatched[0][1])
    assert dispatched[0][0] == agency_a.id
    assert new_run.profile_version_id == runs["rerun"].profile_version_id
    assert runs["rerun"].pending_bodies == []
    # Superseded by the student's newer PUBLISHED run: cleared, never re-run.
    assert runs["stale"].pending_bodies == []
    assert runs["cleared"].pending_bodies == [
        pending_world["waiting"].id, pending_world["unchecked"].id,
    ]
    # The body no check has reached is queued again; the waiting one is the
    # daily recheck's.
    assert [(m.kind, m.run_id, m.body_ids) for m in queued] == [
        ("check_provenance", runs["cleared"].id, (pending_world["unchecked"].id,))
    ]


@pytest.mark.django_db(transaction=True)
def test_a_newer_run_that_never_published_does_not_strand_the_re_run(
    pending_world, agency_a, membership_a, rls_enforced_orm
) -> None:
    """A newer run that failed built no pack: clearing the older run's pending
    bodies would leave the student on a pack that never gets the body back."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert RecommendationRun.objects.filter(id=pending_world["rerun"].id).update(
            state=RecommendationRun.State.QUEUED, pending_bodies=[]
        ) == 1
    dispatched: list = []
    report = sweep(now=NOW, dispatch=lambda **kw: dispatched.append(kw) or True,
                   enqueue=lambda _message: None)
    assert report.reruns == 1
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        stale = RecommendationRun.objects.get(id=pending_world["stale"].id)
        new_run = RecommendationRun.objects.get(id=dispatched[0]["run_id"])
    assert stale.pending_bodies == []
    assert new_run.profile_version_id == stale.profile_version_id


@pytest.mark.django_db(transaction=True)
def test_a_failed_enqueue_is_counted_and_the_sweep_goes_on(
    unchecked_named, agency_a, rls_enforced_orm
) -> None:
    def enqueue(message) -> None:
        raise RuntimeError("queue down")

    report = sweep(now=NOW, dispatch=_no_dispatch, enqueue=enqueue)
    assert (report.named, report.errors) == (0, 2)


def test_the_command_exits_non_zero_when_anything_failed(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.research.management.commands.provenance_pack_sweep.sweep",
        lambda **_: SweepReport(errors=1),
    )
    with pytest.raises(CommandError, match="1 failure"):
        call_command("provenance_pack_sweep")


# --- provenance_recheck: the daily check-then-sweep -------------------------


@pytest.mark.django_db
def test_recheck_runs_the_due_checks_then_the_sweep() -> None:
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("provenance_recheck", stdout=out)
    text = out.getvalue()
    assert text.index("checked 0 domains") < text.index("packs revised 0")


def test_recheck_still_sweeps_when_the_check_fails_and_then_reraises(monkeypatch) -> None:
    """A failed provenance_check must not skip provenance_pack_sweep -- that
    sweep is what carries yesterday's already-resolved verdicts into packs,
    and a scheduled run that silently dropped it on today's error would leave
    those packs stale with no signal anywhere that it happened."""
    from apps.research.management.commands import provenance_recheck

    calls: list[str] = []

    def fake_call_command(name: str, *args: object, **kwargs: object) -> None:
        calls.append(name)
        if name == "provenance_check":
            raise CommandError("1 domain(s) errored; see the log")

    monkeypatch.setattr(provenance_recheck, "call_command", fake_call_command)
    monkeypatch.setattr(provenance_recheck, "screen_recognised", lambda **_: Counter())
    with pytest.raises(CommandError, match="1 domain"):
        call_command("provenance_recheck")
    assert calls == ["provenance_check", "provenance_pack_sweep"]
