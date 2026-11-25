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
_WORD_RE = re.compile(r"[a-z]+")
#: Applied to names AND domain labels, so it only ever makes them meet:
#: German domains spell "Hör" as "hoer", anyascii spells it "hor".
_DIGRAPHS = (("ae", "a"), ("oe", "o"), ("ue", "u"))
#: Non-German Romance/Dutch/English stems and suffixes where `ae`, `oe`, `ue`
#: are authentic vowel sequences (never German ASCII umlauts ä/ö/ü).
_NON_GERMAN_CONTEXT_RE = re.compile(
    r"\b(?:stichting|fondation|fundacion|fondazione|fundacao|universite|"
    r"universidad|universita|universiteit)\b"
)
_PROTECTED_STEM_RE = re.compile(
    r"(?:puer|maestr|oek|zoek|hoek|doen|goed|moed|bloed|broek|groep|voet|"
    r"groen|stoel|proef|beroep|toekomst|genoeg|vroeg|ploeg|kroeg|voeg|"
    r"nuev|buen|escuel|puent|fuerz|fuert|fuent|suert|muert|cuerp|cuent|"
    r"abuel|fueg|jueg|lueg|suel|vuel|duel|huert|muestr|prueb|venezuel|"
    r"huelv|manuel|miguel|samuel|teruel|cruel|rafael|israel|michael|"
    r"caetan|gaetan|paell|faen|aero|vitae|influenc|frecuenc|secuenc|"
    r"consecuenc|fluent|poet|poem|cooper|coordin|coexist)"
)
_ROMANCE_WORD_END_RE = re.compile(r"(?:[bcdfghjklmnpqrstvwxz](?:o|a|os|as))$")
#: Cross-lingual institutional kind stems mapped to canonical lookup words in `vocab.kinds`.
_CROSS_LINGUAL_KIND_STEMS: dict[str, tuple[str, ...]] = {
    "foundation": ("foundation", "stiftung", "vakif"),
    "fondation": ("foundation", "stiftung", "vakif"),
    "fundacion": ("foundation", "stiftung", "vakif"),
    "fondazione": ("foundation", "stiftung", "vakif"),
    "fundacao": ("foundation", "stiftung", "vakif"),
    "fundacja": ("foundation", "stiftung", "vakif"),
    "stichting": ("foundation", "stiftung", "vakif"),
    "stiftelse": ("foundation", "stiftung", "vakif"),
    "stiftelsen": ("foundation", "stiftung", "vakif"),
    "yayasan": ("foundation", "stiftung", "vakif"),
    "stiftung": ("stiftung", "foundation", "vakif"),
    "vakif": ("vakif", "foundation", "stiftung"),
    "vakfi": ("vakif", "foundation", "stiftung"),
    "university": ("university", "universitat", "universite"),
    "universitat": ("university", "universitat", "universite"),
    "universite": ("university", "universitat", "universite"),
    "universidad": ("university", "universitat", "universite"),
    "universita": ("university", "universitat", "universite"),
    "universiteit": ("university", "universitat", "universite"),
    "universitet": ("university", "universitat", "universite"),
    "uniwersytet": ("university", "universitat", "universite"),
    "hochschule": ("university", "universitat", "hochschule"),
    "fachhochschule": ("university", "universitat", "hochschule"),
    "association": ("association", "dernegi", "verein"),
    "asociacion": ("association", "dernegi", "verein"),
    "associazione": ("association", "dernegi", "verein"),
    "vereniging": ("association", "dernegi", "verein"),
    "verein": ("association", "dernegi", "verein"),
    "embassy": ("embassy", "botschaft"),
    "ambassade": ("embassy", "botschaft"),
    "ambasciata": ("embassy", "botschaft"),
    "embajada": ("embassy", "botschaft"),
    "botschaft": ("embassy", "botschaft"),
}
#: A token shorter than this is never distinctive (v2: "a lone short common
#: word is not evidence"); it still contributes to initials.
MIN_DISTINCTIVE = 4
#: Morphology and compounds only between words this long -- below it a one-edit
#: or prefix match is coincidence, not inflection.
_MIN_MORPH = 5
_MIN_HEAD_COMPOUND = 7
_MIN_INITIALS = 3


def _fold_word(word: str) -> str:
    if not ("ae" in word or "oe" in word or "ue" in word):
        return word
    if _PROTECTED_STEM_RE.search(word) or _ROMANCE_WORD_END_RE.search(word):
        return word
    # Protect French `oeu` (oeuvre, coeur, soeur, manoeuvre) and `[qg]ue` (que, guerra, league).
    out = re.sub(r"ae", "a", word)
    out = re.sub(r"oe(?!u)", "o", out)
    out = re.sub(r"(?<![qg])ue", "u", out)
    return out


def fold(text: str) -> str:
    folded = anyascii(text).casefold()
    if _NON_GERMAN_CONTEXT_RE.search(folded):
        return folded
    return _WORD_RE.sub(lambda m: _fold_word(m.group(0)), folded)


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


def _lookup_stem(stem: str, vocab: Vocabulary) -> frozenset[str]:
    direct = vocab.kinds.get(stem)
    if direct:
        return direct
    canonical_keys = _CROSS_LINGUAL_KIND_STEMS.get(stem)
    if canonical_keys:
        found: set[str] = set()
        for key in canonical_keys:
            if key in vocab.kinds:
                found |= vocab.kinds[key]
        if found:
            return frozenset(found)
    return frozenset()


def _morph_kinds(token: str, vocab: Vocabulary) -> frozenset[str]:
    direct = _lookup_stem(token, vocab)
    if direct:
        return direct
    # Rule 3a: a token that ENDS with a kind word is a kind word (Bundesstiftung).
    for start in range(1, len(token) - _MIN_MORPH + 1):
        tail = token[start:]
        hit = _lookup_stem(tail, vocab) or inflected_kind(tail, vocab)
        if hit:
            return hit
    # Rule 3b: a token that STARTS with an institutional head stem (fondation..., fundacion...,
    # stichting..., yayasan..., universite..., universidad...) is a head-initial compound.
    if len(token) >= _MIN_HEAD_COMPOUND + 3:
        for end in range(len(token) - 3, _MIN_HEAD_COMPOUND - 1, -1):
            head = token[:end]
            hit = _lookup_stem(head, vocab)
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
    found = _lookup_stem(token, vocab)
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
    for stem in _CROSS_LINGUAL_KIND_STEMS:
        if len(stem) < _MIN_MORPH or len(token) - len(stem) > _MAX_INFLECTION:
            continue
        if not token.startswith(stem[:3]):
            continue
        shared = len(os.path.commonprefix((token, stem)))
        if shared >= max(_MIN_MORPH, len(stem) - 2) or _one_edit(token, stem):
            hit = _lookup_stem(stem, vocab)
            if hit:
                return hit
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
