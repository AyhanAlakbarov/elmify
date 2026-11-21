import pytest

from apps.documents.derive import candidates
from apps.documents.file_rules import FileRule, bundle_rule, rule_for
from apps.documents.grammar import Rule
from apps.documents.rule_sinks import to_file_rules

pytestmark = pytest.mark.django_db


def _rule(value, note="", condition=""):
    return Rule(index=0, document="other", operation="file", value=value,
                sentence="Diplomas as one PDF, max 2 MB.", note=note, condition=condition)


def test_a_diploma_line_is_a_candidate_though_it_names_no_cv_or_letter():
    found = candidates("Diplomas as one PDF, max 2 MB.\nOur campus is lovely.", ())
    assert [c.text for c in found] == ["Diplomas as one PDF, max 2 MB."]
    assert not found[0].cv and not found[0].letter


def test_file_only_lines_are_cut_first_when_the_page_is_too_long(monkeypatch):
    monkeypatch.setattr("apps.documents.derive._MAX_CANDIDATES", 2)
    page = ("Brochure (PDF, 1 MB)\nYour CV may not exceed two pages.\n"
            "A motivation letter is required.")
    found = candidates(page, (), language="en")
    assert "Your CV may not exceed two pages." in [c.text for c in found]
    assert "Brochure (PDF, 1 MB)" not in [c.text for c in found]


def test_records_keep_the_sentence_and_the_page():
    records = to_file_rules((_rule(("DIPLOMA", "max_bytes", 2_000_000)),),
                            source_url="https://u.example/apply")
    assert records == ({"document": "DIPLOMA", "field": "max_bytes", "value": 2_000_000,
                        "conditional": False, "condition": "",
                        "rule_text": "Diplomas as one PDF, max 2 MB.",
                        "source_url": "https://u.example/apply"},)


def test_a_conditional_rule_is_kept_marked_and_a_note_is_dropped():
    records = to_file_rules(
        (_rule(("DIPLOMA", "format", "PDF"), note="conditional", condition="nationality"),
         _rule(("DIPLOMA", "format", "PDF"), note="third_party")),
        source_url="u",
    )
    assert [(r["conditional"], r["condition"]) for r in records] == [(True, "nationality")]


def _r(document, field, value, conditional=False):
    return {"document": document, "field": field, "value": value, "conditional": conditional}


def test_the_smaller_cap_wins_and_every_document_applies_to_each():
    records = [_r("DIPLOMA", "max_bytes", 5_000_000), _r("EVERY_DOCUMENT", "max_bytes", 2_000_000)]
    assert rule_for(records, "DIPLOMA").max_bytes == 2_000_000


def test_conflicting_formats_give_no_format_and_the_stricter_one_wins_over_either():
    assert rule_for([_r("CV", "format", "PDF"), _r("CV", "format", "JPG")], "CV").format is None
    both = [_r("CV", "format", "PDF"), _r("CV", "format", "PDF_OR_JPG")]
    assert rule_for(both, "CV").format == "PDF"


def test_a_conditional_record_binds_nobody_and_another_document_is_ignored():
    records = [_r("DIPLOMA", "max_bytes", 1_000_000, conditional=True),
               _r("TRANSCRIPT", "combine", "ONE_FILE")]
    assert rule_for(records, "DIPLOMA") == FileRule()


def test_one_file_for_a_kind_and_the_whole_application_bundle():
    records = [_r("DIPLOMA", "combine", "ONE_FILE"), _r("EVERY_DOCUMENT", "combine", "ONE_FILE"),
               _r("EVERY_DOCUMENT", "max_bytes", 10_000_000)]
    assert rule_for(records, "DIPLOMA").one_file is True
    assert bundle_rule(records) == FileRule(max_bytes=10_000_000, format="PDF", one_file=True)
    assert bundle_rule([_r("DIPLOMA", "combine", "ONE_FILE")]) is None


