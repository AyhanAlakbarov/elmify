from apps.dashboard.templatetags.dashboard import coverage_tone, flag, month_year, tone


def test_a_known_country_is_an_image_and_anything_else_is_nothing() -> None:
    html = flag("DE")
    assert '<img class="flag"' in html and "flags/de.svg" in html and 'alt=""' in html
    assert flag("") == ""
    assert flag("ZZ") == ""
    assert flag("../x") == ""


def test_coverage_tone_and_group_tone_are_stable() -> None:
    assert coverage_tone("FULL") == "good"
    assert coverage_tone("partial") == "part"
    assert coverage_tone("") == "unknown"
    assert tone("Chevening") == tone("Chevening")


def test_month_year() -> None:
    assert month_year("2021-09-01") == "Sep 2021"
    assert month_year("2021") == "2021"
    assert month_year(None) == ""
