"""A page as lines, and its lines grouped into awards (verified-catalog §5 steps 1 and 3).

Code does the grouping: an award is a heading the readers say names one scholarship, grant or
award, plus every line under it until the next heading at its own level or above. The readers are
asked only the judgement -- "is this heading the name of an award?" -- and never assign lines
(§5 step 3's own rule: a line stays with the nearest award above it). No heading passes: the whole
page is one award under its title. Lines above the first award are not read, and are counted.

Measured 2026-09-27: grouping by raw headings made Türkiye Bursları's benefit sections fourteen
awards and "Childpage navigation" one, which is why a heading must pass the question first.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from apps.research.candidates import Candidates, Line
from apps.research.card_engine import Question, Quote, Section, yes_no
from apps.research.structured_html import (
    extract_dl_lines,
    extract_jsonld_lines,
    extract_table_groups,
)

_HEADING = re.compile(r"^(#{1,6}) (.*)$")
#: funding_judge's split: a long line breaks after sentence punctuation, so a quote stays a
#: sentence the page printed.
_MAX_LINE_CHARS = 300
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
#: Headings asked per call: one short answer each, well inside the reader's output cap.
HEADINGS_PER_CALL = 25

AWARD_NAME = (
    "Is the line `{key}` the name of one scholarship, grant or award programme?"
)
AWARD_NAME_CRITERIA = (
    "yes: a named award or scheme. no: a benefit it includes (\"Monthly stipend\", "
    "\"Accommodation\"), a section such as \"How to apply\", \"Eligibility\" or \"FAQ\", or "
    "navigation."
)


@dataclass(frozen=True)
class Page:
    """A page's readable text as lines. `levels[n]` is line n's heading level, 0 for a line that
    is not a heading. A table row carries the table's first row as its `header`."""

    title: str
    lang: str
    lines: tuple[Line, ...]
    levels: tuple[int, ...]

    def section(self) -> Section:
        return Section(self.title, self.lang, self.lines)


