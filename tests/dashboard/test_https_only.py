import pytest

from apps.dashboard.templatetags.dashboard import https_only


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        " JAVASCRIPT:alert(1)",
        "http://www.tum.de/apply",
        "https://evil.example\\@tum.de/",
        "https://user:secret@tum.de/apply",
        "data:text/html,<script>alert(1)</script>",
        "tum.de/apply",
        "",
        None,
    ],
)
def test_https_only_refuses_everything_but_https(url) -> None:
    assert https_only(url) == ""


def test_https_only_keeps_a_plain_https_link() -> None:
    assert https_only("https://www.tum.de/en/apply?x=1") == "https://www.tum.de/en/apply?x=1"
