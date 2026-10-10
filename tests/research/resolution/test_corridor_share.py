"""The per-corridor share waiting on a person (spec 11), as the queue alone knows it.

The numerator is the queue; the denominator is the catalogue, which only the
engine can read (brief D3), so the console gets "not computed", never a 0.
"""

import pytest

from apps.research.models import ResolutionItem
from apps.research.resolution.priority import corridor_lines, corridor_share
from apps.research.resolution.writers import file_item

pytestmark = pytest.mark.django_db


def _host(host: str, country: str, state: str = "OPEN") -> None:
    item = file_item("HOST_UNREACHABLE", f"host:{host}",
                     {"host": host, "url": f"https://{host}/", "trail": []},
                     country_code=country)
    if state == "PARKED":
        ResolutionItem.objects.filter(id=item.id).update(state=state)


def test_waiting_is_counted_per_country_with_unknown_as_blank() -> None:
    _host("a.edu.tr", "TR")
    _host("b.edu.tr", "TR", state="PARKED")
    _host("c.de", "DE")
    _host("d.org", "")
    assert corridor_share() == {"": (1, None), "DE": (1, None), "TR": (2, None)}
    assert corridor_share(known={"TR": 200, "DE": 0, "": 5}.__getitem__) == {
        "": (1, 5), "DE": (1, 0), "TR": (2, 200),
    }


def test_the_lines_say_what_they_could_not_compute_and_that_they_are_a_snapshot() -> None:
    assert corridor_lines({"TR": (12, 1417)}) == [
        "TR: 12 waiting / 1,417 known (0.8%) (snapshot, not a rate)"
    ]
    assert corridor_lines({"TR": (12, None), "": (1, 0)}) == [
        "TR: 12 waiting / known: not computed on the web tier (snapshot, not a rate)",
        "??: 1 waiting / 0 known (n/a) (snapshot, not a rate)",
    ]