def _enrich_structured_lines(
    lines: list[Line],
    levels: list[int],
    *,
    text: str,
    html: bytes | str,
) -> tuple[list[Line], list[int]]:
    """Bind `<dl>` `<dt>` headers, 2D `<table>` row/column headers, and visible JSON-LD fields
    onto the page's lines while preserving section heading levels (`levels`)."""
    dl_lines = extract_dl_lines(html)
    table_groups = extract_table_groups(html)
    jsonld_lines = extract_jsonld_lines(html)
    if not dl_lines and not table_groups and not jsonld_lines:
        return lines, levels

    # 1. Upgrade <dd> lines in-place with their <dt> header and mark absorbed <dt> lines.
    absorbed_dt: set[int] = set()
    used_dd: set[int] = set()
    for dl in dl_lines:
        for idx, (line, lvl) in enumerate(zip(lines, levels, strict=True)):
            if idx in used_dd or lvl != 0 or line.header:
                continue
            if line.heading == dl.heading and line.text == dl.text:
                lines[idx] = Line(line.text, heading=line.heading, header=dl.header)
                used_dd.add(idx)
                for prev in range(idx - 1, -1, -1):
                    if levels[prev] != 0 or lines[prev].heading != line.heading:
                        break
                    if lines[prev].text == dl.header and not lines[prev].header:
                        absorbed_dt.add(prev)
                        break
                break

    if absorbed_dt:
        lines = [ln for i, ln in enumerate(lines) if i not in absorbed_dt]
        levels = [lv for i, lv in enumerate(levels) if i not in absorbed_dt]

    # 2. Replace pipe-table runs (`| ... |`) with 2D coordinate-bound cell lines, one table group
    #    per pipe-table run so two tables under the same heading never cross-pollinate.
    if table_groups:
        unused_groups = list(table_groups)
        new_lines: list[Line] = []
        new_levels: list[int] = []
        i = 0
        n = len(lines)
        while i < n:
            if levels[i] == 0 and lines[i].text.startswith("|"):
                end = i + 1
                heading = lines[i].heading
                while end < n and levels[end] == 0 and lines[end].text.startswith("|"):
                    end += 1
                block_text = " ".join(lines[k].text for k in range(i, end))
                matched_grp: tuple[Line, ...] | None = None
                for g_idx, grp in enumerate(unused_groups):
                    if grp and grp[0].heading == heading and all(
                        tl.text in block_text for tl in grp
                    ):
                        matched_grp = unused_groups.pop(g_idx)
                        break
                if matched_grp is None:
                    for g_idx, grp in enumerate(unused_groups):
                        if grp and grp[0].heading == heading and any(
                            tl.text in block_text for tl in grp
                        ):
                            matched_grp = tuple(tl for tl in grp if tl.text in block_text)
                            unused_groups.pop(g_idx)
                            break
                if matched_grp:
                    for tl in matched_grp:
                        pieces = (
                            [tl.text]
                            if len(tl.text) <= _MAX_LINE_CHARS
                            else _SENTENCE_END.split(tl.text)
                        )
                        for piece in (p for p in pieces if p):
                            new_lines.append(Line(piece, heading=heading, header=tl.header))
                            new_levels.append(0)
                else:
                    new_lines.extend(lines[i:end])
                    new_levels.extend(levels[i:end])
                i = end
            else:
                new_lines.append(lines[i])
                new_levels.append(levels[i])
                i += 1
        lines, levels = new_lines, new_levels

    # 3. Bind visible JSON-LD fields in-place when the value already sits on a body line under
    #    its target heading (avoiding duplicate Amount/Date candidates), or insert under the
    #    target heading when the value only appeared outside that section.
    if jsonld_lines and lines:
        existing_pairs = {(ln.text, ln.header) for ln in lines}
        default_heading = next((ln.text for ln, lv in zip(lines, levels, strict=True) if lv), "")
        for jl in jsonld_lines:
            if jl.text not in text or (jl.text, jl.header) in existing_pairs:
                continue
            target_heading = (
                jl.heading
                if any(
                    (lv == 0 and ln.heading == jl.heading) or (lv > 0 and ln.text == jl.heading)
                    for ln, lv in zip(lines, levels, strict=True)
                )
                else default_heading
            )
            merged_in_place = False
            for idx, (ln, lv) in enumerate(zip(lines, levels, strict=True)):
                if lv == 0 and ln.heading == target_heading and jl.text in ln.text:
                    if not ln.header:
                        new_hdr = jl.header
                    elif jl.header not in ln.header:
                        new_hdr = f"{ln.header} | {jl.header}"[:200]
                    else:
                        new_hdr = ln.header
                    lines[idx] = Line(ln.text, heading=ln.heading, header=new_hdr)
                    existing_pairs.add((jl.text, jl.header))
                    merged_in_place = True
                    break
            if merged_in_place:
                continue
            insert_at = len(lines)
            for idx in range(len(lines) - 1, -1, -1):
                if (levels[idx] == 0 and lines[idx].heading == target_heading) or (
                    levels[idx] > 0 and lines[idx].text == target_heading
                ):
                    insert_at = idx + 1
                    break
            lines.insert(insert_at, Line(jl.text, heading=target_heading, header=jl.header))
            levels.insert(insert_at, 0)
            existing_pairs.add((jl.text, jl.header))

    return lines, levels


