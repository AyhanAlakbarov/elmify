"""BLOCKED needs positive evidence; content checks only veto (spec §5.4)."""

import os
from datetime import timedelta
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.funding.models import OfficialEvidenceClaim, OfficialSource, OfficialSourceSnapshot
from apps.research.blocking import (
    _VETOES,
    _veto_hits,
    accreditation_hits,
    body_page_texts,
    content_facts,
    current_revision,
    degree_sentences,
    fee_sentences,
    mill_hit,
    read_accreditors,
    read_mill_list,
    revision_url,
    wikipedia_entries,
)
from apps.research.egress import fetch_json_api
from tests.research.provenance_helpers import (
    FakeFetch,
    FakeStore,
    evidence_program,
    make_body,
    page,
)

FEE_RELEASE = "A processing fee of 150 USD must be paid to release your scholarship award."
APPLICATION_FEE = "An application fee of 50 EUR applies to all applicants."
APEL = (
    "Credit for prior learning (APEL) lets you pay a fee to have experience assessed toward "
    "your degree."
)
DIPLOMA_SALE = "Order your accredited bachelor's degree today for a one-time payment of 299 USD."


def _jev(probabilities: dict[str, float], model: str = "typesafe/jev-1.13.0"):
    calls: list[dict] = []

    def post(url, *, payload, headers):
        calls.append(payload)
        listed = payload["state"]["sentences"]
        return {"model": model, "answers": {
            f"s{i}": {"type": "noul", "noul": probabilities.get(s, 0.0)}
            for i, s in enumerate(listed)
        }}

    post.calls = calls  # type: ignore[attr-defined]
    return post


def test_the_shipped_mill_list_blocks_the_ror_verified_mills_by_domain() -> None:
    rows = read_mill_list()
    domains = {row.domain for row in rows}
    assert {"bircham.edu", "aiu.edu", "warnborough.ac.uk", "iiu-edu.eu", "breyerstate.com",
            "awuedu.org"} <= domains
    hit = mill_hit("warnborough.ac.uk", rows=rows, register_countries=set())
    assert hit is not None and (hit.country_code, hit.overridden) == ("GB", False)
    assert {row.source_revision for row in rows if row.source == "wikipedia"} == {"1376085262"}


def test_only_the_mill_lists_own_country_can_override_it() -> None:
    rows = read_mill_list()
    assert mill_hit("warnborough.ac.uk", rows=rows, register_countries={"GB"}).overridden is True
    assert mill_hit("warnborough.ac.uk", rows=rows, register_countries={"SC"}).overridden is False
    assert mill_hit("tum.de", rows=rows, register_countries=set()) is None


@pytest.mark.parametrize(
    "name",
    ["St Clements University", "Almeda University", "Rochville University", "Belford University",
     "Ashwood University", "Selinus University", "Pacific Western University"],
)
def test_a_reviewed_mill_row_blocks_by_domain_never_by_name(tmp_path: Path, name: str) -> None:
    """The mechanism for the seven whose domains wait for review: a row blocks
    its DOMAIN; a body carrying the NAME on another domain is untouched."""
    domain = name.lower().replace(" ", "-") + "-fixture.com"
    path = tmp_path / "mill-list.csv"
    path.write_text(
        "domain,name,country_code,source,source_revision,verified_on\n"
        f"{domain},{name},US,wikipedia,1376085262,2026-09-26\n", encoding="utf-8",
    )
    rows = read_mill_list(path)
    assert mill_hit(domain, rows=rows, register_countries=set()) is not None
    assert mill_hit("real-university.edu", rows=rows, register_countries=set()) is None


def test_a_mill_row_that_is_not_a_registrable_domain_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "mill-list.csv"
    path.write_text(
        "domain,name,country_code,source,source_revision,verified_on\n"
        "www.bircham.edu,Bircham,ES,wikipedia,1,2026-09-26\n", encoding="utf-8",
    )
    with pytest.raises(ValueError, match="registrable"):
        read_mill_list(path)


