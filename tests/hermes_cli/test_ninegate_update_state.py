"""An update outlives the window that started it.

The job used to be a thread in the gateway, holding its progress in memory.
The desktop app spawns that gateway as a child and SIGTERMs it on quit, so two
things followed from one design:

  * the progress bar belonged to a settings tab. Switching tabs unmounted the
    poller, and the next render started from "no update running" — so the
    button came back, and pressing it answered 409, which is what a customer
    reported as "clicking update throws an error".
  * closing the app during an update killed the update, wherever it had got
    to. That can be between renaming the old tree and restoring the venv into
    the new one.

So progress is a file, and the work runs in its own process. These tests cover
what that file has to survive: a reader in another process, a runner that dies
without finishing, and a second request arriving while one is in flight.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

from hermes_cli import ninegate_update

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """An ATLAS_HOME of our own, so a real install is never read or written."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))
    # A fresh singleton per test, restored afterwards — this module's JOB is
    # process-wide, and a leaked "running" from one test is exactly the kind of
    # order-dependent failure this suite already has too much of.
    monkeypatch.setattr(ninegate_update, "JOB", ninegate_update.UpdateJob())

    return tmp_path


def _state(home):
    return json.loads((home / "update-state.json").read_text(encoding="utf-8"))


def test_no_file_reads_as_idle(home):
    assert ninegate_update.read_state()["running"] is False
    assert ninegate_update.read_state()["done"] is False


def test_progress_is_readable_by_another_process(home):
    """The whole point: the reader is not the writer.

    The gateway answering /progress may be a different process from the one
    doing the work — and after the swap it is a different *build*.
    """
    job = ninegate_update.UpdateJob()
    assert job.begin() is True
    job.progress("download", 42, "Mengunduh Atlas…")

    fresh = ninegate_update.read_state()

    assert fresh["running"] is True
    assert fresh["percent"] == 42
    assert fresh["message"] == "Mengunduh Atlas…"
    assert fresh["pid"] == os.getpid()

    job.finish(ok=True, restart_required=True, message="selesai")
    done = ninegate_update.read_state()

    assert done["running"] is False
    assert done["done"] is True
    assert done["ok"] is True
    assert done["restart_required"] is True
    assert done["percent"] == 100


def test_a_runner_that_died_is_reported_as_interrupted(home):
    """Not as running forever.

    A progress bar for a process that is gone is worse than an error: the
    customer waits instead of retrying, and nothing will ever move it.
    """
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()

    ninegate_update._write_state(
        {
            **ninegate_update.IDLE_STATE,
            "running": True,
            "stage": "download",
            "percent": 30,
            "pid": dead.pid,
            "started_at": time.time(),
            "updated_at": time.time(),
        }
    )

    state = ninegate_update.read_state()

    assert state["running"] is False
    assert state["done"] is True
    assert state["ok"] is False
    assert "terhenti" in state["error"]
    # Written back, so every later reader agrees without re-deciding.
    assert _state(home)["running"] is False


def test_a_stale_heartbeat_is_interrupted_even_if_the_pid_is_alive(home):
    """The pid check cannot be trusted alone — a pid is reused, and on Windows
    it cannot be checked at all. The heartbeat is what makes liveness portable.
    """
    ninegate_update._write_state(
        {
            **ninegate_update.IDLE_STATE,
            "running": True,
            "percent": 10,
            "pid": os.getpid(),  # very much alive
            "started_at": time.time() - 10_000,
            "updated_at": time.time() - (ninegate_update.STALE_AFTER + 30),
        }
    )

    assert ninegate_update.read_state()["running"] is False


def test_a_live_job_is_left_alone(home):
    ninegate_update._write_state(
        {
            **ninegate_update.IDLE_STATE,
            "running": True,
            "percent": 55,
            "pid": os.getpid(),
            "started_at": time.time(),
            "updated_at": time.time(),
        }
    )

    assert ninegate_update.read_state()["running"] is True
    assert ninegate_update.read_state()["percent"] == 55


