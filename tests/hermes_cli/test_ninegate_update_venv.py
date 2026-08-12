"""The venv survives an update.

An installation's interpreter lives inside the source tree the updater
replaces, and no published tarball carries one. Before these tests, a swap
moved the tree and left the interpreter behind in a backup that was then
deleted — the service's ExecStart pointed at nothing, and the update reported
success while doing it, because the smoke test that licensed deleting the
backup ran on a system python3 that had never been the one at risk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import ninegate_update as nu
from hermes_constants import venv_python_path


def _tree_with_venv(root: Path, name: str, *, venv_dir: str = ".venv") -> Path:
    """A source tree carrying a venv, like an installed one."""
    tree = root / name
    tree.mkdir(parents=True)
    (tree / "marker.txt").write_text(name, encoding="utf-8")
    python = venv_python_path(tree / venv_dir)
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tree / venv_dir / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    return tree


class TestSwapKeepsTheInterpreter:
    def test_venv_moves_into_the_new_tree(self, tmp_path: Path) -> None:
        live = _tree_with_venv(tmp_path, "live")
        new = tmp_path / "new"
        new.mkdir()
        (new / "marker.txt").write_text("new", encoding="utf-8")
        backup = tmp_path / "live.rollback"

        nu._swap(new, live, backup)

        assert venv_python_path(live / ".venv").exists(), (
            "the interpreter the service runs on did not survive the swap"
        )
        assert (live / "marker.txt").read_text(encoding="utf-8") == "new"
        assert not venv_python_path(backup / ".venv").exists(), (
            "the venv was copied rather than moved; two trees now claim it"
        )

    def test_deleting_the_backup_cannot_take_the_venv(self, tmp_path: Path) -> None:
        """The step that made the loss permanent.

        `run_update` removes the backup once the smoke test passes. That is
        only safe if the venv is no longer inside it.
        """
        import shutil

        live = _tree_with_venv(tmp_path, "live")
        new = tmp_path / "new"
        new.mkdir()
        backup = tmp_path / "live.rollback"

        nu._swap(new, live, backup)
        shutil.rmtree(backup, ignore_errors=True)

        assert venv_python_path(live / ".venv").exists()

    def test_a_tree_without_a_venv_is_not_an_error(self, tmp_path: Path) -> None:
        live = tmp_path / "live"
        live.mkdir()
        new = tmp_path / "new"
        new.mkdir()

        nu._swap(new, live, tmp_path / "live.rollback")

        assert live.exists()

    def test_the_bare_venv_name_is_honoured_too(self, tmp_path: Path) -> None:
        live = _tree_with_venv(tmp_path, "live", venv_dir="venv")
        new = tmp_path / "new"
        new.mkdir()

        nu._swap(new, live, tmp_path / "live.rollback")

        assert venv_python_path(live / "venv").exists()


class TestRollbackKeepsTheInterpreter:
    def test_restore_brings_the_venv_back(self, tmp_path: Path) -> None:
        """Rolling back must not land on a tree with no interpreter.

        `_swap` moved the venv into the tree `_restore` deletes, so a restore
        that ignored it would reproduce the very breakage it exists to undo.
        """
        live = _tree_with_venv(tmp_path, "live")
        new = tmp_path / "new"
        new.mkdir()
        (new / "marker.txt").write_text("new", encoding="utf-8")
        backup = tmp_path / "live.rollback"

        nu._swap(new, live, backup)
        nu._restore(live, backup)

        assert (live / "marker.txt").read_text(encoding="utf-8") == "live"
        assert venv_python_path(live / ".venv").exists(), (
            "rolled back onto an installation with no interpreter"
        )


class TestSmokeTestUsesTheRealInterpreter:
    def test_prefers_the_venv_in_the_tree(self, tmp_path: Path) -> None:
        tree = _tree_with_venv(tmp_path, "tree")

        assert nu._smoke_test_python(tree) == str(venv_python_path(tree / ".venv"))

    def test_falls_back_when_the_tree_has_no_venv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tree = tmp_path / "tree"
        tree.mkdir()
        monkeypatch.setenv("ATLAS_PYTHON", "/custom/python")

        assert nu._smoke_test_python(tree) == "/custom/python"

    def test_the_venv_outranks_the_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The interpreter that exists in the tree is the one that runs.

        This is the assertion that would have failed before the fix: the
        smoke test reached for a system python3 and passed on it, which is
        why a destroyed venv still looked like a successful update.
        """
        tree = _tree_with_venv(tmp_path, "tree")
        monkeypatch.setenv("ATLAS_PYTHON", "/custom/python")

        assert nu._smoke_test_python(tree) == str(venv_python_path(tree / ".venv"))
