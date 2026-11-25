import json
import pathlib

import pytest

from apps.documents.evidence.publication import (
    ChimericPublicationError,
    PublicationNotFound,
    _surname,
    author_in_byline,
    fetch_publication,
    source_labels,
    title_matches,
    verify_publication,
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
                status, body = response
                return status, body, {}
        return 404, {}, {}


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


def test_turkic_and_azerbaijani_surname_normalization_and_byline_matching():
    assert _surname("Orkhan Əliyev") == "eliyev"
    assert _surname("Mehmet Işıklı") == "isikli"
    assert _surname("İbrahim Öztürk") == "ozturk"
    assert _surname("Şahin, Çağrı") == "sahin"
    assert _surname("Иван Петров") == "petrov"
    assert _surname("Орхан Алиев") == "aliev"

    byline = (
        "Orkhan Aliyev",
        "Mehmet Isikli",
        "Ivan Petrov",
        "Orkhan Guliyev",
        "Farid Jafarov",
        "Juergen Mueller",
        "Carles Bo",
    )
    assert author_in_byline("Orkhan Əliyev", byline)
    assert author_in_byline("Orkhan Eliyev", byline)
    assert author_in_byline("Орхан Алиев", byline)
    assert author_in_byline("Иван Петров", byline)
    assert author_in_byline("Mehmet Işıklı", byline)
    assert author_in_byline("Orxan Quliyev", byline)
    assert author_in_byline("Fərid Cəfərov", byline)
    assert author_in_byline("Jürgen Müller", byline)
    assert not author_in_byline("Nigar Məmmədova", byline)


def test_title_matches_handles_word_reordering_and_colon_subtitles():
    assert title_matches(
        "Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles",
        "Microkinetic assessment of ligand exchanging catalytic cycles",
    )
    assert title_matches(
        "Catalysis Series: Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles",
        "Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles",
    )
    assert title_matches(
        "Über die Quantentheorie der Moleküle",
        "Ueber die Quantentheorie der Molekuele",
    )
    assert title_matches(
        "Математическое моделирование каталитических процессов",
        "Математическое моделирование каталитических процессов",
    )
    assert not title_matches(
        "Математическое моделирование каталитических процессов",
        "Квантовая теория сверхпроводимости в графене",
    )
    assert not title_matches(
        "Deep Reinforcement Learning for Quadruped Locomotion",
        "Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles",
    )


def test_chimeric_doi_rejection_on_title_author_or_year_mismatch():
    transport = _crossref_transport()
    # Matching claims pass cleanly, including Azerbaijani/Turkish diacritics
    rec = fetch_publication(
        DoiRef("10.1021/acscatal.5c00348"),
        transport=transport,
        claimed_title="Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles",
        claimed_author="Orkhan Abdullayev",
        claimed_year=2025,
    )
    assert rec.doi == "10.1021/acscatal.5c00348"

    # Real DOI paired with a different title -> ChimericPublicationError
    with pytest.raises(ChimericPublicationError, match="title"):
        fetch_publication(
            DoiRef("10.1021/acscatal.5c00348"),
            transport=transport,
            claimed_title="Quantum Hall Effect in Graphene Nanoribbons",
        )

    # Real DOI paired with an author not in the byline -> ChimericPublicationError
    with pytest.raises(ChimericPublicationError, match="byline"):
        fetch_publication(
            DoiRef("10.1021/acscatal.5c00348"),
            transport=transport,
            claimed_author="Farid Əliyev",
        )

    # Real DOI paired with a year > 1 year off -> ChimericPublicationError
    with pytest.raises(ChimericPublicationError, match="published in"):
        fetch_publication(
            DoiRef("10.1021/acscatal.5c00348"),
            transport=transport,
            claimed_year=2019,
        )

    check_bad_author = verify_publication(
        DoiRef("10.1021/acscatal.5c00348"),
        claimed_title="Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles",
        student_name="Mehmet Işıklı",
        transport=transport,
    )
    assert check_bad_author.chimeric is True
    assert check_bad_author.status == "chimeric"
    assert check_bad_author.title_match is True
    assert check_bad_author.author_match is False


def test_retraction_and_expression_of_concern_detection_plus_venue_hygiene():
    crossref_retracted = {
        "message": {
            "title": ["Fabricated Superconductivity at Room Temperature"],
            "type": "journal-article",
            "issued": {"date-parts": [[2024]]},
            "author": [{"given": "Ranga", "family": "Dias"}],
            "updated-by": [{"type": "retraction", "DOI": "10.1038/retraction.1"}],
            "update-to": [{"type": "expression-of-concern", "DOI": "10.1038/eoc.1"}],
        }
    }
    transport = FakeTransport(
        {"https://api.crossref.org/works/": (200, crossref_retracted)}
    )
    rec = fetch_publication(DoiRef("10.1038/retracted.2024"), transport=transport)
    assert rec.is_retracted is True
    assert "expression_of_concern" in rec.update_notes

    check = verify_publication(
        DoiRef("10.1038/retracted.2024"),
        claimed_title="Fabricated Superconductivity at Room Temperature",
        student_name="Ranga Dias",
        transport=transport,
    )
    assert check.retracted is True
    assert check.status == "retracted"

    oa_gray = {
        "doi": "https://doi.org/10.9999/gray.2025",
        "title": "Catalytic Activity of Modified Zeolites",
        "publication_year": 2025,
        "type": "article",
        "is_retracted": False,
        "primary_location": {
            "source": {
                "display_name": "International Journal of Rapid Science",
                "is_in_doaj": False,
                "is_core": False,
            }
        },
        "biblio": {},
        "authorships": [{"author": {"display_name": "Orkhan Əliyev"}}],
    }
    oa_transport = FakeTransport({"https://api.openalex.org/works/": (200, oa_gray)})
    oa_rec = fetch_publication(DoiRef("10.9999/gray.2025"), transport=oa_transport)
    assert oa_rec.in_doaj is False
    assert oa_rec.is_core is False
    assert "not in DOAJ or CORE" in source_labels(oa_rec)


def test_preprint_is_promoted_to_published_journal_doi_via_is_preprint_of():
    preprint_body = {
        "message": {
            "title": ["Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles"],
            "type": "posted-content",
            "issued": {"date-parts": [[2024]]},
            "author": [{"given": "Orkhan", "family": "Abdullayev"}],
            "relation": {
                "is-preprint-of": [
                    {"id-type": "doi", "id": "https://doi.org/10.1021/acscatal.5c00348"}
                ]
            },
        }
    }
    journal_body = json.loads((FIXTURES / "crossref_acscatal.json").read_text())
    transport = FakeTransport(
        {
            "https://api.crossref.org/works/10.26434/chemrxiv-2024-xyz": (200, preprint_body),
            "https://api.crossref.org/works/10.1021/acscatal.5c00348": (200, journal_body),
        }
    )
    record = fetch_publication(
        DoiRef("10.26434/chemrxiv-2024-xyz"), transport=transport
    )
    assert record.doi == "10.1021/acscatal.5c00348"
    assert record.published_doi == "10.1021/acscatal.5c00348"
    assert record.has_preprint == "10.26434/chemrxiv-2024-xyz"
    assert record.work_type == "journal-article"
    assert record.venue == "ACS Catalysis"


def test_arxiv_and_datacite_handle_fallbacks():
    atom_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry>"
        "<id>http://arxiv.org/abs/2501.12345v1</id>"
        "<published>2025-01-15T00:00:00Z</published>"
        "<title>Equivariant Message Passing for Catalytic Transition States</title>"
        "<author><name>Orkhan Əliyev</name></author>"
        "<author><name>Mehmet Işıklı</name></author>"
        "</entry>"
        "</feed>"
    )
    transport = FakeTransport(
        {
            "https://export.arxiv.org/api/query?id_list=2501.12345": (
                200,
                {"xml": atom_xml},
            ),
            "https://doi.org/api/handles/10.5281/zenodo.999999": (
                200,
                {"responseCode": 1, "handle": "10.5281/zenodo.999999"},
            ),
        }
    )
    arxiv_rec = fetch_publication(
        DoiRef("10.48550/arXiv.2501.12345"),
        transport=transport,
        claimed_author="Orkhan Aliyev",
    )
    assert arxiv_rec.venue == "arXiv"
    assert arxiv_rec.year == 2025
    assert arxiv_rec.is_preprint is True

    handle_check = verify_publication(
        DoiRef("10.5281/zenodo.999999"),
        claimed_title="Dataset for Catalytic Cycles",
        transport=transport,
    )
    assert handle_check.status == "handle_only"
    assert handle_check.sources == ["handle"]
