"""Stand in for the research worker on a LOCAL machine.

    DJANGO_DEBUG=true uv run python scripts/local_research.py          # once
    DJANGO_DEBUG=true uv run python scripts/local_research.py --watch  # keep running

In production a finished consultation puts a message on the research queue
(SQS) and the worker builds the student's pack. A developer machine has no
queue, so a student who signs up locally waits forever. This script finds every
run that has no pack yet and runs the real handler in-process, exactly as
scripts/seed_demo.py does for the demo student. It adds no behaviour to the app.

The exchange rates are a fixed demo table (the app has no production rate
source yet; see apps/research/services.handle_research_message). Never run this
against a real database.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
os.environ.setdefault("DJANGO_DEBUG", "true")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

if settings.DATABASES["default"]["HOST"] not in {"127.0.0.1", "localhost"}:
    sys.exit("Refusing: local_research only runs against a local database.")

POLL_SECONDS = 5


def _demo_rates():  # type: ignore[no-untyped-def]
    from apps.funding.fx import RateTable

    return RateTable(
        base="EUR",
        rates={
            "EUR": Decimal("1"),
            "USD": Decimal("1.0850"),
            "GBP": Decimal("0.8450"),
            "INR": Decimal("94.5000"),
            "PKR": Decimal("302.0000"),
            "CNY": Decimal("7.8000"),
            "AZN": Decimal("1.8450"),
            "KRW": Decimal("1480.0000"),
            "TRY": Decimal("37.0000"),
        },
        source="LOCAL-DEMO",
        retrieved_on=date.today(),
    )


def process_pending() -> int:
    from django.db import transaction

    from apps.funding.models import PackVersion, RecommendationRun
    from apps.research.schemas import ResearchMessage
    from apps.research.services import handle_research_message
    from apps.research.worker import process_research_message
    from apps.tenancy.context import tenant_scope
    from apps.tenancy.db import set_local_tenant
    from apps.tenancy.models import Agency

    rates = _demo_rates()
    done = 0
    for tenant_id in Agency.objects.values_list("id", flat=True):
        with transaction.atomic(), tenant_scope(tenant_id):
            set_local_tenant(tenant_id)
            packed = PackVersion.objects.values_list("run_id", flat=True)
            run_ids = list(
                RecommendationRun.objects.exclude(id__in=packed).values_list("id", flat=True)
            )
        for run_id in run_ids:
            message = ResearchMessage(kind="run_research", tenant_id=tenant_id, run_id=run_id)
            try:
                process_research_message(
                    message, lambda value: handle_research_message(value, rates=rates)
                )
            except Exception as error:  # a local helper: report and carry on
                print(f"run {run_id}: failed: {type(error).__name__}: {error}")
                continue
            done += 1
            print(f"run {run_id}: pack published")
    return done


def main() -> None:
    watch = "--watch" in sys.argv
    if not watch:
        print(f"{process_pending()} run(s) processed.")
        return
    print(f"Watching for new research runs every {POLL_SECONDS}s. Ctrl+C to stop.")
    try:
        while True:
            process_pending()
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
