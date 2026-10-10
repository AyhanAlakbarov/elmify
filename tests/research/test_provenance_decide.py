"""decide(): evidence in, one verdict out. Pure -- no database, no network,
and no model call anywhere on the admit path (spec §2)."""

from datetime import UTC, date, datetime

import pytest

from apps.research.provenance import (
    ContentHit,
    Facts,
    MillHit,
    RdapResult,
    Recognition,
    decide,
)

REGISTER = Recognition(
    reason="register", bound_domain="tum.de", source_slug="de_register",
    source_url="https://register.example.org/", list_date="2026-09-26", country_code="DE",
)
CURATED = Recognition(reason="curated_list", bound_domain="tum.de", source_slug="az_heis")
VOUCHED = Recognition(
    reason="vouched_by_link", bound_domain="ufaz.az", vouch_url="https://asoiu.edu.az/",
    admitted_via="asoiu.edu.az",
)
FUNDER = Recognition(reason="funder_list", bound_domain="daad.de", source_slug="daad_list")
GOVZONE = Recognition(reason="government_zone", bound_domain="mext.go.jp", source_slug="go_jp")
VENDOR = ContentHit(reason="degree_for_payment", span="Buy your MBA today.", url="https://x/")
ACCREDITATION_MILL_HIT = ContentHit(
    reason="accreditation_mill", span="Accredited by the XYZ Accreditation Council.",
    url="https://x/",
)
FEE_HIT = ContentHit(
    reason="fee_to_release_award", span="Pay $500 to release your scholarship.", url="https://x/"
)


def test_a_register_row_recognises_the_bound_domain_and_records_its_source() -> None:
    decision = decide(Facts(domain="tum.de", recognitions=(REGISTER,)))
    assert (decision.verdict, decision.reason_code, decision.bound_domain) == (
        "RECOGNISED", "register", "tum.de",
    )
    assert decision.evidence["source_slug"] == "de_register"
    assert decision.evidence["list_date"] == "2026-09-26"


def test_the_strongest_route_wins_whatever_the_order() -> None:
    decision = decide(Facts(domain="tum.de", recognitions=(CURATED, REGISTER)))
    assert decision.reason_code == "register"


def test_vouching_records_the_link_it_rests_on() -> None:
    decision = decide(Facts(domain="ufaz.az", recognitions=(VOUCHED,)))
    assert decision.reason_code == "vouched_by_link"
    assert decision.evidence["vouch_url"] == "https://asoiu.edu.az/"
    assert decision.evidence["admitted_via"] == "asoiu.edu.az"


def test_a_hosting_platform_can_never_be_recognised_by_its_domain() -> None:
    on_platform = Recognition(reason="curated_list", bound_domain="tum.blogspot.com")
    decision = decide(Facts(domain="tum.blogspot.com", recognitions=(on_platform,)))
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", "no_domain_binding")


def test_a_mill_blocks_unless_its_own_countrys_register_overrides_it() -> None:
    warnborough_register = Recognition(reason="register", bound_domain="warnborough.ac.uk")
    mill = MillHit(source="wikipedia", revision="1376085262", country_code="GB", overridden=False)
    blocked = decide(
        Facts(domain="warnborough.ac.uk", recognitions=(warnborough_register,), mill=mill)
    )
    assert (blocked.verdict, blocked.reason_code) == ("BLOCKED", "mill_list")
    assert blocked.evidence["mill"] == {
        "source": "wikipedia", "revision": "1376085262", "country_code": "GB",
        "overridden": False,
    }
    overridden = MillHit(source="wikipedia", revision="1", country_code="DE", overridden=True)
    recognised = decide(Facts(domain="tum.de", recognitions=(REGISTER,), mill=overridden))
    assert recognised.verdict == "RECOGNISED"
    # Minor, item 2: the mill hit is recorded even when it was overridden, so
    # the override is visible in the evidence and not only absent from the verdict.
    assert recognised.evidence["mill"] == {
        "source": "wikipedia", "revision": "1", "country_code": "DE", "overridden": True,
    }


def test_a_content_veto_on_a_recognised_body_is_a_conflict_never_a_block() -> None:
    decision = decide(Facts(domain="tum.de", recognitions=(REGISTER,), content_hits=(VENDOR,)))
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", "veto_conflict")
    assert decision.evidence["content_hits"] == [
        {"reason": "degree_for_payment", "span": "Buy your MBA today.", "url": "https://x/"}
    ]


def test_a_content_veto_on_an_unrecognised_body_blocks() -> None:
    decision = decide(Facts(domain="diploma-shop.com", content_hits=(VENDOR,)))
    assert (decision.verdict, decision.reason_code) == ("BLOCKED", "degree_for_payment")


def test_accreditation_mill_blocks_with_no_usable_recognition() -> None:
    decision = decide(Facts(domain="diploma-shop.com", content_hits=(ACCREDITATION_MILL_HIT,)))
    assert (decision.verdict, decision.reason_code) == ("BLOCKED", "accreditation_mill")


