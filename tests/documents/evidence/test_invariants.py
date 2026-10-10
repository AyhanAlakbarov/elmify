"""Structural invariants for apps/documents/evidence, checked by parsing the
source rather than importing it -- these must hold even for a module that
would fail to import (e.g. because it reaches for a database at import time).
"""

import ast
import pathlib

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parents[3] / "apps" / "documents" / "evidence"

#: The dotted module path of the package itself, used to resolve relative
#: imports (`from ..models import X`) to an absolute module path. Every file
#: directly inside PACKAGE -- __init__.py included -- has this as its
#: `__package__`, so the same base works for all of them.
_PACKAGE_DOTTED = "apps.documents.evidence"


def _imports(path):
    """Yield every module name a file imports, as an absolute dotted path.

    `ast.ImportFrom.module` is None or relative-looking for `from . import x`
    / `from ..models import x`; taking it at face value (as the brief's first
    draft did) yields the bare string "models" for `from ..models import X`,
    which no forbidden-import check ever matches. `node.level` (the number of
    leading dots) is what makes resolution possible, so we use it.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = _PACKAGE_DOTTED.split(".")
                base_parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join(base_parts)
                yield f"{base}.{node.module}" if node.module else base
            elif node.module:
                yield node.module


@pytest.mark.parametrize(
    "module",
    sorted(p.name for p in PACKAGE.glob("*.py") if p.name != "facts.py"),
)
def test_only_facts_imports_django_models(module):
    """The interesting logic must be testable without a database. If a fetcher
    starts writing rows, the parsing and gating logic stops being pure and the
    exhaustive tests that protect against fabricated claims get slower and
    weaker.

    Exemptions, and why each is safe:
    - facts.py is excluded from this parametrize entirely: it is the only
      module that WRITES to the ledger, so it is expected to import Django
      models and django.db.
    - intake.py stays IN the parametrize, but is exempted from the `.models`
      check only, one line below. It imports VerifiedFact, DocumentVersion
      and Membership for type annotations only and writes nothing itself --
      a property the Task 7 review verified by grepping the module for
      `.objects.` and `.save(` and finding neither, and which stays true here
      (see test_intake_writes_nothing_itself below). The django.db check
      still applies to it: nothing documents or justifies intake.py reaching
      for the database, so if it ever does, this must fail.

    The rule is deliberately wider than "apps.documents.models": Django models
    in this repo live in several apps (apps.documents.models,
    apps.concierge.models, apps.tenancy.models, ...), and a check that only
    named one of them would miss the other two entirely.
    """
    for name in _imports(PACKAGE / module):
        if module != "intake.py":
            assert not name.endswith(".models"), (
                f"{module} imports a Django models module ({name}); only facts.py may"
            )
        assert name != "django.db", f"{module} imports django.db; only facts.py may"


def test_intake_writes_nothing_itself():
    """intake.py is exempted above because it imports models for type
    annotations only. Pin that with the same grep the Task 7 review used, so
    the exemption cannot silently go stale if a write is added later.
    .delete( and .update( are the other two ORM write verbs -- a queryset
    .update() or .delete() call needs neither .objects. nor .save() to reach
    the database, so the original two-string grep would miss either."""
    text = (PACKAGE / "intake.py").read_text()
    assert ".objects." not in text
    assert ".save(" not in text
    assert ".delete(" not in text
    assert ".update(" not in text


def test_no_module_imports_a_view_form_or_template():
    """The interaction surface is out of scope. IntakeResult carries a
    question; nothing here renders one."""
    for path in PACKAGE.glob("*.py"):
        for name in _imports(path):
            assert "views" not in name, f"{path.name} imports a view"
            assert "forms" not in name, f"{path.name} imports a form"
            assert "template" not in name, f"{path.name} imports templating"


def test_sources_reaches_no_network_module():
    """The trust boundary must not be able to fetch. If it can, a future edit
    can fetch before validating."""
    for name in _imports(PACKAGE / "sources.py"):
        assert name not in {"urllib3", "requests", "httpx"}
        assert not name.endswith(".transport")
