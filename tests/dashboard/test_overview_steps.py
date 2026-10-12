"""The five milestones on the student's home page: one current until all are done."""

from apps.dashboard.overview import Overview


def _overview(**over):
    base = dict(
        applications=0,
        active=0,
        decided=0,
        column_counts=(),
        documents_done=0,
        documents_total=0,
        answers_done=0,
        answers_total=0,
        needs=0,
        pack_programmes=0,
        pack_published=False,
        funding_gap=(),
        deadlines=(),
    )
    return Overview(**{**base, **over})


def test_a_new_student_starts_at_the_profile():
    assert _overview().steps == (
        ("profile", "current"),
        ("matches", "todo"),
        ("choose", "todo"),
        ("documents", "todo"),
        ("apply", "todo"),
    )


def test_the_current_step_moves_on_as_steps_are_done():
    steps = dict(_overview(profile_done=True, applications=2, documents_total=3).steps)
    assert steps == {
        "profile": "done",
        "matches": "done",
        "choose": "done",
        "documents": "current",
        "apply": "todo",
    }


def test_a_published_pack_moves_the_student_to_choosing():
    steps = dict(_overview(profile_done=True, pack_published=True, pack_programmes=4).steps)
    assert steps["matches"] == "done"
    assert steps["choose"] == "current"


def test_everything_done_hides_the_steps():
    done = _overview(
        profile_done=True, applications=1, documents_total=1, documents_done=1, submitted=1
    )
    assert done.all_steps_done
