"""config/settings/base.py::_providers -- fix round 1, finding 2.

A tiny module-level helper, tested directly rather than through Django's
settings machinery (mirrors tests/tenancy/test_database_settings.py's
database_config, the existing precedent for this shape).
"""

from __future__ import annotations

from config.settings.base import _providers


def test_a_stray_space_after_the_comma_still_matches_a_provider() -> None:
    assert _providers("MICROSOFT, GOOGLE") == ("MICROSOFT", "GOOGLE")


def test_a_lowercase_provider_name_still_matches() -> None:
    assert _providers("microsoft") == ("MICROSOFT",)


def test_an_empty_item_is_dropped_not_kept_as_a_provider_string() -> None:
    assert _providers("MICROSOFT,,GOOGLE,") == ("MICROSOFT", "GOOGLE")
