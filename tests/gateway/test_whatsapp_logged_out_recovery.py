"""A restricted number should leave the product ready to pair again.

WhatsApp unlinks every device on a number when it restricts the account, so
the credentials on disk are dead on the server and nothing revives them. Two
things used to go wrong at that moment:

  - the dead session stayed on disk, so every reader that goes by "is there a
    creds.json" reported the account as linked, and the operator had to clear
    the directory by hand before the QR code they were told to scan would work;

  - the platform reported a non-retryable fatal error, and when WhatsApp was
    the only enabled platform the gateway treated that as a startup conflict
    and exited 78 — taking cron, the dashboard's gateway view and every other
    platform down at exactly the moment the operator was trying to re-pair.
"""

import json

import pytest

from hermes_constants import (
    WHATSAPP_LOGGED_OUT_MARKER,
    clear_whatsapp_session,
    whatsapp_session_is_linked,
)


def _dead_session(tmp_path):
    session = tmp_path / "session"
    session.mkdir(parents=True)
    (session / "creds.json").write_text(json.dumps({"me": {"id": "62999@s.whatsapp.net"}}))
    (session / "app-state-sync-key-AAA.json").write_text("{}")
    (session / WHATSAPP_LOGGED_OUT_MARKER).write_text(json.dumps({"reason": 401}))
    return session


class TestClearWhatsappSession:
    def test_a_revoked_session_reads_as_unlinked_then_clears(self, tmp_path):
        session = _dead_session(tmp_path)
        assert whatsapp_session_is_linked(session) is False

        assert clear_whatsapp_session(session) is True
        assert not session.exists()

    def test_clearing_a_session_that_is_not_there_is_not_an_error(self, tmp_path):
        assert clear_whatsapp_session(tmp_path / "nope") is False

    def test_a_cleared_session_is_ready_for_a_fresh_pairing(self, tmp_path):
        session = _dead_session(tmp_path)
        clear_whatsapp_session(session)
        session.mkdir(parents=True, exist_ok=True)

        # Nothing left to mistake for a live pairing.
        assert list(session.iterdir()) == []
        assert whatsapp_session_is_linked(session) is False

    def test_it_honours_the_directory_it_is_given(self, tmp_path):
        """Passing the resolved directory matters: re-resolving here would
        answer about a different profile's session than the caller meant."""
        mine = _dead_session(tmp_path / "a")
        theirs = _dead_session(tmp_path / "b")

        clear_whatsapp_session(mine)
        assert not mine.exists()
        assert theirs.exists(), "clearing one profile must not touch another"


class TestAwaitingSetupDoesNotKillTheGateway:
    def test_pairing_is_classified_apart_from_misconfiguration(self):
        from gateway.run import _AWAITING_SETUP_ERROR_CODES

        assert "whatsapp_not_paired" in _AWAITING_SETUP_ERROR_CODES
        # A genuine misconfiguration must still be able to stop the gateway.
        assert "whatsapp_bridge_missing" not in _AWAITING_SETUP_ERROR_CODES
        assert "whatsapp_node_missing" not in _AWAITING_SETUP_ERROR_CODES

    def test_both_unpaired_paths_report_the_same_code(self):
        """A never-paired install and a revoked pairing are the same state
        once the dead session is cleared, so they must report it the same way
        or only one of them gets the gateway-stays-up treatment."""
        import inspect

        from plugins.platforms.whatsapp import adapter as mod

        src = inspect.getsource(mod)
        assert src.count('"whatsapp_not_paired"') == 2
        assert '"whatsapp_logged_out"' not in src, (
            "the revoked-pairing path should resolve to not-paired after clearing"
        )

    def test_the_revoked_path_clears_before_reporting(self):
        import inspect

        from plugins.platforms.whatsapp import adapter as mod

        src = inspect.getsource(mod)
        clear_at = src.index("clear_whatsapp_session(self._session_path)")
        report_at = src.index('"whatsapp_not_paired"', clear_at)
        assert clear_at < report_at, "clear the corpse before reporting the state"
