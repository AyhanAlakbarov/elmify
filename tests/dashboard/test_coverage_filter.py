"""What the scholarship banner says about tuition and living costs."""

import pytest

from apps.dashboard.templatetags.dashboard import coverage


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("FULL", "Fully covered"),
        ("PARTIAL", "Partly covered"),
        ("NONE", "Not covered"),
        ("UNSTATED", "Not stated"),
        ("", "Not stated"),
        (None, "Not stated"),
        ("SOMETHING_NEW", "Something new"),
    ],
)
def test_coverage_reads_like_a_sentence(raw, shown):
    assert coverage(raw) == shown
