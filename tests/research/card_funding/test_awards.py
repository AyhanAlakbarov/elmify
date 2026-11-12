from apps.research.candidates import find_all
from apps.research.card_funding.awards import (
    AWARD_NAME,
    AWARD_NAME_CRITERIA,
    AwardNames,
    award_section,
    group,
    heading_sections,
    page_lines,
)

TEXT = """# Scholarships at Baku University
Our university supports students.
## Rector's Scholarship
Monthly stipend of AZN 300.
### How to apply
- Apply by 15 May 2027.
| Level | Amount |
| Master | AZN 400 |
## Merit Award
Tuition waiver of 50%.
## Contact
Write to us.
"""


def test_lines_keep_headings_levels_and_table_headers():
    page = page_lines(TEXT, lang="en")
    assert page.title == "Scholarships at Baku University"
    texts = [line.text for line in page.lines]
    assert texts[4] == "How to apply" and page.levels[4] == 3
    assert page.lines[5].text == "Apply by 15 May 2027." and page.lines[5].heading == "How to apply"
    assert page.lines[6].header == "" and page.lines[7].header == "| Level | Amount |"
    assert page.lines[8].header == ""  # a heading ends the table


def test_a_long_line_splits_at_sentence_ends():
    long = "A" * 200 + ". " + "B" * 200 + "."
    assert [line.text for line in page_lines(long, lang="en").lines] == ["A" * 200 + ".",
                                                                          "B" * 200 + "."]


def test_an_award_runs_to_the_next_heading_at_its_own_level():
    page = page_lines(TEXT, lang="en")
    awards, unread = group(page, {2, 8})
    assert [(a.name, a.lines) for a in awards] == [
        ("Rector's Scholarship", (2, 3, 4, 5, 6, 7)),  # its "How to apply" subsection included
        ("Merit Award", (8, 9)),  # stops at "Contact", a heading at its level
    ]
    assert unread == 4  # the page heading, its intro line, "Contact" and its line
    section = award_section(page, awards[1])
    assert [line.text for line in section.lines] == ["Merit Award", "Tuition waiver of 50%."]
    for award in awards:  # inside what D8 screened, for every award
        assert award_section(page, award).texts() <= page.section().texts()


def test_no_award_heading_makes_the_page_one_award():
    page = page_lines(TEXT, lang="en")
    awards, unread = group(page, set())
    assert awards[0].name == page.title and len(awards[0].lines) == len(page.lines)
    assert unread == 0


def test_the_heading_question_refers_to_lines_by_key_only():
    page = page_lines(TEXT, lang="en")
    [(section, index)] = heading_sections(page)
    assert index == (0, 2, 4, 8, 10)
    questions = AwardNames().questions(section, find_all(section.lines), {})
    assert [q.id for q in questions] == ["award_L0", "award_L1", "award_L2", "award_L3", "award_L4"]
    # page text never travels outside the untrusted wrapper: the wording is fixed, the key varies
    assert {(q.text.replace(q.id[6:], "KEY"), q.criteria) for q in questions} == {
        (AWARD_NAME.format(key="KEY"), AWARD_NAME_CRITERIA)}
