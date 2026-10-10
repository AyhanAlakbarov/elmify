import pytest
from django.utils import timezone

from apps.documents import europass_render
from apps.documents.europass import EuropassThrottled, EuropassUnavailable
from apps.documents.europass_render import (
    CircuitOpen,
    payload_hash,
    render_and_store,
)
from apps.documents.models import DocumentDraft, EuropassCircuit, EuropassRenderCache
from apps.documents.storage import document_key
from apps.tenancy import db as tenancy_db
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _approved_draft(agency, django_user_model, name):
    from apps.documents.drafts import create_draft

    from .test_render import _content

    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
    DocumentDraft.objects.filter(id=draft.id).update(
        status=DocumentDraft.Status.APPROVED, render_variant="EUROPASS_API"
    )
    draft.refresh_from_db()
    return draft


class _FakeStore:
    def __init__(self):
        self.puts = []
        self.objects = {}

    def put(self, key, content):
        self.puts.append((key, content))
        self.objects[key] = content

    def get(self, key):
        # A plain dict lookup, because that is now exactly what the real
        # S3ObjectStore.get does for a missing object: raise KeyError.
        return self.objects[key]


def _genuine_pdf():
    import pathlib

    return pathlib.Path("tests/documents/fixtures/europass_api.pdf").read_bytes()


def test_the_payload_hash_is_stable_and_content_derived():
    from .test_europass import _content as _cv

    assert payload_hash(_cv()) == payload_hash(_cv())
    changed = _cv(document_language="fr")
    assert payload_hash(changed) != payload_hash(_cv())


def test_a_non_europass_variant_refuses_before_any_hash_or_call(
    agency_a, django_user_model, monkeypatch
):
    """render_draft dispatches on draft.render_variant or "STANDARD"
    (apps/documents/render.py), so a STANDARD/EUROPASS/GERMAN_TABULAR/blank
    draft must never reach the Europass payload hash, the cache, or
    render_draft at all. Without this guard, payload_hash() computes the
    Europass digest regardless of variant, render_cv takes a branch that
    never calls assert_europass_provenance, and the result would be stored
    under the Europass artefact filename and cached under the Europass
    hash -- so a later genuine EUROPASS_API draft with the same content
    would take the cache-hit path and be handed back that non-Europass
    PDF with called_remote=False."""
    monkeypatch.setattr(
        europass_render, "render_draft", lambda **kw: pytest.fail("called europa.eu")
    )
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "non-europass")
        DocumentDraft.objects.filter(id=draft.id).update(render_variant="STANDARD")
        draft.refresh_from_db()
        with pytest.raises(EuropassUnavailable):
            render_and_store(draft=draft, store=_FakeStore())
        assert EuropassRenderCache.objects.count() == 0


def test_a_cache_hit_makes_no_remote_call(agency_a, django_user_model, monkeypatch):
    """A cache row already keyed to THIS draft, with its object present in
    S3, is the ordinary redelivery case: no europa.eu call, and no re-store
    PUT -- the key is already right. Its presence is still verified with a
    GET (see the stale-row tests below for when it is not present)."""
    monkeypatch.setattr(
        europass_render, "render_draft", lambda **kw: pytest.fail("called europa.eu")
    )
    store = _FakeStore()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "cache-hit")
        from apps.documents.schemas import CVContent

        content = CVContent.model_validate(draft.content)
        key = document_key(
            tenant_id=agency_a.id,
            student_id=draft.student_id,
            draft_id=draft.id,
            filename=europass_render._ARTEFACT_FILENAME,
        )
        store.objects[key] = _genuine_pdf()
        EuropassRenderCache.objects.create(payload_hash=payload_hash(content), object_key=key)
        outcome = render_and_store(draft=draft, store=store)
    assert outcome.object_key == key
    assert outcome.called_remote is False
    assert store.puts == []