def page_lines(text: str, *, lang: str, title: str = "", html: bytes | str = b"") -> Page:
    """`readable_text` output as lines, each under the heading above it; headings are lines too.
    `title` defaults to the first heading. When `html` is provided, `<dl>` `<dt>`/`<dd>` pairs,
    2D `<table>` cells (`Row | Col`), and visible JSON-LD fields are coordinate-bound onto
    `Line.header`."""
    lines: list[Line] = []
    levels: list[int] = []
    heading = ""
    table_header = ""
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        marked = _HEADING.match(line)
        if marked:
            line = marked.group(2).strip()
        elif line.startswith("- "):
            line = line[2:].strip()
        header = ""
        if line.startswith("|"):
            header, table_header = (table_header, table_header or line)
        else:
            table_header = ""
        pieces = [line] if len(line) <= _MAX_LINE_CHARS else _SENTENCE_END.split(line)
        for piece in (p for p in pieces if p):
            lines.append(Line(piece, heading=heading, header=header))
            levels.append(len(marked.group(1)) if marked else 0)
        if marked:
            heading = line
    if html:
        lines, levels = _enrich_structured_lines(lines, levels, text=text, html=html)
    first = next((line.text for line, level in zip(lines, levels, strict=True) if level), "")
    return Page(title or first, lang, tuple(lines), tuple(levels))


@dataclass(frozen=True)
class AwardNames:
    """The one judgement grouping needs, asked of a section of heading lines."""

    name: str = "funding-awards"
    version: str = "v3"
    criteria: str = ""

    def proposals(self, section: Section) -> Sequence[Question]:
        return ()

    def questions(self, section: Section, candidates: Candidates,
                  proposed: Mapping[str, tuple[Quote, ...]]) -> Sequence[Question]:
        return tuple(yes_no(f"award_L{n}", AWARD_NAME.format(key=f"L{n}"), AWARD_NAME_CRITERIA)
                     for n in range(len(section.lines)))


def heading_sections(page: Page) -> list[tuple[Section, tuple[int, ...]]]:
    """The page's headings in sections of `HEADINGS_PER_CALL`, each with the page line index of
    its section lines, so an answer about `L3` maps back to the page."""
    heads = [n for n, level in enumerate(page.levels) if level]
    out = []
    for start in range(0, len(heads), HEADINGS_PER_CALL):
        chunk = tuple(heads[start:start + HEADINGS_PER_CALL])
        out.append((Section(page.title, page.lang, tuple(page.lines[n] for n in chunk)), chunk))
    return out


@dataclass(frozen=True)
class Award:
    name: str
    name_line: int | None  # the heading's page line; None for the page award
    lines: tuple[int, ...]  # page line indexes, the heading first


def group(page: Page, names: set[int]) -> tuple[tuple[Award, ...], int]:
    """Awards from the heading lines that passed, and how many lines no award holds."""
    if not names:
        return (Award(page.title, None, tuple(range(len(page.lines)))),), 0
    awards: list[Award] = []
    held: set[int] = set()
    for start in sorted(names):
        level = page.levels[start]
        end = start + 1
        while end < len(page.lines) and end not in names and not (
                page.levels[end] and page.levels[end] <= level):
            end += 1
        awards.append(Award(page.lines[start].text, start, tuple(range(start, end))))
        held.update(range(start, end))
    return tuple(awards), len(page.lines) - len(held)


def award_section(page: Page, award: Award) -> Section:
    return Section(page.title, page.lang, tuple(page.lines[n] for n in award.lines))


def fold(text: str) -> str:
    """How code compares names: case, punctuation and symbols removed, words single-spaced.
    Accents go only from Latin, Greek and Cyrillic letters (Türkiye is turkiye); in scripts where
    marks carry the word (Devanagari, Thai) they stay, so a name is not broken into fragments.
    Dotless ı is i, so Turkish capitals (BURSLARI) and lower case (bursları) meet."""
    out: list[str] = []
    prev = ""  # the last kept letter
    # '+' becomes a word after normalising, so the full-width ＋ counts too
    folded = unicodedata.normalize("NFKD", text.casefold().replace("ı", "i"))
    for ch in folded.replace("+", " plus "):
        cat = unicodedata.category(ch)
        if cat[0] == "M":
            if prev and not unicodedata.name(prev, "").startswith(("LATIN", "GREEK", "CYRILLIC")):
                out.append(ch)
        elif cat[0] in "LN":
            out.append(ch)
            prev = ch
        else:
            out.append(" ")
            prev = ""
    return " ".join("".join(out).split())


