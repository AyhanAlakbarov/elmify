"""Design-lint-baseline defect 2: the wizard shows human labels, never raw keys."""

from apps.accounts.consultation import QUESTION_LABELS, QUESTIONS


def test_every_question_has_a_human_label():
    for question in QUESTIONS:
        assert question.label, question.key
        assert question.label != question.key
        assert "_" not in question.label, question.key


def test_no_orphan_labels():
    keys = {question.key for question in QUESTIONS}
    assert set(QUESTION_LABELS) == keys
