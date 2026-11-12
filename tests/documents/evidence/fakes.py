"""Fakes shared by the evidence tests: no network, no OpenAI, no Jev.

FakeTransport answers by route. A key containing "?" must END the full URL;
any other key must END the URL's path (the query is ignored). The first
matching key wins and anything unmatched is a 404. Ending, not containing:
"/repos/0rkhann/MicroKatc" must not answer ".../MicroKatc/languages".

A GraphQL query that names a repository (variables "owner" and "name") is
routed by its operation name instead, under "graphql:<Operation>:<owner>/<name>"
(see graphql_key), and an unrouted one is a 404. Every other POST -- discovery's
Contributions query -- is routed by path, so "/graphql" answers it. A route may
be a callable taking the request body, for answers that depend on what was asked.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlsplit

from apps.documents.evidence.extraction import ReadBullet, RepoReading
from apps.documents.evidence.signals import README_FILES
from apps.research.decisions import Answer

LOGIN = "0rkhann"
#: The student's GitHub node id, as discovery's Contributions query answers it.
USER_ID = "U_kgDOtest"
#: A docstring long enough to clear the 500-character evidence floor on its own.
SPAN = "Microkinetic solver for catalytic cycles"
DOC = (SPAN + ". ") * 15
_OPERATION = re.compile(r"\s*query (\w+)")


def graphql_key(operation, full_name):
    return f"graphql:{operation}:{full_name}"


class FakeTransport:
    def __init__(self, routes=None, *, headers=None):
        self.routes = dict(routes or {})
        self.headers = dict(headers or {})
        self.calls: list[tuple[str, str, dict, object]] = []

    def _unpacked(self, response, body=None):
        status, answer, *rest = response(body) if callable(response) else response
        return status, answer, rest[0] if rest else self.headers

    def _answer(self, url):
        path = urlsplit(url).path
        for key, response in self.routes.items():
            if (url if "?" in key else path).endswith(key):
                return self._unpacked(response)
        return 404, {}, self.headers

    def _repository_query(self, body):
        query = body.get("query", "") if isinstance(body, dict) else ""
        variables = (body.get("variables") or {}) if isinstance(body, dict) else {}
        operation = _OPERATION.match(query)
        if operation is None or "owner" not in variables:
            return None
        full_name = f"{variables['owner']}/{variables['name']}"
        response = self.routes.get(graphql_key(operation.group(1), full_name))
        return (404, {}, self.headers) if response is None else self._unpacked(response, body)

    def get_json(self, url, *, headers=None):
        self.calls.append(("GET", url, dict(headers or {}), None))
        return self._answer(url)

    def post_json(self, url, body, *, headers=None):
        self.calls.append(("POST", url, dict(headers or {}), body))
        return self._repository_query(body) or self._answer(url)

    def get_bytes(self, url, *, headers=None, max_bytes):
        self.calls.append(("BYTES", url, dict(headers or {}), max_bytes))
        status, body, found = self._answer(url)
        return status, body if isinstance(body, bytes) else b"", found

    @property
    def urls(self) -> list[str]:
        return [call[1] for call in self.calls]


def row(full_name, *, pushed="2026-10-01T00:00:00Z", created="2025-01-01T00:00:00Z",
        fork=False, size=10, owner_type="User"):
    """One /users/{login}/repos listing row."""
    return {
        "full_name": full_name, "pushed_at": pushed, "created_at": created,
        "fork": fork, "size": size, "owner": {"login": full_name.split("/")[0], "type": owner_type},
    }


def listing(*rows):
    return {f"/users/{LOGIN}/repos": (200, list(rows))}


def contribution(owner, name, commits, *, typename="User", org_name=None,
                 pushed="2026-09-01T00:00:00Z"):
    owner_block = {"login": owner, "__typename": typename}
    if org_name is not None:
        owner_block["name"] = org_name
    return {
        "contributions": {"totalCount": commits},
        "repository": {"name": name, "pushedAt": pushed, "owner": owner_block},
    }


def graphql(*entries, **years):
    """A Contributions answer. Positional entries land in y2026; y2017=[...] adds a year."""
    blocks = {"id": USER_ID, "y2026": {"commitContributionsByRepository": list(entries)}}
    for year, more in years.items():
        blocks[year] = {"commitContributionsByRepository": list(more)}
    return {"/graphql": (200, {"data": {"user": blocks}})}


READING = RepoReading(
    summary=f"{SPAN}.",
    kind="project",
    bullets=(ReadBullet(text="Built a microkinetic solver for catalytic cycles.",
                        evidence=(SPAN,)),),
)


class FakeParser:
    """Stands in for OpenAI().responses: answers each parse() with the next reading."""

    def __init__(self, *readings):
        self.readings = list(readings) or [READING]
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        parsed = self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        return SimpleNamespace(output_parsed=parsed, usage=SimpleNamespace(total_tokens=1000))


def answering(value="yes", confidence=0.95):
    """A decisions.ask client answering every question the same way."""
    calls = []

    def client(state, questions, *, model, provider):
        calls.append(state)
        return {
            qid: Answer(id=qid, value=value, confidence=confidence,
                        probabilities={value: confidence}, model=model, provider=provider)
            for qid in questions
        }

    client.calls = calls
    return client


def overview_key(full_name):
    return graphql_key("RepoOverview", full_name)


def files_key(full_name):
    return graphql_key("RepoFiles", full_name)


def blob(text, *, truncated=False, binary=False):
    """One GraphQL Blob. Cut or binary, `text` is null, as GitHub sends it."""
    return {"byteSize": len(text.encode()), "isTruncated": truncated,
            "text": None if truncated or binary else text}


def commit(message, date="2026-09-01T00:00:00Z", *, parents=1):
    """One history node of RepoOverview, newest first like GitHub's."""
    return {"message": message, "authoredDate": date, "parents": {"totalCount": parents}}