def test_a_deny_listed_accreditor_is_picked_verbatim_by_code() -> None:
    accreditors = read_accreditors()
    hits = accreditation_hits(
        "https://diploma.example.com/about",
        "Our programmes are fully accredited by the World Association of Universities and "
        "Colleges.",
        accreditors,
    )
    assert [(hit.reason, hit.url) for hit in hits] == [
        ("accreditation_mill", "https://diploma.example.com/about")
    ]
    assert "World Association of Universities and Colleges" in hits[0].span


def test_real_accreditors_are_on_no_list_so_they_never_hit() -> None:
    text = "The school is accredited by EQUIS, AMBA and AACSB; its engineering degrees by ABET."
    assert accreditation_hits("https://esmt.berlin/", text, read_accreditors()) == ()


def test_the_pickers_choose_by_code_and_an_application_fee_is_not_picked() -> None:
    text = " ".join([FEE_RELEASE, APPLICATION_FEE, APEL, DIPLOMA_SALE])
    assert fee_sentences(text) == [FEE_RELEASE]
    assert APPLICATION_FEE not in degree_sentences(text)
    assert set(degree_sentences(text)) == {APEL, DIPLOMA_SALE}


def test_a_fee_to_release_an_award_is_a_hit(settings) -> None:
    settings.JEV_API_KEY = "k"
    post = _jev({FEE_RELEASE: 0.95})
    hits, status, detail = content_facts(
        [("https://funder.example.com/award", FEE_RELEASE + " " + APPLICATION_FEE)],
        run_id=uuid4(), post=post, accreditors=(),
    )
    assert (status, detail) == ("run", "")
    assert [(hit.reason, hit.span) for hit in hits] == [("fee_to_release_award", FEE_RELEASE)]
    question = post.calls[0]["questions"]["s0"]
    assert question["type"] == "noul"
    assert question["instructions"]["inspect"] == "`sentences[0]`"
    assert set(question["criteria"]) == {"true", "false"}


def test_apel_wording_at_a_real_university_does_not_block(settings) -> None:
    settings.JEV_API_KEY = "k"
    hits, _, _ = content_facts(
        [("https://www.ox.ac.uk/", APEL)], run_id=uuid4(), post=_jev({APEL: 0.1}), accreditors=(),
    )
    assert hits == ()


def test_unconfigured_jev_is_skipped_recorded_and_never_called(settings) -> None:
    settings.JEV_API_KEY = ""
    post = _jev({FEE_RELEASE: 0.99})
    hits, status, detail = content_facts(
        [("https://funder.example.com/", FEE_RELEASE)], run_id=uuid4(), post=post, accreditors=(),
    )
    assert (hits, status, detail, post.calls) == ((), "skipped", "no_key", [])


def test_a_different_served_model_means_the_threshold_does_not_apply(settings) -> None:
    settings.JEV_API_KEY = "k"
    hits, status, detail = content_facts(
        [("https://funder.example.com/", FEE_RELEASE)], run_id=uuid4(),
        post=_jev({FEE_RELEASE: 0.99}, model="typesafe/jev-2.0.0"), accreditors=(),
    )
    assert (hits, status, detail) == ((), "skipped", "other_model")


def test_a_spent_run_limit_skips_rather_than_calls(settings) -> None:
    settings.JEV_API_KEY = "k"
    settings.PROVENANCE_VETO_RUN_LIMIT = 0
    post = _jev({FEE_RELEASE: 0.99})
    hits, status, detail = content_facts(
        [("https://funder.example.com/", FEE_RELEASE)], run_id=uuid4(), post=post, accreditors=(),
    )
    assert (hits, status, detail, post.calls) == ((), "skipped", "rate_limited", [])