#: Words that name no award by themselves, folded. A name made only of these (and of numbers)
#: matches every scholarship on a site, so it never attaches a hunted value.
GENERIC = frozenset(w for entry in (
    "a", "an", "and", "for", "in", "of", "the", "to", "s", "award", "awards", "bursary",
    "bursaries", "fellowship", "fellowships", "fund", "funding", "grant", "grants",
    "international", "master", "masters", "phd", "bachelor", "programme", "programmes",
    "program", "programs", "scholarship", "scholarships", "stipend", "stipends", "student",
    "students", "university", "burs", "bursu", "bursları", "təqaüd", "təqaüdü", "стипендия",
    "стипендии", "грант", "гранты", "программа", "stipendium", "stipendien", "bourse",
    "bourses", "beca", "becas", "borsa", "borse", "beurs",
    "bolsa", "bolsas", "奖学金", "奨学金", "장학금", "منحة", "beasiswa", "học bổng",
    "stypendium", "стипендию", "стипендий", "стипендиальная", "гранта", "программы",
    "merit", "excellence", "tuition", "fee", "waiver", "graduate", "postgraduate",
    "doctoral", "undergraduate", "government", "research", "full", "partial")
    for w in fold(entry).split())
PAGE_WORDS_FILE = Path(__file__).resolve().parents[3] / "docs" / "research" / "page-words.csv"
#: Page words are data (docs/research/page-words.csv): application, call, deadline, dates,
#: eligibility, documents, guide, info and function words in the round-2 languages. Never a
#: level, audience or kind word (research, doctoral, undergraduate): those name another award.
_NUMBER = re.compile(r"^\d+([./-]\d+)*(年度?)?$|^\d+(st|nd|rd|th)$")


@cache
def page_words() -> frozenset[str]:
    """The only words a heading may add to an award's name and still be that award's heading."""
    with PAGE_WORDS_FILE.open(encoding="utf-8", newline="") as handle:
        return frozenset(fold(row["word"]) for row in csv.DictReader(handle))


def _caseless(text: str) -> bool:
    return text.upper() == text.lower()


def _page_word(token: str) -> bool:
    """A number, a page word, or (a script without case: Han, Hangul, Kana) a run of them."""
    words = page_words()
    if _NUMBER.match(token) or token in words:
        return True
    if not _caseless(token):
        return False
    ok = [True] + [False] * len(token)  # token[:i] splits into page words
    for i in range(1, len(token) + 1):
        ok[i] = any(ok[k] and token[k:i] in words for k in range(i))
    return ok[-1]


def nameable(name: str) -> bool:
    """Whether code can match this award's name at all: one word that is not generic."""
    return any(w not in GENERIC and not w.isdigit() for w in fold(name).split())


def names_award(heading: str, name: str) -> bool:
    """Whether the section HEADING `heading` is the heading of the award `name`: the name's
    folded words appear in it whole and in order, and every other word is a number or a page word. A
    site-wide page title never goes here, and a heading that adds any other word ("Vice-Rector's
    Scholarship", "... Dissertation Scholarship") names a different award. A name code cannot
    tell from any other scholarship never matches. A name in a script without case may be
    followed or preceded by page words with no space ("中国政府奖学金申请指南")."""
    if not nameable(name):
        return False
    want, folded = fold(name), fold(heading)
    got = folded.split()
    for i in range(len(got) - len(want.split()) + 1):
        if got[i:i + len(want.split())] == want.split():
            rest = got[:i] + got[i + len(want.split()):]
            return all(_page_word(w) for w in rest)
    if _caseless(want.replace(" ", "")) and want in folded:
        before, _, after = folded.partition(want)
        return all(_page_word(w) for w in before.split() + after.split())
    return False
