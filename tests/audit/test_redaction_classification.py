"""The erasure classification must cover every field FK-reachable from Membership.

student_reachable_models() walks forward FKs transitively from Membership, so
this guarantees classification only for a model reachable that way -- not,
despite the module's former claim, "every field that can reach a student".
A model holding student-derived data with no FK path is invisible to this
walk and gets no classification, silently: documents.EuropassRenderCache is a
live example, keyed by a payload sha256 with no student FK at all, storing a
key that names the membership.

This test fails when someone adds a field to a model the walk DOES reach.
That is the point: it stops the build until erasure has an answer for the new
field. It says nothing about a model the walk cannot see.
"""

from apps.audit.redaction import (
    KEEP,
    REDACT,
    UNDECIDED,
    classifiable_fields,
    student_reachable_models,
)


def _label(model):
    return f"{model._meta.app_label}.{model.__name__}"


def test_every_reachable_field_is_classified_exactly_once():
    unclassified = []
    duplicated = []
    for model in student_reachable_models():
        label = _label(model)
        classes = {
            "REDACT": set(REDACT[label].fields) if label in REDACT else set(),
            "KEEP": set(KEEP.get(label, ())),
            "UNDECIDED": set(UNDECIDED.get(label, ())),
        }
        for name in classifiable_fields(model):
            holders = [cls for cls, names in classes.items() if name in names]
            if not holders:
                unclassified.append(f"{label}.{name}")
            elif len(holders) > 1:
                duplicated.append(f"{label}.{name} in {holders}")
    assert not unclassified, "unclassified fields:\n  " + "\n  ".join(sorted(unclassified))
    assert not duplicated, "multiply classified:\n  " + "\n  ".join(sorted(duplicated))


def test_classification_names_no_field_that_does_not_exist():
    """A typo in the map is silent otherwise: it classifies nothing and hides a real field."""
    reachable = {_label(m): set(classifiable_fields(m)) for m in student_reachable_models()}
    stale = []
    for mapping, names in (
        ("REDACT", {k: v.fields for k, v in REDACT.items()}),
        ("KEEP", KEEP),
        ("UNDECIDED", UNDECIDED),
    ):
        for label, fields in names.items():
            if label not in reachable:
                stale.append(f"{mapping}: {label} is not student-reachable")
                continue
            for field in fields:
                if field not in reachable[label]:
                    stale.append(f"{mapping}: {label}.{field} does not exist")
    assert not stale, "stale classification entries:\n  " + "\n  ".join(sorted(stale))


def test_every_redact_model_has_a_subject_path():
    """Without a path, redact_student cannot find that model's rows for one student.

    The path is hand-written per model because a shortest-path search picks the
    wrong FK: ManualOperation.actor is the staff member, not the subject.
    """
    missing = [label for label, spec in REDACT.items() if not spec.subject]
    assert not missing, f"REDACT entries with no subject path: {missing}"


def test_erasure_refuses_to_run_while_anything_is_undecided():
    """UNDECIDED is a launch blocker made visible, not a parking lot.

    Delete this assertion only together with the last UNDECIDED entry.
    """
    assert UNDECIDED == {}, (
        "fields still awaiting a retention decision (phased requirements.md §10): "
        f"{UNDECIDED}"
    )


def test_walk_uses_forward_fks_and_sees_the_hidden_models():
    """A reverse walk misses models declaring related_name='+'.

    ConversationMessage.body is the counselor's free-text correspondence about
    the student and has no reverse accessor. Do not 'simplify' the walk to
    Membership._meta.related_objects.
    """
    labels = {_label(m) for m in student_reachable_models()}
    for hidden in (
        "concierge.ConversationMessage",
        "documents.ConsentEvent",
        "documents.RevisionRequest",
        "funding.ConstraintOverride",
    ):
        assert hidden in labels, f"{hidden} not reached: the walk went backwards"


def test_walk_reaches_models_that_are_more_than_one_hop_away():
    """A one-hop scan misses ApplicationStep.detail -- the values typed into a
    third-party application form -- and ConsultationReport, both REDACT."""
    labels = {_label(m) for m in student_reachable_models()}
    for distant in (
        "portals.ApplicationStep",
        "reports.ConsultationReport",
        "funding.RecommendationCandidate",
        "concierge.Receipt",
    ):
        assert distant in labels, f"{distant} not reached: the walk stopped at one hop"
