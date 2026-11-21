"""The bench's verified gate (spec §9): a clean map with a walked login and
sign-up becomes the platform-shared, verified map every tenant is served."""

import pytest

from apps.portals.bench_runner import BenchReport, StudentRun
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

ENTRY = {"profile_field": "identity.full_name", "sure": True,
         "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]}}
AMBER = {"profile_field": "identity.full_name", "expected": "Ana", "actual": "ANA"}


def _clean() -> BenchReport:
    return BenchReport(per_student={"s": StudentRun()}, boxes=1)


def _dirty() -> BenchReport:
    return BenchReport(per_student={"s": StudentRun(ambers=[AMBER])}, boxes=1)


@pytest.fixture
def tenant_map(portal_form, agency_a):
    from apps.portals.models import FieldMap

    return FieldMap.objects.create(
        portal_form=portal_form, version=1, learned_by_tenant=agency_a, entries=[ENTRY]
    )


def _walked(portal_form, *, walk_ok: bool = True) -> None:
    from apps.portals.models import PageRecord

    for kind in ("LOGIN", "SIGNUP"):
        PageRecord.objects.create(
            portal_form=portal_form, source="BENCH_WALK", page_kind=kind, step=1,
            snapshot={"page_url": "https://apply.example.edu", "controls": []},
            password_rules="At least 12 characters" if kind == "SIGNUP" else "",
            walk_ok=walk_ok, html_key=f"bench/{kind}.html",
        )


def _promote(form, source_map, report, *, operator):
    """promote() as the operator calls it: after checking this exact mapping."""
    from apps.portals.bench import mapping_digest, promote

    return promote(form, source_map, report, operator=operator,
                   confirmed=mapping_digest(source_map))


def _verified_exists() -> bool:
    from apps.portals.models import FieldMap

    return FieldMap.objects.filter(verified_at__isnull=False).exists()


def test_promotion_with_an_amber_is_refused_and_writes_nothing(tenant_map, operator) -> None:
    from apps.portals.bench import PromotionRefused

    _walked(tenant_map.portal_form)
    with pytest.raises(PromotionRefused, match="not clean"):
        _promote(tenant_map.portal_form, tenant_map, _dirty(), operator=operator)
    assert not _verified_exists()


def test_an_empty_map_is_never_promoted(portal_form, agency_a, operator) -> None:
    from apps.portals.bench import PromotionRefused
    from apps.portals.models import FieldMap

    empty = FieldMap.objects.create(
        portal_form=portal_form, version=1, learned_by_tenant=agency_a, entries=[]
    )
    _walked(portal_form)
    assert not BenchReport(per_student={"s": StudentRun()}).clean  # the runner's own verdict
    with pytest.raises(PromotionRefused, match="empty"):
        _promote(portal_form, empty, _clean(), operator=operator)
    assert not _verified_exists()


@pytest.mark.parametrize("walk_ok", [False, None])
def test_promotion_needs_a_login_and_signup_that_were_walked(
    tenant_map, operator, walk_ok: bool | None
) -> None:
    from apps.portals.bench import PromotionRefused

    if walk_ok is not None:
        _walked(tenant_map.portal_form, walk_ok=walk_ok)
    with pytest.raises(PromotionRefused, match="LOGIN"):
        _promote(tenant_map.portal_form, tenant_map, _clean(), operator=operator)
    assert not _verified_exists()


def test_signup_needs_its_password_rules_and_a_superseded_walk_does_not_count(
    tenant_map, operator
) -> None:
    from django.utils import timezone

    from apps.portals.bench import PromotionRefused
    from apps.portals.models import PageRecord

    form = tenant_map.portal_form
    _walked(form)
    PageRecord.objects.filter(page_kind="SIGNUP").update(password_rules="")
    with pytest.raises(PromotionRefused, match="SIGNUP"):
        _promote(form, tenant_map, _clean(), operator=operator)
    PageRecord.objects.update(superseded_at=timezone.now())
    _walked(form, walk_ok=False)
    PageRecord.objects.filter(superseded_at__isnull=True, page_kind="LOGIN").update(walk_ok=True)
    PageRecord.objects.filter(superseded_at__isnull=False).update(
        walk_ok=True, password_rules="old rules"
    )
    with pytest.raises(PromotionRefused, match="SIGNUP"):
        _promote(form, tenant_map, _clean(), operator=operator)
    assert not _verified_exists()


def test_a_verified_map_serves_every_tenant_and_a_tenant_cannot_shadow_it(
    tenant_map, operator, agency_a, agency_b
) -> None:
    from apps.funding.models import AuditEvent
    from apps.portals.learn import _store_map
    from apps.portals.models import FieldMap

    form = tenant_map.portal_form
    # agency_b learned its own map before the bench ever ran.
    stale_b = _store_map(form, [ENTRY], learned_by_tenant_id=agency_b.id)
    _walked(form)
    verified = _promote(form, tenant_map, _clean(), operator=operator)
    assert verified.learned_by_tenant_id is None and verified.verified_at is not None
    assert verified.entries == tenant_map.entries and verified.slots == tenant_map.slots
    form.refresh_from_db()
    assert form.password_rules == "At least 12 characters" and form.needs_bench is False
    for tenant in (agency_a, agency_b):
        assert FieldMap.current_for(form, tenant.id) == verified
    # A tenant learning again supersedes ITS OWN older map, and still loses.
    relearned = _store_map(form, [ENTRY], learned_by_tenant_id=agency_a.id)
    tenant_map.refresh_from_db()
    assert tenant_map.superseded_at is not None
    assert FieldMap.current_for(form, agency_a.id) == verified
    # Until a live relearn says the portal changed: then the tenant's own wins.
    form.needs_bench = True
    form.save(update_fields=["needs_bench"])
    assert FieldMap.current_for(form, agency_a.id) == relearned
    # agency_b's map predates the verified one: the flag does not resurrect it.
    assert stale_b.superseded_at is None
    assert FieldMap.current_for(form, agency_b.id) == verified
    with tenant_scope(operator.tenant_id):
        assert AuditEvent.objects.filter(
            event="portal.field_map_verified", object_id=verified.id
        ).exists()


def test_the_bench_benches_the_relearned_map_when_the_form_needs_it(
    tenant_map, operator, agency_a
) -> None:
    from apps.portals.learn import _store_map
    from apps.portals.management.commands.portal_bench import bench_map

    form = tenant_map.portal_form
    _walked(form)
    verified = _promote(form, tenant_map, _clean(), operator=operator)
    assert bench_map(form) == verified
    relearned = _store_map(form, [ENTRY], learned_by_tenant_id=agency_a.id)
    form.needs_bench = True
    form.save(update_fields=["needs_bench"])
    assert bench_map(form) == relearned


def test_walk_ok_marks_the_newest_current_record(portal_form, operator) -> None:
    from django.core.management import call_command
    from django.utils import timezone

    from apps.funding.models import AuditEvent
    from apps.portals.models import PageRecord

    _walked(portal_form, walk_ok=False)
    newest = PageRecord.objects.create(
        portal_form=portal_form, source="BENCH_WALK", page_kind="LOGIN", step=2, snapshot={},
    )
    # A later record from a walk already replaced is history, never marked.
    PageRecord.objects.create(
        portal_form=portal_form, source="BENCH_WALK", page_kind="LOGIN", step=3, snapshot={},
        superseded_at=timezone.now(),
    )
    call_command(
        "portal_bench", str(portal_form.id), "--operator", "owner@example.org",
        "--walk-ok", "LOGIN",
    )
    assert list(
        PageRecord.objects.filter(page_kind="LOGIN", walk_ok=True).values_list("id", flat=True)
    ) == [newest.id]
    with tenant_scope(operator.tenant_id):
        event = AuditEvent.objects.get(event="portal.bench_walk_ok")
    assert event.object_id == newest.id and event.actor_id == operator.id


def test_walk_ok_and_promote_cannot_be_asked_together(portal_form, operator) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="not allowed with"):
        call_command(
            "portal_bench", str(portal_form.id), "--operator", "owner@example.org",
            "--walk-ok", "LOGIN", "--promote",
        )


