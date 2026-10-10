"""Diffbot Enhance on the residue: one URL out, the token never in an error.

The fixture is hand-built from the documented response shape, not captured:
no Diffbot token existed when this was written (its `_provenance` says so).
"""

import json
from datetime import date
from functools import partial
from pathlib import Path

import pytest

from apps.research.egress import SourceBlocked
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.diffbot import DiffbotEnhance

FIXTURE = Path(__file__).parent / "fixtures" / "diffbot_enhance_shape.json"

#: These tests are about `homepage()`, not the terms-freshness gate: a fixed,
#: always-fresh reading date so they do not depend on when they happen to run.
_enhance = partial(DiffbotEnhance, terms_read_on="2026-01-01", today=date(2026, 1, 1))


def test_only_the_homepage_is_read_from_the_documented_shape() -> None:
    documented = json.loads(FIXTURE.read_text("utf-8"))
    assert "HAND-BUILT" in documented["_provenance"]
    enhance = _enhance(token="t", get=lambda *a, **k: documented, sleep=lambda s: None)
    assert enhance.homepage("Georgian Young Lawyers' Association") == "https://www.gyla.ge"


def test_the_request_asks_for_organisations_only() -> None:
    sent = {}

    def get(url, *, params, headers, **_):
        sent.update(params)
        return {"data": []}

    _enhance(token="t", get=get, sleep=lambda s: None).homepage("Person Name")
    assert sent == {"token": "t", "type": "Organization", "name": "Person Name"}


def test_an_entity_that_is_not_an_organisation_is_never_read() -> None:
    answer = {"data": [
        {"entity": {"type": "Person", "name": "x", "homepageUri": "person.example"}},
        {"entity": {"type": "Organization", "name": "x", "homepageUri": "https://org.example/"}},
    ]}
    enhance = _enhance(token="t", get=lambda *a, **k: answer, sleep=lambda s: None)
    assert enhance.homepage("x") == "https://org.example/"


def test_no_entity_is_an_empty_answer_not_an_error() -> None:
    enhance = _enhance(token="t", get=lambda *a, **k: {"data": []}, sleep=lambda s: None)
    assert enhance.homepage("Stiftung Gustav Werner und Haus am Berg") == ""


@pytest.mark.parametrize("error", [SourceBlocked, ValueError])
def test_the_token_never_reaches_an_exception(error: type[Exception]) -> None:
    def failing(url, *, params, headers, **_):
        raise error(f"MaxRetryError: /kg/v3/enhance?token={params['token']}")

    enhance = _enhance(token="secret-token", get=failing, sleep=lambda s: None)
    with pytest.raises(ProviderUnavailable) as raised:
        enhance.homepage("x")
    assert "secret-token" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert "secret-token" not in repr(enhance)


def test_calls_are_paced_to_the_free_tier() -> None:
    slept = []
    enhance = _enhance(token="t", get=lambda *a, **k: {"data": []},
                             sleep=slept.append, clock=iter([0.0, 1.0]).__next__)
    enhance.homepage("a")
    enhance.homepage("b")
    assert slept == [pytest.approx(11.0)]


def test_stale_or_absent_terms_refuse_construction() -> None:
    for terms_read_on in ("", "not a date", "2025-01-01", "2027-01-01"):
        with pytest.raises(ValueError, match="DIFFBOT_TERMS_READ_ON"):
            DiffbotEnhance(token="t", terms_read_on=terms_read_on, today=date(2026, 1, 1))


def test_fresh_terms_construct_cleanly() -> None:
    DiffbotEnhance(token="t", terms_read_on="2026-01-01", today=date(2026, 1, 31))
    DiffbotEnhance(token="t", terms_read_on="2026-01-01", today=date(2026, 1, 1))
