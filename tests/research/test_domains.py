from apps.research.domains import AGGREGATOR_DOMAINS, STEERING, is_catalogue


def test_the_probe_aggregators_are_on_the_denylist() -> None:
    """Every one of these was a top-ranked non-answer in the 2026-09-17 probe."""
    for host in (
        "scholars4dev.com",
        "scholarshiproar.com",
        "findamasters.com",
        "educations.com",
        "topuniversities.com",
        "edumap.az",
        "xaricdetehsil.net",
    ):
        assert host in AGGREGATOR_DOMAINS, host
        assert is_catalogue(host), host


def test_the_old_list_is_still_wholly_included() -> None:
    """domains.py has three consumers and the failure mode it exists to
    prevent is a host excluded in one place and trusted in another."""
    from apps.research.domains import CATALOGUE_DOMAINS

    assert set(CATALOGUE_DOMAINS) <= set(AGGREGATOR_DOMAINS)


def test_a_subdomain_of_a_denied_host_is_denied() -> None:
    assert is_catalogue("www.scholars4dev.com")


def test_steering_gives_a_local_language_for_every_launch_corridor() -> None:
    """Spec 5: AZ and TR home-side, DE/NL/SE/FR/HU/IT destination-side."""
    for code in ("AZ", "TR", "DE", "NL", "SE", "FR", "HU", "IT"):
        assert STEERING[code].language, code


def test_steering_carries_no_provider_country_or_language_parameter() -> None:
    """Measured OFF: Brave country (-8 in Indonesia), Brave search_lang
    (inert, Jaccard 1.000), Tavily language (-1.0). The table steers the
    query text we write, never a parameter we send."""
    fields = set(vars(STEERING["TR"]))
    assert fields == {"language", "funder_query", "country_name", "english_second_pass"}


def test_every_steered_country_carries_a_query_in_its_own_language() -> None:
    """Corrected 2026-09-23. The table used to carry only a language NAME,
    which `requests_for` substituted into an English template -- so the
    "local" pass sent English prose mentioning Turkish, the losing half of
    the ablation. The first live TR sweep returned 91% non-Turkish hosts."""
    for code in ("AZ", "TR", "DE", "FR", "IT"):
        assert STEERING[code].funder_query.strip(), code
        assert STEERING[code].country_name.strip(), code
    assert "burs" in STEERING["TR"].funder_query
    assert "Stipendien" in STEERING["DE"].funder_query


def test_hosting_platforms_are_denied_like_aggregators() -> None:
    """Added after the first live TR sweep recorded these as candidate
    funders. A registrable domain here names the landlord, not the
    publisher."""
    for host in ("amazonaws.com", "azureedge.net", "blogspot.com"):
        assert is_catalogue(host), host


def test_a_registry_verified_domain_carries_its_kind_for_free() -> None:
    """The registrar checked before allocating: .edu.tr needs a YÖK-approved
    certificate, .gov.tr a signed application from the body itself. No fetch
    and no model call is needed to know what those hosts are."""
    from apps.research.domains import verified_kind

    assert verified_kind("turkiyeburslari.gov.tr") == "NATIONAL_GOVERNMENT"
    assert verified_kind("itu.edu.tr") == "INSTITUTION"
    assert verified_kind("abertay.ac.uk") == "INSTITUTION"
    assert verified_kind("gov.uk") == "NATIONAL_GOVERNMENT"


def test_a_flat_namespace_yields_nothing_and_that_is_not_a_failure() -> None:
    """DENIC: ".de domains are available to everyone ... whether you are based
    in Germany or abroad." No gov.de, no edu.de. So Germany gets no free
    answers and the classifier does all the work there -- which is most of the
    work, because foundations are swept in every country."""
    from apps.research.domains import verified_kind

    for host in ("bwstiftung.de", "uni-heidelberg.de", "wur.nl", "su.se"):
        assert verified_kind(host) == "", host
    # .org.tr is open -- a documented suffix next to it does not make it one.
    assert verified_kind("elginkanvakfi.org.tr") == ""


def test_email_domain_resolves_an_own_domain_address() -> None:
    from apps.research.domains import email_domain

    assert email_domain("iletisim@1870vakfi.org") == "1870vakfi.org"
    assert email_domain("Vakif1972@VAKIF1972.org.tr") == "vakif1972.org.tr"
    # A mail host under the organisation's domain still names the organisation.
    assert email_domain("burs@mail.tev.org.tr") == "tev.org.tr"


def test_email_domain_refuses_free_mail_and_garbage() -> None:
    """A Gmail address names nobody; a rung-0 hit must never be a mail provider."""
    from apps.research.domains import FREE_MAIL_DOMAINS, email_domain

    for host in ("gmail.com", "hotmail.com", "yahoo.com.tr", "yandex.com", "mynet.com"):
        assert host in FREE_MAIL_DOMAINS, host
        assert email_domain(f"vakif@{host}") == ""
    assert email_domain("") == ""
    assert email_domain("no-at-sign") == ""
    assert email_domain("@nothing.org") == ""
    assert email_domain("x@localhost") == ""


def test_the_denylist_has_no_duplicates() -> None:
    """A duplicate spends one of the 150 slots Tavily gives the prefix."""
    assert len(AGGREGATOR_DOMAINS) == len(set(AGGREGATOR_DOMAINS))


def test_tavilys_prefix_keeps_every_host_that_is_not_country_scoped() -> None:
    """Tavily takes the first 150, on name lookups with no country. The cut may
    fall only on single-country listings and national catalogues; a probe
    aggregator or a many-country listing past it fails here, not in a year."""
    from apps.research import domains

    wide = {*domains._ROUTING, *domains._PROBE_AGGREGATORS, *domains._SWEEP_AGGREGATORS}
    assert wide <= set(AGGREGATOR_DOMAINS[:150])


def test_the_catalogue_list_fits_tavilys_cap_whole() -> None:
    """search.SearchSource sends CATALOGUE_DOMAINS to Tavily unsliced."""
    from apps.research.domains import CATALOGUE_DOMAINS

    assert len(CATALOGUE_DOMAINS) <= 150


def test_an_official_national_catalogue_is_a_hoppable_catalogue() -> None:
    """Study in Holland routes to the university; it never speaks for it."""
    from apps.research.domains import is_hoppable_catalogue

    for host in ("www.studyinnl.org", "studyinjapan.go.jp", "www.educanada.ca"):
        assert is_catalogue(host), host
        assert is_hoppable_catalogue(host), host
    assert is_catalogue("www.ucas.com")
    assert not is_hoppable_catalogue("www.ucas.com")
