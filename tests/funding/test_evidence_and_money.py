"""Evidence row and money figure partials. Db-free."""

from apps.funding.models import EvidenceClaim


def test_source_domain_is_the_hostname():
    claim = EvidenceClaim(source_url="https://www.daad.de/en/scholarships/epos/")
    assert claim.source_domain == "www.daad.de"


def test_source_domain_falls_back_to_raw_value():
    assert EvidenceClaim(source_url="not-a-url").source_domain == "not-a-url"