def test_the_gateway_claim_shows_a_start_before_the_runner_exists(home):
    """Without it, the first poll after the request returns the PREVIOUS run's
    result — which reads as "already finished", and the customer concludes the
    button did nothing.
    """
    ninegate_update._write_state(
        {**ninegate_update.IDLE_STATE, "done": True, "ok": True, "percent": 100, "version": "old"}
    )

    job = ninegate_update.UpdateJob()

    assert job.claim() is True

    claimed = ninegate_update.read_state()

    assert claimed["running"] is True
    assert claimed["done"] is False
    assert claimed["ok"] is False
    assert claimed["percent"] == 0
    assert claimed["pid"] is None


def test_the_runner_adopts_the_claim(home):
    """A claim with no pid is the gateway holding the place for the runner it
    just spawned. The runner must take it over, not refuse it as a conflict."""
    gateway_side = ninegate_update.UpdateJob()
    assert gateway_side.claim() is True

    runner_side = ninegate_update.UpdateJob()
    assert runner_side.begin() is True
    assert ninegate_update.read_state()["pid"] == os.getpid()


def test_a_second_request_is_refused_while_one_runs(home):
    """This is the 409 the UI used to walk into. It is still a 409 — what
    changed is that the UI no longer forgets an update is running."""
    runner = ninegate_update.UpdateJob()
    assert runner.begin() is True

    assert ninegate_update.UpdateJob().claim() is False
    assert ninegate_update.UpdateJob().begin() is False


def test_a_failed_spawn_releases_the_claim_with_a_reason(home):
    job = ninegate_update.UpdateJob()
    job.claim()
    job.fail_claim("Pembaruan tidak bisa dimulai: boom")

    state = ninegate_update.read_state()

    assert state["running"] is False
    assert state["done"] is True
    assert state["ok"] is False
    assert "boom" in state["error"]


def test_a_finished_run_does_not_block_the_next_one(home):
    first = ninegate_update.UpdateJob()
    first.begin()
    first.finish(ok=True)

    assert ninegate_update.UpdateJob().claim() is True


def test_the_detached_runner_refuses_without_a_gateway_or_key(home, monkeypatch):
    """It must write the failure rather than exiting quietly: the gateway has
    already claimed, and an unreleased claim is a progress bar that only clears
    when it times out."""
    monkeypatch.setattr(sys, "argv", ["ninegate_update", "--apply"])
    monkeypatch.delenv("NINEGATE_GATEWAY_URL", raising=False)
    monkeypatch.delenv("NINEGATE_API_KEY", raising=False)

    assert ninegate_update.main() == 2

    state = ninegate_update.read_state()

    assert state["running"] is False
    assert state["ok"] is False
    assert "API key" in state["error"]


def test_the_detached_runner_reports_through_the_file(home):
    """End to end, with a real second process.

    Nothing here is mocked: a separate interpreter runs the module, fails to
    reach a gateway that is not listening, and this process — which never
    touched that job — reads what happened out of the file. That is the whole
    contract the desktop app depends on when it reopens mid-update.
    """
    env = dict(os.environ)
    env["ATLAS_HOME"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH", "")]))
    # Nothing listens here, so the manifest fetch fails immediately and
    # offline: the test is about the reporting, not about the network.
    env["NINEGATE_GATEWAY_URL"] = "http://127.0.0.1:1"
    env["NINEGATE_API_KEY"] = "ng_live_" + "x" * 24

    done = subprocess.run(
        [sys.executable, "-m", "hermes_cli.ninegate_update", "--apply"],
        cwd=str(home),
        env=env,
        capture_output=True,
        timeout=120,
    )

    assert done.returncode == 1, done.stderr.decode("utf-8", "replace")

    state = ninegate_update.read_state()

    assert state["running"] is False
    assert state["done"] is True
    assert state["ok"] is False
    assert state["error"]
    # It got far enough to claim the job and stamp itself as the owner.
    assert state["started_at"] is not None
