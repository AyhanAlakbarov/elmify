"""Every {% static %} path names a file collectstatic will collect.

Production's CompressedManifestStaticFilesStorage raises on a path missing from
the manifest; test settings use StaticFilesStorage, which never does. This is
the check that runs in the suite (CLAUDE.md, "Static files").
"""

import re
from pathlib import Path

from django.contrib.staticfiles import finders

#: No trailing ``%}``: ``{% static "x" as v %}`` names a file too.
_STATIC = re.compile(r"""{%\s*static\s+['"]([^'"]+)['"]""")
ROOT = Path(__file__).resolve().parents[1]


def test_every_static_reference_names_a_file_collectstatic_will_find() -> None:
    templates = [*ROOT.glob("templates/**/*.html"), *ROOT.glob("apps/*/templates/**/*.html")]
    missing = sorted(
        {
            path
            for template in templates
            for path in _STATIC.findall(template.read_text(encoding="utf-8"))
            if finders.find(path) is None
        }
    )
    assert missing == []


def test_the_pattern_finds_a_reference() -> None:
    assert _STATIC.findall("{% static 'dashboard/documents.js' %}") == ["dashboard/documents.js"]


def test_the_pattern_finds_the_as_form() -> None:
    assert _STATIC.findall('{% static "dashboard/documents.js" as script %}') == [
        "dashboard/documents.js"
    ]
