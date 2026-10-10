"""AWARD_DISPUTED: the funding reader files it, and withdraws it (plan Task 8).

The reader's two writers decide, per row, whether a person is needed. What
files: UNAGREED, and AGREED-but-unservable, neither reviewed nor suspended.
What does not: ABSTAINED (a reading failed -- the reader's retry, not a
person's question), WITHDRAWN and a suspension (the page's own words decided).
What withdraws: a row that is served, suspended, or withdrawn by a re-read.
"""

from io import StringIO
from typing import get_args
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.funding.models import (
    FundingOpportunity,
    Institution,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)
from apps.research import funding_judge
from apps.research.discovery import ResearchLead
from apps.research.funding_judge import FundingDecision
from apps.research.funding_reader import (
    withdraw_unread,
    write_funding_decision,
    write_holder_decision,
)
from apps.research.models import ResolutionItem
from apps.research.resolution import apply as applier
from apps.research.resolution.kinds import AwardDisputedEvidence
from apps.research.resolution.writers import AWARD_VOCABULARIES, award_choices

pytestmark = pytest.mark.django_db

WAIVER = "All admitted international students receive a 50% tuition waiver."
SHA = "a" * 64


@pytest.fixture
def program():
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}", name="Example University", country_code="DE",
        official_website="https://university.example.test",
    )
    return Program.objects.create(
        institution=institution, canonical_key=f"program:{uuid4()}", name="MSc Chemistry",
        campus_name="Main", city="Berlin", country_code="DE", location_key="de:berlin",
        degree_level="MASTER", teaching_languages=["English"], duration_months=24,
    )


def _snapshot(url: str = "https://university.example.test/msc-chemistry", sha: str = SHA):
    source, _ = OfficialSource.objects.get_or_create(
        canonical_url=url,
        defaults={"publisher": "university.example.test",
                  "source_type": OfficialSource.Type.PROGRAM},
    )
    return OfficialSourceSnapshot.objects.create(
        source=source, sha256=sha, s3_key=f"k-{uuid4().hex}", s3_version_id="v", byte_size=10,
        final_url=url, redirect_chain=[], admissions_cycle="2027", retrieved_at=timezone.now(),
    )


def _lead(url: str = "https://university.example.test/msc-chemistry", by: str = "seed:eacea"):
    return ResearchLead.from_url(
        url, source_type="PROGRAM", funding_family="", discovered_by=by,
        one_programme_per_site=True,
    )


def _decision(agreement: str = "UNAGREED", **overrides) -> FundingDecision:
    fields = dict(
        kind="I2_PROGRAMME_ATTACHED", scope="PROGRAM", offered="YES",
        internationals_included="YES", nationality_shape="OPEN",
        route="AUTOMATIC_ON_ADMISSION", money_form="FEE_WAIVER", holder="INSTITUTION",
        tuition="PARTIAL", living="NONE", extras=(), obligation=(), agreement=agreement,
        quotes=(WAIVER,), name="Tuition waiver",
        disputed=("holder", "money_form", "timing") if agreement == "UNAGREED" else (),
    )
    fields.update(overrides)
    return FundingDecision(**fields)  # type: ignore[arg-type]


def _write(decision, program, snapshot, lead=None):
    return write_funding_decision(
        decision, program=program, lead=lead or _lead(snapshot.source.canonical_url),
        source=snapshot.source, snapshot=snapshot,
    )


def _items():
    return list(ResolutionItem.objects.filter(kind="AWARD_DISPUTED"))


# --- the vocabulary rule ------------------------------------------------------


