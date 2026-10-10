from apps.documents.diffing import diff_cv_content
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    PersonalInformation,
    SkillEntry,
)


def _content(name="Jane Doe", grade=None, skills=()):
    return CVContent(
        personal_information=PersonalInformation(full_name=name, email="jane@example.com"),
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="Example U",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
                grade_native=grade,
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=skills,
        languages=(),
        document_language="en",
    )


def test_no_changes_yields_empty_diff():
    assert diff_cv_content(_content(), _content()) == ()


def test_field_change_detected_with_path():
    changes = diff_cv_content(_content(name="Jane Doe"), _content(name="Jane A. Doe"))
    change = next(c for c in changes if c.field_path == "personal_information.full_name")
    assert (change.old_value, change.new_value) == ("Jane Doe", "Jane A. Doe")


def test_nested_tuple_entry_change_detected():
    changes = diff_cv_content(_content(grade=None), _content(grade="1.7"))
    assert any(c.field_path == "education[0].grade_native" for c in changes)


def test_appended_list_entry_is_reported_as_a_change():
    changes = diff_cv_content(_content(), _content(skills=(SkillEntry(name="Python"),)))
    assert any(c.field_path == "skills[0]" and c.old_value is None for c in changes)
