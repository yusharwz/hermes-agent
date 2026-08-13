"""A live gateway keeps its scoped locks, whatever argv it happens to wear.

This protects a customer's phone number rather than a feature.

A scoped lock is how one gateway stops another from using the same external
identity — the same WhatsApp session, the same Telegram token. Its staleness
check asked "is the pid holding this a gateway?" with the strict matcher, which
only accepts ``gateway run``. On a host with no service manager the manual
restart fallback runs the gateway runtime in the ``gateway restart`` process
itself, so a perfectly healthy gateway wears that argv for its whole life and
was judged an impostor: every lock it held was declared stale and handed to
whoever asked next.

For WhatsApp that means two clients on one session. The server removes the
first, it reconnects and removes the second, and the two take the device from
each other until WhatsApp restricts the number — which is what happened, over
68 bridge launches in five hours.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from gateway import status as gw_status
from gateway.status import (
    acquire_scoped_lock,
    looks_like_gateway_command_line,
    looks_like_gateway_runtime_command_line,
)


RUN = "/opt/app/.venv/bin/python -m atlas_cli.main gateway run"
RESTART = "/opt/app/.venv/bin/python -m atlas_cli.main gateway restart"
STATUS = "/opt/app/.venv/bin/python -m atlas_cli.main gateway status"
CRON = "/usr/sbin/cron -f"


def test_the_strict_matcher_stays_strict():
    """Lifecycle decisions still only accept the canonical runtime."""
    assert looks_like_gateway_command_line(RUN) is True
    assert looks_like_gateway_command_line(RESTART) is False


def test_the_runtime_matcher_accepts_the_restart_shape():
    assert looks_like_gateway_runtime_command_line(RUN) is True
    assert looks_like_gateway_runtime_command_line(RESTART) is True


@pytest.mark.parametrize("command", [STATUS, CRON, "", None])
def test_the_runtime_matcher_still_rejects_impostors(command):
    """The collision guard the staleness check wants is not weakened."""
    assert looks_like_gateway_runtime_command_line(command) is False


def _register_lock_for(pid: int, identity: str, argv: list[str]) -> None:
    path = gw_status._get_scope_lock_path("whatsapp-session", identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    gw_status._write_json_file(
        path,
        {
            "pid": pid,
            "start_time": gw_status._get_process_start_time(pid),
            "kind": "gateway",
            "argv": argv,
            "scope": "whatsapp-session",
            "identity_hash": gw_status._scope_hash(identity),
            "metadata": {},
            "updated_at": gw_status._utc_now_iso(),
        },
    )


@pytest.fixture
def sleeper(tmp_path):
    """A live process wearing a gateway argv, so /proc has something real."""
    script = tmp_path / "main.py"
    script.write_text("import time; time.sleep(120)")
    proc = subprocess.Popen(
        [sys.executable, str(script), "atlas_cli.main", "gateway", "restart"]
    )
    time.sleep(1)
    try:
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=30)


def test_a_live_restart_shaped_gateway_keeps_its_lock(sleeper, tmp_path, monkeypatch):
    """The regression, end to end: this used to hand the session away."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path / "home"))
    identity = "/sessions/whatsapp"
    _register_lock_for(
        sleeper.pid, identity, ["atlas_cli.main", "gateway", "restart"]
    )

    acquired, existing = acquire_scoped_lock("whatsapp-session", identity)

    assert acquired is False, "a live gateway's session was taken from it"
    assert existing is not None


def test_a_dead_holder_still_releases_its_lock(tmp_path, monkeypatch):
    """Fixing the false positive must not create a false negative."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path / "home"))
    identity = "/sessions/whatsapp-dead"

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    pid = proc.pid
    _register_lock_for(pid, identity, ["atlas_cli.main", "gateway", "restart"])
    proc.kill()
    proc.wait(timeout=30)

    acquired, _ = acquire_scoped_lock("whatsapp-session", identity)
    assert acquired is True, "a dead gateway kept the session locked"
