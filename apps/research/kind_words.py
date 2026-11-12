"""Kind words per language -- what `angles.KindVocabulary` asks for (spec 6.5 rule 1).

`vocabulary.py` answers the resolver's question (which kinds does this folded
token label), so it keeps no language and knows nothing of our holder kinds.
The angle generator asks the opposite one: the words for PRIVATE_FOUNDATION
in Turkish. Three files in `vocabulary.DATA_DIR` answer it:

- ``holder_kinds.json`` -- our holder kind -> the Wikidata items that mean
  it. Kept by hand and reviewed as a diff; it names classes, never a body.
- ``kind_word_corrections.json`` -- words Wikidata lacks or has wrong, kept
  by hand (owner decision 2026-10-12). A word is added only with the official
  page that uses it in that sense, and dropped only with why it is wrong: an
  Azerbaijani foundation calls itself a "fond", and Wikidata's only word is
  "Vəqf".
- ``kind_words.json`` -- the mapped items' labels and aliases in every
  language Wikidata has, with the corrections applied, written by
  `manage.py build_kind_words`. Never translated by a model (lever 3): a
  query in the wrong word for "foundation" is the failure this prevents.

A language with no word answers `()`, which `generate_angles` reports as
`no_vocabulary` for that language rather than guessing one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import vocabulary, wikidata
from .classify import KIND_DEFINITIONS
from .languages import MAX_LANGUAGE_LEN as _LANGUAGE_MAX
from .vocabulary import Sparql, VocabularyShape

_MAP_FILE = "holder_kinds.json"
_WORDS_FILE = "kind_words.json"
_CORRECTIONS_FILE = "kind_word_corrections.json"
#: A macrolanguage code Wikidata never labels, read as its usual written form:
#: Norway's P37 lists "no" beside "nb" and "nn", and its labels are all "nb".
_WRITTEN_AS = {"no": "nb"}

_WORDS_Q = """SELECT ?kind ?word ?lang ?rank WHERE {{
  VALUES ?kind {{ {items} }}
  {{ ?kind rdfs:label ?word . BIND(0 AS ?rank) }}
  UNION {{ ?kind skos:altLabel ?word . BIND(1 AS ?rank) }}
  BIND(LANG(?word) AS ?lang)
}}"""


def read_holder_kinds() -> dict[str, tuple[str, ...]]:
    """The hand-kept map, validated: every key is one of our holder kinds and
    every value a QID, since the QIDs are interpolated into the query."""
    path = vocabulary.DATA_DIR / _MAP_FILE
    raw = json.loads(path.read_text("utf-8"))["kinds"]
    kinds: dict[str, tuple[str, ...]] = {}
    for kind, items in raw.items():
        qids = tuple(item["qid"] for item in items)
        if kind not in KIND_DEFINITIONS:
            raise VocabularyShape(f"{_MAP_FILE}: {kind!r} is not a holder kind")
        bad = [qid for qid in qids if not wikidata._QID.match(qid)]
        if bad or not qids:
            raise VocabularyShape(f"{_MAP_FILE}: {kind} has no usable items {bad}")
        kinds[kind] = qids
    return kinds


def read_corrections(
    kinds: Mapping[str, object],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(adds, drops), validated. Absent file: none of either."""
    path = vocabulary.DATA_DIR / _CORRECTIONS_FILE
    if not path.exists():
        return [], []
    doc = json.loads(path.read_text("utf-8"))
    adds, drops = list(doc.get("add", [])), list(doc.get("drop", []))
    for row in [*adds, *drops]:
        kind, language, word = row.get("kind", ""), row.get("language", ""), row.get("word", "")
        if kind not in kinds or not vocabulary._LANG.match(language) or not word.strip():
            raise VocabularyShape(f"{_CORRECTIONS_FILE}: unusable row {row}")
    for row in adds:
        # The source is the whole point of a hand-added word: no page, no word.
        if not row.get("source", "").startswith("https://") or not row.get("checked_on"):
            raise VocabularyShape(f"{_CORRECTIONS_FILE}: {row['word']!r} has no source and date")
    for row in drops:
        if not row.get("why"):
            raise VocabularyShape(f"{_CORRECTIONS_FILE}: dropping {row['word']!r} says no why")
    return adds, drops


