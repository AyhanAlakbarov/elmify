import json
import pathlib

import pytest

from apps.documents.evidence.publication import (
    PublicationNotFound,
    fetch_publication,
)
from apps.documents.evidence.sources import DoiRef

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class FakeTransport:
    """Records every URL asked for, so a test can assert we never talk to a
    host we did not intend to."""

    def __init__(self, responses):
        self._responses = responses
        self.seen: list[str] = []

    def get_json(self, url, *, headers=None):
        self.seen.append(url)
        for prefix, response in self._responses.items():
            if url.startswith(prefix):
                return response
        return 404, {}


def _crossref_transport():
    body = json.loads((FIXTURES / "crossref_acscatal.json").read_text())
    return FakeTransport({"https://api.crossref.org/works/": (200, body)})


def test_a_doi_becomes_a_complete_publication_record():
    record = fetch_publication(
        DoiRef("10.1021/acscatal.5c00348"), transport=_crossref_transport()
    )
    assert record.title == "Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles"
    assert record.venue == "ACS Catalysis"
    assert record.year == 2025
    assert record.volume == "15"
    assert record.issue == "6"
    assert record.pages == "4739-4745"
    assert record.work_type == "journal-article"


def test_authors_keep_their_byline_order():
    """Order is a claim. PublicationEntry.self_author_index indexes into this
    list, so reordering it would point at the wrong person."""
    record = fetch_publication(
        DoiRef("10.1021/acscatal.5c00348"), transport=_crossref_transport()
    )
    assert record.authors == (
        "Orkhan Abdullayev",
        "Diego Garay-Ruiz",
        "Berta Bori-Bru",
        "Carles Bo",
    )


def test_we_only_ever_talk_to_the_hosts_we_intend():
    transport = _crossref_transport()
    fetch_publication(DoiRef("10.1021/acscatal.5c00348"), transport=transport)
    for url in transport.seen:
        assert url.startswith("https://api.crossref.org/") or url.startswith(
            "https://api.openalex.org/"
        )


def test_a_doi_crossref_does_not_have_falls_back_to_openalex():
    openalex_body = {
        "doi": "https://doi.org/10.9999/conf.2023.1",
        "title": "Spectral Analysis of Stars",
        "publication_year": 2023,
        "type": "article",
        "primary_location": {"source": {"display_name": "IAC Proceedings"}},
        "biblio": {"volume": None, "issue": None, "first_page": None, "last_page": None},
        "authorships": [
            {"author": {"display_name": "Orkhan Abdullayev"}},
            {"author": {"display_name": "Nihat Abdullayev"}},
        ],
    }
    transport = FakeTransport({"https://api.openalex.org/works/": (200, openalex_body)})
    record = fetch_publication(DoiRef("10.9999/conf.2023.1"), transport=transport)
    assert record.title == "Spectral Analysis of Stars"
    assert record.venue == "IAC Proceedings"
    assert record.authors == ("Orkhan Abdullayev", "Nihat Abdullayev")


def test_a_doi_neither_registry_has_raises():
    transport = FakeTransport({})
    with pytest.raises(PublicationNotFound):
        fetch_publication(DoiRef("10.9999/nope.1"), transport=transport)


def test_a_record_with_no_authors_is_not_a_record():
    """An error never produces a partial fact. A publication whose byline we
    cannot read cannot support an authorship claim, so it is not returned as a
    usable record."""
    body = {"message": {"title": ["Untitled"], "type": "journal-article", "author": []}}
    transport = FakeTransport({"https://api.crossref.org/works/": (200, body)})
    with pytest.raises(PublicationNotFound):
        fetch_publication(DoiRef("10.1234/empty.1"), transport=transport)


def test_a_crossref_author_with_neither_given_nor_family_is_not_a_byline():
    """`("", "", "").strip()` for an author with no given/family name yields
    the non-empty string "" -- `authors = ("",)` -- which used to slip past
    `not authors` (a non-empty tuple is truthy) and let write_publication_fact
    write it at AUTHORITATIVE_DOCUMENT, auto-confirmed, for self_author_index
    to point into. any(authors) is what actually checks the byline has a
    usable name in it, the same check _from_openalex already applies."""
    body = {
        "message": {
            "title": ["Untitled"],
            "type": "journal-article",
            "author": [{}],
        }
    }
    transport = FakeTransport({"https://api.crossref.org/works/": (200, body)})
    with pytest.raises(PublicationNotFound):
        fetch_publication(DoiRef("10.1234/blank-author.1"), transport=transport)