def test_accreditation_mill_on_a_recognised_body_is_a_conflict_never_a_block() -> None:
    decision = decide(
        Facts(domain="tum.de", recognitions=(REGISTER,), content_hits=(ACCREDITATION_MILL_HIT,))
    )
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", "veto_conflict")


def test_fee_to_release_award_blocks_with_no_usable_recognition() -> None:
    decision = decide(Facts(domain="scholarship-scam.com", content_hits=(FEE_HIT,)))
    assert (decision.verdict, decision.reason_code) == ("BLOCKED", "fee_to_release_award")


def test_funder_list_wins_as_the_reason() -> None:
    decision = decide(Facts(domain="daad.de", recognitions=(FUNDER,)))
    assert decision.reason_code == "funder_list"


def test_government_zone_wins_as_the_reason() -> None:
    decision = decide(Facts(domain="mext.go.jp", recognitions=(GOVZONE,)))
    assert decision.reason_code == "government_zone"


def test_a_veto_outranks_a_takeover_signal() -> None:
    facts = Facts(
        domain="tum.de", recognitions=(REGISTER,), content_hits=(VENDOR,),
        rdap=RdapResult("ok", registered=date(2016, 6, 6)),
        first_bound_at=datetime(2015, 1, 1, tzinfo=UTC),
    )
    decision = decide(facts)
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", "veto_conflict")


def test_a_domain_registered_after_we_first_bound_it_is_unconfirmed() -> None:
    facts = Facts(
        domain="tum.de", recognitions=(REGISTER,),
        rdap=RdapResult("ok", registered=date(2016, 6, 6)),
        first_bound_at=datetime(2015, 1, 1, tzinfo=UTC),
    )
    decision = decide(facts)
    assert (decision.verdict, decision.reason_code) == (
        "UNCONFIRMED", "domain_registered_after_listing",
    )
    assert decision.evidence["rdap"] == {"status": "ok", "date": "2016-06-06", "detail": ""}


def test_a_recognition_bound_to_a_different_domain_is_not_usable() -> None:
    """Controller ruling, fix round 1: a recognition is usable only when its
    `bound_domain` equals `facts.domain` (registrable-normalised). ESMT's own
    `domains[]` is esmt.org while its recognised website is esmt.berlin (spec
    §5.2); a lookup on esmt.org must not be admitted through a row bound to
    esmt.berlin -- that is a different, unchecked domain."""
    esmt_register = Recognition(reason="register", bound_domain="esmt.berlin")
    decision = decide(Facts(domain="esmt.org", recognitions=(esmt_register,)))
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", "no_domain_binding")


def test_a_veto_never_blocks_a_recognition_dropped_for_its_domain() -> None:
    """Minor, item 3: a recognition dropped for its domain (here, bound to a
    hosting platform) must give no_domain_binding, never let a content veto
    escalate it to BLOCKED -- a real university's page a curated list names
    must not be condemned permanently over a domain gap."""
    on_platform = Recognition(reason="curated_list", bound_domain="tum.blogspot.com")
    decision = decide(
        Facts(domain="tum.blogspot.com", recognitions=(on_platform,), content_hits=(VENDOR,))
    )
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", "no_domain_binding")


@pytest.mark.parametrize("rdap", [RdapResult("skipped", detail=".de"), RdapResult("failed")])
def test_an_rdap_gap_never_changes_a_recognised_verdict(rdap) -> None:
    facts = Facts(
        domain="tum.de", recognitions=(REGISTER,), rdap=rdap,
        first_bound_at=datetime(2015, 1, 1, tzinfo=UTC),
    )
    assert decide(facts).verdict == "RECOGNISED"


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (Facts(domain="asoiu.edu.az", unverified_list_row=True), "unmapped_list_row"),
        (Facts(domain="ufaz.az", was_vouched=True), "vouch_link_missing"),
        (Facts(domain="uni.example.com", lookup_failed=True), "lookup_failed"),
        (Facts(domain="nyenrode.nl", register_state="unbound_rows"), "no_domain_binding"),
        (Facts(domain="dubai-branch.ae", register_state="absent"), "absent_from_register"),
        (Facts(domain="uni.jp", register_state="not_loaded"), "register_not_loaded"),
        (Facts(domain="mit.edu", register_state="no_register"), "no_register"),
        (Facts(domain="mit.edu", register_state="no_register", lookup_failed=True),
         "lookup_failed"),
        (Facts(domain="uni.wixsite.com", register_state="absent"), "no_domain_binding"),
    ],
)
def test_every_unconfirmed_reason(facts, reason) -> None:
    decision = decide(facts)
    assert (decision.verdict, decision.reason_code) == ("UNCONFIRMED", reason)


def test_absence_is_never_blocked() -> None:
    for state in ("absent", "unbound_rows", "not_loaded", "no_register"):
        assert decide(Facts(domain="little-known.edu", register_state=state)).verdict != "BLOCKED"


def test_skipped_content_checks_are_recorded() -> None:
    decision = decide(Facts(domain="tum.de", recognitions=(REGISTER,), content_checks="skipped",
                            content_checks_detail="rate_limited"))
    assert decision.evidence["content_checks"] == "skipped"
    assert decision.evidence["content_checks_detail"] == "rate_limited"