def test_every_choice_is_the_judges_own_vocabulary_minus_unstated() -> None:
    """Never hand-copied: a label added to the judge reaches the operator's
    choices, and one removed stops being offered."""
    aliases = {
        "money_form": funding_judge._Money,
        "route": funding_judge._Route,
        "nationality_shape": funding_judge._Nationality,
        "internationals_included": funding_judge._Stated,
        "kind": funding_judge._Kind,
    }
    assert AWARD_VOCABULARIES == aliases
    for name, alias in aliases.items():
        assert award_choices(name) == [v for v in get_args(alias) if v != "UNSTATED"]
        assert "UNSTATED" not in award_choices(name)
        # A column the applier can set, and a label the judge decides.
        FundingOpportunity._meta.get_field(name)
        assert name in FundingDecision.__dataclass_fields__
    # The applier refuses any field not named here, so the two cannot drift.
    assert applier._AWARD_FIELDS == frozenset(aliases)


# --- filing ---------------------------------------------------------------------


def test_an_unagreed_write_files_one_item_naming_only_the_choosable_fields(program) -> None:
    snapshot = _snapshot()
    row = _write(_decision(), program, snapshot)
    (item,) = _items()
    assert item.subject_key == f"award:{row.canonical_key}" and item.state == "OPEN"
    evidence = AwardDisputedEvidence.model_validate(item.evidence)
    assert evidence.snapshot_sha256 == SHA
    assert evidence.page_url == snapshot.source.canonical_url
    assert evidence.quotes == [WAIVER] and evidence.award_name == "Tuition waiver"
    # `holder` is an existence field (the whole-row options answer it) and
    # `timing` has no column an operator may set: neither becomes a choice.
    assert [(d.field, d.choices) for d in evidence.disputed] == [
        ("money_form", award_choices("money_form"))
    ]
    assert evidence.why == "the readings disagreed"
    assert "money_form" in item.ask


def test_the_same_award_met_by_a_second_run_is_still_one_item(program) -> None:
    """Cross-tenant dedupe: two runs (two agencies' discover) reach one key."""
    snapshot = _snapshot()
    _write(_decision(), program, snapshot, lead=_lead(by="seed:eacea"))
    _write(_decision(), program, snapshot, lead=_lead(by="search:tenant-b"))
    assert len(_items()) == 1


def test_an_agreed_row_the_writer_would_not_serve_files_with_its_detail_disputes(
    program,
) -> None:
    """Tiered agreement: an AGREED row may still carry detail splits (blanked to
    UNSTATED). With no benefit and no form of money it is unservable, and the
    person's question is exactly the blanked field."""
    row = _write(
        _decision("AGREED", money_form="UNSTATED", tuition="NONE", disputed=("money_form",),
                  unconfirmed=("money_form",)),
        program, _snapshot(),
    )
    assert row.served is False
    (item,) = _items()
    evidence = AwardDisputedEvidence.model_validate(item.evidence)
    assert [d.field for d in evidence.disputed] == ["money_form"]
    assert evidence.why.startswith("agreed, but names no benefit")


def test_an_agreed_unservable_row_with_nothing_split_offers_only_the_whole_row(
    program,
) -> None:
    _write(_decision("AGREED", money_form="UNSTATED", tuition="NONE"), program, _snapshot())
    (item,) = _items()
    assert item.evidence["disputed"] == []
    assert "its benefit" in item.ask


def test_a_later_served_write_withdraws_it(program) -> None:
    snapshot = _snapshot()
    _write(_decision(), program, snapshot)
    assert len(_items()) == 1
    row = _write(_decision("AGREED"), program, snapshot)
    assert row.served is True
    assert _items() == []


def test_a_decided_item_is_never_withdrawn_by_a_write(program) -> None:
    """A person's answer is the applier's to apply or refuse, never silently dropped."""
    snapshot = _snapshot()
    _write(_decision(), program, snapshot)
    ResolutionItem.objects.update(
        state="DECIDED", resolution={"option": "not_an_award", "fields": {}, "note": ""},
        decided_at=timezone.now(),
    )
    _write(_decision("AGREED"), program, snapshot)
    assert [item.state for item in _items()] == ["DECIDED"]


def test_an_abstained_write_files_nothing(program) -> None:
    _write(_decision("ABSTAINED", disputed=("readings",)), program, _snapshot())
    assert _items() == []


