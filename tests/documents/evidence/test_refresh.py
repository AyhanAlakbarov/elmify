"""refresh_evidence end to end, with fake GitHub, fake OpenAI and fake Jev."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from apps.concierge.documents import register, retire_replaced
from apps.concierge.models import DocumentVersion
from apps.documents.evidence import facts, refresh
from apps.documents.evidence.checks import SUPPORT_LIMIT, SUPPORT_WINDOW_SECONDS
from apps.documents.evidence.extraction import ReadBullet, RepoReading
from apps.documents.evidence.github import Candidate
from apps.documents.evidence.intake import INTAKE_RATE_LIMIT
from apps.documents.evidence.readings import usable_readings
from apps.documents.evidence.refresh import refresh_evidence, reset, select, unknown_login
from apps.documents.evidence.sources import RepoRef
from apps.documents.models import EvidenceReading, VerifiedFact
from apps.ratelimit import rate_limited
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.uploads import promoted_upload

from .fakes import (
    DOC,
    LOGIN,
    READING,
    USER_ID,
    FakeParser,
    FakeTransport,
    answering,
    blob,
    commit,
    contribution,
    files_key,
    graphql,
    listing,
    overview,
    overview_key,
    overviews,
    repo_routes,
    row,
)

pytestmark = pytest.mark.django_db
LAB = "AxelRolov/cdr_bench"
OWN = "0rkhann/MicroKatc"
EMPTY = {**graphql(), **listing()}


def _routes(**overrides):
    routes = {
        **graphql(contribution("AxelRolov", "cdr_bench", 7, pushed="2026-03-31T07:27:55Z")),
        **listing(row(OWN, pushed="2026-10-02T19:05:04Z")),
        **repo_routes(LAB, pushed="2026-03-31T07:27:55Z"),
        **repo_routes(OWN, pushed="2026-10-02T19:05:04Z"),
    }
    routes.update(overrides)
    return routes


@pytest.fixture(autouse=True)
def _token(settings):
    settings.GITHUB_TOKEN = "test-token"


@pytest.fixture
def student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="refresh-student")
        member = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        facts.set_github_login(member, LOGIN)
    return member


def _refresh(student, routes, *, parser=None, store=None, **kwargs):
    transport = FakeTransport(routes)
    parser = parser if parser is not None else FakeParser()
    with tenant_scope(student.tenant_id):
        report = refresh_evidence(student, transport=transport, client=parser,
                                  support_client=answering(), store=store, **kwargs)
    return report, transport, parser


def _readings(student):
    with tenant_scope(student.tenant_id):
        return {r.repo or str(r.document_id): r
                for r in EvidenceReading.objects.filter(student=student)}


# --- selection ---------------------------------------------------------------------


def _c(name, group, *, owner="0rkhann", commits=0, day=1, size=10, untouched=False):
    return Candidate(ref=RepoRef("github", owner, name), group=group,
                     pushed_at=datetime(2026, 1, day, tzinfo=UTC), size=size, commits=commits,
                     untouched_fork=untouched)


def test_lab_repos_need_three_commits_and_rank_by_commits():
    chosen = select([_c("a", "lab", owner="lab", commits=2), _c("b", "lab", owner="lab", commits=9),
                     _c("c", "lab", owner="lab", commits=3)], LOGIN)
    assert [c.ref.name for c in chosen] == ["b", "c"]


def test_ten_slots_and_at_most_five_for_own_repos():
    own = [_c(f"o{i:02d}", "own", day=1 + i) for i in range(12)]
    cv = [_c(f"cv{i}", "cv", owner="x") for i in range(4)]
    lab = [_c(f"l{i}", "lab", owner="lab", commits=5) for i in range(8)]
    alone = select(own, LOGIN)
    assert [c.ref.name for c in alone] == ["o11", "o10", "o09", "o08", "o07"]
    assert [c.group for c in select(cv + lab + own, LOGIN)] == ["cv"] * 4 + ["lab"] * 6
    mixed = select(cv[:2] + lab[:4] + own, LOGIN)
    assert len(mixed) == 10 and sum(c.group == "own" for c in mixed) == 4


def test_the_skips():
    chosen = select([_c("empty", "own", size=0), _c(LOGIN, "own"),
                     _c(f"{LOGIN}.github.io", "own"), _c("copy", "cv", untouched=True),
                     _c("kept", "own")], LOGIN)
    assert [c.ref.name for c in chosen] == ["kept"]


def test_review_focus_1_the_skips_ignore_case():
    assert select([_c("0RKHANN", "own"), _c("0rkhann.GitHub.io", "own")], "0RKHANN") == ()


# --- the GitHub half ---------------------------------------------------------------


def test_a_first_refresh_reads_each_chosen_repo_and_suggests_its_skills(student):
    report, transport, parser = _refresh(student, _routes())
    assert report.read == [LAB, OWN]
    assert (report.model_calls, report.tokens, report.stopped) == (2, 2000, "")
    assert report.github_requests == len(transport.calls)
    lab = _readings(student)[LAB].reading
    assert lab["bullets"][0]["verdict"] == "supported"
    assert lab["origin"] == {"group": "lab", "owner_type": "User", "owner_name": "", "commits": 7}
    assert (lab["url"], lab["first_commit"]) == (f"https://github.com/{LAB}", "2026-09-01")
    # A repo the student does not own is read through history(author: {id}); their own, whole.
    fetched = overviews(transport)
    assert fetched[LAB]["author"] == USER_ID and "author" not in fetched[OWN]
    with tenant_scope(student.tenant_id):
        skills = VerifiedFact.objects.filter(student=student,
                                             category=VerifiedFact.Category.SKILL)
        assert [s.payload["name"] for s in skills] == ["Python"]  # two repos, one suggestion
        assert all(s.confirmed_by_id is None for s in skills)


def test_the_login_never_reaches_the_model(student):
    _, _, parser = _refresh(student, _routes())
    assert LOGIN not in json.dumps([call["input"] for call in parser.calls]).casefold()


def test_an_unchanged_repo_is_not_read_again(student):
    _refresh(student, _routes())
    report, transport, parser = _refresh(student, _routes(), force=True)
    assert (parser.calls, report.read, overviews(transport)) == ([], [], {})


def test_a_push_or_a_new_reader_reads_again(student, monkeypatch):
    _refresh(student, _routes())
    moved = _routes(**listing(row(OWN, pushed="2026-10-10T00:00:00Z")))
    assert _refresh(student, moved, force=True)[0].read == [OWN]
    monkeypatch.setattr(refresh, "READER_VERSION", 2)
    assert _refresh(student, moved, force=True)[0].read == [LAB, OWN]


def test_a_new_reader_does_not_send_the_old_etag(student, monkeypatch):
    """Sent, the tree would answer 304 and the repo would never be read by the new reader."""
    _refresh(student, _routes(**repo_routes(OWN, pushed="2026-10-02T19:05:04Z", etag='W/"t1"')))
    monkeypatch.setattr(refresh, "READER_VERSION", 2)
    report, transport, _ = _refresh(student, _routes(), force=True)
    [tree] = [call for call in transport.calls if f"/repos/{OWN}/git/trees/" in call[1]]
    assert "If-None-Match" not in tree[2] and OWN in report.read


def test_only_bullets_that_pass_the_checks_are_kept(student, caplog):
    """readings.usable_readings filters nothing: what is stored is what letters may use."""
    invented = READING.model_copy(update={"bullets": (
        *READING.bullets,
        ReadBullet(text="Cut solve time by 90%.", evidence=("Cut solve time by 90%",)),
    )})
    caplog.set_level("INFO", logger="apps.documents.evidence.refresh")
    report, _, _ = _refresh(student, _routes(), parser=FakeParser(invented))
    bullets = _readings(student)[OWN].reading["bullets"]
    assert [(b["text"], b["verdict"]) for b in bullets] == [
        (READING.bullets[0].text, "supported")]
    # Final review #8: what the checks removed is counted and logged (never stored).
    assert report.dropped == 2  # one invented bullet per repo read
    assert "dropped=2" in caplog.text


def test_the_support_limit_leaves_bullets_unchecked_and_stops_nothing(student):
    for _ in range(SUPPORT_LIMIT):
        rate_limited("evidence-support", student.id, limit=SUPPORT_LIMIT,
                     window_seconds=SUPPORT_WINDOW_SECONDS)
    report, _, _ = _refresh(student, _routes())
    assert (report.stopped, report.read) == ("", [LAB, OWN])
    assert _readings(student)[LAB].reading["bullets"][0]["verdict"] == "unchecked"

def test_a_repo_gone_from_a_complete_discovery_loses_its_reading(student):
    _refresh(student, _routes())
    report, _, _ = _refresh(student, _routes(**listing()), force=True)
    assert (set(_readings(student)), report.deleted) == ({LAB}, 1)


def test_an_incomplete_discovery_deletes_nothing(student):
    _refresh(student, _routes())
    broken = _routes(**listing(), **{"/graphql": (200, {"data": {"user": {}},
                                                         "errors": [{"message": "timeout"}]})})
    _refresh(student, broken, force=True)
    assert set(_readings(student)) == {LAB, OWN}


@pytest.mark.parametrize("failure", [
    {overview_key(OWN): (502, {})},
    # GraphQL answers 200 when the repo is gone, renamed or private: kept all the same,
    # because only a complete discovery deletes a reading (spec §6).
    {overview_key(OWN): (200, {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND"}]})},
    {f"/repos/{OWN}/git/trees/main": (500, {})},
    # A failed RepoFiles must not read as an empty repo under the floor.
    {files_key(OWN): (200, {"errors": [{"message": "timeout"}]})},
])
def test_a_repo_that_fails_to_fetch_keeps_its_old_reading(student, failure):
    _refresh(student, _routes())
    failing = _routes(**listing(row(OWN, pushed="2026-10-11T00:00:00Z")), **failure)
    report, _, _ = _refresh(student, failing, force=True)
    assert report.read == []
    assert _readings(student)[OWN].changed_at == datetime(2026, 10, 2, 19, 5, 4, tzinfo=UTC)


def test_a_tree_that_did_not_move_is_not_read_again(student):
    """A push to another branch moves pushed_at; the tree's etag says the default branch
    did not move (spec §7.1), so no RepoFiles query and no model call follow."""
    _refresh(student, _routes(**repo_routes(OWN, pushed="2026-10-02T19:05:04Z", etag='W/"t1"')))
    assert _readings(student)[OWN].reading["tree_etag"] == 'W/"t1"'
    moved = _routes(**listing(row(OWN, pushed="2026-10-13T00:00:00Z")),
                    **{f"/repos/{OWN}/git/trees/main": (304, {})})
    report, transport, parser = _refresh(student, moved, force=True)
    [tree] = [call for call in transport.calls if f"/repos/{OWN}/git/trees/" in call[1]]
    assert tree[2]["If-None-Match"] == 'W/"t1"'
    assert (report.read, parser.calls) == ([], [])
    assert not any(c[0] == "POST" and "RepoFiles" in c[3]["query"] for c in transport.calls)
    assert _readings(student)[OWN].changed_at == datetime(2026, 10, 2, 19, 5, 4, tzinfo=UTC)


def test_a_repo_with_too_little_to_read_is_not_read_and_its_reading_goes(student):
    _refresh(student, _routes())
    thin = _routes(**listing(row(OWN, pushed="2026-10-12T00:00:00Z")),
                   **repo_routes(OWN, files={}, description="x" * 900))
    report, _, parser = _refresh(student, thin, force=True)
    assert OWN not in _readings(student) and parser.calls == []


def test_a_rate_limit_stops_the_refresh_deletes_nothing_and_holds_the_next_start(student):
    _refresh(student, _routes())
    limit = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"}
    limited = _routes(**listing(row("0rkhann/newer", pushed="2026-10-14T00:00:00Z")),
                      **{overview_key("0rkhann/newer"): (403, {}, limit)})
    report, _, _ = _refresh(student, limited, force=True)
    assert report.stopped == "github_rate_limited"
    assert set(_readings(student)) == {LAB, OWN}  # OWN left the listing; nothing deleted
    # Fewer than 200 left at the last answer: the next refresh does not start.
    later, transport, _ = _refresh(student, _routes(), force=True)
    assert (later.stopped, transport.calls) == ("github_budget", [])


def test_no_token_means_no_request_and_nothing_deleted(student, settings, caplog):
    _refresh(student, _routes())
    settings.GITHUB_TOKEN = ""
    report, transport, _ = _refresh(student, _routes(**listing()), force=True)
    assert (report.stopped, transport.calls) == ("no_token", [])
    assert set(_readings(student)) == {LAB, OWN}
    assert "GITHUB_TOKEN" in caplog.text


def test_an_unknown_login_gives_the_one_student_facing_message(student):
    unknown = {"/graphql": (200, {"data": {"user": None}, "errors": [{"type": "NOT_FOUND"}]})}
    report, _, _ = _refresh(student, unknown)
    assert (report.stopped, report.message) == ("unknown_user",
                                                "We couldn't find GitHub user 0rkhann.")
    assert unknown_login(student.id) == LOGIN


def test_a_refresh_within_ten_minutes_is_skipped_unless_forced_or_reset(student):
    _refresh(student, _routes())
    report, transport, _ = _refresh(student, _routes())
    assert (report.stopped, transport.calls) == ("recent", [])
    assert _refresh(student, _routes(), force=True)[0].stopped == ""
    reset(student.id)
    assert _refresh(student, _routes())[0].stopped == ""


def test_final_1_a_login_cleared_during_a_refresh_leaves_no_github_reading(student):
    """Clearing deletes every github reading (spec §5.1), including one a refresh that
    was already running writes after the clear."""

    class Clearing(FakeParser):
        def parse(self, **kwargs):
            facts.clear_github_login(student)
            return super().parse(**kwargs)

    _refresh(student, _routes(), parser=Clearing())
    _refresh(student, _routes())  # not forced: the in-flight refresh set the 10-minute flag
    assert _readings(student) == {}
    with tenant_scope(student.tenant_id):
        assert usable_readings(student) == ()


def test_residual_a_clear_between_save_reading_check_and_insert_leaves_no_reading(
        student, monkeypatch):
    """The clear lands after save_reading's login check, so the reading is written after it.
    The refresh re-reads the login when its GitHub half ends and deletes it -- no second
    refresh needed."""
    real_save, real_login = facts.save_reading, facts.github_login

    def racing_save(*args, **kwargs):
        facts.clear_github_login(student)
        monkeypatch.setattr(facts, "github_login", lambda _student: LOGIN)
        try:
            return real_save(*args, **kwargs)
        finally:
            monkeypatch.setattr(facts, "github_login", real_login)

    monkeypatch.setattr(facts, "save_reading", racing_save)
    _refresh(student, _routes())
    assert _readings(student) == {}
    with tenant_scope(student.tenant_id):
        assert usable_readings(student) == ()


def test_final_1_a_refresh_with_no_login_deletes_every_github_reading(student):
    """The residual race: the clear commits between save_reading's login check and its
    insert. The next refresh -- even within ten minutes -- deletes what is left."""
    _refresh(student, _routes())
    with tenant_scope(student.tenant_id):
        [tip] = [t for t in facts._identity_tips(student) if t.payload.get("github_username")]
        facts._supersede(tip, {"github_url": None, "github_username": None})
    report, transport, _ = _refresh(student, _routes())
    assert (_readings(student), report.deleted, transport.calls) == ({}, 2, [])


def test_final_2_a_readme_holding_the_placeholder_characters_is_read(student):
    readme = {"README.md": "Notes \ue0009\ue001 here. " + DOC, "solver.py": f'"""{DOC}"""\n'}
    report, _, _ = _refresh(student, _routes(**repo_routes(OWN, pushed="2026-10-02T19:05:04Z",
                                                           files=readme)))
    assert report.read == [LAB, OWN]


def test_final_5_a_changed_fork_is_read_by_the_students_own_commits_only(student):
    fork = "0rkhann/solver-fork"
    mine = [commit("Tune the solver for sparse inputs", "2026-09-10T00:00:00Z")]
    upstream = [commit("Add GPU kernel", "2020-01-01T00:00:00Z")]

    def answer(body):
        authored = body["variables"].get("author") == USER_ID
        return overview(commits=mine if authored else mine + upstream,
                        readmes={"README.md": blob(DOC)}, fork=True, parent="up/solver")

    routes = _routes(
        **listing(row(fork, fork=True, pushed="2026-10-05T00:00:00Z")),
        **repo_routes(fork, pushed="2026-10-05T00:00:00Z", fork=True),
    )
    routes[overview_key(fork)] = answer
    routes[f"/repos/{fork}"] = (200, {"parent": {"full_name": "up/solver"},
                                      "default_branch": "main"})
    routes["/repos/up/solver/compare/main...0rkhann:main"] = (200, {"ahead_by": 1})
    report, transport, parser = _refresh(student, routes)
    assert fork in report.read
    assert overviews(transport)[fork]["author"] == USER_ID
    sent = json.dumps([call["input"] for call in parser.calls])
    assert "Tune the solver" in sent and "GPU kernel" not in sent
    assert _readings(student)[fork].reading["first_commit"] == "2026-09-10"


def test_the_read_limit_stops_quietly_and_keeps_what_exists(student):
    for _ in range(INTAKE_RATE_LIMIT):
        rate_limited("evidence_intake", student.id, limit=INTAKE_RATE_LIMIT, window_seconds=3600)
    report, _, parser = _refresh(student, _routes())
    assert (report.stopped, parser.calls, _readings(student)) == ("read_limit", [], {})


def test_an_off_schema_answer_is_retried_once(student):
    report, _, parser = _refresh(student, _routes(), parser=FakeParser(None, READING, READING))
    assert len(parser.calls) == 3 and report.read == [LAB, OWN]


class _RaisesOnce(FakeParser):
    """openai's responses.parse raises pydantic's ValidationError itself on an off-schema
    answer, before parsed_or_none ever sees a response."""

    def parse(self, **kwargs):
        if not self.calls:
            self.calls.append(kwargs)
            RepoReading.model_validate({"summary": 1})  # raises ValidationError
        return super().parse(**kwargs)


def test_a_validation_error_from_the_sdk_is_retried_not_raised_into_the_worker(student):
    """Uncaught, it would escape refresh_evidence and the job would be redelivered forever
    (spec §12.1, §12.3)."""
    report, _, parser = _refresh(student, _routes(), parser=_RaisesOnce())
    assert len(parser.calls) == 3 and report.read == [LAB, OWN]


def test_a_repo_the_cv_links_is_read_first(student, fake_store):
    from weasyprint import HTML

    pdf = HTML(string='<p>Jane <a href="https://github.com/someone/linked">x</a></p>').write_pdf()
    promoted_upload(register(student.tenant_id, student.id, kind="CV"), fake_store, pdf)
    routes = _routes(**repo_routes("someone/linked", pushed="2026-01-01T00:00:00Z"))
    report, _, _ = _refresh(student, routes, store=fake_store)
    assert report.read == ["someone/linked", LAB, OWN]
    assert _readings(student)["someone/linked"].reading["origin"]["group"] == "cv"


@pytest.mark.parametrize("unreadable", ["no_checked_copy", "no_stored_object", "corrupt"])
def test_a_cv_that_cannot_be_read_deletes_nothing(student, fake_store, unreadable):
    """The repos only the CV links are unanswered, not gone (spec §6, §12.3)."""
    from weasyprint import HTML

    pdf = HTML(string='<p>Jane <a href="https://github.com/someone/linked">x</a></p>').write_pdf()
    cv = promoted_upload(register(student.tenant_id, student.id, kind="CV"), fake_store, pdf)
    routes = _routes(**repo_routes("someone/linked", pushed="2026-01-01T00:00:00Z"))
    _refresh(student, routes, store=fake_store)
    if unreadable == "no_checked_copy":
        with tenant_scope(student.tenant_id):
            DocumentVersion.objects.filter(id=cv.id).update(promoted_key="")
    elif unreadable == "no_stored_object":  # S3ObjectStore.get -> KeyError
        promoted_upload(register(student.tenant_id, student.id, kind="CV"), None, pdf + b" ")
    else:  # a newer CV whose bytes load and do not parse: extract_link_urls would say ()
        promoted_upload(register(student.tenant_id, student.id, kind="CV"), fake_store,
                        b"%PDF-1.4 garbage")
    report, _, _ = _refresh(student, routes, store=fake_store, force=True)
    assert (report.deleted, report.stopped) == (0, "")
    assert "someone/linked" in _readings(student)


def test_a_readable_cv_that_links_nothing_still_lets_deletion_run(student, fake_store):
    _refresh(student, _routes())
    promoted_upload(register(student.tenant_id, student.id, kind="CV"), fake_store,
                    _pdf("Jane Roe, no links at all."))
    report, _, _ = _refresh(student, _routes(**listing()), store=fake_store, force=True)
    assert (set(_readings(student)), report.deleted) == ({LAB}, 1)

# --- the PDF half ------------------------------------------------------------------

THESIS = "Gaussian process surrogates were benchmarked for carbene design. " * 12
PDF_READING = RepoReading(
    summary="A benchmark of Gaussian process surrogates.",
    kind="project",
    bullets=(ReadBullet(text="Benchmarked Gaussian process surrogates for carbene design.",
                        evidence=("Gaussian process surrogates were benchmarked for carbene "
                                  "design",)),),
)


def _pdf(text):
    from weasyprint import HTML

    return HTML(string=f"<p>{text}</p>").write_pdf()


def _thesis(student, store, *, body=None, mode=None, replaces=None):
    document = register(student.tenant_id, student.id, kind="THESIS_OR_REPORT", mode=mode,
                        replaces=replaces)
    document = promoted_upload(document, store, body or _pdf(THESIS))
    with tenant_scope(student.tenant_id):
        retire_replaced(document)
    return document


def _documents(student):
    with tenant_scope(student.tenant_id):
        return set(EvidenceReading.objects.filter(student=student, source_kind="pdf")
                   .values_list("document_id", flat=True))


def test_a_thesis_is_read_once_as_research_work_and_points_at_its_upload(student, fake_store):
    thesis = _thesis(student, fake_store)
    report, _, parser = _refresh(student, EMPTY, parser=FakeParser(PDF_READING), store=fake_store)
    assert report.read == [f"upload:{thesis.id}"]
    reading = _readings(student)[str(thesis.id)]
    assert (reading.source_kind, reading.reading["truncated"]) == ("pdf", False)
    assert reading.reading["bullets"][0]["verdict"] == "supported"
    assert "Describe research work" in parser.calls[0]["input"][0]["content"]
    again, _, parser = _refresh(student, EMPTY, parser=FakeParser(PDF_READING), store=fake_store,
                                force=True)
    assert (again.read, parser.calls) == ([], [])


def test_replace_replaces_add_another_keeps_both_and_retiring_deletes(student, fake_store):
    first = _thesis(student, fake_store)
    second = _thesis(student, fake_store, body=_pdf(THESIS + " A report."))
    _refresh(student, EMPTY, parser=FakeParser(PDF_READING), store=fake_store)
    assert _documents(student) == {first.id, second.id}
    third = _thesis(student, fake_store, body=_pdf(THESIS + " Final."), mode="REPLACE",
                    replaces=str(first.id))
    _refresh(student, EMPTY, parser=FakeParser(PDF_READING), store=fake_store, force=True)
    assert _documents(student) == {second.id, third.id}


def test_review_focus_5_a_scanned_thesis_is_never_sent_to_the_model(student, fake_store):
    from weasyprint import HTML

    scan = HTML(string='<div style="width:200px;height:200px;background:#000"></div>').write_pdf()
    _thesis(student, fake_store, body=scan)
    report, _, parser = _refresh(student, EMPTY, store=fake_store)
    assert (parser.calls, report.read, report.stopped) == ([], [], "")
    # The next upload still reads.
    _thesis(student, fake_store)
    report, _, _ = _refresh(student, EMPTY, parser=FakeParser(PDF_READING), store=fake_store,
                            force=True)
    assert len(report.read) == 1


def test_the_pdf_half_runs_when_the_github_half_is_skipped(student, fake_store):
    """Spec §12.1: only the GitHub half waits out the ten minutes."""
    _refresh(student, EMPTY)
    thesis = _thesis(student, fake_store)
    report, transport, _ = _refresh(student, EMPTY, parser=FakeParser(PDF_READING),
                                    store=fake_store)
    assert (report.stopped, report.read, transport.calls) == (
        "recent", [f"upload:{thesis.id}"], [])


def test_a_thesis_whose_object_is_missing_is_skipped_quietly(student, fake_store):
    document = register(student.tenant_id, student.id, kind="THESIS_OR_REPORT")
    promoted_upload(document, None, _pdf(THESIS))  # nothing put: the store raises KeyError
    report, _, parser = _refresh(student, EMPTY, store=fake_store)
    assert (report.read, report.stopped, parser.calls) == ([], "", [])
