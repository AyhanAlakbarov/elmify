"""Default letter shape where the page states none, sourced row by row.

Spec `2026-09-19-letter-shape-tailoring` Task 6. Replaces
``silent_funder.DEFAULT_ARCHETYPES_BY_FUNDER_KIND``, which was five orders written to
make the plan work and cited nothing. Every row here names the ``M-`` rules it rests
on (``docs/research/letter-shape-rules.csv``) and a test reads that catalog to check
the ids are real; a row with no rule stays out of the table rather than being guessed.

Keyed by MODE, never by subject (owner, 2026-09-19): the research splits on academic
track, portfolio and reader, and the only subject effect found was register, which
the design's own draft leaves as an unbuilt tint.

Two things worth recording about how ``COUNTRY_SYSTEM`` and the funder overrides read
``docs/research/letter-shape-country-map.csv``:

- **A country with several map rows is not a conflict: the rows are per institution
  or per scheme, and ``_FUNDER_SYSTEM``/``_GOVERNMENT_SCHOLARSHIP_SYSTEM`` resolve a
  scheme BEFORE this table is consulted, so only the university-admission row can
  ever be read from here.** Germany, France and Japan each have more than one map
  row (Germany: its universities vs. DAAD; France: its universities vs. Campus
  France's pre-consular field vs. Eiffel; Japan: its universities vs. MEXT), and
  Russia has the same shape (a university row and a scholarship row) and was never
  in doubt. ``COUNTRY_SYSTEM`` therefore carries each one's university-admission
  row: Germany and France from ``"Universities via uni-assist; TUM"`` /
  ``"Universities (Mon Master, Sciences Po)"`` (both System A), Japan from
  ``"Universities (UTokyo Science; GraSPP)"`` (System C).
- **The FORMAL_LETTER form is not tied to a whole system bucket.** System ``A``
  bundles both the German/Dutch/Nordic essay convention (no salutation, no
  signature -- M-006, M-010, M-015) and France/Mexico/Brazil's genuine
  addressed-and-signed letter (M-025, M-034, M-101). Rather than force one form onto
  a heterogeneous bucket, the base ``A`` row stays an essay (the larger,
  higher-confidence share of its evidence) and ``_FORMAL_LETTER_COUNTRIES`` corrects
  the form for the specific countries whose own rule says otherwise. Chile is not one
  of them: its only rule (M-036) is a word-count ("proportion") rule, not a
  formalities one, so Chile is not in the table and takes the plain System-A essay.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

logger = logging.getLogger(__name__)

#: Country -> lettering system, from docs/research/letter-shape-country-map.csv, read
#: from each country's UNIVERSITY-ADMISSION row (see module docstring for why a
#: country with more than one map row is not a conflict). Low-confidence or
#: unread-page rows (Estonia, Argentina, Colombia, Morocco, Singapore, Egypt) are left
#: out for the same "no genuine citation to rest a default on" reason. A country the
#: map does not cover at all resolves to B, the plain essay that breaks no formality
#: rule anywhere, and the resolution is logged so the first real applicant from such a
#: country surfaces the gap.
COUNTRY_SYSTEM: dict[str, str] = {
    # System A: continental-Europe / Latin-America university essay or letter.
    "DE": "A", "AT": "A", "CH": "A", "NL": "A", "BE": "A", "IT": "A", "SE": "A",
    "FI": "A", "CZ": "A", "RU": "A", "FR": "A", "MX": "A", "CL": "A", "BR": "A",
    # System B: Anglosphere free-form essay, no letter formalities published.
    "GB": "B", "IE": "B", "AU": "B", "NZ": "B", "ZA": "B", "HK": "B", "MY": "B",
    "BH": "B", "GH": "B",
    # System C: North-American-shaped statement of purpose, faculty named.
    "US": "C", "CA": "C", "KZ": "C", "SA": "C", "AE": "C", "QA": "C", "JP": "C",
    # System E: East-Asian two-document (personal statement + study plan) shape.
    "KR": "E", "CN": "E", "TW": "E",
}
_FALLBACK_SYSTEM = "B"
#: A funder whose own sheet overrides wherever the university sits, regardless of
#: country (M-084/085/117 for F -- see SYSTEM_DEFAULTS below). GOVERNMENT_SCHOLARSHIP
#: is not here: its own system depends on which country's scheme it is, and that is
#: `_GOVERNMENT_SCHOLARSHIP_SYSTEM` below.
_FUNDER_SYSTEM = {
    "DEVELOPMENT_FOUNDATION": "D",
    "IMMIGRATION_AUTHORITY": "F",
}
#: A national government scholarship's own system, keyed by country, where the map
#: names one that differs from the DAAD shape (D): Japan's MEXT, South Korea's GKS
#: and China's CSC are all System E in docs/research/letter-shape-country-map.csv.
#: Every other government-scholarship country in the map (Germany's DAAD, France's
#: Eiffel, Russia's Open Doors, Azerbaijan's Heydar Aliyev grant, Brunei's BDGS,
#: Ethiopia's Arba Minch scholarship, Türkiye Bursları, Stipendium Hungaricum) is
#: already System D, so it needs no entry here and falls through to the default.
#: Malaysia's MIS is left out: its map row reads "B (no document for coursework)",
#: which is an absence of a document, not a documented letter system.
_GOVERNMENT_SCHOLARSHIP_SYSTEM: dict[str, str] = {
    "JP": "E", "KR": "E", "CN": "E",
}
#: Countries whose own rule describes a genuine addressed, dated and signed letter
#: even though their base system (System A's Germanic majority) does not. Applied
#: after the system lookup.
_FORMAL_LETTER_COUNTRIES: dict[str, tuple[str, ...]] = {
    "FR": ("M-025",),
    "MX": ("M-034",),
    "BR": ("M-101",),
}
#: A country whose own rule states a distinct OPENING move that does not
#: generalise to the rest of its lettering system -- applied after the system
#: lookup, alongside `_FORMAL_LETTER_COUNTRIES`. France's M-026 (opening names
#: the applicant's current or imminent diploma and the programme applied for)
#: used to sit in System A's base row, which asserted it for Germany, the
#: Netherlands, Sweden and every other System-A country too -- the same
#: over-generalisation fix round 1 removed from the research-mode row. Value
#: is (opening text, citing rule id). (Task 6 fix round 2, finding 2.)
_COUNTRY_OPENING: dict[str, tuple[str, str]] = {
    "FR": (
        "name your current or imminent diploma and the programme applied for",
        "M-026",
    ),
}


@dataclass(frozen=True)
class DefaultRow:
    archetypes: tuple[str, ...]
    opening: str
    closing: str
    form: str
    word_target: int
    rules: tuple[str, ...]


#: Lettering-system base row, by system letter. Every row's `rules` cites ids from
#: docs/research/letter-shape-rules.csv verified to exist by
#: tests/documents/test_letter_defaults.py.
SYSTEM_DEFAULTS: dict[str, DefaultRow] = {
    "A": DefaultRow(
        archetypes=("ACADEMIC_PREPARATION", "WHY_PROGRAMME", "CAREER_PLAN_RETURN"),
        opening="open on why this programme and why this university",
        closing="close by tying your preparation back to the programme, without new claims",
        form="ESSAY", word_target=500,
        # M-006 uni-assist (1-2 pages), M-010 ETH (~1 page, form sets it),
        # M-014 Utrecht (order: the template's six guiding questions open with
        # "why this programme and why Utrecht"). France's own opening (M-026)
        # does not generalise to the rest of this system -- Germany, the
        # Netherlands, Sweden and the others -- so it moved to
        # `_COUNTRY_OPENING["FR"]`, applied only to France by
        # `_formal_letter_override`. (Task 6 fix round 2, finding 2.)
        rules=("M-006", "M-010", "M-014"),
    ),
    "B": DefaultRow(
        archetypes=("WHY_PROGRAMME", "ACADEMIC_PREPARATION", "CAREER_PLAN_RETURN"),
        opening="state the purpose in the first sentences without repeating the CV",
        closing="close by returning to the reasons",
        form="ESSAY", word_target=550,
        # M-040 Imperial (opening: "we want to hear about you, not us"), M-044
        # Reading (order: motivation, then fit, then career), M-045 UCL (closing:
        # bring the focus back to your reasons), M-107 Edinburgh (~500 words).
        rules=("M-040", "M-044", "M-045", "M-107"),
    ),
    "C": DefaultRow(
        archetypes=("ACADEMIC_PREPARATION", "WHY_PROGRAMME", "CAREER_PLAN_RETURN"),
        opening="open with a brief portrait of what drives you academically",
        closing="close on your career interests in two or three sentences",
        form="ESSAY", word_target=750,
        # M-052 Berkeley (four-part order), M-053 Berkeley (500-1000 words),
        # M-056 MIT EECS (opening AND closing: "open with a brief portrait...
        # close ... with a 2-3 sentence discussion of your career interests").
        rules=("M-052", "M-053", "M-056"),
    ),
    "D": DefaultRow(
        archetypes=(
            "WHY_COUNTRY", "WHY_PROGRAMME", "ACADEMIC_PREPARATION",
            "CAREER_PLAN_RETURN", "HOME_COUNTRY_CONTRIBUTION",
        ),
        opening="",
        closing="",
        form="ESSAY", word_target=450,
        # M-001 DAAD (<=1 page). M-002 DAAD publishes a CONTENT list, not an
        # order -- goal/sector (a), home-country contribution (b), why this
        # programme (c), why you (d) -- and says so explicitly: "Not all of
        # the above questions have to be addressed!" No item is pinned to a
        # position, so opening/closing stay blank rather than asserting one
        # DAAD's own page disclaims; the archetype order above is this
        # engine's own choice, never a page requirement. M-003 DAAD (do not
        # open by repeating the CV -- a real, narrow opening constraint, kept
        # as a citation for content rather than restated as a row-level
        # position claim). M-005 DAAD (no letter formalities are prescribed --
        # why this row is ESSAY, not a letter). (Task 6 fix round 2,
        # finding 3.)
        rules=("M-001", "M-002", "M-003", "M-005"),
    ),
    "E": DefaultRow(
        archetypes=("ACADEMIC_PREPARATION", "WHY_PROGRAMME", "CAREER_PLAN_RETURN"),
        opening="open on academic background and past achievements",
        closing="close on the study plan and career goals after graduation",
        form="ESSAY", word_target=500,
        # M-080 SNU DTM is tagged "proportion" (a byte-count rule), not order: it
        # lists Form 2 Personal Statement's content -- background, achievements,
        # extracurriculars, volunteer work, employment, reasons for SNU -- and
        # separately the Study Plan's content -- academic goals and career
        # aspirations. This row's opening/closing are inferred from that field
        # order, never from a rule that states a sequence. M-097 TMU is tagged
        # "order" but describes a two-DOCUMENT shape (statement of purpose vs.
        # resume-and-personal-statement), not a sequence within one letter.
        # M-118 UTokyo Engineering (a named study-plan form, not a free letter).
        # So this row's positional claim is weaker than the others in this
        # table -- inferred from M-080's listed field order rather than stated
        # by any citation -- and is left standing rather than blanked, because
        # unlike System F below, no reading of these three citations
        # contradicts the claimed positions, only that none of them asserts a
        # sequence outright. (Task 6 fix round 4, finding 2.)
        rules=("M-080", "M-097", "M-118"),
    ),
    "F": DefaultRow(
        archetypes=("WHY_COUNTRY", "WHY_PROGRAMME", "PERSONAL_BACKGROUND",
                    "CAREER_PLAN_RETURN"),
        opening="",
        closing="",
        form="FORMAL_LETTER", word_target=500,
        # None of the three citations supports the opening/closing this row
        # used to assert ("purpose and duration of stay" / "observe visa
        # conditions and depart"). M-084 Ireland is tagged "formalities": a
        # signed letter of application outlining reason for coming, family
        # ties, length of stay and who bears the cost -- a content list, no
        # sequencing language. M-085 Ireland is tagged "order" but its text is
        # two content items joined by a semicolon ("explain why the course...
        # does not naturally follow...; state that you will observe the
        # conditions of your visa... will leave the State") -- structurally
        # like the citations fix round 2 removed from the portfolio row, not
        # like a stated sequence. M-117 RMIT is the only one of the three with
        # explicit sequencing language ("four question areas in order"), but
        # that order is background/academic history, why course/institution,
        # career goals, why country -- a different topic sequence from this
        # row's former opening and closing, which appear in none of the three
        # citations. So this row makes no positional claim and leaves
        # opening/closing blank rather than assert an ordering the research
        # does not support, the same treatment fix rounds 2-3 gave the
        # portfolio, System A and System D rows. (Task 6 fix round 4,
        # finding 1.)
        rules=("M-084", "M-085", "M-117"),
    ),
}

#: Mode row: overrides only the cells it fills; a blank cell inherits the system
#: row's value at merge time (`defaults_for`). Keyed by mode name.
MODE_DEFAULTS: dict[str, DefaultRow] = {
    # A research track's citations (M-011, M-068, M-112) are all "personalisation"
    # rules: name a prospective supervisor SOMEWHERE in the letter. None of them
    # says that naming must be the opening move, or describes a closing about fit
    # with the group's work -- so this row does not claim a position for it and
    # leaves opening/closing blank to inherit the system row's, rather than assert
    # an ordering the research does not support.
    "research": DefaultRow(
        archetypes=("RESEARCH_PLAN", "ACADEMIC_PREPARATION", "CAREER_PLAN_RETURN"),
        opening="",
        closing="",
        form="", word_target=0,
        rules=("M-011", "M-068", "M-112"),
    ),
    "portfolio": DefaultRow(
        archetypes=("ACADEMIC_PREPARATION", "WHY_PROGRAMME", "CAREER_PLAN_RETURN"),
        opening="",
        closing="",
        form="", word_target=0,
        # M-071 RISD (proportion) and M-072 CalArts (order) both establish only
        # that the statement must engage with the submitted portfolio rather
        # than stand alone -- neither says that engagement must be the OPENING
        # or CLOSING move, so this row does not claim a position for it and
        # leaves opening/closing blank to inherit the system row's, the same
        # treatment fix round 1 gave the research row above. (Task 6 fix
        # round 2, finding 1.)
        rules=("M-071", "M-072"),
    ),
}


def _formal_letter_override(row: DefaultRow, country_code: str) -> DefaultRow:
    """Apply the two independent per-country corrections a base system row can't carry.

    Form: `_FORMAL_LETTER_COUNTRIES` corrects the shape to a genuine addressed,
    dated and signed letter for a country whose own rule says so, even though its
    base system does not. Opening: `_COUNTRY_OPENING` corrects the opening move
    for a country whose own rule states one that does not generalise to the rest
    of its system bucket (France's M-026 inside System A -- Task 6 fix round 2,
    finding 2). The two are additive over the base row and independent of each
    other.
    """
    added_rules: tuple[str, ...] = ()
    form = row.form
    formal_rules = _FORMAL_LETTER_COUNTRIES.get(country_code)
    if formal_rules is not None and form != "FORMAL_LETTER":
        form = "FORMAL_LETTER"
        added_rules += formal_rules

    opening = row.opening
    opening_override = _COUNTRY_OPENING.get(country_code)
    if opening_override is not None:
        opening, opening_rule_id = opening_override
        added_rules += (opening_rule_id,)

    if not added_rules:
        return row
    return replace(row, form=form, opening=opening, rules=row.rules + added_rules)


def defaults_for(
    *, country_code: str, track: str, portfolio_led: bool, funder_kind: str
) -> DefaultRow:
    """The default row for one programme's mode.

    The funder's own system overrides the country's: an immigration authority is
    always F, and a government scholarship is its own country's scheme system where
    the map names one (Japan, South Korea, China), else the DAAD shape (D) --
    whatever country the university sits in. A blank track resolves as taught --
    the safer of the two, because it never demands a named supervisor the student
    cannot supply. A country with no documented system falls back to B, the plain
    essay that breaks no formality rule anywhere; a country whose own rule requires
    a genuine letter regardless (France, Mexico, Brazil) still gets that correction,
    from `_FORMAL_LETTER_COUNTRIES`.
    """
    cc = country_code.upper()
    if funder_kind == "GOVERNMENT_SCHOLARSHIP":
        system = _GOVERNMENT_SCHOLARSHIP_SYSTEM.get(cc, "D")
    else:
        system = _FUNDER_SYSTEM.get(funder_kind, "")
        if not system:
            system = COUNTRY_SYSTEM.get(cc, "")
            if not system:
                logger.warning(
                    "country %r has no documented lettering system; using the"
                    " plain essay",
                    country_code,
                )
                system = _FALLBACK_SYSTEM
    base = _formal_letter_override(SYSTEM_DEFAULTS[system], cc)
    mode_key = "research" if track == "research" else "portfolio" if portfolio_led else ""
    mode = MODE_DEFAULTS.get(mode_key)
    if mode is None:
        return base
    # A mode row overrides only the cells it fills; empty cells inherit.
    return DefaultRow(
        archetypes=mode.archetypes or base.archetypes,
        opening=mode.opening or base.opening,
        closing=mode.closing or base.closing,
        form=mode.form or base.form,
        word_target=mode.word_target or base.word_target,
        rules=base.rules + mode.rules,
    )
