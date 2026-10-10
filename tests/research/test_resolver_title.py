"""Rung 3: the homepage must name the same KIND of organisation and carry the name.

4.13a, rule B.
"""

from apps.research.names import profile
from apps.research.resolver import page_titles, title_agrees
from tests.research.test_names import vocab


def _html(title: str, site_name: str = "") -> bytes:
    meta = f'<meta property="og:site_name" content="{site_name}">' if site_name else ""
    return f"<html><head><title>{title}</title>{meta}</head><body>x</body></html>".encode()


def _agrees(name: str, body: bytes) -> bool:
    v = vocab()
    return title_agrees(profile([name], v), page_titles(body), v)


def test_the_right_site_names_its_kind_and_itself() -> None:
    assert _agrees("Hrant Dink Vakfı", _html("Anasayfa - Hrant Dink Vakfı"))
    assert _agrees("İnönü Vakfı", _html("İnönü Vakfı, İsmet İnönü …"))


def test_an_adjacent_organisation_of_another_kind_is_refused() -> None:
    assert not _agrees("Kanserle Savaş Vakfı", _html("Kanser Savaşçıları Derneği"))
    assert not _agrees("İnönü Vakfı", _html("İnönü Üniversitesi"))
    assert not _agrees("Carl-Zeiss-Stiftung", _html("Solutions to shape the future | ZEISS"))


def test_og_site_name_counts_and_a_page_without_either_says_nothing() -> None:
    assert _agrees("Hrant Dink Vakfı", _html("Home", site_name="Hrant Dink Vakfı"))
    assert page_titles(b"") == ()
    assert page_titles(b"<html><body>no head</body></html>") == ()


def test_a_title_in_the_page_s_own_legacy_charset_still_names_its_kind() -> None:
    body = ('<html><head><meta charset="windows-1254"><title>Hrant Dink Vakfı'
            "</title></head></html>").encode("cp1254")
    assert page_titles(body) == ("Hrant Dink Vakfı",)
    xhtml = ('<?xml version="1.0" encoding="utf-8"?><html><head><title>Hrant Dink Vakfı'
             "</title></head></html>").encode()
    assert page_titles(xhtml) == ("Hrant Dink Vakfı",)