def from_rest(rows):
    """Recorded REST /commits rows as history nodes (the fixtures predate GraphQL). A row
    GitHub could not attribute has no date, as in the recording."""
    nodes = []
    for row in rows:
        found = row.get("commit") or {}
        nodes.append({"message": found.get("message") or "",
                      "authoredDate": (found.get("author") or {}).get("date"),
                      "parents": {"totalCount": len(row.get("parents") or [{}])}})
    return nodes


def overview(*, description="A solver", fork=False, parent=None, languages=None,
             commits=(), readmes=None):
    """A RepoOverview answer; `readmes` maps README_FILES names to blob() dicts."""
    found = {
        "description": description,
        "isFork": fork,
        "parent": {"nameWithOwner": parent} if parent else None,
        "languages": {"edges": [{"size": size, "node": {"name": name}}
                                for name, size in (languages or {"Python": 5000}).items()]},
        "defaultBranchRef": {"name": "main", "target": {"history": {"nodes": list(commits)}}},
    }
    for index, name in enumerate(README_FILES):
        found[f"r{index}"] = (readmes or {}).get(name)
    return 200, {"data": {"repository": found}}


def repo_routes(full_name, *, pushed="2026-10-01T00:00:00Z", description="A solver",
                files=None, meta_status=200, fork=False, parent=None, commits=None,
                languages=None, truncated=(), binary=(), etag=""):
    """Everything discovery, fetch_repo and repo_evidence ask about one repository:
    REST metadata (discovery's CV-link and fork lookups), RepoOverview, the tree and
    RepoFiles. A path in `truncated` comes back cut by GraphQL and whole from the raw
    download; one in `binary` comes back with null text."""
    files = {"solver.py": f'"""{DOC}"""\n'} if files is None else files
    base = f"/repos/{full_name}"

    def as_blob(path):
        return blob(files[path], truncated=path in truncated, binary=path in binary)

    def answer_files(body):
        found = {}
        for name, expression in body["variables"].items():
            path = expression.removeprefix("HEAD:")
            if name[0] == "p" and name[1:].isdigit():
                found[f"f{name[1:]}"] = as_blob(path) if path in files else None
        return 200, {"data": {"repository": found}}

    tree = {"truncated": False, "tree": [
        {"path": path, "type": "blob", "size": len(text.encode())} for path, text in files.items()
    ]}
    return {
        overview_key(full_name): overview(
            description=description, fork=fork, parent=parent, languages=languages,
            commits=[commit("Add the solver")] if commits is None else commits,
            readmes={name: as_blob(name) for name in README_FILES if name in files},
        ),
        files_key(full_name): answer_files,
        f"{base}/git/trees/main": (200, tree, {"etag": etag} if etag else {}),
        **{f"{base}/contents/{quote(path)}": (200, files[path].encode())
           for path in (*truncated, *binary)},
        base: (meta_status, {"full_name": full_name, "description": description,
                             "default_branch": "main", "fork": fork, "pushed_at": pushed}),
    }


