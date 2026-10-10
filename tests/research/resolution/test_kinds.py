"""The closed registry of kinds: one declaration, one closed question each.

`validate_public_url` resolves DNS, so conftest replaces the copy kinds.py
imported with a no-op; the one test below that restores the real function is
what proves a pasted private address is refused.
"""

import pytest
from pydantic import ValidationError

from apps.research import egress
from apps.research.models import _RESOLUTION_PREFIXES, ResolutionItem
from apps.research.resolution import kinds
from apps.research.resolution.kinds import KINDS, evidence_for, resolution_for

_SITE = {
    "register": "vgm_tr",
    "external_key": "1",
    "names": ["Vakfı"],
    "country_code": "TR",
    "candidates": [{"url": "https://vakfi.org.tr/", "title": "Vakfı"}],
}


def test_the_registry_is_the_one_declaration_of_kinds() -> None:
    assert set(KINDS) == set(ResolutionItem.Kind.values) == set(_RESOLUTION_PREFIXES)
    for kind, spec in KINDS.items():
        assert spec.kind == kind
        assert spec.subject_prefix == _RESOLUTION_PREFIXES[kind]


def test_evidence_refuses_a_field_it_does_not_name() -> None:
    """extra=forbid is the person-free guarantee: a writer cannot slip a
    student id or a tenant into evidence without a schema change a test sees."""
    with pytest.raises(ValidationError):
        evidence_for(
            "HOST_UNREACHABLE",
            {"host": "a.test", "url": "https://a.test/", "trail": [], "tenant_id": "x"},
        )


def test_site_unknown_pick_must_be_one_of_the_candidates() -> None:
    evidence = evidence_for("SITE_UNKNOWN", _SITE)
    with pytest.raises(ValidationError):
        resolution_for(
            "SITE_UNKNOWN", {"option": "pick", "url": "https://elsewhere.test/"}, evidence=evidence
        )
    assert (
        resolution_for(
            "SITE_UNKNOWN", {"option": "pick", "url": "https://vakfi.org.tr/"}, evidence=evidence
        ).option
        == "pick"
    )


def test_site_unknown_carries_a_conflicts_reason_and_bounds_it() -> None:
    """A CONFLICT row (brief D4) says why it is a conflict; an UNRESOLVED one
    says nothing, and the reason is bounded like every other evidence string."""
    assert evidence_for("SITE_UNKNOWN", _SITE).why == ""  # type: ignore[attr-defined]
    conflict = evidence_for("SITE_UNKNOWN", {**_SITE, "why": "Wikidata Q1 is already on a.test"})
    assert conflict.why == "Wikidata Q1 is already on a.test"  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        evidence_for("SITE_UNKNOWN", {**_SITE, "why": "x" * 301})


def test_a_whole_row_answer_takes_no_url() -> None:
    evidence = evidence_for("SITE_UNKNOWN", _SITE)
    with pytest.raises(ValidationError):
        resolution_for(
            "SITE_UNKNOWN",
            {"option": "not_a_funder", "url": "https://vakfi.org.tr/"},
            evidence=evidence,
        )


def test_a_resolution_is_never_validated_without_its_evidence() -> None:
    with pytest.raises(ValidationError):
        KINDS["HOST_UNREACHABLE"].resolution.model_validate({"option": "closed"})


def test_a_pasted_private_address_is_refused_by_the_real_check(monkeypatch) -> None:
    """The one test on the real `validate_public_url`: an IP literal needs no
    DNS, and a loopback paste is exactly how a hostile answer would point the
    applier's fetch inward."""
    monkeypatch.setattr(kinds, "validate_public_url", egress.validate_public_url)
    evidence = evidence_for("SITE_UNKNOWN", _SITE)
    with pytest.raises(ValidationError):
        resolution_for(
            "SITE_UNKNOWN", {"option": "paste", "url": "https://127.0.0.1/"}, evidence=evidence
        )


