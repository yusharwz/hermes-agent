"""The updater stops re-downloading a desktop application it already has.

The desktop artefact is 117–140 MB — larger than the agent tree and the skills
payload together — and it changes far less often than they do, because it is
built elsewhere: macOS on a hosted runner, Windows on the build box. A run of
agent-only releases republishes the same bytes, and the updater fetched them
every time to write an identical file back over itself.

The test is written against sha256 rather than the version string on purpose:
that is what makes "identical" mean identical bytes, so an application rebuilt
under the same version number is still fetched.
"""

from __future__ import annotations

import json

import pytest

from hermes_cli import ninegate_update


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(ninegate_update, "desktop_platform", lambda: "linux-x64")
    return tmp_path


def _marker(home, payload) -> None:
    (home / "installed.json").write_text(json.dumps(payload), encoding="utf-8")


def test_identical_sha256_counts_as_installed(home):
    _marker(home, {"desktop": {"linux-x64": {"file": "Atlas.AppImage", "sha256": "abc123"}}})
    assert ninegate_update._desktop_already_installed(home, {"sha256": "abc123"}) is True


def test_a_rebuilt_application_is_still_fetched(home):
    """Same version, different bytes — the marker must not excuse the download."""
    _marker(home, {"desktop": {"linux-x64": {"sha256": "abc123", "version": "e2f5f28"}}})
    assert (
        ninegate_update._desktop_already_installed(home, {"sha256": "def456", "version": "e2f5f28"})
        is False
    )


def test_another_platforms_entry_is_not_ours(home):
    _marker(home, {"desktop": {"windows-x64": {"sha256": "abc123"}}})
    assert ninegate_update._desktop_already_installed(home, {"sha256": "abc123"}) is False


@pytest.mark.parametrize(
    "payload",
    [
        None,                                        # no marker at all
        "{not json",                                 # truncated write
        json.dumps([1, 2, 3]),                       # right file, wrong shape
        json.dumps({}),                              # pre-desktop manifest
        json.dumps({"desktop": {}}),                 # nothing published yet
        json.dumps({"desktop": {"linux-x64": {}}}),  # entry without a checksum
        json.dumps({"desktop": {"linux-x64": "Atlas.AppImage"}}),  # older shape
    ],
)
def test_anything_unreadable_means_download_it(home, payload):
    """Every doubt resolves toward fetching.

    A needless download costs a slow update. A wrongly skipped one costs the
    customer an application that never arrives, and leaves no trace saying so.
    """
    if payload is not None:
        (home / "installed.json").write_text(payload, encoding="utf-8")
    assert ninegate_update._desktop_already_installed(home, {"sha256": "abc123"}) is False


def test_an_empty_checksum_never_matches(home):
    """Two unknowns are not a match — `"" == ""` must not skip an install."""
    _marker(home, {"desktop": {"linux-x64": {"sha256": ""}}})
    assert ninegate_update._desktop_already_installed(home, {"sha256": ""}) is False