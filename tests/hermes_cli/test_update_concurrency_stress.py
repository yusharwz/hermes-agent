"""Two updates must never swap one install tree. Blok E3.

UpdateJob's docstring called itself "deliberately a singleton ... two concurrent
updates renaming the same directories would race for the rollback copy, and the
loser would restore over the winner's work." It was not one. ``begin()`` read
the state file, decided, and then wrote it, with a window in between, guarded
only by ``self._lock`` — a threading.Lock, which serialises threads inside one
interpreter and says nothing whatever about a second process.

Measured before the fix: twelve processes calling ``begin()`` through a FIFO
gate, five returned True. Each would go on to ``_swap()``, which moves the venv
into the new tree *before* renaming that tree into place — so the second swap
renames the first's finished install to .backup, and a third restores over both.
The venv is the part that does not come back.

WHY THIS TEST SPAWNS PROCESSES
==============================
It cannot be done with threads. The bug is precisely that the in-process lock
works, so a threaded version of this test passes against the broken code. The
gate is a FIFO rather than a sleep because the window is sub-millisecond: with
processes released by file-polling the pre-existing state-file check wins on
timing alone and the test passes without the lock, which is how a test comes to
assert nothing.

The workers carry ``hermes_cli.ninegate_update`` in argv deliberately. The
cross-process lock's staleness oracle reads /proc/<pid>/cmdline to answer "may
this lock be taken from its holder?", and a holder it does not recognise has
its lock taken. That is not incidental to the test setup — it is the reason
looks_like_update_runner_command_line() had to exist at all.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

WORKER = """
import os, sys, json
sys.path.insert(0, {root!r})
from hermes_cli import ninegate_update as nu
open(sys.argv[2]).read(1)          # blocks until the gate opens
print(json.dumps({{"won": nu.JOB.begin()}}), flush=True)
import time; time.sleep(3)         # hold it, the way a real swap would
"""

WORKERS = 12


@pytest.mark.skipif(os.name == "nt", reason="FIFO gate is POSIX-only")
def test_only_one_process_may_claim_the_install_tree(tmp_path):
    home = tmp_path / "atlas-home"
    home.mkdir()
    fifo = tmp_path / "gate.fifo"
    os.mkfifo(fifo)

    env = {**os.environ, "ATLAS_HOME": str(home)}
    code = WORKER.format(root=str(REPO_ROOT))

    procs = [
        subprocess.Popen(
            # argv[1] is inert: it exists so /proc/<pid>/cmdline carries the
            # runner's identity, which is what the lock's oracle inspects.
            [sys.executable, "-c", code, "hermes_cli.ninegate_update", str(fifo)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )
        for _ in range(WORKERS)
    ]
    try:
        # Every worker must be parked on the blocking read before the gate
        # opens, or they trickle in and never actually collide.
        time.sleep(2.5)
        with open(fifo, "w") as gate:
            gate.write("x" * WORKERS)

        winners = 0
        for proc in procs:
            line = proc.stdout.readline() or '{"won": false}'
            winners += bool(json.loads(line)["won"])
    finally:
        for proc in procs:
            proc.kill()

    assert winners == 1, (
        f"{winners} of {WORKERS} processes claimed the update. More than one means "
        "two runs swap the same tree: the second renames the first's finished "
        "install aside, and the venv does not survive the third restoring over "
        "both. Exactly one must win."
    )
