"""RDAP through IANA's bootstrap, straight to the registry (spec §5.5). It
never blocks, and a registry that gives no date is skipped, never passed."""

from datetime import date

from apps.research.egress import FetchResult, SourceBlocked
from apps.research.rdap import BOOTSTRAP_URL, load_bootstrap, registration_date

#: Subset of data.iana.org/rdap/dns.json (publication 2026-09-16).
BOOTSTRAP = (
    b'{"version": "1.0", "services": ['
    b'[["berlin"], ["https://rdap.nic.berlin/v1/"]],'
    b'[["com", "net"], ["https://rdap.verisign.com/com/v1/"]],'
    b'[["kr", "xn--3e0b707e"], ["https://rdap.nic.or.kr/"]],'
    b'[["uk"], ["https://rdap.nominet.uk/uk/"]],'
    b'[["de"], ["http://rdap.denic.de/", "https://rdap.denic.de/"]]]}'
)
#: rdap.nic.berlin/v1/domain/esmt.berlin, 2026-09-26 (events only).
ESMT = (
    b'{"ldhName": "esmt.berlin", "events": ['
    b'{"eventAction": "registration", "eventDate": "2016-06-06T16:12:51.077302Z"},'
    b'{"eventAction": "last changed", "eventDate": "2024-02-23T12:46:51.339528Z"}]}'
)
#: DENIC answers with a last-changed date only.
DENIC = (
    b'{"ldhName": "tum.de", "events": ['
    b'{"eventAction": "last changed", "eventDate": "2025-01-01T00:00:00Z"}]}'
)


class Files:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies, self.calls = bodies, []

    def __call__(self, url: str, **kwargs: object) -> FetchResult:
        self.calls.append((url, kwargs))
        if url not in self.bodies:
            raise SourceBlocked("source returned HTTP 404")
        return FetchResult(url, (), "application/rdap+json", self.bodies[url])


def test_the_bootstrap_maps_each_tld_to_its_https_registry() -> None:
    table = load_bootstrap(fetch=Files({BOOTSTRAP_URL: BOOTSTRAP}))
    assert table["berlin"] == "https://rdap.nic.berlin/v1/"
    assert table["de"] == "https://rdap.denic.de/"
    assert table["xn--3e0b707e"] == "https://rdap.nic.or.kr/"


def test_a_registration_date_is_read_from_the_registry_itself() -> None:
    table = load_bootstrap(fetch=Files({BOOTSTRAP_URL: BOOTSTRAP}))
    files = Files({"https://rdap.nic.berlin/v1/domain/esmt.berlin": ESMT})
    result = registration_date("esmt.berlin", table, fetch=files)
    assert (result.status, result.registered) == ("ok", date(2016, 6, 6))
    assert files.calls[0][1] == {"require_https": True, "max_bytes": 2 * 1024 * 1024}


def test_a_registry_with_no_registration_date_is_skipped_not_passed() -> None:
    table = load_bootstrap(fetch=Files({BOOTSTRAP_URL: BOOTSTRAP}))
    files = Files({"https://rdap.denic.de/domain/tum.de": DENIC})
    result = registration_date("tum.de", table, fetch=files)
    assert (result.status, result.registered) == ("skipped", None)


def test_ac_uk_is_skipped_without_asking_nominet() -> None:
    files = Files({})
    result = registration_date("ox.ac.uk", {"uk": "https://rdap.nominet.uk/uk/"}, fetch=files)
    assert result.status == "skipped" and files.calls == []


def test_a_tld_with_no_rdap_service_is_skipped() -> None:
    assert registration_date("asoiu.edu.az", {}, fetch=Files({})).status == "skipped"


def test_a_registry_failure_is_failed_never_passed() -> None:
    bootstrap = {"berlin": "https://rdap.nic.berlin/v1/"}
    result = registration_date("esmt.berlin", bootstrap, fetch=Files({}))
    assert result.status == "failed" and "404" in result.detail


def test_an_idn_domain_is_queried_by_its_a_label() -> None:
    table = load_bootstrap(fetch=Files({BOOTSTRAP_URL: BOOTSTRAP}))
    kaist = (
        b'{"ldhName": "kaist.xn--3e0b707e", "events": ['
        b'{"eventAction": "registration", "eventDate": "2001-01-01T00:00:00Z"}]}'
    )
    files = Files({"https://rdap.nic.or.kr/domain/kaist.xn--3e0b707e": kaist})
    result = registration_date("kaist.한국", table, fetch=files)
    assert (result.status, result.registered) == ("ok", date(2001, 1, 1))
    assert files.calls[0][0] == "https://rdap.nic.or.kr/domain/kaist.xn--3e0b707e"


def test_a_domain_that_fails_idna_encoding_is_skipped_without_a_fetch() -> None:
    files = Files({})
    result = registration_date("xn--☃.example", {"example": "https://rdap.example/"}, fetch=files)
    assert result.status == "skipped" and files.calls == []


def test_eventaction_is_matched_case_insensitively() -> None:
    bootstrap = {"berlin": "https://rdap.nic.berlin/v1/"}
    capitalized = (
        b'{"ldhName": "esmt.berlin", "events": ['
        b'{"eventAction": "Registration", "eventDate": "2016-06-06T16:12:51.077302Z"}]}'
    )
    files = Files({"https://rdap.nic.berlin/v1/domain/esmt.berlin": capitalized})
    result = registration_date("esmt.berlin", bootstrap, fetch=files)
    assert (result.status, result.registered) == ("ok", date(2016, 6, 6))


def test_bootstrap_and_registry_fetches_pass_a_tighter_max_bytes() -> None:
    files = Files({BOOTSTRAP_URL: BOOTSTRAP})
    load_bootstrap(fetch=files)
    assert files.calls[0][1]["max_bytes"] == 2 * 1024 * 1024

    table = load_bootstrap(fetch=Files({BOOTSTRAP_URL: BOOTSTRAP}))
    files = Files({"https://rdap.nic.berlin/v1/domain/esmt.berlin": ESMT})
    registration_date("esmt.berlin", table, fetch=files)
    assert files.calls[0][1]["max_bytes"] == 2 * 1024 * 1024