def test_two_different_name_patterns_give_none():
    records = [_r("CV", "name_pattern", "{surname}_CV.pdf"), _r("CV", "name_pattern", "cv.pdf")]
    assert rule_for(records, "CV").name_pattern is None


@pytest.mark.parametrize("bad", [2e6 + 0.5, "2MB", "2000000.0", None, 0, -5, True])
def test_an_unreadable_cap_is_skipped_not_raised(bad):
    records = [_r("CV", "max_bytes", bad), _r("CV", "max_bytes", 3_000_000)]
    assert rule_for(records, "CV").max_bytes == 3_000_000
    assert rule_for(records[:1], "CV") == FileRule()


def test_integral_float_and_digit_string_caps_are_read():
    assert rule_for([_r("CV", "max_bytes", 2e6)], "CV").max_bytes == 2_000_000
    assert rule_for([_r("CV", "max_bytes", "2000000")], "CV").max_bytes == 2_000_000


def test_records_missing_keys_or_with_an_unknown_format_are_skipped():
    records = [{"document": "CV", "value": 1}, {"document": "CV", "field": "max_bytes"},
               {"document": "CV", "field": "format"}, _r("CV", "format", "DOCX"), {}]
    assert rule_for(records, "CV") == FileRule()
    assert bundle_rule(records) is None


def test_a_combine_record_without_a_value_or_with_junk_is_skipped():
    bare = {"document": "EVERY_DOCUMENT", "field": "combine"}
    assert bundle_rule([bare]) is None
    assert bundle_rule([bare, _r("EVERY_DOCUMENT", "combine", "NOT_STATED")]) is None
    assert rule_for([{"document": "CV", "field": "combine"}], "CV") == FileRule()


def test_a_json_true_is_not_a_one_byte_cap():
    assert rule_for([_r("CV", "max_bytes", True)], "CV") == FileRule()


@pytest.mark.parametrize("junk", ["not a dict", None, 5, [1]])
def test_a_row_that_is_not_a_dict_is_skipped(junk):
    assert rule_for([junk], "CV") == FileRule()
    assert bundle_rule([junk]) is None
    assert rule_for([junk, _r("CV", "max_bytes", 1000)], "CV").max_bytes == 1000


def test_the_overflow_warning_says_how_many_dropped_lines_were_file_only(monkeypatch, caplog):
    monkeypatch.setattr("apps.documents.derive._MAX_CANDIDATES", 2)
    page = ("Brochure (PDF, 1 MB)\nFlyer (PDF, 2 MB)\nYour CV may not exceed two pages.\n"
            "A motivation letter is required.\nA reference letter is required.")
    with caplog.at_level("WARNING"):
        candidates(page, (), language="en")
    assert any("2 of the dropped" in r.getMessage() and "file-only" in r.getMessage()
               for r in caplog.records)


def test_an_upload_kind_is_its_file_rules_document_and_a_box_kind():
    """One name per document: what a student uploads, what a page's file rule names and
    what a learned upload box is labelled are the same string (REFERENCE_LETTER, never
    RECOMMENDATION), so nothing translates between them."""
    from typing import get_args

    from apps.concierge.models import UPLOAD_KIND_VALUES
    from apps.documents.file_rules import UPLOAD_DOCUMENTS
    from apps.documents.grammar import FILE_FIELDS
    from apps.portals.learn import DocKind

    # A thesis or report is evidence the CV reader reads (CV evidence spec §8), not a file
    # a portal box or a page's file rule asks for; prepare.py and views.py already treat a
    # kind outside UPLOAD_DOCUMENTS as no portal file.
    evidence_only = {"THESIS_OR_REPORT"}
    assert UPLOAD_DOCUMENTS == UPLOAD_KIND_VALUES - {"OTHER"} - evidence_only
    assert UPLOAD_DOCUMENTS <= set(FILE_FIELDS["document"])
    assert UPLOAD_KIND_VALUES - evidence_only <= set(get_args(DocKind))
