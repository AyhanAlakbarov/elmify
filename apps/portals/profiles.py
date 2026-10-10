"""Per-application Chrome profiles: where live portal session cookies live.

Three controls, in the order of what they actually protect against.

- A tenant-isolated path, 0700 at both levels, so one tenant's cookie jar is
  not reachable through another's and no other account on the host can read it.
- A TTL sweep, so an abandoned session's cookies stop existing rather than
  sitting on disk until the task is replaced.
- Encryption at rest is the volume's, not this module's. The profile is a live
  Chrome directory (SQLite and LevelDB files) held open for the session's whole
  life, so an application-level tar-and-encrypt would have to decrypt it back
  to disk to be usable and would protect nothing during the window that
  matters. The portal task's EBS volume is created with Encrypted: true
  (infra/template.yaml, Task 14), which is what "encrypted at rest" means for a
  directory something is writing to.
  # ponytail: volume-level encryption. If a profile ever has to outlive its
  # task -- EFS, S3, a second host -- it leaves that volume and needs real
  # envelope encryption before it does.

There is deliberately no shared storage: an interrupted session resumes only on
the task that owns it, and a task that dies takes its profile with it. That is
not a gap, it is why reauthentication exists (apps/portals/auth.py).
"""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from .engine import StagehandPortalSession, portal_session
from .models import Application

#: Touched on entry and exit of every session. The directory's own mtime is not
#: enough: Chrome writes to files inside it without changing the parent.
LAST_USED = ".last_used"
PROFILE_MODE = 0o700


def _root() -> Path:
    return Path(settings.PORTAL_PROFILE_ROOT)


def profile_dir(application: Application) -> Path:
    # mkdir(parents=True) ignores `mode` on auto-created parents -- only the
    # final component gets it -- so each level is created (and chmod'd)
    # explicitly instead. mode=0o700 has no group/other bits for umask to
    # clear, so the created mode is already correct; chmod is belt-and-braces
    # for the case where the directory already existed with a looser mode.
    tenant_dir = _root() / str(application.tenant_id)
    tenant_dir.mkdir(mode=PROFILE_MODE, exist_ok=True)
    tenant_dir.chmod(PROFILE_MODE)
    path = tenant_dir / str(application.id)
    path.mkdir(mode=PROFILE_MODE, exist_ok=True)
    path.chmod(PROFILE_MODE)
    return path


def _is_profile(path: Path) -> bool:
    """A tenant/application pair of real directories, and nothing else.

    This is the guard on an rmtree. Symlinks are rejected rather than resolved:
    a symlink here is either a mistake or an attempt to have us delete
    something outside the root, and neither deserves a follow.
    """
    if path.is_symlink() or not path.is_dir():
        return False
    if path.parent.is_symlink():
        return False
    try:
        UUID(path.name)
        UUID(path.parent.name)
    except ValueError:
        return False
    return True


def sweep_expired(
    *, root: Path | None = None, ttl: timedelta | None = None, now: datetime | None = None
) -> int:
    """Delete every profile untouched for longer than the TTL. Returns the count."""
    root = root or _root()
    ttl = ttl or timedelta(hours=settings.PORTAL_PROFILE_TTL_HOURS)
    now = now or timezone.now()
    if not root.exists():
        return 0
    removed = 0
    for tenant_dir in root.iterdir():
        if tenant_dir.is_symlink() or not tenant_dir.is_dir():
            continue
        for candidate in tenant_dir.iterdir():
            if not _is_profile(candidate):
                continue
            marker = candidate / LAST_USED
            # No marker means a crashed session or a directory nobody is
            # tracking. Both are cookies with no owner, so both go.
            if marker.exists():
                last_used = datetime.fromtimestamp(marker.stat().st_mtime, tz=now.tzinfo)
                if now - last_used <= ttl:
                    continue
            shutil.rmtree(candidate)
            removed += 1
    return removed


@contextmanager
def open_portal_session(application: Application) -> Iterator[StagehandPortalSession]:
    """A browser pinned to this application's portal and this application's profile."""
    assert application.portal_form is not None  # never queued portal-less
    path = profile_dir(application)
    (path / LAST_USED).touch()
    try:
        with portal_session(
            user_data_dir=path, allowed_host=application.portal_form.portal_host
        ) as session:
            yield session
    finally:
        # Touched again on the way out so the TTL measures time since the last
        # use, not time since the session started -- a six-hour fill would
        # otherwise be swept while it was still running.
        (path / LAST_USED).touch()
