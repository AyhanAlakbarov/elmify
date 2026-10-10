"""Live checks (spec §11): run by hand with `-m live`, never in CI. Each reads
one real source and asserts its shape, so a publisher's change is caught here
before a register load reads nothing."""

import os

import pytest

from apps.research.egress import fetch_data_file
from apps.research.rdap import load_bootstrap, registration_date
from apps.research.recognition import enic_register_links, parse_register, read_sources

pytestmark = pytest.mark.live


def test_live_the_korean_register_parses_and_lists_kentech() -> None:
    korea = next(source for source in read_sources() if source.slug == "kr_univ_info")
    body = fetch_data_file(korea.data_url, max_bytes=korea.max_bytes, require_https=True).body
    rows = parse_register(body, korea)
    assert len(rows) > 1500
    assert any("kentech.ac.kr" in row.website for row in rows)


def test_live_rdap_gives_esmt_berlins_registration_date() -> None:
    result = registration_date("esmt.berlin", load_bootstrap())
    assert result.status == "ok" and result.registered is not None
    assert result.registered.isoformat() == "2016-06-06"


@pytest.mark.django_db
@pytest.mark.skipif(not os.getenv("FIRECRAWL_API_KEY"), reason="FIRECRAWL_API_KEY not set")
def test_live_enic_naric_still_links_the_ofs_register() -> None:
    from apps.research.fetch import fetch_page

    fetched = fetch_page("https://www.enic-naric.net/page-United-Kingdom", purpose="provenance")
    assert any("officeforstudents.org.uk" in link for link in enic_register_links(fetched.body))