def asked(transport):
    """Every file path the fetches named: RepoFiles variables, then raw downloads."""
    paths = []
    for method, url, _headers, body in transport.calls:
        if method == "POST" and "query RepoFiles" in body["query"]:
            paths += [value.removeprefix("HEAD:") for name, value in body["variables"].items()
                      if name[0] == "p" and name[1:].isdigit()]
        elif method == "BYTES":
            paths.append(unquote(urlsplit(url).path.split("/contents/", 1)[1]))
    return paths


def overviews(transport):
    """RepoOverview variables by owner/name: which repos were fetched, and how."""
    return {
        f"{call[3]['variables']['owner']}/{call[3]['variables']['name']}": call[3]["variables"]
        for call in transport.calls
        if call[0] == "POST" and "query RepoOverview" in call[3]["query"]
    }


#: The trial's synthetic repo (evidence-engine review §7): an HTML README with badges,
#: a 241 KB notebook (cut by GraphQL, so downloaded raw) with an image-only output, a
#: module GraphQL cut (absent), latest_model.py, a pip freeze, a data dump, an LFS
#: pointer, a path with a space, agent notes, trailers and a merge.
SYNTH = "0rkhann/synth-bench"
SYNTH_NOTEBOOK = "notebooks/surrogate analysis.ipynb"
_SYNTH_NOTEBOOK_TEXT = json.dumps({"nbformat": 4, "cells": [
    {"cell_type": "markdown",
     "source": ["# Surrogate benchmark\n", "Gaussian process surrogates."]},
    {"cell_type": "code", "source": "import numpy as np\nfit()", "outputs": [
        {"output_type": "display_data", "data": {"image/png": "iVBOR" + "A" * 241_000}},
        {"output_type": "stream", "text": ["RMSE 0.42\n"]},
    ]},
]})
SYNTH_FILES = {
    "README.md": (
        '<p align="center"><img src="https://img.shields.io/badge/ci-passing-green" alt="ci"></p>\n'
        "<h1>Synth bench</h1>\n<p>Benchmark of Gaussian process surrogates.</p>\n"
        + "Benchmark details for the surrogate study. " * 250
    ),
    "CLAUDE.md": "Agent notes about the benchmark. " * 200,
    "LICENSE.md": "MIT License, the whole text.",
    "requirements.txt": "apturl==0.5.2\nnumpy==1.26.0\n",
    "latest_model.py": '"""Latest surrogate model: a Gaussian process with a Matern kernel."""\n',
    "contest_solver.py": '"""Contest solver for the benchmark leaderboard."""\n',
    "generated_tables.py": '"""Generated lookup tables, too big for GraphQL."""\n',
    "tests/test_model.py": '"""Tests of the model."""\n',
    "src/model_test.py": '"""More tests of the model."""\n',
    "data/readings.txt": "1,2,3\n" * 20_000,
    "docs/notes.txt": "Notes on the acquisition function.",
    "docs/my notes.md": "Design notes kept at a path with a space.",
    "results/table.md": "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 12\n",
    SYNTH_NOTEBOOK: _SYNTH_NOTEBOOK_TEXT,
}
SYNTH_COMMITS = [
    commit("Fit the surrogate\n\nCo-authored-by: Jane Roe <jane@example.com>\n"
           "Signed-off-by: Jane Roe <jane@example.com>", "2026-09-02T00:00:00Z"),
    commit("Merge pull request #3 from 0rkhann/feature", "2026-09-03T00:00:00Z", parents=2),
    commit("Thanks @0rkhann for the review of 0RKHANN/synth-bench", "2026-09-04T00:00:00Z"),
]


def synthetic_routes():
    return repo_routes(SYNTH, description="Synthetic benchmark for the evidence reader",
                       files=SYNTH_FILES, commits=SYNTH_COMMITS,
                       truncated=(SYNTH_NOTEBOOK, "generated_tables.py"))
