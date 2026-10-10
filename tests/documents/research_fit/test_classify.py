from apps.documents.research_fit.classify import (
    Classified,
    ClassifiedItem,
    ClassifiedSentence,
    FrontierClassifier,
    entity_in_sentence,
)


class _Response:
    def __init__(self, parsed):
        self.output_parsed = parsed
        self.output = []


class _Parser:
    def __init__(self, *parsed):
        self.responses = [_Response(p) for p in parsed]
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


_SENTENCES = (
    "Prof. Dr. A. Schmidt leads the Chair of Robotics.",
    "We work on legged locomotion and model predictive control.",
    "The canteen is open from 11 to 14.",
)


def test_entity_must_be_a_verbatim_substring():
    assert entity_in_sentence("Chair of Robotics", _SENTENCES[0]) == "Chair of Robotics"
    assert entity_in_sentence("chair of robotics", _SENTENCES[0]) == "Chair of Robotics"
    assert entity_in_sentence("Robotics Lab", _SENTENCES[0]) is None
    assert entity_in_sentence(None, _SENTENCES[0]) is None


def test_the_frontier_classifier_labels_data_and_verifies_entities():
    parsed = Classified(items=(
        ClassifiedItem(
            index=0, relevance=0.9, kind="research_group", entity="Chair of Robotics"
        ),
        # not on the sentence
        ClassifiedItem(
            index=1, relevance=0.95, kind="research_group", entity="Robotics Lab"
        ),
        ClassifiedItem(index=2, relevance=0.05, kind="none", entity=None),
    ))
    parser = _Parser(parsed)
    out = FrontierClassifier(parser, student_id="s").classify(
        _SENTENCES, topic="legged locomotion"
    )
    assert out[0] == ClassifiedSentence(
        index=0, relevance=0.9, kind="research_group", entity="Chair of Robotics"
    )
    assert out[1] == ClassifiedSentence(index=1, relevance=0.95, kind="none", entity=None)
    assert out[2].kind == "none"
    call = parser.calls[0]
    assert call["text_format"] is Classified and call["store"] is False
    assert call["max_output_tokens"] == 4_000
    developer, user = call["input"]
    assert "DATA" in developer["content"] and "legged locomotion" in developer["content"]
    assert "0 | Prof. Dr. A. Schmidt leads the Chair of Robotics." in user["content"]


def test_an_off_schema_reading_yields_nothing_not_an_exception():
    class _Bad:
        def parse(self, **kwargs):
            raise ValueError("off-schema")

    assert FrontierClassifier(_Bad(), student_id="s").classify(_SENTENCES, topic="t") == ()


def test_indices_outside_the_listing_are_dropped():
    parsed = Classified(items=(
        ClassifiedItem(index=99, relevance=1.0, kind="research_group", entity="x"),
    ))
    out = FrontierClassifier(_Parser(parsed), student_id="s").classify(_SENTENCES, topic="t")
    assert out == ()


def test_an_entity_after_a_character_casefold_lengthens_is_returned_whole():
    """PR #114 review: casefold is not length-preserving, so slicing the
    ORIGINAL string with casefolded offsets came back a character short --
    "rof. Dr. B. Muller" -- and that string is what the letter is told to
    write. It still passed the claim check and the re-check, so nothing
    surfaced it. Measured on the two page languages this module targets."""
    from apps.documents.research_fit.classify import entity_in_sentence

    german = "Der Lehrstuhl für Fußrobotik wird von Prof. Dr. B. Müller geleitet."
    assert entity_in_sentence("Prof. Dr. B. Müller", german) == "Prof. Dr. B. Müller"
    turkish = "İstanbul Teknik Üniversitesi Robotik Laboratuvarı yürüyen robotlar üzerine çalışır."
    assert entity_in_sentence("Robotik Laboratuvarı", turkish) == "Robotik Laboratuvarı"
    assert entity_in_sentence("Nobody At All", german) is None