def test_a_same_key_stale_cache_row_falls_through_to_a_render(
    agency_a, django_user_model, monkeypatch
):
    """The staleness check must fire on the SAME-KEY path too, not only the
    cross-draft one: delete_student_documents erases every object under a
    student's prefix -- every draft that student has, not only cross-payload
    duplicates -- while leaving the cache row behind. A row already keyed to
    THIS exact draft can point at nothing just as easily as a cross-draft
    one, and reporting success for it would be a permanent 404."""

    class _Artifact:
        pdf_bytes = _genuine_pdf()

    calls = []

    def _render(**kwargs):
        calls.append(1)
        return _Artifact()

    monkeypatch.setattr(europass_render, "render_draft", _render)
    store = _FakeStore()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "same-key-stale")
        from apps.documents.schemas import CVContent

        content = CVContent.model_validate(draft.content)
        key = document_key(
            tenant_id=agency_a.id,
            student_id=draft.student_id,
            draft_id=draft.id,
            filename=europass_render._ARTEFACT_FILENAME,
        )
        # object_key already equals what THIS draft's own key would be --
        # but nothing was ever put at that key in the store, so the fast
        # same-key path must not trust it blindly.
        EuropassRenderCache.objects.create(payload_hash=payload_hash(content), object_key=key)
        outcome = render_and_store(draft=draft, store=store)
        assert EuropassRenderCache.objects.filter(object_key=outcome.object_key).exists()
    assert len(calls) == 1
    assert outcome.called_remote is True
    assert len(store.puts) == 1


def test_a_cross_draft_cache_hit_re_stores_under_this_drafts_key(
    agency_a, django_user_model, monkeypatch
):
    """Two drafts can share a payload_hash (the cache row is keyed only on
    the payload), but download_document resolves its key from draft_id --
    so handing back the first draft's key would be a permanent 404 for the
    second. The second draft must get its own resolvable copy."""
    monkeypatch.setattr(
        europass_render, "render_draft", lambda **kw: pytest.fail("called europa.eu")
    )
    store = _FakeStore()
    with tenant_scope(agency_a.id):
        first = _approved_draft(agency_a, django_user_model, "cross-draft-a")
        second = _approved_draft(agency_a, django_user_model, "cross-draft-b")
        from apps.documents.schemas import CVContent

        content = CVContent.model_validate(first.content)
        pdf = _genuine_pdf()
        stored_key = document_key(
            tenant_id=agency_a.id,
            student_id=first.student_id,
            draft_id=first.id,
            filename=europass_render._ARTEFACT_FILENAME,
        )
        store.objects[stored_key] = pdf
        EuropassRenderCache.objects.create(
            payload_hash=payload_hash(content), object_key=stored_key
        )
        outcome = render_and_store(draft=second, store=store)
        expected_key = document_key(
            tenant_id=agency_a.id,
            student_id=second.student_id,
            draft_id=second.id,
            filename=europass_render._ARTEFACT_FILENAME,
        )
    assert outcome.called_remote is False
    assert outcome.object_key == expected_key
    assert outcome.object_key != stored_key
    assert dict(store.puts)[outcome.object_key] == pdf


def test_a_stale_cache_row_falls_through_to_a_render(agency_a, django_user_model, monkeypatch):
    """delete_student_documents erases S3 objects but never touches this
    table, so a cache row can outlive its object. That must be a miss, not
    a failure that gives up on the draft."""

    class _Artifact:
        pdf_bytes = _genuine_pdf()

    calls = []

    def _render(**kwargs):
        calls.append(1)
        return _Artifact()

    monkeypatch.setattr(europass_render, "render_draft", _render)
    store = _FakeStore()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "stale-cache")
        from apps.documents.schemas import CVContent

        content = CVContent.model_validate(draft.content)
        digest = payload_hash(content)
        EuropassRenderCache.objects.create(payload_hash=digest, object_key="gone/forever.pdf")
        outcome = render_and_store(draft=draft, store=store)
        assert not EuropassRenderCache.objects.filter(object_key="gone/forever.pdf").exists()
        assert EuropassRenderCache.objects.filter(object_key=outcome.object_key).exists()
    assert len(calls) == 1
    assert outcome.called_remote is True


def test_a_second_delivery_of_the_same_message_renders_once(
    agency_a, django_user_model, monkeypatch
):
    """SQS is at-least-once. The cache is the idempotency key."""
    calls = []

    class _Artifact:
        pdf_bytes = _genuine_pdf()

    def _render(**kwargs):
        calls.append(1)
        return _Artifact()

    monkeypatch.setattr(europass_render, "render_draft", _render)
    store = _FakeStore()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "idem")
        first = render_and_store(draft=draft, store=store)
        second = render_and_store(draft=draft, store=store)
    assert len(calls) == 1
    assert first.object_key == second.object_key
    assert second.called_remote is False


