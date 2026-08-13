"""A bridge is identified by the session it serves, never by the port it holds.

Two ways the adapter used to trust a port number on its own, both of which
reach across an installation boundary:

  * Reuse. It probed ``/health`` and, if a bridge answered and its script hash
    matched, adopted it — "Using existing bridge". Nothing asked which WhatsApp
    account that bridge was signed in as. A second install, a second profile,
    or upstream Atlas on a colliding default would all answer, and adopting
    one means this gateway starts reading and replying on somebody else's
    number. The scoped session lock cannot catch it: a different session is a
    different lock, and both holders believe they are alone.

  * Eviction. Before starting its own bridge it signalled whatever was
    LISTENING on the port. The LISTEN filter was added after this killed users'
    browsers; it stops a client being hit, but not another product's server.

Both now compare the session directory, which is the identity the lock, the
pidfile and the bridge's own command line already use.
"""

from pathlib import Path

import pytest

from plugins.platforms.whatsapp import adapter as wa


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "platforms" / "whatsapp" / "session"
    path.mkdir(parents=True)
    return path


# --- eviction --------------------------------------------------------------


def test_our_own_stale_bridge_is_evicted(session, monkeypatch):
    killed = []
    monkeypatch.setattr(wa, "_IS_WINDOWS", False)
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [4242])
    monkeypatch.setattr(
        "gateway.status._read_process_cmdline",
        lambda pid: f"node /opt/bridge.js --port 3100 --session {session}",
    )
    monkeypatch.setattr(wa.os, "kill", lambda pid, sig: killed.append(pid))

    wa._kill_port_process(3100, session)
    assert killed == [4242]


def test_another_installs_bridge_is_left_alone(session, tmp_path, monkeypatch):
    """The exact Atlas-beside-Atlas case: a real bridge, a real session, not ours."""
    killed = []
    theirs = tmp_path / "their-home" / "whatsapp" / "session"
    monkeypatch.setattr(wa, "_IS_WINDOWS", False)
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [4242])
    monkeypatch.setattr(
        "gateway.status._read_process_cmdline",
        lambda pid: f"node /opt/bridge.js --port 3100 --session {theirs}",
    )
    monkeypatch.setattr(wa.os, "kill", lambda pid, sig: killed.append(pid))

    wa._kill_port_process(3100, session)
    assert killed == []


def test_an_unrelated_server_is_left_alone(session, monkeypatch):
    killed = []
    monkeypatch.setattr(wa, "_IS_WINDOWS", False)
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [4242])
    monkeypatch.setattr(
        "gateway.status._read_process_cmdline", lambda pid: "python -m http.server 3100"
    )
    monkeypatch.setattr(wa.os, "kill", lambda pid, sig: killed.append(pid))

    wa._kill_port_process(3100, session)
    assert killed == []


def test_an_unreadable_process_is_left_alone(session, monkeypatch):
    """Another user's process. Not ours to signal, and not ours to guess about."""
    killed = []
    monkeypatch.setattr(wa, "_IS_WINDOWS", False)
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [4242])
    monkeypatch.setattr("gateway.status._read_process_cmdline", lambda pid: "")
    monkeypatch.setattr(wa.os, "kill", lambda pid, sig: killed.append(pid))

    wa._kill_port_process(3100, session)
    assert killed == []


# --- identity --------------------------------------------------------------


def test_a_bridge_is_ours_only_when_the_session_matches(session, tmp_path, monkeypatch):
    theirs = tmp_path / "elsewhere" / "session"
    monkeypatch.setattr(
        "gateway.status._read_process_cmdline",
        lambda pid: f"node bridge.js --session {session}",
    )
    assert wa._process_is_our_bridge(1, session) is True
    assert wa._process_is_our_bridge(1, theirs) is False


def test_a_process_that_is_not_node_is_never_ours(session, monkeypatch):
    """The session path appearing in a command line is not enough on its own —
    a backup job or an editor may well have it open."""
    monkeypatch.setattr(
        "gateway.status._read_process_cmdline", lambda pid: f"tar -czf backup {session}"
    )
    assert wa._process_is_our_bridge(1, session) is False
