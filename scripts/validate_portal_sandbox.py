"""Proves the portal browser comes up headful AND sandboxed on a fake display.

Run this on any host that will actually drive portals -- your laptop, or a
container image before it ships:

    xvfb-run -a --server-args="-screen 0 1280x1024x24" \
        uv run python scripts/validate_portal_sandbox.py

Why a script and not a test: launching Chrome inside pytest leaves a live
PostgreSQL session behind, so pytest-django cannot drop test_tehsil at
teardown and the next run collides on leftover rows. The suite already pins
our side of this statically (tests/portals/test_boundary.py); what needs a
real browser is whether the sandbox engages, and that is checked here.

Seccomp: 2 is SECCOMP_MODE_FILTER read straight from the kernel, which argv
cannot fake -- a --no-sandbox grep can be defeated by a process that rewrites
its own command line. The browser process, the pre-fork zygote and the broker
sit at 0 by design, so the assertion is on the children.

Exits 0 on success, 1 on a real failure, 2 when prerequisites are missing.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.portals.engine import chrome_binary  # noqa: E402


def seccomp_modes(chrome: Path) -> list[int]:
    """Seccomp mode of every live process whose exe IS the Chrome binary."""
    modes = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            if os.readlink(f"/proc/{pid}/exe") != str(chrome):
                continue
            status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
        except OSError:
            continue  # process exited mid-scan
        modes += [int(line.split()[1]) for line in status.splitlines()
                  if line.startswith("Seccomp:")]
    return modes


async def probe(chrome: Path) -> list[int]:
    from stagehand import local_browser

    with tempfile.TemporaryDirectory() as profile:
        browser = await local_browser.launch(
            headless=False,
            executable_path=str(chrome),
            chromium_sandbox=True,
            user_data_dir=profile,
            preserve_user_data_dir=False,
        )
        try:
            return seccomp_modes(chrome)
        finally:
            await browser.close()


def main() -> int:
    # Resolved here, not at import time: a missing cache must fall through to
    # the SKIP branch below rather than raise before main() gets a chance to
    # print it.
    try:
        chrome = chrome_binary()
    except RuntimeError as exc:
        print(f"SKIP: {exc}")
        return 2
    if not os.environ.get("DISPLAY"):
        print("SKIP: headful Chrome needs a display -- run under xvfb-run")
        return 2
    if os.environ.get("CI"):
        print("SKIP: stagehand strips the sandbox when CI is set, so this "
              "would measure the wrong thing -- unset CI")
        return 2

    print(f"DISPLAY={os.environ['DISPLAY']}  chrome={chrome}")
    modes = asyncio.run(probe(chrome))
    filtered = modes.count(2)
    print(f"chrome processes: {len(modes)}  seccomp-filtered: {filtered}")

    if not modes:
        print("FAIL: no Chrome process launched")
        return 1
    if not filtered:
        print(f"FAIL: no child is seccomp-filtered, the sandbox is off: {modes}")
        return 1
    print("OK: headful and sandboxed on a fake display")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