def test_an_abstained_reread_leaves_a_filed_question_standing(program) -> None:
    """A failed reading answers nothing; the question stays live."""
    snapshot = _snapshot()
    _write(_decision(), program, snapshot)
    _write(_decision("ABSTAINED", disputed=("readings",)), program, snapshot)
    assert len(_items()) == 1


def test_a_suspension_files_nothing_and_withdraws_what_was_filed(program) -> None:
    snapshot = _snapshot()
    _write(_decision(), program, snapshot)
    _write(
        _decision("AGREED", offered="NO", suspension_quote="Not offered for the 2027 intake.",
                  applies_to="2027"),
        program, snapshot,
    )
    assert _items() == []


def test_a_row_the_reread_withdrew_takes_its_question_with_it(program) -> None:
    snapshot = _snapshot()
    _write(_decision(), program, snapshot)
    assert withdraw_unread(snapshot.source, snapshot, set()) == 1
    assert _items() == []


def test_a_row_with_no_quote_files_nothing_and_still_writes(program) -> None:
    """The evidence needs a quote to show; a missing one must never cost the
    catalogue write it rides in."""
    row = _write(_decision(quotes=()), program, _snapshot())
    assert row is not None and _items() == []


def test_the_holder_writer_files_and_withdraws_the_same_way() -> None:
    url = "https://example-foundation.org/stipend"
    snapshot = _snapshot(url)
    lead = ResearchLead.from_url(
        url, source_type="PROGRAM", funding_family="", discovered_by="seed:holder",
    )

    def write(decision):
        return write_holder_decision(
            decision, holder_domain="example-foundation.org", holder_name="Example Foundation",
            lead=lead, source=snapshot.source, snapshot=snapshot,
        )

    holder = dict(kind="I0_HOLDER_AWARD", scope="HOLDER_OWN", holder="PRIVATE_FOUNDATION")
    row = write(_decision(**holder, disputed=("route", "scope")))
    (item,) = _items()
    assert item.subject_key == f"award:{row.canonical_key}"
    assert [d["field"] for d in item.evidence["disputed"]] == ["route"]
    write(_decision("AGREED", **holder))
    assert _items() == []


# --- the backfill -------------------------------------------------------------


def _backfill() -> str:
    out = StringIO()
    call_command("file_award_disputes", stdout=out)
    return out.getvalue()


def test_the_backfill_files_what_the_writers_would_have_and_nothing_else(program) -> None:
    # A heading each: one programme, one kind, one heading is one award (spec 8.7).
    unagreed = _write(_decision(heading="A"), program,
                      _snapshot("https://university.example.test/a"))
    unservable = _write(
        _decision("AGREED", money_form="UNSTATED", tuition="NONE", heading="B"),
        program, _snapshot("https://university.example.test/b"),
    )
    _write(_decision("AGREED", heading="C"), program,
           _snapshot("https://university.example.test/c"))
    _write(_decision("ABSTAINED", disputed=("readings",), heading="D"),
           program, _snapshot("https://university.example.test/d"))
    ResolutionItem.objects.all().delete()  # rows written before the queue existed

    text = _backfill()
    assert "filed=2 skipped=1" in text
    assert {i.subject_key for i in _items()} == {
        f"award:{unagreed.canonical_key}", f"award:{unservable.canonical_key}"
    }
    assert "filed=2 skipped=1" in _backfill()  # idempotent: one item per subject
    assert len(_items()) == 2


def test_the_backfill_binds_the_latest_page_version(program) -> None:
    first = _snapshot(sha="b" * 64)
    row = _write(_decision(), program, first)
    newer = _snapshot(sha="c" * 64)
    _write(_decision(), program, newer)
    ResolutionItem.objects.all().delete()
    _backfill()
    (item,) = _items()
    assert item.subject_key == f"award:{row.canonical_key}"
    assert item.evidence["snapshot_sha256"] == "c" * 64
