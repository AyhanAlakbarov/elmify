import pytest
from django.core.management import call_command

from apps.funding.models import OfficialSourceSnapshot

pytestmark = pytest.mark.django_db


def test_a_changed_page_marks_its_snapshot_stale(monkeypatch, snapshot_factory):
    """Spec 8: `changed` -> the reader. The reader's own trigger is already in
    the schema -- `retrieval_status = STALE` is what `snapshot.is_stale`
    answers -- so the poller sets it rather than inventing a second queue.

    It does NOT enqueue a ResearchMessage: that queue is FIFO by TENANT and
    the poller runs platform-wide with no tenant scope, so every message it
    wrote would go to one arbitrary group or to none."""
    snapshot = snapshot_factory(final_url="https://uni.example.org/apply/")
    monkeypatch.setattr(
        "apps.research.management.commands.poll_monitor_checks.list_checks",
        lambda **kwargs: (
            _Page(url="https://uni.example.org/apply/", status="changed"),
        ),
    )

    call_command("poll_monitor_checks", "--monitor", "m1")

    snapshot.refresh_from_db()
    assert snapshot.retrieval_status == OfficialSourceSnapshot.RetrievalStatus.STALE


def test_a_new_page_enters_the_ladder(monkeypatch):
    """`new` -> the ladder, then the reader. A page the monitor discovered has
    never been fetched by us, so it has no snapshot to mark stale."""
    fetched = []
    monkeypatch.setattr(
        "apps.research.management.commands.poll_monitor_checks.list_checks",
        lambda **kwargs: (_Page(url="https://uni.example.org/new/", status="new"),),
    )
    monkeypatch.setattr(
        "apps.research.management.commands.poll_monitor_checks.fetch_page",
        lambda url, **kwargs: fetched.append(url),
    )

    call_command("poll_monitor_checks", "--monitor", "m1")

    assert fetched == ["https://uni.example.org/new/"]


def test_a_removed_page_is_recorded_on_its_snapshot_not_as_a_task(
    monkeypatch, snapshot_factory
):
    """Spec 8 calls this 'a catalog review row'. It is NOT written as a
    ConsultantResearchTask: that model is TenantScopedModel and the poller
    runs with no tenant scope, so the row would be written under a null
    tenant and be invisible to every agency -- or refused outright by RLS.
    The snapshot's own FAILED status is the catalog-visible fact, and the
    owner console reads it."""
    from apps.research.models import ConsultantResearchTask

    snapshot = snapshot_factory(final_url="https://uni.example.org/gone/")
    monkeypatch.setattr(
        "apps.research.management.commands.poll_monitor_checks.list_checks",
        lambda **kwargs: (_Page(url="https://uni.example.org/gone/", status="removed"),),
    )

    call_command("poll_monitor_checks", "--monitor", "m1")

    snapshot.refresh_from_db()
    assert snapshot.retrieval_status == OfficialSourceSnapshot.RetrievalStatus.FAILED
    # `.objects` is TenantManager and raises TenantContextMissing outside a
    # tenant_scope, exactly as it should -- the poller runs with none. The
    # assertion needs to see across every tenant (and no tenant), which is
    # `_base_manager` (CLAUDE.md: "Model._base_manager skips it").
    assert ConsultantResearchTask._base_manager.count() == 0


class _Page:
    def __init__(self, url, status):
        self.url = url
        self.status = status