def build_kind_words_doc(
    *, retrieved_on: str, sparql: Sparql = wikidata.sparql
) -> dict[str, Any]:
    kinds = read_holder_kinds()
    adds, drops = read_corrections(kinds)
    items = sorted({qid for qids in kinds.values() for qid in qids})
    found: dict[str, dict[str, dict[str, int]]] = {}
    for row in sparql(_WORDS_Q.format(items=" ".join(f"wd:{qid}" for qid in items))):
        qid, word, language = vocabulary._qid(row["kind"]), row["word"].strip(), row["lang"]
        if not vocabulary._LANG.match(language) or len(language) > _LANGUAGE_MAX:
            continue
        # A dotted form is an abbreviation ("co.", "e.V."), not a kind word.
        # Never a length floor: 재단 and 財団 are "foundation" in two characters.
        if "." in word or len(word) < 2:
            continue
        ranks = found.setdefault(qid, {}).setdefault(language, {})
        ranks[word] = min(int(row["rank"]), ranks.get(word, 1))
    # An assertion, not tuning: an item with no English label is a wrong QID
    # or a changed query, and the build stops rather than writing it.
    unlabelled = [qid for qid in items if not found.get(qid, {}).get("en")]
    if unlabelled:
        raise VocabularyShape(f"no English label for {unlabelled}")
    words: dict[str, dict[str, list[str]]] = {}
    for kind, qids in sorted(kinds.items()):
        by_language: dict[str, list[str]] = {}
        languages = sorted({language for qid in qids for language in found[qid]})
        for language in languages:
            kept: dict[str, tuple[int, int, str]] = {}
            for order, qid in enumerate(qids):
                for word, rank in found[qid].get(language, {}).items():
                    # Labels before aliases, then the map's own item order;
                    # "Foundation" and "foundation" are one word.
                    key = (rank, order, word)
                    held = kept.get(word.casefold())
                    if held is None or key < held:
                        kept[word.casefold()] = key
            by_language[language] = [word for _, _, word in sorted(kept.values())]
        words[kind] = by_language
    for row in drops:
        held_words = words[row["kind"]].get(row["language"], [])
        kept_words = [w for w in held_words if w.casefold() != row["word"].casefold()]
        if len(kept_words) == len(held_words):
            # Wikidata was corrected: the row is stale and is removed by hand,
            # so the file never claims a fix that no longer does anything.
            raise VocabularyShape(f"{_CORRECTIONS_FILE}: nothing to drop for {row}")
        words[row["kind"]][row["language"]] = kept_words
    # Reversed, so the file's first added word for a language leads its list:
    # a hand-added word is the one an official page was seen to use.
    for row in reversed(adds):
        held_words = words[row["kind"]].setdefault(row["language"], [])
        word = row["word"].strip()
        held_words[:] = [word, *(w for w in held_words if w.casefold() != word.casefold())]
    return {
        "words": words,
        "corrections": {"added": len(adds), "dropped": len(drops)},
        "items": {kind: list(qids) for kind, qids in sorted(kinds.items())},
        "retrieved_on": retrieved_on, "source": wikidata.ENDPOINT, "query": _WORDS_Q,
    }


@dataclass(frozen=True)
class KindWords:
    """`angles.KindVocabulary`, read from the committed file."""

    by_kind: Mapping[str, Mapping[str, tuple[str, ...]]]

    def words(self, kind: str, language: str) -> tuple[str, ...]:
        by_language = self.by_kind.get(kind, {})
        # A regional tag with no words of its own ("en-gb", "zh-cn") reads its
        # base language's: Wikidata labels the base far more often.
        base = language.split("-")[0]
        return (
            by_language.get(language)
            or by_language.get(base)
            or by_language.get(_WRITTEN_AS.get(base, ""), ())
        )


def load_kind_words() -> KindWords | None:
    """None when the file was never built: the caller refuses, it never
    falls back to a model's own word for the kind."""
    path = vocabulary.DATA_DIR / _WORDS_FILE
    if not path.exists():
        return None
    doc = json.loads(path.read_text("utf-8"))
    return KindWords({
        kind: {language: tuple(words) for language, words in by_language.items()}
        for kind, by_language in doc["words"].items()
    })
