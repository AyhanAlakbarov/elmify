from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.funding.models import OfficialSource
from apps.research.egress import FetchResult
from apps.research.snapshot import persist_snapshot


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: list[tuple[str, bytes]] = []

    def put(self, key: str, body: bytes) -> str:
        self.objects.append((key, body))
        return "version-1"


@pytest.mark.django_db
def test_snapshot_stores_body_in_object_storage_and_metadata_in_postgres() -> None:
    source = OfficialSource.objects.create(
        canonical_url="https://official.example/program",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    store = MemoryObjectStore()
    result = persist_snapshot(
        source=source,
        fetch=FetchResult(
            "https://official.example/program",
            ("https://official.example/start",),
            "text/html",
            b"official body",
        ),
        store=store,
        admissions_cycle="2027",
        retrieved_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert store.objects == [(result.s3_key, b"official body")]
    assert result.s3_version_id == "version-1"
    assert result.sha256 == "62a1c97ac2be209866e770e905bb11268f8e247ee0e66fbd318117988f234865"
    assert result.final_url == "https://official.example/program"
    assert result.redirect_chain == ("https://official.example/start",)
    assert result.byte_size == 13
    assert result.admissions_cycle == "2027"
    assert "body" not in {field.name for field in result.snapshot._meta.fields}
    assert result.snapshot.fetched_via == "EGRESS"


@pytest.mark.django_db
def test_a_snapshot_records_which_tier_fetched_it() -> None:
    """Funder spec §4.3: a vendor body is the vendor's rendering, and the row says so."""
    source = OfficialSource.objects.create(
        canonical_url="https://official.example/p",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    fetch = FetchResult(
        "https://official.example/p", (), "text/html", b"<p>x</p>", fetched_via="SCRAPE_DO"
    )

    result = persist_snapshot(
        source=source, fetch=fetch, store=MemoryObjectStore(), admissions_cycle="2027"
    )

    assert result.snapshot.fetched_via == "SCRAPE_DO"


@pytest.mark.django_db
def test_browser_render_metadata_is_persisted_without_dom_or_screenshot_bytes() -> None:
    source = OfficialSource.objects.create(
        canonical_url="https://official.example/rendered",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    result = persist_snapshot(
        source=source,
        fetch=FetchResult(
            "https://official.example/rendered",
            (),
            "text/html",
            b"rendered body",
        ),
        store=MemoryObjectStore(),
        admissions_cycle="2027",
        render_metadata=SimpleNamespace(
            dom_key="renders/dom/1.html",
            screenshot_key="renders/screenshot/1.png",
            status="SUCCEEDED",
        ),
    )

    assert result.snapshot.dom_object_key == "renders/dom/1.html"
    assert result.snapshot.screenshot_object_key == "renders/screenshot/1.png"
    assert result.snapshot.render_status == "SUCCEEDED"
    assert not hasattr(result.snapshot, "dom_bytes")
    assert not hasattr(result.snapshot, "screenshot_bytes")


@pytest.mark.django_db
def test_new_snapshot_supersedes_the_last_reviewed_snapshot() -> None:
    source = OfficialSource.objects.create(
        canonical_url="https://official.example/versioned",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    previous = persist_snapshot(
        source=source,
        fetch=FetchResult("https://official.example/versioned", (), "text/html", b"old"),
        store=MemoryObjectStore(),
        admissions_cycle="2027",
    )
    previous.snapshot.reviewed_at = previous.snapshot.retrieved_at
    previous.snapshot.save(update_fields=["reviewed_at"])

    current = persist_snapshot(
        source=source,
        fetch=FetchResult("https://official.example/versioned", (), "text/html", b"new"),
        store=MemoryObjectStore(),
        admissions_cycle="2027",
    )

    assert current.snapshot.supersedes_id == previous.snapshot.id
    assert current.snapshot.reviewed_at is None
