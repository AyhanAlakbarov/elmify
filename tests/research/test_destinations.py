"""A student who picks no country is searched across the 53 target countries."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

import apps.research.tap as tap_module
from apps.reference_data import ISO_3166_ALPHA2_CODES
from apps.research.destinations import TARGET_COUNTRIES, anywhere
from apps.research.models import Organisation, SearchTap
from apps.research.register import record_organisation
from apps.research.tap import request_tap, run_tap
from apps.research.tap_query import inputs_from
from apps.research.tap_seams import AngleRow
from apps.tenancy.context import tenant_scope
from tests.research.test_tap import (  # noqa: F401
    _profile,
    _Provider,
    _Seams,
    one_call_at_a_time,
    queued,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _institution(domain, country, status=Organisation.Status.REGISTERED, kind="INSTITUTION"):
    record_organisation(
        domain=domain, name=domain, kind=kind, country_code=country, found_via="REGISTER",
        status=status,
    )


def test_the_target_list_is_53_unique_valid_codes() -> None:
    assert len(TARGET_COUNTRIES) == len(set(TARGET_COUNTRIES)) == 53
    assert set(TARGET_COUNTRIES) <= ISO_3166_ALPHA2_CODES


def test_inputs_from_stays_raw_for_an_empty_country_list() -> None:
    assert inputs_from(_profile(allowed_countries=())).destinations == ()


def test_excluding_russia_leaves_52(agency_a) -> None:
    with tenant_scope(agency_a.id):
        assert len(anywhere({"RU"})) == 52 and "RU" not in anywhere({"RU"})


def test_thinnest_catalogue_first_ties_keep_list_order(agency_a) -> None:
    with tenant_scope(agency_a.id):
        for i in range(2):
            _institution(f"uni{i}.de", "DE")
        _institution("uni.at", "AT")
        _institution("cand.fr", "FR", status=Organisation.Status.CANDIDATE)
        _institution("rej.be", "BE", status=Organisation.Status.REJECTED)
        _institution("fund.nl", "NL", kind="PRIVATE_FOUNDATION")
        order = anywhere()
    assert order[-1] == "DE" and order[-3:-1] == ("AT", "FR")
    rest = [c for c in TARGET_COUNTRIES if c not in ("DE", "AT", "FR")]
    assert list(order[:-3]) == rest


def test_moving_from_one_country_to_anywhere_asks_the_rest() -> None:
    delta = tap_module._new_part(
        _profile(), _profile(allowed_countries=(), excluded_countries=("RU",))
    )
    assert delta is not None
    assert "DE" not in delta.destinations and "RU" not in delta.destinations
    assert len(delta.destinations) == 51
    anywhere_profile = _profile(allowed_countries=())
    assert tap_module._new_part(anywhere_profile, anywhere_profile) is None


def test_the_web_hook_never_reads_the_catalogue(
    agency_a, django_user_model, queued  # noqa: F811
) -> None:
    from tests.research.coverage_factories import make_published_student

    student = make_published_student(
        agency_a, django_user_model, allowed=(), target_field="Physical chemistry",
        research_interests=("catalysis",),
    )
    with tenant_scope(agency_a.id), CaptureQueriesContext(connection) as queries:
        request_tap(student, kind=SearchTap.Kind.FIRST)
        tap_module._new_part(_profile(), _profile(allowed_countries=()))
    assert not [q["sql"] for q in queries if "research_organisation" in q["sql"]]


def test_a_worker_searches_every_country_thinnest_first(
    agency_a, django_user_model, queued  # noqa: F811
) -> None:
    from tests.research.coverage_factories import make_published_student

    student = make_published_student(
        agency_a, django_user_model, allowed=(), excluded_countries=("RU",),
        target_field="Physical chemistry", research_interests=("catalysis",),
    )
    with tenant_scope(agency_a.id):
        _institution("uni.de", "DE")
        tap = request_tap(student, kind=SearchTap.Kind.FIRST)
        exa = _Provider()
        seams = _Seams(angles=(AngleRow("c", "en", "{field} in {destination}"),))
        run_tap(tap.id, seams=seams, providers=[exa])
    queries = [r.query for r in exa.requests]
    # a plateau may stop it early; what ran follows the thinnest-first order
    assert queries[:3] == [f"physical chemistry in {c}" for c in ("Austria", "Belgium", "Bulgaria")]
    assert not any(q.endswith(("Russia", "Germany")) for q in queries)


def test_a_follow_up_to_anywhere_spends_its_query_cap_on_the_thinnest_countries(
    agency_a, django_user_model, queued, settings  # noqa: F811
) -> None:
    """DE -> anywhere is 52 new countries; TAP_MAX_QUERIES must not go to the
    alphabetical EU head when those are the best-covered (owner: thinnest first)."""
    from tests.research.coverage_factories import make_published_student

    settings.TAP_MAX_QUERIES = 3
    student = make_published_student(
        agency_a, django_user_model, allowed=(), target_field="Physical chemistry",
        research_interests=("catalysis",),
    )
    delta = tap_module._new_part(_profile(), _profile(allowed_countries=()))
    assert delta is not None and delta.destinations[:3] == ("AT", "BE", "BG")
    with tenant_scope(agency_a.id):
        _institution("uni.at", "AT")
        _institution("uni.be", "BE")
        tap = request_tap(student, kind=SearchTap.Kind.FOLLOW_UP, inputs=delta)
        exa = _Provider()
        seams = _Seams(angles=(AngleRow("c", "en", "{field} in {destination}"),))
        run_tap(tap.id, inputs=delta, seams=seams, providers=[exa])
    assert [r.query for r in exa.requests] == [
        f"physical chemistry in {c}" for c in ("Bulgaria", "Croatia", "Cyprus")
    ]
