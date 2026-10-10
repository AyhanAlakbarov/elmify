import json

import pytest
from django.core.management import call_command

from apps.research.models import SiteJobRecord

pytestmark = pytest.mark.django_db


def _corpus(tmp_path, rows):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(rows))
    return str(path)


def test_a_found_page_the_corpus_disagrees_with_is_a_FALSE_STOP(tmp_path, capsys):
    """Spec 7.0: 'A false stop -- a page triaged documents-list that the
    corpus says is not the programme's -- is counted by the corpus beside the
    misses, because the stop rule is only as good as D3's documents-list
    kind.' A stop rule scored only on recall looks perfect while stopping on
    the wrong page every time."""
    program_id = "11111111-1111-1111-1111-111111111111"
    SiteJobRecord.objects.create(
        program_id=program_id, source_url="https://uni.example.org/msc-ai/",
        admissions_cycle="2027", outcome="found", stopped_at_stage=2,
        searched={}, leads=["https://uni.example.org/faq/"], credits={},
    )
    corpus = _corpus(
        tmp_path,
        [{"source_url": "https://uni.example.org/msc-ai/", "admissions_cycle": "2027",
          "requirement_urls": ["https://uni.example.org/apply/documents/"], "decoy_urls": []}],
    )

    call_command("score_funnel", "--corpus", corpus)

    out = capsys.readouterr().out
    assert "false_stops=1" in out
    assert "found=1" in out


def test_a_stage_that_found_nothing_the_earlier_ones_missed_is_reported(tmp_path, capsys):
    """Spec 7.0: each stage is scored by itself, so a stage that never finds a
    page the earlier ones missed is REMOVED, not kept for comfort. The number
    that says so is this one."""
    program_id = "22222222-2222-2222-2222-222222222222"
    SiteJobRecord.objects.create(
        program_id=program_id, source_url="https://uni.example.org/msc-ai/",
        admissions_cycle="2027", outcome="found", stopped_at_stage=2,
        searched={"map": 40, "crawl": 25, "guided_map": 50, "navigator": 3},
        leads=["https://uni.example.org/apply/documents/"], credits={},
    )
    corpus = _corpus(
        tmp_path,
        [{"source_url": "https://uni.example.org/msc-ai/", "admissions_cycle": "2027",
          "requirement_urls": ["https://uni.example.org/apply/documents/"], "decoy_urls": []}],
    )

    call_command("score_funnel", "--corpus", corpus)

    out = capsys.readouterr().out
    assert "stage2_first=1" in out
    assert "stage3_first=0" in out
    assert "stage4_first=0" in out


def test_a_miss_is_counted_separately_from_a_block(tmp_path, capsys):
    """'Found nothing' and 'could not look' are different rows -- the failure
    this whole engine exists to remove, and a score that merges them
    re-creates it inside the instrument that is supposed to measure it."""
    SiteJobRecord.objects.create(
        program_id="33333333-3333-3333-3333-333333333333",
        source_url="https://uni.example.org/a/", admissions_cycle="2027",
        outcome="not_found", stopped_at_stage=5, searched={}, leads=[], credits={},
    )
    SiteJobRecord.objects.create(
        program_id="44444444-4444-4444-4444-444444444444",
        source_url="https://uni.example.org/b/", admissions_cycle="2027",
        outcome="blocked", stopped_at_stage=1, searched={}, leads=[], credits={},
    )
    corpus = _corpus(
        tmp_path,
        [
            {"source_url": "https://uni.example.org/a/", "admissions_cycle": "2027",
             "requirement_urls": ["https://uni.example.org/a/apply/"], "decoy_urls": []},
            {"source_url": "https://uni.example.org/b/", "admissions_cycle": "2027",
             "requirement_urls": ["https://uni.example.org/b/apply/"], "decoy_urls": []},
        ],
    )

    call_command("score_funnel", "--corpus", corpus)

    out = capsys.readouterr().out
    assert "not_found=1" in out
    assert "blocked=1" in out
