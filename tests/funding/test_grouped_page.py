import pytest

from apps.dashboard.pack import applied_candidate_ids
from apps.funding.models import EvidenceClaim, RecommendationCandidate, RecommendationRun
from apps.funding.views import _pack_context
from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card
from tests.funding.conftest import make_db_candidate, make_run

pytestmark = pytest.mark.django_db
PAGE = "/student/recommendation/"
#: the dashboard suite's published pack (programme + award), reused here.
pack = dashboard_conftest.pack


def test_programmes_are_grouped_under_the_funding_that_pays_for_them(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    client.force_login(user_a)
    with reads_no_catalogue():
        response = client.get(PAGE, HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert "<h1>Programmes &amp; funding</h1>" in body
    heading = body.index("<h3>DAAD Study Scholarship</h3>")
    assert body.index("M.Sc. Informatics", heading) > heading
    assert "Holder" in body and "DAAD" in body
    assert "934 EUR a month" in body
    assert "(unstructured)" in body
    assert "Programmes without separate funding" in body


def test_add_to_my_applications_and_already_added(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, award, portal=False)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert f'action="/student/applications/add/{programme.id}/"' in body
    assert f'action="/student/applications/add/{award.id}/"' not in body
    assert "In your applications." in body


def test_funding_that_comes_with_admission_offers_no_add(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    _programme, award = pack
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            funding_card={**award.funding_card, "route": "AUTOMATIC_ON_ADMISSION"}
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert f'action="/student/applications/add/{award.id}/"' not in body
    assert "Comes with the admission" in body


def test_a_javascript_source_url_is_never_a_link(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        EvidenceClaim.objects.filter(id=programme.evidence_id).update(
            source_url="javascript:alert(1)"
        )
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert 'href="javascript:' not in body


def test_a_checking_candidate_never_links_its_placeholder_source(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        source = EvidenceClaim.objects.get(id=programme.evidence_id).source_url
        RecommendationCandidate.objects.filter(id=programme.id).update(state="CHECKING")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Under review" in body
    assert source not in body


def test_the_page_reloads_itself_only_while_research_runs(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    run = make_run(agency_a, membership_a)
    client.force_login(user_a)
    assert '<meta http-equiv="refresh" content="15">' in client.get(
        PAGE, HTTP_HOST=domain_a.host
    ).content.decode()
    with tenant_scope(agency_a.id):
        RecommendationRun.objects.filter(id=run.id).update(state="DRAFT_READY")
    assert 'http-equiv="refresh"' not in client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()


def test_an_open_award_heads_every_eligible_programme_in_its_country(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, award = pack
    pool_only = make_db_candidate(agency_a, programme.run, program_name="LMU M.Sc. Physics")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            funds_program_ids=[], country_code="DE",
            funding_card={**award.funding_card, "scope": "HOLDER"},
        )
        RecommendationCandidate.objects.filter(id=pool_only.id).update(country_code="DE")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    heading = body.index("<h3>DAAD Study Scholarship</h3>")
    label = body.index("Eligible programmes in DE:", heading)
    assert body.index("M.Sc. Informatics", label) > label
    assert body.index("(in Other options)", label) < body.index("<h4>LMU M.Sc. Physics", label)


def test_an_award_with_no_programme_renders_no_empty_list(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    _programme, award = pack
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(funds_program_ids=[])
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "No programme in this list matches this funding." in body
    assert "Programmes it can pay for:" not in body


def test_the_context_reads_no_catalogue(agency_a, membership_a, pack) -> None:
    with tenant_scope(agency_a.id), reads_no_catalogue():
        context = _pack_context(membership_a)
    assert [g.award.program_name if g.award else None for g in context["groups"]] == [
        "DAAD Study Scholarship", None,
    ]
    assert context["research_pending"] is False


def test_applied_candidate_ids(agency_a, membership_a, pack) -> None:
    programme, award = pack
    with tenant_scope(agency_a.id):
        assert applied_candidate_ids(membership_a) == set()
        add_card(agency_a, membership_a, award, portal=False)
        assert applied_candidate_ids(membership_a) == {award.id}


def test_an_awards_eligibility_claim_is_printed_once(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    _programme, award = pack
    with tenant_scope(agency_a.id):
        EvidenceClaim.objects.filter(id=award.evidence_id).update(claim="Open to all nationalities")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert body.count("Open to all nationalities") == 1


def test_replace_with_offers_only_candidates_it_can_take(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """A CHECKING candidate is refused by replace (400); it is never offered."""
    programme, _award = pack
    visible = make_db_candidate(agency_a, programme.run, program_name="LMU M.Sc. Physics")
    checking = make_db_candidate(agency_a, programme.run, program_name="KIT M.Sc. Optics")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=checking.id).update(state="CHECKING")
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert f'<option value="{visible.id}">' in body
    assert f'<option value="{checking.id}">' not in body


def test_a_rerun_after_the_pack_still_reloads_the_page(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    """Spec §5: "while research is still running" -- a newer queued run, not
    only the first one."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        RecommendationRun.objects.filter(id=programme.run_id).update(state="PUBLISHED")
        assert _pack_context(membership_a)["research_pending"] is False
    make_run(agency_a, membership_a)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert '<meta http-equiv="refresh" content="15">' in body
    assert "<h2>Your pack</h2>" in body
