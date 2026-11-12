"""Every bullet that survives is quoted from the evidence, carries only the evidence's
numbers, and has a support verdict."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.test import override_settings

from apps.documents.evidence.checks import (
    SUPPORT_LIMIT,
    CheckedBullet,
    check,
    numbers_supported,
    support,
)
from apps.documents.evidence.extraction import ReadBullet, RepoReading, Technique
from apps.ratelimit import rate_limited
from apps.research.decisions import DecisionsUnavailable

from .fakes import answering

EVIDENCE = (
    "Description: Benchmark of Gaussian process surrogates\n\n"
    "Trained on 10B tokens.  It reached   92% accuracy on 3.88M rows.\n"
    "--- README.md ---\nUses PCA to reduce descriptors. Project NHC-BO."
)


def _reading(*bullets, **fields):
    return RepoReading(summary=fields.pop("summary", "Surrogate benchmark."), kind="project",
                       bullets=bullets or (ReadBullet(text="Benchmarked surrogates.",
                                                      evidence=("Gaussian process surrogates",)),),
                       **fields)


def test_a_quote_not_in_the_evidence_drops_the_bullet():
    kept = ReadBullet(text="Benchmarked GP surrogates.",
                      evidence=("benchmark of  GAUSSIAN process surrogates",))
    invented = ReadBullet(text="Led a team of five.", evidence=("led a team of five",))
    checked = check(_reading(kept, invented), EVIDENCE)
    assert [b.text for b in checked.bullets] == ["Benchmarked GP surrogates."]
    assert checked.dropped == 1


def test_a_bullet_keeps_only_its_surviving_spans():
    bullet = ReadBullet(text="Benchmarked surrogates.",
                        evidence=("Gaussian process surrogates", "not in the evidence"))
    [kept] = check(_reading(bullet), EVIDENCE).bullets
    assert kept.evidence == ("Gaussian process surrogates",)


def test_a_number_missing_from_the_bullets_own_spans_drops_it():
    """10B is in the evidence, but not in this bullet's span: it is still dropped."""
    bullet = ReadBullet(text="Trained on 10B+ tokens to 92% accuracy.",
                        evidence=("It reached   92% accuracy",))
    checked = check(_reading(bullet), EVIDENCE)
    assert checked.bullets == () and checked.dropped == 1


def test_numbers_in_their_spans_survive():
    bullet = ReadBullet(text="Reached 92 % accuracy on 3.88M rows after 10B tokens.",
                        evidence=("Trained on 10B tokens.", "92% accuracy on 3.88M rows"))
    assert len(check(_reading(bullet), EVIDENCE).bullets) == 1


@pytest.mark.parametrize("text,source,ok", [
    ("10B", "10 billion", False),
    ("10B", "trained on 10B", True),
    ("92%", "92 percent", False),
    ("1,000 runs", "1000 runs", False),
    ("v2 of the tool", "no numbers", True),
    # Final review #7: a leading-dot decimal and a leading minus are numbers too.
    ("accuracy .95", "accuracy rose", False),
    ("accuracy .95", "reached accuracy .95 on test", True),
    ("-3 dB noise floor", "a 3 dB noise floor", False),
    ("-3 dB noise floor", "measured at -3 dB", True),
    ("built on v1.5", "no numbers", True),
    ("pages 10-20", "see pages 10-20", True),
])
def test_numbers_supported(text, source, ok):
    assert numbers_supported(text, source) is ok


def test_methods_outcomes_and_summary_lose_numbers_the_evidence_lacks():
    checked = check(
        _reading(methods="Reduced descriptors with PCA.", outcomes="Cut error by 40%.",
                 summary="A 7-model benchmark."),
        EVIDENCE,
    )
    assert checked.methods == "Reduced descriptors with PCA."
    assert checked.outcomes is None
    assert checked.summary == ""


def test_techniques_and_names_must_be_in_the_evidence():
    checked = check(
        _reading(techniques=(Technique(name="PCA", excerpt="Uses PCA"),
                             Technique(name="UMAP", excerpt="UMAP embedding")),
                 names=("NHC-BO", "Invented Lab")),
        EVIDENCE,
    )
    assert [t.name for t in checked.techniques] == ["PCA"]
    assert checked.names == ("NHC-BO",)


def _checked():
    return check(_reading(), EVIDENCE)


