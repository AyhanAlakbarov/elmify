"""What protects a directory full of live portal session cookies."""

import os
from datetime import timedelta
from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _application(agency, student):
    from apps.portals.models import Application, PortalForm

    # form_key varies: PortalForm has a unique (portal_host, form_key)
    # constraint and these helpers are called more than once per test.
    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_the_profile_path_is_tenant_isolated(settings, tmp_path, agency_a, membership_a):
    from apps.portals.profiles import profile_dir

    settings.PORTAL_PROFILE_ROOT = tmp_path
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        path = profile_dir(application)

    assert path.parent.name == str(agency_a.id)
    assert path.name == str(application.id)
    assert path.is_relative_to(tmp_path)


def test_the_profile_and_its_tenant_directory_are_private(
    settings, tmp_path, agency_a, membership_a
):
    """0700 on both levels. One tenant's cookie jar must not be listable
    through another tenant's directory, and the process running this is not
    the only account on a shared host."""
    from apps.portals.profiles import profile_dir

    settings.PORTAL_PROFILE_ROOT = tmp_path
    with tenant_scope(agency_a.id):
        path = profile_dir(_application(agency_a, membership_a))

    assert os.stat(path).st_mode & 0o777 == 0o700
    assert os.stat(path.parent).st_mode & 0o777 == 0o700


def test_both_levels_are_private_without_relying_on_the_follow_up_chmod(
    settings, tmp_path, agency_a, membership_a, monkeypatch
):
    """mkdir(mode=..., parents=True) ignores mode on parents, so the tenant
    directory was briefly 0755 on first creation. With chmod stubbed out, both
    levels must still come out 0700 -- that is the difference between creating
    them correctly and repairing them afterwards."""
    from pathlib import Path

    from apps.portals.profiles import profile_dir

    settings.PORTAL_PROFILE_ROOT = tmp_path
    monkeypatch.setattr(Path, "chmod", lambda self, mode: None)
    with tenant_scope(agency_a.id):
        path = profile_dir(_application(agency_a, membership_a))

    assert os.stat(path).st_mode & 0o777 == 0o700
    assert os.stat(path.parent).st_mode & 0o777 == 0o700


def test_sweep_removes_profiles_past_their_ttl_and_keeps_fresh_ones(
    settings, tmp_path, agency_a, membership_a
):
    from apps.portals.profiles import LAST_USED, profile_dir, sweep_expired

    settings.PORTAL_PROFILE_ROOT = tmp_path
    with tenant_scope(agency_a.id):
        stale = profile_dir(_application(agency_a, membership_a))
        fresh = profile_dir(_application(agency_a, membership_a))

    for path in (stale, fresh):
        (path / LAST_USED).touch()
    old = (stale / LAST_USED).stat().st_mtime - timedelta(days=3).total_seconds()
    os.utime(stale / LAST_USED, (old, old))

    assert sweep_expired(root=tmp_path, ttl=timedelta(days=1)) == 1
    assert not stale.exists()
    assert fresh.exists()


def test_sweep_removes_a_profile_that_never_recorded_a_use(settings, tmp_path):
    """A directory with no marker is either a crashed session or something
    that does not belong here. Both are cookies nobody is tracking."""
    from apps.portals.profiles import sweep_expired

    orphan = tmp_path / str(uuid4()) / str(uuid4())
    orphan.mkdir(parents=True)

    assert sweep_expired(root=tmp_path, ttl=timedelta(days=1)) == 1
    assert not orphan.exists()


def test_sweep_never_follows_a_symlink_out_of_the_root(settings, tmp_path):
    """This function calls rmtree. The shape check is the whole safety
    argument, so it gets a test that fails loudly if it is ever loosened."""
    from apps.portals.profiles import sweep_expired

    outside = tmp_path.parent / "not-a-profile"
    outside.mkdir()
    (outside / "keepme").touch()
    tenant = tmp_path / str(uuid4())
    tenant.mkdir()
    (tenant / str(uuid4())).symlink_to(outside, target_is_directory=True)

    assert sweep_expired(root=tmp_path, ttl=timedelta(days=1)) == 0
    assert (outside / "keepme").exists()


def test_sweep_ignores_anything_not_shaped_like_a_profile(settings, tmp_path):
    from apps.portals.profiles import sweep_expired

    (tmp_path / "README").write_text("not a tenant directory", encoding="utf-8")
    (tmp_path / "loose").mkdir()

    assert sweep_expired(root=tmp_path, ttl=timedelta(days=1)) == 0
    assert (tmp_path / "loose").exists()