@pytest.mark.django_db
def test_the_bodys_own_stored_pages_are_what_the_vetoes_read() -> None:
    body = make_body("tum.de")
    program = evidence_program("https://www.tum.de/msc")
    claim = OfficialEvidenceClaim.objects.get(program=program)
    snapshot = OfficialSourceSnapshot.objects.create(
        source=OfficialSource.objects.get(canonical_url="https://www.tum.de/msc"),
        s3_key="official-sources/tum-msc", s3_version_id="1", sha256="c" * 64,
        final_url="https://www.tum.de/msc", redirect_chain=[], retrieved_at=timezone.now(),
        admissions_cycle="2027", content_type="text/html", byte_size=10,
    )
    OfficialEvidenceClaim.objects.filter(id=claim.id).update(snapshot=snapshot)
    store = FakeStore({"official-sources/tum-msc": b"<p>" + APEL.encode() + b"</p>"})
    assert body_page_texts(body, "tum.de", store=store) == [("https://www.tum.de/msc", APEL)]
    assert body_page_texts(body, "tum.de", store=FakeStore()) == []


_PERMALINK = (
    b'<html><body><ul><li id="t-permalink">'
    b'<a href="/w/index.php?title=List&amp;oldid=%s">Permanent link</a></li></ul>\n'
)
PINNED = _PERMALINK % b"1376085262" + (
    b'<div class="mw-parser-output"><ul><li>Almeda University, Idaho[8]</li>'
    b"<li>Belford University</li></ul></div></body></html>"
)
CURRENT = _PERMALINK % b"1380000000" + (
    b'<div class="mw-parser-output"><ul><li>Almeda University, Idaho[8]</li>'
    b"<li>New Mill University, Nowhere</li></ul></div></body></html>"
)


def test_wikipedia_entries_and_revisions() -> None:
    assert current_revision(CURRENT) == "1380000000"
    assert wikipedia_entries(PINNED) - wikipedia_entries(CURRENT) >= {"Belford University"}
    assert "Almeda University, Idaho" in wikipedia_entries(PINNED)


def test_the_diff_command_shows_a_vandalised_or_real_edit(monkeypatch) -> None:
    from apps.research.management.commands import mill_list_diff

    monkeypatch.setattr(mill_list_diff, "fetch_page", FakeFetch({
        mill_list_diff.PAGE: page(mill_list_diff.PAGE, CURRENT),
        revision_url("1376085262"): page(revision_url("1376085262"), PINNED),
    }))
    out = StringIO()
    call_command("mill_list_diff", stdout=out)
    text = out.getvalue()
    assert "pinned 1376085262, current 1380000000" in text
    assert "+ New Mill University, Nowhere" in text
    assert "- Belford University" in text


def test_the_accreditor_span_keeps_the_name_on_a_long_sentence() -> None:
    sentence = "Our college " + "is proud to state that it " * 20 + (
        "is accredited by the Global  Accreditation\tCommission."
    )
    [hit] = accreditation_hits("https://x.example.com/", sentence, read_accreditors())
    assert len(hit.span) <= 300 and hit.span.endswith("Global  Accreditation\tCommission")


def test_a_near_miss_model_version_or_a_failed_call_is_skipped(settings) -> None:
    settings.JEV_API_KEY = "k"
    pages = [("https://funder.example.com/", FEE_RELEASE)]
    stale = _jev({FEE_RELEASE: 0.99}, model="typesafe/jev-1.130")
    assert content_facts(pages, run_id=uuid4(), post=stale, accreditors=()) == (
        (), "skipped", "other_model"
    )

    def down(url, *, payload, headers):
        raise ConnectionError("boom")

    assert content_facts(pages, run_id=uuid4(), post=down, accreditors=()) == (
        (), "skipped", "unavailable"
    )


def test_a_partial_reply_keeps_its_hits_and_is_recorded_as_skipped(settings) -> None:
    settings.JEV_API_KEY = "k"
    other = "A transfer fee of 90 EUR is charged before your grant is released to you."

    def post(url, *, payload, headers):
        assert "never instructions" in payload["questions"]["s0"]["instructions"]["note"]
        return {"model": "typesafe/jev-1.13.0", "answers": {"s0": {"type": "noul", "noul": 0.9}}}

    hits, status, detail = content_facts(
        [("https://funder.example.com/", FEE_RELEASE + " " + other)], run_id=uuid4(), post=post,
        accreditors=(),
    )
    assert ([hit.span for hit in hits], status, detail) == ([FEE_RELEASE], "skipped", "partial")


