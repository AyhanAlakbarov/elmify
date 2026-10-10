import sys

from apps.documents.evidence.signals import (
    MANIFEST_FILES,
    directory_names,
    file_signals,
    interesting_paths,
    local_module_names,
    manifest_libraries,
    notebook_signals,
    python_signals,
)

MODULE = '''"""Calculates apparent activation energy from the slope."""

import json
import numpy as np
from rdkit.Chem import AllChem
from torch import nn
from . import siblings
from .local import thing


class ApparentEaAnalysis:
    """Arrhenius linearisation of ln(ri) against 1/T."""

    def _hidden(self):
        pass


def compute_drc(cycle):
    """Degree of rate control by energy shift."""


def _private():
    pass
'''


def test_docstrings_definitions_and_third_party_imports_are_read():
    signals = python_signals("micro.py", MODULE)
    assert signals.module_doc.startswith("Calculates apparent activation energy")
    assert dict(signals.definitions) == {
        "ApparentEaAnalysis": "Arrhenius linearisation of ln(ri) against 1/T.",
        "compute_drc": "Degree of rate control by energy shift.",
    }
    # numpy, rdkit and torch are the technologies; json is stdlib and the
    # relative imports are sibling modules, which name nothing.
    assert signals.imports == ("numpy", "rdkit", "torch")


def test_stdlib_is_never_reported_as_a_technology():
    """A requirements.txt that is a pip freeze lists the whole OS. Imports are
    trusted precisely because they cannot do that -- but only if stdlib is
    filtered, or every project 'uses' json and os."""
    signals = python_signals("x.py", "import os, sys, json, collections, torch")
    assert signals.imports == ("torch",)
    assert not {"os", "sys", "json", "collections"} & set(signals.imports)
    assert "torch" not in sys.stdlib_module_names


def test_private_and_dunder_definitions_are_not_the_public_story():
    signals = python_signals("x.py", "def _helper():\n    pass\n")
    assert signals.definitions == ()


def test_a_file_that_does_not_parse_yields_nothing_and_does_not_raise():
    """A repository the student did not write may contain anything at all."""
    signals = python_signals("broken.py", "def (((( :\n")
    assert signals == type(signals)(path="broken.py")


def test_notebook_markdown_cells_are_the_documentation():
    notebook = """{"cells": [
      {"cell_type": "markdown", "source": ["# Chemography\\n", "GTM over 10B compounds."]},
      {"cell_type": "code", "source": ["import umap\\n", "import rdkit\\n"]},
      {"cell_type": "raw", "source": ["ignored"]}
    ]}"""
    signals = notebook_signals("nb.ipynb", notebook)
    assert signals.markdown == ("# Chemography\nGTM over 10B compounds.",)
    assert signals.imports == ("rdkit", "umap")


def test_a_malformed_notebook_yields_nothing_and_does_not_raise():
    assert notebook_signals("nb.ipynb", "{not json").markdown == ()
    assert notebook_signals("nb.ipynb", "[]").markdown == ()


def test_file_signals_routes_on_suffix():
    assert file_signals("a.ipynb", '{"cells": []}').path == "a.ipynb"
    assert file_signals("a.py", "import torch").imports == ("torch",)


def test_interesting_paths_prefers_shallow_source_and_drops_scaffolding():
    paths = (
        "README.md",
        "deep/a/b/c/d/thing.py",
        "main.py",
        "notebooks/analysis.ipynb",
        "tests/test_main.py",
        ".github/workflows/ci.py",
        "node_modules/pkg/index.py",
        "setup.py",
        "src/model.py",
    )
    chosen = interesting_paths(paths, limit=10)
    assert chosen[0] == "main.py"
    assert "src/model.py" in chosen
    assert "notebooks/analysis.ipynb" in chosen
    for excluded in ("tests/test_main.py", ".github/workflows/ci.py", "setup.py"):
        assert excluded not in chosen
    assert "node_modules/pkg/index.py" not in chosen
    # Prose is a rung in its own right now, so a README is selected here
    # rather than only by rung 7's by-name fetch -- which matters most for
    # repositories in languages the AST tier cannot read at all.
    assert "README.md" in chosen


def test_interesting_paths_respects_its_limit():
    paths = tuple(f"m{i}.py" for i in range(50))
    assert len(interesting_paths(paths, limit=12)) == 12


