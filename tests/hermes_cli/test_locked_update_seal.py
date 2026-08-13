"""A locked Atlas build updates from NineGate and never from git.

The install this protects has no ``.git``: it is a tarball tree under
``~/.atlas/atlas-agent``. Unsealed, ``hermes update`` read that as a broken
checkout and offered the two remedies it knows — reinstall from upstream's
install URL (POSIX), or download upstream's ``main.zip`` and copy it over the
tree (Windows). Both replace Atlas with the upstream it was forked from:
the leash, the gateway pinning and the stripped vendor credentials all go,
and the customer reaches it by typing the ordinary update command.

The seal is one gate at the top of the update, plus a refusal inside the ZIP
path itself, because that path has a second entrance through the Windows
``CalledProcessError`` fallback at the end of the update.

A NOTE ON HOW THESE TESTS ARE WRITTEN
=====================================
``test_locked_build_refuses_the_upstream_zip`` patches ``urlretrieve`` to fail
rather than trusting the refusal to be reached. That is not defensive style,
it is a scar: proving the refusal had teeth by deleting it and running the
suite, in a real checkout, made ``_update_via_zip`` do exactly what it says on
the tin — fetch upstream's main.zip and copy 2566 files over the fork's
working tree. The assertion below is what the test is *for*; the patch is what
keeps a future regression from costing a `git reset --hard` to notice.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def locked(monkeypatch):
    """Make ``is_locked()`` true the way a customer install does."""
    monkeypatch.setenv("ATLAS_LOCKED", "1")


@pytest.fixture
def unlocked(monkeypatch):
    monkeypatch.delenv("ATLAS_LOCKED", raising=False)


def test_unlocked_build_stays_on_the_git_path(unlocked):
    """The dev fork must be untouched by the seal."""
    from hermes_cli.main import _run_locked_native_update

    assert _run_locked_native_update(SimpleNamespace(), False) is False


def test_cmd_update_impl_consults_the_gate_before_touching_git(locked):
    """The gate must actually be wired into the update, not merely exist.

    Without this the whole seal could be deleted from ``_cmd_update_impl`` and
    every other test here would still pass: they call the gate directly.
    """
    import hermes_cli.main as main

    with patch.object(main, "_run_locked_native_update", return_value=True) as gate, \
         patch.object(main, "_run_pre_update_backup") as backup:
        main._cmd_update_impl(SimpleNamespace(yes=True), False)

    assert gate.called, "a locked build must be offered the native path"
    assert not backup.called, "a True gate must short-circuit before the git update"


def test_locked_update_delegates_to_the_native_updater(locked, monkeypatch):
    """A locked build spawns the NineGate runner and reports its result."""
    from hermes_cli import ninegate_update

    monkeypatch.setattr(
        "agent.ninegate_leash.subscription_key", lambda: "ng-key", raising=False
    )

    spawned = []

    # The first read happens BEFORE the spawn and returns a finished PREVIOUS
    # run — the state every real install is in, since the file outlives the
    # update that wrote it. A poll loop that accepts it reports that update's
    # result as this one's, so the reads after the spawn keep started_at=1.0
    # until the runner has genuinely claimed the job at 2.0.
    states = iter(
        [
            {**ninegate_update.IDLE_STATE, "done": True, "ok": True, "started_at": 1.0},
            {**ninegate_update.IDLE_STATE, "done": True, "ok": True, "started_at": 1.0},
            {**ninegate_update.IDLE_STATE, "running": True, "started_at": 2.0,
             "stage": "mengunduh", "percent": 10},
            {**ninegate_update.IDLE_STATE, "running": True, "started_at": 2.0,
             "stage": "menukar", "percent": 80},
            {**ninegate_update.IDLE_STATE, "running": False, "done": True, "ok": True,
             "started_at": 2.0, "version": "1021b0d", "restart_required": True},
        ]
    )

    def read_state():
        try:
            return next(states)
        except StopIteration:  # pragma: no cover - loop should have exited
            raise AssertionError("polled past completion")

    from hermes_cli.main import _run_locked_native_update

    with patch.object(ninegate_update, "read_state", side_effect=read_state), \
         patch.object(ninegate_update, "spawn_detached",
                      side_effect=lambda gw, key: spawned.append((gw, key))), \
         patch.object(ninegate_update, "atlas_home"), \
         patch("hermes_cli.update_cmd._time.sleep"):
        assert _run_locked_native_update(SimpleNamespace(), False) is True

    assert len(spawned) == 1, "the native runner must be spawned exactly once"
    assert spawned[0][1] == "ng-key"
    assert next(states, None) is None, "the loop must consume the finished state"


def test_locked_update_without_a_key_refuses(locked, monkeypatch):
    """No subscription key is a stop, not a fall-through to git."""
    monkeypatch.setattr(
        "agent.ninegate_leash.subscription_key", lambda: "", raising=False
    )

    from hermes_cli.main import _run_locked_native_update

    with pytest.raises(SystemExit) as excinfo:
        _run_locked_native_update(SimpleNamespace(), False)

    assert excinfo.value.code == 1


def test_locked_build_refuses_the_upstream_zip(locked, capsys):
    """The ZIP path pulls upstream Hermes; a locked build must not reach it.

    The refusal has to land before the download, so the download is replaced
    with a tripwire: if it ever runs, this fails as a test rather than as a
    tree full of upstream.
    """
    from hermes_cli.main import _update_via_zip

    def must_not_download(*args, **kwargs):
        raise AssertionError(
            "reached the upstream download — the locked refusal is gone"
        )

    with patch("urllib.request.urlretrieve", side_effect=must_not_download):
        with pytest.raises(SystemExit) as excinfo:
            _update_via_zip(SimpleNamespace(branch=None))

    assert excinfo.value.code == 1

    # The exit CODE proves nothing on its own: _update_via_zip wraps its body
    # in a broad `except Exception` that also exits 1, so a build that tried
    # the download and blew up on the tripwire above exits exactly like a
    # build that refused. Deleting the refusal left this test green until it
    # asserted on which of the two actually happened.
    out = capsys.readouterr().out
    assert "Refusing to update from the upstream ZIP archive" in out
    assert "Downloading latest version" not in out, "refused too late — after the download began"


def test_zip_update_preserves_a_dot_venv():
    """`uv sync` builds `.venv`; only `venv` was preserved, so it was deleted.

    Asserted on the source rather than by running an update: the entry list is
    the whole decision, and an end-to-end ZIP update would need a served
    archive to prove one set membership.
    """
    import inspect

    from hermes_cli import update_cmd

    source = inspect.getsource(update_cmd._update_via_zip)
    assert '".venv"' in source, "a uv-built tree keeps its interpreter in .venv"
    assert '"venv"' in source, "upstream's installer still makes plain venv"