def test_award_accept_must_answer_every_disputed_field_from_its_choices() -> None:
    evidence = evidence_for(
        "AWARD_DISPUTED",
        {
            "canonical_key": "read:k",
            "award_name": "A",
            "page_url": "https://u.test/f",
            "snapshot_sha256": "0" * 64,
            "quotes": ["q"],
            "disputed": [
                {"field": "money_form", "choices": ["GRANT", "FEE_WAIVER", "LOAN", "MIXED"]}
            ],
        },
    )
    with pytest.raises(ValidationError):
        resolution_for("AWARD_DISPUTED", {"option": "accept", "fields": {}}, evidence=evidence)
    with pytest.raises(ValidationError):
        resolution_for(
            "AWARD_DISPUTED",
            {"option": "accept", "fields": {"money_form": "GIFT"}},
            evidence=evidence,
        )
    with pytest.raises(ValidationError):
        resolution_for(
            "AWARD_DISPUTED",
            {"option": "not_an_award", "fields": {"money_form": "GRANT"}},
            evidence=evidence,
        )
    assert resolution_for(
        "AWARD_DISPUTED",
        {"option": "accept", "fields": {"money_form": "GRANT"}},
        evidence=evidence,
    ).fields == {"money_form": "GRANT"}


def test_host_paste_must_stay_on_the_hosts_registrable_domain() -> None:
    """A page that moved to another organisation's domain is SITE_UNKNOWN's
    question, not this one's -- and a pasted off-domain URL is exactly how a
    hostile page would get itself into the catalog."""
    # Real public suffixes: `registrable_domain` answers "" for `.test`, and
    # "" is never a match -- which the last assertion pins.
    evidence = evidence_for(
        "HOST_UNREACHABLE",
        {"host": "www.uni.edu.tr", "url": "https://www.uni.edu.tr/x", "trail": []},
    )
    with pytest.raises(ValidationError):
        resolution_for(
            "HOST_UNREACHABLE", {"option": "paste", "url": "https://other.edu.tr/x"},
            evidence=evidence,
        )
    assert (
        resolution_for(
            "HOST_UNREACHABLE", {"option": "paste", "url": "https://apply.uni.edu.tr/x"},
            evidence=evidence,
        ).url
        == "https://apply.uni.edu.tr/x"
    )
    unkeyable = evidence_for(
        "HOST_UNREACHABLE", {"host": "www.uni.test", "url": "https://www.uni.test/x", "trail": []}
    )
    with pytest.raises(ValidationError):
        resolution_for(
            "HOST_UNREACHABLE", {"option": "paste", "url": "https://www.uni.test/y"},
            evidence=unkeyable,
        )


def test_kind_or_country_requires_funds_students() -> None:
    evidence = evidence_for(
        "KIND_OR_COUNTRY_UNSURE",
        {
            "primary_domain": "f.test",
            "homepage_title": "F",
            "guess_kind": "PRIVATE_FOUNDATION",
            "guess_country": "TR",
            "confidence": 0.4,
        },
    )
    with pytest.raises(ValidationError):
        resolution_for(
            "KIND_OR_COUNTRY_UNSURE",
            {"option": "set", "kind": "PRIVATE_FOUNDATION", "country_code": "TR"},
            evidence=evidence,
        )
    with pytest.raises(ValidationError):
        resolution_for(
            "KIND_OR_COUNTRY_UNSURE",
            {"option": "set", "kind": "NOT_A_KIND", "funds_students": True},
            evidence=evidence,
        )
    assert resolution_for(
        "KIND_OR_COUNTRY_UNSURE",
        {"option": "set", "kind": "PRIVATE_FOUNDATION", "country_code": "TR",
         "funds_students": False},
        evidence=evidence,
    ).funds_students is False


def test_every_kind_renders_a_closed_question_under_300_characters() -> None:
    for kind, spec in KINDS.items():
        assert spec.options, kind
        assert 0 < len(spec.render_ask(spec.example_evidence())) <= 300, kind


def test_a_long_name_still_renders_under_300_characters() -> None:
    long = evidence_for(
        "SITE_UNKNOWN", {**_SITE, "names": ["N" * 300], "why": "W" * 300}
    )
    assert len(KINDS["SITE_UNKNOWN"].render_ask(long)) <= 300


def test_the_options_are_exactly_the_resolutions_choices() -> None:
    """The console offers `options`; the resolution model admits `option`. Two
    lists of one thing drift, so they are compared, not trusted."""
    from typing import get_args

    for kind, spec in KINDS.items():
        literal = spec.resolution.model_fields["option"].annotation
        assert set(get_args(literal)) == set(spec.options), kind
