import pytest

from apps.research.egress import SourceBlocked
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.tavily import tavily_guided_map


def _post(payload_out, *, sink=None):
    def post(url, *, payload, headers, read_timeout=None):
        if sink is not None:
            sink.append((url, payload, headers, read_timeout))
        return payload_out

    return post


def test_only_urls_are_kept_from_the_response():
    """CLAUDE.md, the search-provider rule: a provider is a POINTER. Nothing
    from the response object is persisted, and the shape of this function is
    what makes that true by construction rather than by discipline -- there is
    no field on SiteSearchResult a snippet could land in."""
    sink = []
    result = tavily_guided_map(
        url="https://uni.example.org/msc-ai/",
        instructions="Find the application documents page.",
        select_domains=("uni.example.org",),
        api_key="k",
        post=_post(
            {
                "results": [
                    "https://uni.example.org/apply/documents/",
                    "https://uni.example.org/apply/checklist.pdf",
                ],
                "response_time": 3.1,
            },
            sink=sink,
        ),
    )

    assert result.urls == (
        "https://uni.example.org/apply/documents/",
        "https://uni.example.org/apply/checklist.pdf",
    )
    assert result.provider == "tavily-map"
    _url, payload, _headers, _read_timeout = sink[0]
    assert payload["instructions"].startswith("Find the application")


def test_a_url_off_the_selected_domains_is_dropped():
    """`allow_external` defaults to TRUE on Tavily's /map. A stage that
    returned an off-site URL would hand the funnel a lead that
    require_origin then refuses -- one wasted ladder walk per stray URL, and
    an aggregator page counted as a programme's own."""
    result = tavily_guided_map(
        url="https://uni.example.org/msc-ai/",
        instructions="Find the application documents page.",
        select_domains=("uni.example.org",),
        api_key="k",
        post=_post(
            {
                "results": [
                    "https://uni.example.org/apply/",
                    "https://scholarship-aggregator.example.com/uni-example",
                ]
            }
        ),
    )

    assert result.urls == ("https://uni.example.org/apply/",)


def test_a_subdomain_of_a_selected_domain_is_kept():
    """admissions.* and apply.* are where the documents list usually lives."""
    result = tavily_guided_map(
        url="https://uni.example.org/msc-ai/",
        instructions="Find the application documents page.",
        select_domains=("uni.example.org",),
        api_key="k",
        post=_post({"results": ["https://admissions.uni.example.org/documents/"]}),
    )

    assert result.urls == ("https://admissions.uni.example.org/documents/",)


def test_the_billed_cost_follows_tavily_s_published_tariff():
    """2 credits per ten successful pages WITH instructions (1 without),
    $0.008 a credit. The number is what makes this stage comparable with
    /agent's 20-40 cents in the corpus's scoring; a stage whose price is a
    guess cannot be scored against one whose price is known."""
    result = tavily_guided_map(
        url="https://uni.example.org/",
        instructions="Find the application documents page.",
        select_domains=("uni.example.org",),
        api_key="k",
        post=_post({"results": [f"https://uni.example.org/p{n}/" for n in range(25)]}),
    )

    assert result.cost_usd == pytest.approx(3 * 2 * 0.008)


def test_the_billed_cost_counts_the_raw_response_not_the_filtered_urls():
    """Tavily bills per successful page MAPPED, before our domain filter. The
    old code counted the post-filter list, which UNDER-reports spend on a
    page that returned aggregator noise alongside the real URLs: 25 raw
    results filtered down to 5 must still bill 3 tens, not 1."""
    result = tavily_guided_map(
        url="https://uni.example.org/",
        instructions="Find the application documents page.",
        select_domains=("uni.example.org",),
        api_key="k",
        post=_post(
            {
                "results": (
                    [f"https://uni.example.org/p{n}/" for n in range(5)]
                    + [f"https://scholarship-aggregator.example.com/x{n}" for n in range(20)]
                )
            }
        ),
    )

    assert len(result.urls) == 5
    assert result.cost_usd == pytest.approx(3 * 2 * 0.008)


def test_the_limit_comes_from_the_setting(settings):
    settings.FETCH_GUIDED_MAP_LIMIT = 30
    sink = []
    tavily_guided_map(
        url="https://uni.example.org/",
        instructions="Find the application documents page.",
        select_domains=("uni.example.org",),
        api_key="k",
        post=_post({"results": []}, sink=sink),
    )

    assert sink[0][1]["limit"] == 30


def test_a_missing_key_raises():
    with pytest.raises(ProviderUnavailable, match="SEARCH_API_KEY"):
        tavily_guided_map(
            url="https://uni.example.org/",
            instructions="Find it.",
            select_domains=("uni.example.org",),
            api_key="",
            post=_post({"results": []}),
        )


def test_a_transport_failure_is_a_provider_failure_not_an_empty_site():
    """`fetch_json_api` (the default `post`) raises SourceBlocked for every
    real transport/vendor failure -- a timeout, a 5xx, a dropped connection.
    That is what a real vendor outage looks like from this function."""

    def broken(url, *, payload, headers, read_timeout=None):
        raise SourceBlocked("read timed out")

    with pytest.raises(ProviderUnavailable):
        tavily_guided_map(
            url="https://uni.example.org/",
            instructions="Find it.",
            select_domains=("uni.example.org",),
            api_key="k",
            post=broken,
        )


def test_a_programming_error_is_not_laundered_into_a_provider_outage():
    """The mistake `site._call` is deliberately narrowed against: a bare
    `except Exception` would turn our own TypeError into 'vendor outage' and
    hide the defect. `tavily_guided_map` must only catch SourceBlocked."""

    def broken(url, *, payload, headers, read_timeout=None):
        raise TypeError("a bug in this module, not the vendor")

    with pytest.raises(TypeError):
        tavily_guided_map(
            url="https://uni.example.org/",
            instructions="Find it.",
            select_domains=("uni.example.org",),
            api_key="k",
            post=broken,
        )


def test_the_read_timeout_matches_the_server_side_crawl_not_the_egress_default():
    """search.py's tavily_crawl comment: the 20s egress default is tuned for
    one page and 'killed the first vendor pass on programme 2'. A
    limit=50, max_depth=2 guided walk is server-side and the same shape."""
    from apps.research.search import _CRAWL_READ_TIMEOUT

    sink = []
    tavily_guided_map(
        url="https://uni.example.org/",
        instructions="Find the application documents page.",
        select_domains=("uni.example.org",),
        api_key="k",
        post=_post({"results": []}, sink=sink),
    )

    assert sink[0][3] == _CRAWL_READ_TIMEOUT == 120.0
