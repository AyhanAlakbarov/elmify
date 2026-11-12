"""The four-language wording sheet (plan 6, T8). Reads the BUILT extension: under
CI a missing dist/i18n.json is a failure, not a skip (as bundle_text)."""

import json
import os
import pathlib
from io import StringIO

import pytest
from django.core.management.base import CommandError

from apps.portals.management.commands import portal_bench
from apps.portals.models import PageRecord, PortalForm

DIST = pathlib.Path(__file__).resolve().parents[2] / "extension" / "dist"


def _catalogue() -> dict[str, dict[str, str]]:
    path = DIST / "i18n.json"
    if not path.exists():
        message = "extension/dist is missing -- npm --prefix extension run build"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    loaded: dict[str, dict[str, str]] = json.loads(path.read_text())
    return loaded


def test_every_message_and_mark_exists_in_all_four_languages() -> None:
    catalogue = _catalogue()
    assert set(catalogue) == {"az", "tr", "ru", "en"}
    keys = set(catalogue["en"])
    assert {"mark_filled", "mark_fromAnswer", "mark_answer", "r_our_guess"} <= keys
    for lang, messages in catalogue.items():
        assert set(messages) == keys, f"{lang} misses {keys - set(messages)}"
        assert all(text.strip() for text in messages.values()), lang


@pytest.mark.django_db
def test_the_sheet_links_each_recorded_page_to_a_local_copy(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _catalogue()
    form = PortalForm.objects.create(portal_host="portal.example", form_key="apply")
    PageRecord.objects.create(
        portal_form=form, source=PageRecord.Source.BENCH_WALK, page_kind="FORM", step=1,
        snapshot={"page_url": "https://portal.example/apply",
                  "controls": [{"selector": "#a", "tag": "input", "label": "Given name <b>"}]},
        html_key="k1",
    )
    store = type("Store", (), {"get": lambda self, key: b"<p>saved</p>"})()
    monkeypatch.setattr(portal_bench.bench, "_store", lambda: store)
    command = portal_bench.Command()
    command.stdout = StringIO()
    command._wording(form, tmp_path / "wording.html")
    sheet = (tmp_path / "wording.html").read_text()
    assert "page-1.html" in sheet and "Given name &lt;b&gt;" in sheet
    assert "portal.example" not in sheet
    copy = (tmp_path / "page-1.html").read_bytes()
    assert copy.endswith(b"<p>saved</p>")
    # Opened from disk there is no server to send the replay's CSP: the copy
    # carries it, so nothing on the portal's page runs on the operator's machine.
    assert copy.startswith(b'<!doctype html><meta http-equiv="Content-Security-Policy"')
    assert b"script-src 'none'" in copy
    assert "file://" in command.stdout.getvalue()


def test_wording_is_in_the_mutually_exclusive_group() -> None:
    parser = portal_bench.Command().create_parser("manage.py", "portal_bench")
    with pytest.raises(CommandError):
        parser.parse_args(["--operator", "a@b.c", "--wording", "x.html", "--queue"])


def test_the_expiry_line_names_an_id_document_not_a_passport() -> None:
    """Final review M4: expired_id_document counts ID cards too, so the line cannot say
    passport. The date placeholder stays, in every language."""
    catalogue = _catalogue()
    for lang, word in (("en", "passport"), ("az", "pasport"), ("tr", "pasaport"),
                       ("ru", "паспорт")):
        line = catalogue[lang]["r_document_expired"]
        assert "{date}" in line and word not in line.lower(), (lang, line)
    assert "ID document" in catalogue["en"]["r_document_expired"]


def test_a_refused_tap_falls_back_to_the_plain_message_before_the_generic_failure() -> None:
    """Final review 2, m1: pairing_required (and the other account codes) already have
    an m_<code> message; the panel must say it, not 'try again'."""
    source = (DIST.parent / "src" / "panel" / "panel.ts").read_text()
    assert source.index("m_offer_${code}") < source.index("has(`m_${code}`)") < source.index(
        '"offer_request_failed",')
    assert "m_pairing_required" in _catalogue()["en"]