def test_an_open_circuit_refuses_without_calling(agency_a, django_user_model, monkeypatch):
    monkeypatch.setattr(
        europass_render, "render_draft", lambda **kw: pytest.fail("called europa.eu")
    )
    circuit = EuropassCircuit.load()
    circuit.paused_until = timezone.now() + timezone.timedelta(seconds=300)
    circuit.save()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "open-circuit")
        with pytest.raises(CircuitOpen):
            render_and_store(draft=draft, store=_FakeStore())


def test_a_throttle_opens_the_circuit_for_the_retry_after(
    agency_a, django_user_model, monkeypatch
):
    def _throttled(**kwargs):
        raise EuropassThrottled("slow down", retry_after_seconds=180)

    monkeypatch.setattr(europass_render, "render_draft", _throttled)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "throttled")
        with pytest.raises(EuropassThrottled):
            render_and_store(draft=draft, store=_FakeStore())
    circuit = EuropassCircuit.load()
    assert circuit.is_open() is True
    assert 170 <= (circuit.paused_until - timezone.now()).total_seconds() <= 180


def test_three_consecutive_failures_open_the_circuit(agency_a, django_user_model, monkeypatch):
    def _down(**kwargs):
        raise EuropassUnavailable("europa.eu is down")

    monkeypatch.setattr(europass_render, "render_draft", _down)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "consecutive")
        for _ in range(3):
            with pytest.raises(EuropassUnavailable):
                render_and_store(draft=draft, store=_FakeStore())
    assert EuropassCircuit.load().is_open() is True


def test_a_below_threshold_failure_does_not_revert_a_concurrent_pause(
    agency_a, django_user_model, monkeypatch
):
    """circuit is loaded before the outbound call. A below-threshold failure
    must persist only consecutive_failures -- writing back paused_until and
    reason too would silently revert whatever a concurrent writer set on
    this row between our load and our save."""

    def _down(**kwargs):
        concurrent = EuropassCircuit.load()
        concurrent.paused_until = timezone.now() + timezone.timedelta(seconds=999)
        concurrent.reason = "set by someone else"
        concurrent.save(update_fields=["paused_until", "reason"])
        raise EuropassUnavailable("europa.eu is down")

    monkeypatch.setattr(europass_render, "render_draft", _down)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "no-clobber")
        with pytest.raises(EuropassUnavailable):
            render_and_store(draft=draft, store=_FakeStore())
    circuit = EuropassCircuit.load()
    assert circuit.consecutive_failures == 1
    assert circuit.reason == "set by someone else"
    assert circuit.is_open() is True


def test_a_success_resets_the_failure_counter(agency_a, django_user_model, monkeypatch):
    class _Artifact:
        pdf_bytes = _genuine_pdf()

    circuit = EuropassCircuit.load()
    circuit.consecutive_failures = 2
    circuit.save()
    monkeypatch.setattr(europass_render, "render_draft", lambda **kw: _Artifact())
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "reset")
        render_and_store(draft=draft, store=_FakeStore())
    assert EuropassCircuit.load().consecutive_failures == 0


def test_a_provenance_failure_does_not_trip_the_breaker(
    agency_a, django_user_model, monkeypatch
):
    """europa.eu is UP -- it just returned something that is not a Europass
    document. Counting that as an availability failure would park every other
    student's CV over a problem no retry can fix."""
    from apps.documents.europass import EuropassProvenanceMissing

    def _not_europass(**kwargs):
        raise EuropassProvenanceMissing("no attachment.xml")

    monkeypatch.setattr(europass_render, "render_draft", _not_europass)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "provenance")
        for _ in range(3):
            with pytest.raises(EuropassProvenanceMissing):
                render_and_store(draft=draft, store=_FakeStore())
    circuit = EuropassCircuit.load()
    assert circuit.consecutive_failures == 0
    assert circuit.is_open() is False