def test_newer_is_decided_by_version_not_by_the_clock(tenant_map, operator, agency_a) -> None:
    from datetime import timedelta

    from apps.portals.learn import _store_map
    from apps.portals.models import FieldMap

    form = tenant_map.portal_form
    _walked(form)
    verified = _promote(form, tenant_map, _clean(), operator=operator)
    relearned = _store_map(form, [ENTRY], learned_by_tenant_id=agency_a.id)
    # A skewed host clock stamps the relearn before the promotion.
    FieldMap.objects.filter(pk=relearned.pk).update(
        created_at=verified.created_at - timedelta(minutes=5)
    )
    form.needs_bench = True
    form.save(update_fields=["needs_bench"])
    assert FieldMap.current_for(form, agency_a.id) == relearned


def test_a_map_that_changed_since_the_bench_run_is_not_promoted(
    tenant_map, operator, agency_a, portal_form
) -> None:
    from apps.portals.bench import PromotionRefused
    from apps.portals.learn import _store_map
    from apps.portals.models import FieldMap, PortalForm

    _walked(portal_form)
    other = PortalForm.objects.create(portal_host="other.example.edu", form_key="bench-2")
    foreign = FieldMap.objects.create(
        portal_form=other, version=1, learned_by_tenant=agency_a, entries=[ENTRY]
    )
    with pytest.raises(PromotionRefused, match="current map"):
        _promote(portal_form, foreign, _clean(), operator=operator)
    # A relearn landed between the replay and the promotion: it superseded the
    # benched map, and the portal-changed flag it raised must survive.
    benched_form = PortalForm.objects.get(pk=portal_form.pk)
    _store_map(portal_form, [ENTRY], learned_by_tenant_id=agency_a.id)
    PortalForm.objects.filter(pk=portal_form.pk).update(needs_bench=True)
    with pytest.raises(PromotionRefused, match="current map"):
        _promote(benched_form, tenant_map, _clean(), operator=operator)
    assert not _verified_exists()
    assert PortalForm.objects.get(pk=portal_form.pk).needs_bench is True