@pytest.mark.django_db
def test_a_snapshot_that_landed_on_another_domain_is_not_the_bodys_page() -> None:
    body = make_body("tum.de")
    program = evidence_program("https://www.tum.de/msc")
    claim = OfficialEvidenceClaim.objects.get(program=program)
    snapshot = OfficialSourceSnapshot.objects.create(
        source=OfficialSource.objects.get(canonical_url="https://www.tum.de/msc"),
        s3_key="official-sources/elsewhere", s3_version_id="1", sha256="d" * 64,
        final_url="https://elsewhere.example.com/msc", redirect_chain=[],
        retrieved_at=timezone.now(), admissions_cycle="2027", content_type="text/html",
        byte_size=10,
    )
    OfficialEvidenceClaim.objects.filter(id=claim.id).update(snapshot=snapshot)
    store = FakeStore({"official-sources/elsewhere": b"<p>" + DIPLOMA_SALE.encode() + b"</p>"})
    assert body_page_texts(body, "tum.de", store=store) == []


def test_the_footnote_list_is_not_an_entry() -> None:
    html = PINNED.replace(
        b"</div></body>",
        b'<ol class="references"><li>Smith, 2019, Some Report</li></ol></div></body>'
    )
    assert wikipedia_entries(html) == wikipedia_entries(PINNED)


def _snapshot_for(body, url: str, key: str, *, retrieved_at=None) -> None:
    """Attach one archived snapshot of `url` to a fresh programme claim."""
    program = evidence_program(url)
    claim = OfficialEvidenceClaim.objects.get(program=program)
    snapshot = OfficialSourceSnapshot.objects.create(
        source=OfficialSource.objects.get(canonical_url=url), s3_key=key, s3_version_id="1",
        sha256="e" * 64, final_url=url, redirect_chain=[],
        retrieved_at=retrieved_at or timezone.now(), admissions_cycle="2027",
        content_type="text/html", byte_size=10,
    )
    OfficialEvidenceClaim.objects.filter(id=claim.id).update(snapshot=snapshot)


@pytest.mark.django_db
def test_inline_markup_does_not_split_a_sentence_so_every_check_still_hits(settings) -> None:
    """Fix round 1: harvest.page_text put every text node on its own line, so
    `<a>`, `<b>` and `<em>` cut each sentence in two and all three checks missed
    ordinary HTML. readable_text keeps inline text joined, one block a line."""
    settings.JEV_API_KEY = "k"
    body = make_body("diplomamill.com")
    _snapshot_for(body, "https://www.diplomamill.com/about", "official-sources/mill")
    html = (
        b"<html><body>"
        b"<p>Our degrees are fully accredited by the <a href='/w'>World Association of "
        b"Universities and Colleges</a>.</p>"
        b"<p>A processing fee of <b>150 USD</b> must be paid to release your scholarship "
        b"award.</p>"
        b"<p>Order your accredited <em>bachelor's degree</em> today for a one-time payment "
        b"of 299 USD.</p>"
        b"</body></html>"
    )
    store = FakeStore({"official-sources/mill": html})
    pages = body_page_texts(body, "diplomamill.com", store=store)
    hits, status, _ = content_facts(
        pages, run_id=uuid4(), post=_jev({FEE_RELEASE: 0.95, DIPLOMA_SALE: 0.95}),
    )
    assert status == "run"
    assert {hit.reason for hit in hits} == {
        "accreditation_mill", "fee_to_release_award", "degree_for_payment"
    }


@pytest.mark.parametrize(
    "text",
    [
        "Accredited by the Central States Consortium of Colleges and Schools.",
        "Accredited by the Central States Consortium of Colleges & Schools.",
        "Accredited by the Global-Accreditation, Commission since 2004.",
        "Accredited by the World Association of Universities​and Colleges.",
        "ACCREDITED BY THE BOARD OF ONLINE UNIVERSITIES ACCREDITATION.",
        "# Accreditation\n- World Association of Universities and Colleges\n- ISO 9001",
    ],
)
def test_a_deny_listed_accreditor_is_found_through_punctuation_case_and_a_heading(
    text: str,
) -> None:
    [hit] = accreditation_hits("https://x.example.com/", text, read_accreditors())
    assert hit.reason == "accreditation_mill"
    # The span is the page's own words, never the normalised form.
    assert hit.span in text