@pytest.mark.parametrize("value,confidence,verdict", [
    ("yes", 0.95, "supported"),
    ("yes", 0.9, "supported"),
    ("yes", 0.85, "rejected"),
    ("unsure", 0.99, "rejected"),
    ("no", 0.99, "rejected"),
])
def test_an_answer_stores_supported_or_rejected(value, confidence, verdict):
    checked = support(_checked(), student_id=uuid4(), client=answering(value, confidence))
    assert checked.bullets[0].verdict == verdict


def test_only_the_bullet_and_its_own_spans_are_sent():
    client = answering()
    support(_checked(), student_id=uuid4(), client=client)
    assert client.calls == [{"sentence": "Benchmarked surrogates.",
                             "evidence": ["Gaussian process surrogates"]}]


def test_a_failed_call_gives_unchecked():
    def failing(state, questions, *, model, provider):
        raise DecisionsUnavailable("down")

    [bullet] = support(_checked(), student_id=uuid4(), client=failing).bullets
    assert bullet.verdict == "unchecked"


def test_the_evidence_support_limit_gives_unchecked_without_a_call():
    student = uuid4()
    for _ in range(SUPPORT_LIMIT):
        rate_limited("evidence-support", student, limit=SUPPORT_LIMIT, window_seconds=3600)
    client = answering()
    [bullet] = support(_checked(), student_id=student, client=client).bullets
    assert bullet.verdict == "unchecked" and client.calls == []


@override_settings(DECISIONS_PROVIDER={"default": "adapter:openai"})
def test_student_text_is_never_routed_to_an_adapter():
    client = answering()
    [bullet] = support(_checked(), student_id=uuid4(), client=client).bullets
    assert bullet.verdict == "unchecked" and client.calls == []


def test_to_json_is_what_gets_stored():
    checked = support(check(_reading(techniques=(Technique(name="PCA", excerpt="Uses PCA"),)),
                            EVIDENCE),
                      student_id=uuid4(), client=answering())
    assert checked.to_json() == {
        "summary": "Surrogate benchmark.", "kind": "project",
        "bullets": [{"text": "Benchmarked surrogates.",
                     "evidence": ["Gaussian process surrogates"], "verdict": "supported"}],
        "methods": None, "outcomes": None,
        "techniques": [{"name": "PCA", "excerpt": "Uses PCA"}], "names": [],
    }
    assert isinstance(checked.bullets[0], CheckedBullet)


def test_the_support_decision_has_its_own_provider_mapping(settings):
    """Spec §7.4: a new decision id gets a provider_for mapping (decisions.py:243). It
    names typesafe; support() still refuses any other answer (the test above)."""
    assert settings.DECISIONS_PROVIDER["evidence_support"] == "typesafe"


@pytest.mark.parametrize("evidence,text,span", [
    ("Processed 3.88M rows in the pilot.", "Processed 88M rows.", "88M rows"),
    ("Funded by the 1,500 EUR grant.", "Won a 500 EUR grant.", "500 EUR grant"),
    ("Accuracy 0.92 on test.", "Reached 92 on test.", "92 on test"),
    ("Led a team of engineers.", "Led a team of engineers.", "e"),
    ("We ranked 1 of 5 teams. The M parameter was tuned.", "Fit a 1M parameter model.",
     "ranked 1"),
])
def test_a_span_cut_inside_a_word_or_number_drops_the_bullet(evidence, text, span):
    spans = (span, "M parameter") if span == "ranked 1" else (span,)
    checked = check(_reading(ReadBullet(text=text, evidence=spans)), evidence)
    assert checked.bullets == () and checked.dropped == 1


def test_a_name_must_be_a_whole_word_in_the_evidence():
    assert check(_reading(names=("MIT",)), EVIDENCE + " Was submitted.").names == ()


@pytest.mark.parametrize(
    "slop_bullet",
    [
        "Benchmarked surrogates \u2014 achieving fast convergence.",
        "Benchmarked surrogates, highlighting the model's versatility.",
        "Spearheaded a pivotal moment in Gaussian process surrogates.",
    ],
)
def test_bullets_and_fields_with_ai_slop_not_in_evidence_are_dropped(slop_bullet):
    bullet = ReadBullet(text=slop_bullet, evidence=("Gaussian process surrogates",))
    checked = check(
        _reading(
            bullet,
            methods="Reduced descriptors with PCA, underscoring its significance.",
            outcomes="Delved into surrogate accuracy.",
        ),
        EVIDENCE,
    )
    assert checked.bullets == ()
    assert checked.dropped == 1
    assert checked.methods is None
    assert checked.outcomes is None

