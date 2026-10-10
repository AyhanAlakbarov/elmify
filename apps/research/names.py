"""The resolver's reading of an organisation's name (spec 6.5).

Three things live here and nothing else: how a name and a domain label are
folded so they can meet (symmetric, every script -- 4.13b), which tokens are
KIND words (rules 1 and 3, with the morphology tolerance v5 measured:
vakfı ~ vakıf, Stiftungen ~ Stiftung, Bundesstiftung ends with Stiftung), and
which tokens are DISTINCTIVE -- the only ones that are evidence of which body
a site belongs to. Place names (rule 2) and a country's common name words are
never distinctive; both come from `vocabulary.Vocabulary`, never from here.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from anyascii import anyascii

if TYPE_CHECKING:
    from .vocabulary import Vocabulary

_SPLIT = re.compile(r"[^a-z0-9]+")
#: Applied to names AND domain labels, so it only ever makes them meet:
#: German domains spell "Hör" as "hoer", anyascii spells it "hor".
_DIGRAPHS = (("ae", "a"), ("oe", "o"), ("ue", "u"))
#: A token shorter than this is never distinctive (v2: "a lone short common
#: word is not evidence"); it still contributes to initials.
MIN_DISTINCTIVE = 4
#: Morphology and compounds only between words this long -- below it a one-edit
#: or prefix match is coincidence, not inflection.
_MIN_MORPH = 5
_MIN_INITIALS = 3


def fold(text: str) -> str:
    folded = anyascii(text).casefold()
    for digraph, vowel in _DIGRAPHS:
        folded = folded.replace(digraph, vowel)
    return folded


def tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in _SPLIT.split(fold(text)) if token)


def _one_edit(a: str, b: str) -> bool:
    """Damerau distance <= 1: one insertion, deletion, substitution or
    adjacent transposition (vakfi/vakif)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return (
            len(diff) == 2
            and diff[1] == diff[0] + 1
            and a[diff[0]] == b[diff[1]]
            and a[diff[1]] == b[diff[0]]
        )
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = next((k for k in range(len(short)) if short[k] != long_[k]), len(short))
    return short[i:] == long_[i + 1 :]


def _morph_kinds(token: str, vocab: Vocabulary) -> frozenset[str]:
    # Rule 3: a token that ENDS with a kind word is a kind word (Bundesstiftung).
    for start in range(1, len(token) - _MIN_MORPH + 1):
        hit = vocab.kinds.get(token[start:])
        if hit:
            return hit
    for word in vocab.kinds_by_prefix.get(token[:3], ()):
        if len(word) < _MIN_MORPH:
            continue
        shared = len(os.path.commonprefix((token, word)))
        if shared >= max(_MIN_MORPH, len(word) - 2) or _one_edit(token, word):
            return vocab.kinds[word]
    return frozenset()


def kind_of(token: str, vocab: Vocabulary) -> frozenset[str]:
    """The Wikidata kind items this token names, or an empty set."""
    cached = vocab.kind_cache.get(token)
    if cached is not None:
        return cached
    found = vocab.kinds.get(token, frozenset())
    if not found and len(token) >= _MIN_MORPH:
        found = _morph_kinds(token, vocab)
    vocab.kind_cache[token] = found
    return found


#: An inflection adds at most this many letters (vakif -> vakiflar,
#: embassy -> embassies); a longer tail is another word.
_MAX_INFLECTION = 3


def inflected_kind(token: str, vocab: Vocabulary) -> frozenset[str]:
    """A kind word or an INFLECTION of one -- never a compound.

    What rule 1's directory test asks of each piece of a domain label. It must
    not use `kind_of`'s compound rule: "boschstiftung" ends with a kind word,
    and reading it as one made bosch-stiftung.de (hertie-stiftung.de,
    gatesfoundation.org) a directory, scored zero, and handed the title check
    to the runner-up -- which can be an adjacent body of the same kind.
    """
    found = vocab.kinds.get(token)
    if found:
        return found
    if len(token) < _MIN_MORPH:
        return frozenset()
    for word in vocab.kinds_by_prefix.get(token[:3], ()):
        if len(word) < _MIN_MORPH or len(token) - len(word) > _MAX_INFLECTION:
            continue
        shared = len(os.path.commonprefix((token, word)))
        if shared >= max(_MIN_MORPH, len(word) - 2) or _one_edit(token, word):
            return vocab.kinds[word]
    return frozenset()


@dataclass(frozen=True)
class NameProfile:
    distinctive: frozenset[str]
    #: Kind items the name states ("Vakfı" -> foundation). The title check's
    #: agreement is on these, never on the holder vocabulary.
    kinds: frozenset[str]
    kind_words: frozenset[str]
    #: Each variant's tokens joined -- "full slug" (tier 3).
    slugs: frozenset[str]
    #: Each variant's initials, with and without its <= 3-letter words.
    initials: frozenset[str]

    @property
    def one_token(self) -> bool:
        return len(self.distinctive) <= 1 and not self.kinds


def profile(names: Sequence[str], vocab: Vocabulary) -> NameProfile:
    """Every variant scored as one union (rule 4) -- native, English, Russian."""
    distinctive: set[str] = set()
    kinds: set[str] = set()
    kind_words: set[str] = set()
    slugs: set[str] = set()
    initials: set[str] = set()
    for name in names:
        toks = tokens(name)
        if not toks:
            continue
        for token in toks:
            named = kind_of(token, vocab)
            if named:
                kinds |= named
                kind_words.add(token)
            elif (
                len(token) >= MIN_DISTINCTIVE
                and token not in vocab.geo
                and token not in vocab.generic
            ):
                distinctive.add(token)
        slug = "".join(toks)
        if len(slug) >= MIN_DISTINCTIVE:
            slugs.add(slug)
        for group in (toks, tuple(t for t in toks if len(t) > 3)):
            acronym = "".join(t[0] for t in group)
            if len(acronym) >= _MIN_INITIALS:
                initials.add(acronym)
    return NameProfile(
        frozenset(distinctive), frozenset(kinds), frozenset(kind_words),
        frozenset(slugs), frozenset(initials),
    )