def test_a_local_rate_limit_rejection_does_not_trip_the_breaker(
    agency_a, django_user_model, monkeypatch
):
    """Our own per-student limiter, not europa.eu's availability. Counting it
    would let one student's approval burst park every other tenant's queue --
    same shape as the provenance carve-out above."""
    from apps.documents.render import RenderRateLimited

    def _rate_limited(**kwargs):
        raise RenderRateLimited("Europass render rate limit reached; retry later")

    monkeypatch.setattr(europass_render, "render_draft", _rate_limited)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-limited")
        for _ in range(3):
            with pytest.raises(RenderRateLimited):
                render_and_store(draft=draft, store=_FakeStore())
    circuit = EuropassCircuit.load()
    assert circuit.consecutive_failures == 0
    assert circuit.is_open() is False


@pytest.mark.django_db(transaction=True)
def test_all_three_set_local_tenant_calls_fire_across_a_full_cycle(
    agency_a, django_user_model, monkeypatch
):
    """Pins all three set_local_tenant calls in render_and_store: the cache
    lookup, the stale-row delete, and the final store-plus-cache-row write.

    set_local_tenant's SET_LOCAL is transaction-local (apps/tenancy/db.py),
    and the RLS policy on documents_europassrendercache hides every row when
    the GUC is unset -- so deleting any one of the three call sites gives a
    permanent cache miss (or, for the write, a WITH CHECK violation) in
    production, while every other test in this module keeps passing: they
    all run under plain pytest.mark.django_db, whose outer transaction lets
    the GUC set by an earlier savepoint leak into later ones, and none of
    them use a role where RLS is actually enforced (see the report -- the
    local/CI Postgres role here is a superuser, which bypasses RLS, even
    FORCE ROW LEVEL SECURITY, entirely; a spy is what makes this test
    discriminate independent of that).

    A spy on set_local_tenant proves each of the three call sites actually
    fires, transaction=True is kept so the flow matches production's real
    commit semantics rather than a savepoint that would never surface the
    bug this pins."""
    calls: list = []
    real_set_local_tenant = tenancy_db.set_local_tenant

    def _spy(tenant_id):
        calls.append(tenant_id)
        real_set_local_tenant(tenant_id)

    monkeypatch.setattr(europass_render, "set_local_tenant", _spy)

    class _Artifact:
        pdf_bytes = _genuine_pdf()

    monkeypatch.setattr(europass_render, "render_draft", lambda **kw: _Artifact())
    store = _FakeStore()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "spy-all-three")
        # Cache miss: exercises the lookup atomic, then the store atomic.
        first = render_and_store(draft=draft, store=store)
        assert first.called_remote is True
        assert len(calls) == 2

        # Erase the underlying object (as delete_student_documents would)
        # so the same-key row is stale: exercises the lookup atomic again,
        # then the stale-row delete atomic, then a fresh store atomic.
        del store.objects[first.object_key]
        second = render_and_store(draft=draft, store=store)
        assert second.called_remote is True
        assert len(calls) == 5

    assert calls == [agency_a.id] * 5


def test_a_successful_render_stores_and_caches(agency_a, django_user_model, monkeypatch):
    class _Artifact:
        pdf_bytes = _genuine_pdf()

    monkeypatch.setattr(europass_render, "render_draft", lambda **kw: _Artifact())
    store = _FakeStore()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "stored")
        outcome = render_and_store(draft=draft, store=store)
        assert EuropassRenderCache.objects.filter(object_key=outcome.object_key).exists()
    assert outcome.called_remote is True
    assert len(store.puts) == 1


def test_the_cache_key_tells_an_oldest_first_programme_from_a_newest_first_one():
    """The key hashes what is SENT, and an order directive changes what is
    sent: two programmes asking different orders must not share one PDF."""
    from apps.documents.constraints import PageDirective
    from apps.documents.render import europass_content
    from apps.documents.schemas import ExperienceEntry

    from .test_europass import _content as _cv

    chronological = (
        PageDirective(action="order", target="cv", value="chronological",
                      rule_text="the page's sentence", source_url=""),
    )
    content = _cv(
        experience=(
            ExperienceEntry(employer="ICIQ", title="Intern", start_date="2021-01-01",
                            end_date="2021-06-30", bullets=("A.",)),
            ExperienceEntry(employer="EPFL", title="Assistant", start_date="2022-01-01",
                            bullets=("B.",)),
        )
    )

    newest = payload_hash(*europass_content(content, ()))
    oldest = payload_hash(*europass_content(content, chronological))

    assert newest != oldest
