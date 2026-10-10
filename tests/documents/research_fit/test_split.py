from apps.documents.research_fit.split import page_sentences


def test_an_abbreviated_title_does_not_split_a_sentence():
    lines = ["Prof. Dr. A. Schmidt leads the chair. We work on legged locomotion."]
    assert page_sentences(lines) == (
        "Prof. Dr. A. Schmidt leads the chair.",
        "We work on legged locomotion.",
    )


def test_bullet_and_heading_lines_are_their_own_sentences():
    lines = ["# Chair of Robotics", "- Legged locomotion", "- Model predictive control"]
    assert page_sentences(lines) == (
        "Chair of Robotics",
        "Legged locomotion",
        "Model predictive control",
    )


def test_german_and_turkish_abbreviations_survive():
    lines = [
        "Der Lehrstuhl wird von Prof. Dr.-Ing. B. Müller geleitet. Wir forschen an Robotik.",
        "Bölüm Başkanı Prof. Dr. C. Yılmaz robotik üzerine çalışmaktadır. "
        "Laboratuvarımız 2019'da kuruldu.",
    ]
    out = page_sentences(lines)
    assert out[0] == "Der Lehrstuhl wird von Prof. Dr.-Ing. B. Müller geleitet."
    assert out[2] == "Bölüm Başkanı Prof. Dr. C. Yılmaz robotik üzerine çalışmaktadır."


def test_table_rows_and_blank_lines_are_handled():
    assert page_sentences(["| Name | Topic |", "", "| Schmidt | Locomotion |"]) == (
        "Name | Topic",
        "Schmidt | Locomotion",
    )


def test_a_very_short_fragment_is_dropped():
    assert page_sentences(["Contact.", "The Chair of Robotics hosts theses on locomotion."]) == (
        "The Chair of Robotics hosts theses on locomotion.",
    )
