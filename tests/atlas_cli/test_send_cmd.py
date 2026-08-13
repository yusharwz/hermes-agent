"""Tests for the ``atlas send`` CLI subcommand.

Covers the argument parsing / stdin / file / list behavior of
``atlas_cli.send_cmd``. The underlying ``send_message_tool`` is stubbed so
no network I/O or gateway is required.
"""

from __future__ import annotations

import io
import json

import pytest

from atlas_cli import send_cmd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(argv):
    """Build the top-level parser and return the parsed args for ``argv``."""
    import argparse

    parser = argparse.ArgumentParser(prog="atlas")
    subparsers = parser.add_subparsers(dest="command")
    send_cmd.register_send_subparser(subparsers)
    return parser.parse_args(["send", *argv])


class _FakeTool:
    """Replacement for ``tools.send_message_tool.send_message_tool``."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, args, **_kw):
        self.calls.append(dict(args))
        return json.dumps(self.payload)


@pytest.fixture
def fake_tool(monkeypatch):
    """Install a fake send_message_tool and return the stub for inspection."""
    import sys
    import types

    fake = _FakeTool({"success": True, "message_id": "m123"})

    mod = types.ModuleType("tools.send_message_tool")
    mod.send_message_tool = fake
    # Register the stub so ``from tools.send_message_tool import ...`` inside
    # cmd_send resolves to our fake. Also patch the parent ``tools`` package
    # entry so attribute lookup works.
    monkeypatch.setitem(sys.modules, "tools.send_message_tool", mod)
    return fake


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------




def test_file_decode_error_suggests_media_directive(fake_tool, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    bad = tmp_path / "bad-bytes.bin"
    bad.write_bytes(b"\xff\xfe\x00")

    args = _parse(["--to", "telegram", "--file", str(bad)])
    with pytest.raises(SystemExit) as exc:
        send_cmd.cmd_send(args)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not a text file" in err.lower()
    assert f"MEDIA:{bad}" in err
    assert "[[as_document]]" in err






# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Parser registration contract
# ---------------------------------------------------------------------------


def test_register_send_subparser_is_reusable():
    """Sanity check: the registrar returns a parser and wires ``cmd_send``."""
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    send_parser = send_cmd.register_send_subparser(subparsers)
    assert send_parser is not None
    args = parser.parse_args(["send", "--to", "telegram", "hi"])
    assert args.func is send_cmd.cmd_send
    assert args.to == "telegram"
    assert args.message == "hi"


# ---------------------------------------------------------------------------
# Env loader
# ---------------------------------------------------------------------------


def test_load_atlas_env_bridges_config_yaml_scalars(tmp_path, monkeypatch):
    """Top-level config.yaml scalars should be bridged into os.environ.

    This mirrors the gateway/run.py bootstrap behavior: without this, running
    ``atlas send`` from a fresh shell cannot resolve the home channel
    because ``TELEGRAM_HOME_CHANNEL`` (saved by ``atlas config set``) lives
    in config.yaml, not in .env — and the gateway's config loader reads via
    ``os.getenv(...)``.
    """
    import os

    atlas_home = tmp_path / ".atlas"
    atlas_home.mkdir()
    (atlas_home / ".env").write_text("SOME_TOKEN=abc123\n")
    (atlas_home / "config.yaml").write_text(
        "TELEGRAM_HOME_CHANNEL: '5550001111'\nnested:\n  ignored: true\n"
    )

    monkeypatch.setenv("ATLAS_HOME", str(atlas_home))
    monkeypatch.delenv("TELEGRAM_HOME_CHANNEL", raising=False)
    monkeypatch.delenv("SOME_TOKEN", raising=False)

    # Force get_atlas_home() to re-resolve under the patched env.
    from importlib import reload

    import atlas_cli.config as _hc_config
    reload(_hc_config)

    send_cmd._load_atlas_env()

    assert os.environ.get("SOME_TOKEN") == "abc123"
    assert os.environ.get("TELEGRAM_HOME_CHANNEL") == "5550001111"


def test_load_atlas_env_utf8_bom_preserves_first_key(tmp_path, monkeypatch):
    """A leading UTF-8 BOM must not mangle the first .env key name.

    PowerShell 5.1 `Set-Content -Encoding UTF8` and Notepad prepend a BOM
    (EF BB BF). With encoding=utf-8, python-dotenv kept U+FEFF on the first
    key, so the credential never appeared under its canonical name and
    `atlas send` failed to authenticate.
    """
    import os

    atlas_home = tmp_path / ".atlas"
    atlas_home.mkdir()
    (atlas_home / ".env").write_bytes(
        b"\xef\xbb\xbfSEND_BOM_BOT_TOKEN=tok-first\nSEND_BOM_SECOND=two\n"
    )

    monkeypatch.setenv("ATLAS_HOME", str(atlas_home))
    monkeypatch.delenv("SEND_BOM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SEND_BOM_SECOND", raising=False)

    from importlib import reload
    import atlas_cli.config as _hc_config
    reload(_hc_config)

    send_cmd._load_atlas_env()

    assert os.environ.get("SEND_BOM_BOT_TOKEN") == "tok-first"
    assert os.environ.get("SEND_BOM_SECOND") == "two"
    assert "\ufeff" + "SEND_BOM_BOT_TOKEN" not in os.environ

def test_load_atlas_env_bomless_utf8_still_loads(tmp_path, monkeypatch):
    """BOM-less UTF-8 .env files must keep loading after the utf-8-sig switch."""
    import os

    atlas_home = tmp_path / ".atlas"
    atlas_home.mkdir()
    (atlas_home / ".env").write_bytes(b"SEND_PLAIN_TOKEN=plain-val\n")

    monkeypatch.setenv("ATLAS_HOME", str(atlas_home))
    monkeypatch.delenv("SEND_PLAIN_TOKEN", raising=False)

    from importlib import reload
    import atlas_cli.config as _hc_config
    reload(_hc_config)

    send_cmd._load_atlas_env()

    assert os.environ.get("SEND_PLAIN_TOKEN") == "plain-val"

def test_load_atlas_env_latin1_fallback_still_loads(tmp_path, monkeypatch):
    """Invalid UTF-8 bytes must still load via the latin-1 fallback path,
    and a leading BOM must be stripped before the latin-1 decode so the
    first key keeps its canonical name."""
    import os

    atlas_home = tmp_path / ".atlas"
    atlas_home.mkdir()
    # BOM + valid first key + latin-1 é (0xE9, invalid UTF-8 alone) in a
    # later value — forces the UnicodeDecodeError → latin-1 stream path.
    (atlas_home / ".env").write_bytes(
        b"\xef\xbb\xbfSEND_L1_TOKEN=tok-l1\nSEND_L1_NOTE=caf\xe9\n"
    )

    monkeypatch.setenv("ATLAS_HOME", str(atlas_home))
    monkeypatch.delenv("SEND_L1_TOKEN", raising=False)
    monkeypatch.delenv("SEND_L1_NOTE", raising=False)

    from importlib import reload
    import atlas_cli.config as _hc_config
    reload(_hc_config)

    send_cmd._load_atlas_env()

    assert os.environ.get("SEND_L1_TOKEN") == "tok-l1"
    assert os.environ.get("SEND_L1_NOTE") == "caf\xe9"
    assert "\ufeff" + "SEND_L1_TOKEN" not in os.environ

def test_load_atlas_env_latin1_fallback_overrides_shell(tmp_path, monkeypatch):
    """The stream-based latin-1 fallback must keep override=True semantics:
    the .env value wins over a stale shell export, same as the primary path."""
    import os

    atlas_home = tmp_path / ".atlas"
    atlas_home.mkdir()
    # 0xE9 forces the UnicodeDecodeError \u2192 latin-1 stream fallback.
    (atlas_home / ".env").write_bytes(b"SEND_OVR_TOKEN=caf\xe9-file\n")

    monkeypatch.setenv("ATLAS_HOME", str(atlas_home))
    monkeypatch.setenv("SEND_OVR_TOKEN", "stale-shell-value")

    from importlib import reload
    import atlas_cli.config as _hc_config
    reload(_hc_config)

    send_cmd._load_atlas_env()

    assert os.environ.get("SEND_OVR_TOKEN") == "caf\xe9-file"

def test_load_atlas_env_fallback_read_error_is_swallowed(tmp_path, monkeypatch):
    """An I/O error inside the latin-1 fallback must not escape \u2014 the send
    path is best-effort by design and must never crash on a broken .env."""
    from pathlib import Path

    atlas_home = tmp_path / ".atlas"
    atlas_home.mkdir()
    # Invalid UTF-8 so the fallback (and its read_bytes call) is reached.
    (atlas_home / ".env").write_bytes(b"SEND_ERR_TOKEN=caf\xe9\n")

    monkeypatch.setenv("ATLAS_HOME", str(atlas_home))

    def _boom(self):
        raise OSError("disk went away")

    monkeypatch.setattr(Path, "read_bytes", _boom)

    from importlib import reload
    import atlas_cli.config as _hc_config
    reload(_hc_config)

    # Should not raise.
    send_cmd._load_atlas_env()

def test_load_atlas_env_bom_only_env_is_noop(tmp_path, monkeypatch):
    """A .env containing only a BOM must load zero vars without error."""
    import os

    atlas_home = tmp_path / ".atlas"
    atlas_home.mkdir()
    (atlas_home / ".env").write_bytes(b"\xef\xbb\xbf")

    monkeypatch.setenv("ATLAS_HOME", str(atlas_home))

    from importlib import reload
    import atlas_cli.config as _hc_config
    reload(_hc_config)

    before = dict(os.environ)
    send_cmd._load_atlas_env()

    added = {k: v for k, v in os.environ.items() if k not in before}
    assert "\ufeff" not in "".join(added)
