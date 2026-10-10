import hashlib

import pytest
from django.db import IntegrityError

from apps.research.models import GoldItem


@pytest.mark.django_db
def test_a_fact_is_queued_once_per_run_round_and_purpose():
    kw = dict(run="r1", kind="deadline", question="application_date", language="az",
              page_url="https://edu.gov.az/x", line_text="Müraciət 15 yanvar 2027-dək.",
              heading="", claim="This line states a deadline or period for applying.",
              round=1, purpose="improvement")
    GoldItem.objects.create(**kw)
    with pytest.raises(IntegrityError):
        GoldItem.objects.create(**kw)


@pytest.mark.django_db
def test_an_unlabelled_item_has_an_empty_verdict():
    item = GoldItem.objects.create(
        run="r1", kind="money", question="money_to_student", language="en",
        page_url="https://x.org", line_text="A stipend of 43,000 HUF.",
        heading="", claim="c", round=1, purpose="certification",
    )
    assert item.verdict == "" and item.labelled_at is None


@pytest.mark.django_db
def test_a_long_line_saves_and_is_keyed_by_its_hash():
    line = "x" * 6000
    item = GoldItem.objects.create(
        run="r1", kind="money", question="money_to_student", language="en",
        page_url="https://x.org", line_text=line, claim="c", round=1, purpose="improvement",
    )
    assert item.line_sha256 == hashlib.sha256(line.encode()).hexdigest()