def test_a_relearn_flagging_the_form_after_the_run_blocks_a_promotion_of_the_old_map(
    tenant_map, operator, agency_b, portal_form
) -> None:
    from apps.portals.bench import PromotionRefused
    from apps.portals.learn import _store_map
    from apps.portals.models import PortalForm

    _walked(portal_form)
    benched_form = PortalForm.objects.get(pk=portal_form.pk)  # needs_bench False
    # Another tenant's relearn: tenant_map stays current, but the portal changed.
    _store_map(portal_form, [ENTRY], learned_by_tenant_id=agency_b.id)
    PortalForm.objects.filter(pk=portal_form.pk).update(needs_bench=True)
    with pytest.raises(PromotionRefused, match="current map"):
        _promote(benched_form, tenant_map, _clean(), operator=operator)
    assert not _verified_exists()


def test_promote_on_a_run_that_is_not_clean_raises_and_writes_nothing(
    tenant_map, operator, bench_store, monkeypatch
) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError

    from apps.portals.management.commands import portal_bench

    _walked(tenant_map.portal_form)
    for kind in ("LOGIN", "SIGNUP"):
        bench_store.put(f"bench/{kind}.html", b"<html></html>")
    monkeypatch.setattr(portal_bench, "replay", lambda form, field_map, *, pages: _dirty())
    with pytest.raises(CommandError, match="not clean"):
        call_command(
            "portal_bench", str(tenant_map.portal_form.id), "--operator", "owner@example.org",
            "--promote",
        )
    assert not _verified_exists()


def test_promote_on_a_clean_run_verifies_the_benched_map(
    tenant_map, operator, bench_store, monkeypatch
) -> None:
    from django.core.management import call_command

    from apps.portals.bench import mapping_digest
    from apps.portals.management.commands import portal_bench
    from apps.portals.models import FieldMap

    _walked(tenant_map.portal_form)
    for kind in ("LOGIN", "SIGNUP"):
        bench_store.put(f"bench/{kind}.html", b"<html></html>")
    monkeypatch.setattr(portal_bench, "replay", lambda form, field_map, *, pages: _clean())
    call_command(
        "portal_bench", str(tenant_map.portal_form.id), "--operator", "owner@example.org",
        "--promote", "--confirm", mapping_digest(tenant_map),
    )
    verified = FieldMap.objects.get(verified_at__isnull=False)
    assert verified.entries == tenant_map.entries


def test_a_clean_run_is_not_promoted_until_the_operator_confirms_the_mapping(
    tenant_map, operator, bench_store, monkeypatch
) -> None:
    """Read-back cannot see a wrong-but-consistent map, so the gate shows every
    row beside the box's label on the operator's own walk and promotes only the
    exact mapping the operator confirmed."""
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    from apps.portals.bench import mapping_digest
    from apps.portals.management.commands import portal_bench
    from apps.portals.models import PageRecord

    _walked(tenant_map.portal_form)
    PageRecord.objects.filter(page_kind="LOGIN").update(snapshot={
        "page_url": "https://apply.example.edu",
        "controls": [{"selector": "#name", "tag": "input", "label": "Referee e-mail"}],
    })
    for kind in ("LOGIN", "SIGNUP"):
        bench_store.put(f"bench/{kind}.html", b"<html></html>")
    monkeypatch.setattr(portal_bench, "replay", lambda form, field_map, *, pages: _clean())
    args = ["portal_bench", str(tenant_map.portal_form.id), "--operator", "owner@example.org",
            "--promote"]
    out = StringIO()
    with pytest.raises(CommandError, match=f"--confirm {mapping_digest(tenant_map)}"):
        call_command(*args, stdout=out)
    assert "identity.full_name -> #name  [Referee e-mail]" in out.getvalue()
    assert f"tenant {tenant_map.learned_by_tenant_id}" in out.getvalue()
    with pytest.raises(CommandError, match="--confirm"):
        call_command(*args, "--confirm", "000000000000")
    assert not _verified_exists()


def test_promote_refuses_a_digest_of_another_mapping(tenant_map, operator) -> None:
    from apps.portals.bench import PromotionRefused, promote

    _walked(tenant_map.portal_form)
    with pytest.raises(PromotionRefused, match="confirmed this exact mapping"):
        promote(tenant_map.portal_form, tenant_map, _clean(), operator=operator,
                confirmed="000000000000")
    assert not _verified_exists()
