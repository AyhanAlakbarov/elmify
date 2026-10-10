import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.research.sitejob import (
    DOCUMENT_SUFFIXES,
    Lead,
    ProgrammeOutcome,
    SiteJobResult,
    Stage,
    document_links,
    guided_instruction,
    navigator_brief,
    navigator_policy,
)


class _Page:
    """The two fields document_links reads off a FetchedPage."""

    def __init__(self, body: bytes, final_url: str) -> None:
        self.body = body
        self.final_url = final_url


def test_the_policy_refuses_a_value_it_does_not_know(settings):
    """A typo in FETCH_NAVIGATOR_POLICY that fell through to "not always" would
    silently stop stages 3 and 4 running at all, and the symptom is a programme
    recorded `not found` -- indistinguishable from one whose pages do not
    exist. That is the exact confusion this whole engine exists to remove, so
    the typo is a startup error, not a quiet default."""
    settings.FETCH_NAVIGATOR_POLICY = "on-miss"

    with pytest.raises(ImproperlyConfigured):
        navigator_policy()


def test_the_policy_reads_the_two_documented_values(settings):
    settings.FETCH_NAVIGATOR_POLICY = "always"
    assert navigator_policy() == "always"
    settings.FETCH_NAVIGATOR_POLICY = "on_miss"
    assert navigator_policy() == "on_miss"


def test_document_links_are_the_page_s_own_documents_only():
    """Stage 1 is bounded by the page's DOCUMENT links, never by a hop count
    (spec 7.0). An HTML sibling is stage 2's job; following it here would turn
    a bounded stage into an unbounded crawl with no budget line of its own."""
    body = (
        b'<a href="/docs/checklist.pdf">Checklist</a>'
        b'<a href="/apply/">How to apply</a>'
        b'<a href="https://cdn.example.org/cv-template.docx">Template</a>'
        b'<a href="/forms.zip">Forms</a>'
    ).ljust(1_000, b" ")
    links = document_links(_Page(body, "https://uni.example.org/msc-ai/"))

    assert links == (
        "https://uni.example.org/docs/checklist.pdf",
        "https://cdn.example.org/cv-template.docx",
        "https://uni.example.org/forms.zip",
    )


def test_a_named_file_is_collected_even_with_an_unknown_suffix():
    """typed-decisions 6.6: a rule may name a template file by name. The
    suffix list cannot be complete -- .odt, .rtf and a bare /download endpoint
    all serve templates -- so a rule's own filename is a second, additive way
    in. Additive: it adds a candidate, it never removes one."""
    body = b'<a href="/files/SI_CV_form">SI CV form</a>'.ljust(1_000, b" ")
    links = document_links(
        _Page(body, "https://si.example.org/apply/"), named_files=("SI_CV_form",)
    )

    assert links == ("https://si.example.org/files/SI_CV_form",)


def test_every_document_suffix_is_lowercase_and_dotted():
    """The comparison is against a casefolded path; a suffix stored without its
    dot would match `report-pdf.html`."""
    assert all(s.startswith(".") and s == s.lower() for s in DOCUMENT_SUFFIXES)


def test_the_result_carries_what_was_searched_not_just_a_label():
    """Spec 7.6: each outcome comes with evidence, never a bare label. A
    `not found` with no record of what was searched is the row a person cannot
    act on and the corpus cannot score."""
    result = SiteJobResult(
        outcome=ProgrammeOutcome.NOT_FOUND,
        stopped_at=Stage.NAVIGATOR,
        leads=(Lead(url="https://uni.example.org/apply/", stage=Stage.MAP),),
        searched={"map": 76, "crawl": 25, "guided_map": 50, "navigator": 4},
        credits={"FIRECRAWL": 31, "SCRAPE_DO": 0},
    )

    assert result.outcome is ProgrammeOutcome.NOT_FOUND
    assert result.searched["map"] == 76
    assert result.leads[0].stage is Stage.MAP


_SLOTS = dict(
    programme="M.Sc. Artificial Intelligence",
    degree_level="master's",
    institution="Friedrich-Alexander-Universität Erlangen-Nürnberg",
    intake_year="2027",
    languages=("German", "English"),
    document_words=("Lebenslauf", "Motivationsschreiben", "CV", "motivation letter"),
    domains=("fau.eu", "daad.de"),
)


def test_the_brief_fills_every_slot():
    brief = navigator_brief(**_SLOTS)

    for value in ("M.Sc. Artificial Intelligence", "2027", "Lebenslauf", "fau.eu", "German"):
        assert value in brief


def test_the_brief_forbids_summarising_the_requirements():
    """Spec 7.4. We read them ourselves, from the origin. A summary is a
    vendor's reading of a page, which is the one thing this whole funnel
    refuses to keep -- and asking for it costs credits Firecrawl bills for."""
    assert "do not summarise" in navigator_brief(**_SLOTS).lower()


def test_the_brief_prefers_the_named_domains_and_rules_out_aggregators():
    brief = navigator_brief(**_SLOTS).lower()

    assert "aggregator" in brief
    assert "news" in brief


def test_the_brief_stays_under_ten_thousand_characters():
    """Firecrawl's documented ceiling for `prompt`. A brief built from a
    programme with sixteen site languages and a long institution name is the
    case that finds it -- and a 400 from the vendor at stage 4 reads as a
    programme whose pages could not be found."""
    long_slots = dict(
        _SLOTS,
        languages=tuple(f"language-{n}" for n in range(40)),
        document_words=tuple(f"word-{n}" * 12 for n in range(200)),
        domains=tuple(f"domain-{n}.example.org" for n in range(200)),
    )

    assert len(navigator_brief(**long_slots)) <= 10_000


def test_the_guided_instruction_is_one_sentence_from_the_same_slots():
    """Spec 7.3a: the same slots as the navigator's brief. Two stages asking
    for different things would make their corpus scores incomparable, which
    is the whole point of scoring each stage by itself."""
    instruction = guided_instruction(**_SLOTS)

    assert instruction.count(".") <= 2
    assert "Lebenslauf" in instruction
    assert "M.Sc. Artificial Intelligence" in instruction
