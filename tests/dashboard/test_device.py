import pytest

from apps.dashboard.device import INSTALL, OTHER_BROWSER, PHONE, apply_blocker
from apps.dashboard.needs import EXTENSION_URL

CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"  # noqa: E501
EDGE = CHROME + " Edg/129.0"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
ANDROID = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/129.0 Mobile Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"


@pytest.mark.parametrize(
    ("agent", "paired", "text"),
    [
        (CHROME, True, None),
        (EDGE, True, None),
        (CHROME, False, INSTALL),
        (FIREFOX, True, OTHER_BROWSER),
        ("", True, OTHER_BROWSER),
        (ANDROID, True, PHONE),
        (IPHONE, False, PHONE),
    ],
)
def test_apply_needs_the_extension_on_a_computer(agent, paired, text) -> None:
    blocker = apply_blocker(agent, paired=paired)
    assert (blocker.text if blocker else None) == text


def test_install_links_the_extension_settings() -> None:
    blocker = apply_blocker(CHROME, paired=False)
    assert blocker is not None and blocker.url == EXTENSION_URL