@pytest.mark.parametrize(
    "text",
    [
        "Accredited by EQUIS, AMBA & AACSB; engineering by ABET.",
        "# Accreditation\n- EQUIS\n- AMBA\n- AACSB\n- ABET",
        "Accredited by the Global Accreditation Commissioners Forum.",
        "Accredited by the Global Accreditation Commissionership of Examples.",
    ],
)
def test_a_real_accreditor_or_a_longer_word_never_hits(text: str) -> None:
    assert accreditation_hits("https://x.example.com/", text, read_accreditors()) == ()


def test_a_listed_name_with_no_accreditation_context_does_not_hit() -> None:
    text = "# Our partners\n- World Association of Universities and Colleges"
    assert accreditation_hits("https://x.example.com/", text, read_accreditors()) == ()


def test_a_sentence_sent_to_jev_is_cut_to_500_characters(settings) -> None:
    settings.JEV_API_KEY = "k"
    long = FEE_RELEASE[:-1] + ", " + "and the office confirms it in writing " * 20 + "."
    post = _jev({})
    content_facts([("https://funder.example.com/", long)], run_id=uuid4(), post=post,
                  accreditors=())
    [sent] = post.calls[0]["state"]["sentences"]
    assert sent == long[:500]


def test_a_host_or_www_input_is_keyed_by_its_registrable_domain() -> None:
    rows = read_mill_list()
    assert mill_hit("www.warnborough.ac.uk", rows=rows, register_countries=set()) is not None
    assert mill_hit("https://www.aiu.edu/apply", rows=rows, register_countries=set()) is not None


@pytest.mark.django_db
def test_at_most_five_pages_are_read_newest_first() -> None:
    body = make_body("tum.de")
    now = timezone.now()
    for age in range(7):
        _snapshot_for(
            body, f"https://www.tum.de/p{age}", f"official-sources/p{age}",
            retrieved_at=now - timedelta(days=age),
        )
    store = FakeStore(
        {f"official-sources/p{age}": f"<p>Page {age}</p>".encode() for age in range(7)}
    )
    pages = body_page_texts(body, "tum.de", store=store)
    assert [url for url, _ in pages] == [f"https://www.tum.de/p{age}" for age in range(5)]


def test_two_different_skip_causes_are_both_recorded(settings) -> None:
    settings.JEV_API_KEY = "k"
    calls: list[int] = []

    def flaky(url, *, payload, headers):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("boom")
        return {"model": "typesafe/jev-2.0.0", "answers": {}}

    _hits, status, detail = content_facts(
        [("https://funder.example.com/", FEE_RELEASE + " " + DIPLOMA_SALE)], run_id=uuid4(),
        post=flaky, accreditors=(),
    )
    assert (status, detail) == ("skipped", "other_model,unavailable")


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
@pytest.mark.parametrize(
    ("reason", "sentence", "vetoed"),
    [
        ("fee_to_release_award", FEE_RELEASE, True),
        ("fee_to_release_award", APPLICATION_FEE, False),
        ("degree_for_payment", DIPLOMA_SALE, True),
        ("degree_for_payment", APEL, False),
    ],
)
def test_live_pinned_jev_separates_the_carve_outs_at_the_threshold(
    settings, reason: str, sentence: str, vetoed: bool
) -> None:
    """Run by hand with -m live: the four fixtures against the pinned JEV_MODEL
    at VETO_THRESHOLD. Synthetic sentences only; no student data."""
    settings.JEV_API_KEY = os.environ["OPENROUTER_API_KEY"]
    [veto] = [veto for veto in _VETOES if veto.reason == reason]
    hits, skipped = _veto_hits(
        "https://funder.example.com/", [sentence], veto, post=fetch_json_api, run_id=uuid4()
    )
    assert skipped is None
    assert bool(hits) is vetoed
