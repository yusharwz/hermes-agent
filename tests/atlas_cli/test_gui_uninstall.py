"""Tests for atlas_cli.gui_uninstall — GUI-only uninstall + install discovery.

Covers the cross-platform artifact discovery, the agent/GUI detection the
desktop UI gates options on, and that ``uninstall_gui`` removes only GUI
artifacts (built renderer/release/node_modules, packaged bundle, Electron
userData) while leaving the Python agent + config/sessions/.env intact.
"""

import sys
from pathlib import Path

import pytest

import atlas_cli.gui_uninstall as gu


def _make_agent(atlas_home: Path) -> Path:
    """Create a fake agent install: source package + venv."""
    agent_root = atlas_home / "atlas-agent"
    (agent_root / "atlas_cli").mkdir(parents=True)
    (agent_root / "atlas_cli" / "__init__.py").write_text("")
    (agent_root / "venv" / "bin").mkdir(parents=True)
    return agent_root


def _make_gui_build(atlas_home: Path) -> None:
    """Create the source-built GUI artifacts a `atlas desktop` run produces."""
    desktop = atlas_home / "atlas-agent" / "apps" / "desktop"
    (desktop / "dist").mkdir(parents=True)
    (desktop / "dist" / "index.html").write_text("<html>")
    (desktop / "release" / "linux-unpacked").mkdir(parents=True)
    (desktop / "node_modules").mkdir(parents=True)
    (atlas_home / "atlas-agent" / "node_modules").mkdir(parents=True)
    (atlas_home / "desktop-build-stamp.json").write_text("{}")


def _make_user_data(atlas_home: Path) -> None:
    (atlas_home / "config.yaml").write_text("x: 1\n")
    (atlas_home / ".env").write_text("KEY=secret\n")
    (atlas_home / "sessions").mkdir()










def test_gui_install_summary_shape(tmp_path, monkeypatch):
    atlas_home = tmp_path / ".atlas"
    _make_agent(atlas_home)
    _make_gui_build(atlas_home)
    monkeypatch.setattr(gu, "packaged_gui_app_paths", lambda: [])
    monkeypatch.setattr(gu, "desktop_userdata_dir", lambda: tmp_path / "none")

    summary = gu.gui_install_summary(atlas_home)
    # JSON-serializable primitives the desktop UI gates on.
    assert summary["agent_installed"] is True
    assert summary["gui_installed"] is True
    assert isinstance(summary["source_built_artifacts"], list)
    assert all(isinstance(p, str) for p in summary["source_built_artifacts"])
    assert summary["atlas_home"] == str(atlas_home)
    assert summary["platform"] == sys.platform






@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink semantics")
def test_remove_path_handles_symlink(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    assert gu._remove_path(link) is True
    assert not link.exists()
    # The symlink is gone but its target is untouched.
    assert target.exists()


class _Args:
    """Minimal argparse-Namespace stand-in for run_uninstall."""

    def __init__(self, *, yes=False, full=False, gui=False, gui_summary=False):
        self.yes = yes
        self.full = full
        self.gui = gui
        self.gui_summary = gui_summary








def test_uninstall_args_namespace_mode_mapping():
    """_UninstallArgs maps mode → the gui/full flags run_uninstall reads."""
    import atlas_cli.uninstall as uninstall

    gui = uninstall._UninstallArgs(mode="gui")
    assert gui.gui is True and gui.full is False and gui.yes is True

    lite = uninstall._UninstallArgs(mode="lite")
    assert lite.gui is False and lite.full is False and lite.yes is True

    full = uninstall._UninstallArgs(mode="full")
    assert full.gui is False and full.full is True and full.yes is True