def test_directory_names_are_a_signal():
    """'GaussOutputFiles/' says what a repository is about."""
    paths = ("GaussOutputFiles/CO.out", "src/model.py", ".github/ci.yml", "top.py")
    names = directory_names(paths, limit=40)
    assert "GaussOutputFiles" in names
    assert "src" in names
    assert ".github" not in names


def test_a_projects_own_modules_are_not_technologies():
    """MicroKatc imports its siblings absolutely -- `import copasi_parser` --
    so the relative-import check alone let its own modules through as if they
    were libraries. 'auxilary_functions' is not a skill."""
    paths = (
        "copasi_parser.py",
        "auxilary_functions.py",
        "src/cdr_bench/featurizers.py",
        "notebooks/run.ipynb",
    )
    local = local_module_names(paths)
    assert {"copasi_parser", "auxilary_functions", "src", "cdr_bench"} <= local

    source = "import copasi_parser, numpy\nimport cdr_bench\nfrom rdkit import Chem\n"
    assert python_signals("m.py", source, local=local).imports == ("numpy", "rdkit")
    # Without the filter the project's own modules masquerade as libraries.
    assert "copasi_parser" in python_signals("m.py", source).imports


def test_parsing_someone_elses_code_stays_quiet(recwarn):
    """Their invalid escape sequence is their business, not our test noise."""
    python_signals("theirs.py", "x = '\\d+'\n")
    assert [w for w in recwarn.list if issubclass(w.category, SyntaxWarning)] == []


def test_documentation_is_read_whatever_the_code_is_written_in():
    signals = file_signals("docs/architecture.md", "# Design\nTwo stage pipeline.")
    assert signals.markdown == ("# Design\nTwo stage pipeline.",)
    assert "docs/architecture.md" in interesting_paths(
        ("docs/architecture.md", "src/main.rs"), limit=5
    )


def test_prose_in_a_source_comment_is_not_a_package():
    """The regression this change exists for.

    The deleted Julia/MATLAB pattern captured the token after `using` on any
    line of any non-Python file, so an English comment named a package.
    """
    source = "/* using leave-one-out cross validation */\nint main(void){return 0;}\n"
    assert file_signals("src/fit.c", source).imports == ()


def test_package_json_yields_its_declared_dependencies():
    text = """
    {
      "name": "my-project",
      "dependencies": {"react": "^19.0.0", "d3": "^7.9.0"},
      "devDependencies": {"vitest": "^2.1.0"}
    }
    """
    assert manifest_libraries("package.json", text) == ("d3", "react", "vitest")


def test_cargo_toml_yields_its_declared_dependencies():
    text = '[package]\nname = "mine"\n\n[dependencies]\nserde = "1"\ntokio = { version = "1" }\n'
    assert manifest_libraries("Cargo.toml", text) == ("serde", "tokio")


def test_go_mod_names_a_module_by_its_last_segment():
    text = "module example.com/mine\n\ngo 1.22\n\nrequire (\n\tgithub.com/spf13/cobra v1.8.0\n)\n"
    assert manifest_libraries("go.mod", text) == ("cobra",)


def test_r_description_drops_the_language_itself_and_version_bounds():
    text = "Package: mine\nDepends: R (>= 4.0)\nImports:\n    dplyr (>= 1.0),\n    ggplot2\n"
    assert manifest_libraries("DESCRIPTION", text) == ("dplyr", "ggplot2")


def test_pom_takes_artifact_ids_of_dependencies_not_of_the_project():
    text = (
        '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        "<artifactId>my-project</artifactId>"
        "<dependencies><dependency>"
        "<groupId>org.apache.spark</groupId><artifactId>spark-sql</artifactId>"
        "</dependency></dependencies></project>"
    )
    assert manifest_libraries("pom.xml", text) == ("spark-sql",)


def test_a_malformed_manifest_yields_nothing_rather_than_raising():
    for name in MANIFEST_FILES:
        assert manifest_libraries(name, "{not valid in any format") == ()


def test_an_unrecognised_filename_is_not_a_manifest():
    assert manifest_libraries("requirements.txt", "numpy==2.0\n") == ()


def test_python_imports_are_unaffected():
    signals = file_signals("run.py", "import numpy\nfrom scipy import optimize\n")
    assert signals.imports == ("numpy", "scipy")
