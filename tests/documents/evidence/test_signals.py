import json
import sys

import pytest

from apps.documents.evidence.signals import (
    MANIFEST_FILES,
    directory_names,
    file_signals,
    interesting_paths,
    local_module_names,
    manifest_libraries,
    notebook_signals,
    python_signals,
    strip_markup,
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


def test_files_without_a_parser_do_not_take_a_fetch_slot():
    paths = tuple(f"a{i}.js" for i in range(8)) + tuple(f"b{i}.go" for i in range(8))
    paths += ("x.py", "y.py", "z.py")
    chosen = interesting_paths(paths, limit=5)
    assert {"x.py", "y.py", "z.py"} <= set(chosen)
    assert not [p for p in chosen if p.endswith((".js", ".go"))]


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


def test_strip_markup_drops_tags_and_badges_and_keeps_link_and_alt_text():
    readme = (
        '<h1 align="center">MicroKatc</h1>\n'
        '<p><img src="https://img.shields.io/badge/build-passing-green" alt="build passing"> '
        '<a href="https://example.org/docs">Docs</a></p>\n'
        '<img src="fig/energy.png" alt="Energy profile">\n'
        "<!-- hidden -->\n"
        "# Usage\n- run `python main.py`\n"
        "[![CI](https://github.com/a/b/actions/workflows/ci.yml/badge.svg)](https://github.com/a/b)\n"
        "See [the paper](https://doi.org/10.1/x)."
    )
    text = strip_markup(readme)
    assert "MicroKatc" in text and "Docs" in text and "Energy profile" in text
    assert "# Usage" in text and "- run `python main.py`" in text
    assert "See the paper." in text
    for gone in ("<", "shields", "badge", "build passing", "hidden", "https://"):
        assert gone not in text


def test_final_2_strip_markup_survives_its_own_placeholder_characters():
    assert strip_markup("Notes \ue0009\ue001 here `x`") == "Notes 9 here `x`"


def test_strip_markup_leaves_plain_markdown_alone_and_survives_nothing():
    assert strip_markup("# Title\n- item") == "# Title\n- item"
    assert strip_markup("") == ""


def _notebook(cells):
    return json.dumps({"cells": cells, "nbformat": 4})


def test_a_241_kb_notebook_is_read_whole_and_an_image_only_output_is_skipped():
    """The old 200,000-character cut came BEFORE json.loads, so a notebook this
    size failed to parse and contributed nothing."""
    image = {"output_type": "display_data", "data": {"image/png": "iVBOR" + "A" * 241_000}}
    cells = [
        {"cell_type": "markdown", "source": ["# Gaussian process surrogates\n", "Benchmark."]},
        {"cell_type": "code", "source": "import numpy as np\nfit()",
         "outputs": [image, {"output_type": "stream", "text": ["RMSE 0.42\n"]},
                     {"output_type": "execute_result", "data": {"text/plain": "array([1, 2])"}},
                     {"output_type": "error", "ename": "X"}]},
    ]
    text = _notebook(cells)
    assert len(text) > 241_000
    signals = notebook_signals("nb.ipynb", text)
    assert signals.markdown == ("# Gaussian process surrogates\nBenchmark.",)
    assert signals.outputs == ("RMSE 0.42", "array([1, 2])")
    assert signals.imports == ("numpy",)


@pytest.mark.parametrize(
    "path,read",
    [
        ("latest_model.py", True),
        ("contest_solver.py", True),
        ("src/attestation.py", True),
        ("tests/test_model.py", False),
        ("test/helpers.py", False),
        ("test_model.py", False),
        ("src/model_test.py", False),
        ("requirements.txt", False),
        ("requirements-dev.txt", False),
        ("LICENSE.md", False),
        ("CODE_OF_CONDUCT.md", False),
        ("CONTRIBUTING.rst", False),
        ("CLAUDE.md", False),
        ("docs/AGENTS.md", False),
        ("data/readings.txt", False),
        ("docs/notes.txt", True),
        ("docs/huge.txt", False),
        ("docs/unsized.txt", False),
        ("license_check.py", True),
    ],
)
def test_the_file_selection_rules(path, read):
    sizes = {"docs/notes.txt": 800, "docs/huge.txt": 60_000, "data/readings.txt": 900}
    assert (path in interesting_paths((path,), limit=5, sizes=sizes)) is read


def test_strip_markup_separates_block_text_and_line_breaks():
    assert strip_markup("<h1>Title</h1><p>Body text</p><ul><li>a</li><li>b</li></ul>").split() == [
        "Title", "Body", "text", "a", "b",
    ]
    lines = strip_markup("<h1>Title</h1><p>Body text</p><ul><li>a</li><li>b</li></ul>").splitlines()
    assert [line for line in lines if line] == ["Title", "Body text", "a", "b"]
    assert strip_markup("line one<br>line two<br/>three").splitlines() == [
        "line one", "line two", "three",
    ]


@pytest.mark.parametrize(
    "source",
    [
        "uses `List<int>` here",
        "```cpp\n#include <vector>\nstd::vector<int> v;\n```",
        "a vector<string> x of names",
    ],
)
def test_strip_markup_keeps_angle_brackets_that_are_not_html(source):
    assert strip_markup(source) == source


def test_strip_markup_drops_badges_but_keeps_a_fenced_cpp_block():
    readme = (
        '<p><img src="https://img.shields.io/badge/a-b-green" alt="x"></p>\n'
        "```cpp\n#include <vector>\nstd::vector<int> v;\n```\n"
    )
    text = strip_markup(readme)
    assert "#include <vector>" in text and "std::vector<int> v;" in text
    assert "shields" not in text and "<img" not in text
