"""A throwaway Postgres 17.10 for one test session, from the pixi environment.

Why: Claude Code's Linux sandbox gives each shell command a private network namespace,
so a sandboxed `pytest` cannot reach the docker Postgres on the host's 127.0.0.1:5432.
It can reach a server it started itself. When this worktree has run `pixi install` and no
database is configured (`POSTGRES_HOST` unset), `django_db_modify_db_settings` in
tests/conftest.py starts one here; otherwise nothing changes, which keeps CI (it sets
POSTGRES_HOST) and docker users on their server. `ELMIFY_EPHEMERAL_PG=0` opts out.

TCP on 127.0.0.1 only, no Unix socket (sandboxed commands may not create AF_UNIX sockets).
The first start in a checkout caches an initdb'd cluster under $XDG_CACHE_HOME; later
starts copy it (measured 2026-10-20: ~0.2 s, against ~0.6 s for a cold initdb).
"""

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / ".pixi" / "envs" / "default" / "bin"


@dataclass(frozen=True)
class Ephemeral:
    host: str
    port: int
    data: Path

    def stop(self) -> None:
        subprocess.run(
            [str(BIN / "pg_ctl"), "-D", str(self.data / "pg"), "-m", "immediate", "stop"],
            capture_output=True,
            check=False,
        )
        shutil.rmtree(self.data, ignore_errors=True)


def wanted(environ: Mapping[str, str] = os.environ) -> bool:
    """Start one only where nothing else is configured: pixi Postgres present, no host set."""
    return (
        (BIN / "postgres").exists()
        and not environ.get("POSTGRES_HOST")
        and environ.get("ELMIFY_EPHEMERAL_PG", "1") != "0"
    )


def _initdb(target: Path) -> None:
    subprocess.run(
        [str(BIN / "initdb"), "-D", str(target), "-U", "elmify", "--auth=trust", "-E", "UTF8",
         "--no-sync", "--no-instructions"],
        capture_output=True,
        check=True,
    )


def _template() -> Path:
    version = subprocess.run(
        [str(BIN / "postgres"), "--version"], capture_output=True, text=True, check=True
    ).stdout.split()[-1]
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "elmify-pg-template"
    template = cache / version
    if not (template / "PG_VERSION").exists():
        cache.mkdir(parents=True, exist_ok=True)
        building = Path(tempfile.mkdtemp(dir=cache, prefix=f"{version}.building."))
        _initdb(building / "pg")
        try:
            (building / "pg").rename(template)
        except OSError:  # a parallel run cached it first
            pass
        shutil.rmtree(building, ignore_errors=True)
    return template


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start() -> Ephemeral:
    data = Path(tempfile.mkdtemp(prefix="elmify-pg."))
    shutil.copytree(_template(), data / "pg", symlinks=True)
    port = _free_port()
    options = (
        f"-c listen_addresses=127.0.0.1 -c port={port} -c unix_socket_directories='' "
        "-c fsync=off -c synchronous_commit=off -c full_page_writes=off"
    )
    try:
        subprocess.run(
            [str(BIN / "pg_ctl"), "-D", str(data / "pg"), "-w", "-s", "-l", str(data / "pg.log"),
             "-o", options, "start"],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        log_file = data / "pg.log"
        log = log_file.read_text(errors="replace")[-2000:] if log_file.exists() else ""
        shutil.rmtree(data, ignore_errors=True)
        raise RuntimeError(f"ephemeral Postgres did not start: {e.stderr!r}\n{log}") from e
    return Ephemeral("127.0.0.1", port, data)
