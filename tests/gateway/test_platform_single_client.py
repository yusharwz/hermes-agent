"""One identity, one client — for the platforms where a second one does harm.

The rule the WhatsApp incident established: if two adapters can attach to the
same account at once, they must be serialised on a lock keyed by that account.
WhatsApp was the loud case, because the server evicts the older device and the
number gets restricted for the resulting churn. The quiet cases are worse in
a different way: nothing is disconnected, nothing errors, and the assistant
simply answers every message twice for as long as both are running.

  email       two adapters sweep one mailbox, both see the same UNSEEN mail,
              both reply, and each marks it read under the other.
  mattermost  one bot token, and the server delivers `posted` to every
              subscribed WebSocket. Concurrent sessions are allowed, so the
              clash never surfaces as an error.
  simplex     one daemon holds one chat profile and one database, and its
              event stream goes to whoever is connected.

WHAT THIS FILE DOES NOT CLAIM
=============================
`UNAUDITED` below is exactly that. Those platforms have not been examined for
this pattern, and their absence from the locked set is not evidence that they
are safe — only that nobody has looked. Do not read it as a clean bill.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Platforms proven to serialise on the identity a second client would duplicate.
# A platform dropping out of this set is a regression, and the failure names it.
LOCKED = {
    "buzz", "discord", "email", "feishu", "irc", "line", "mattermost",
    "matrix", "simplex", "slack", "telegram", "whatsapp",
}

# Deliberate, with the reason.
INTENTIONALLY_UNLOCKED = {
    # Pure webhook: Meta POSTs to one URL. There is no second client to
    # serialise, because there is no client at all.
    "whatsapp_cloud",
}

# Not examined. Listed so the gap is visible rather than implied.
UNAUDITED = {
    "dingtalk", "google_chat", "homeassistant", "ntfy", "photon", "raft",
    "sms", "teams", "wecom",
}


def _adapter_source(platform: str) -> str:
    path = ROOT / "plugins" / "platforms" / platform / "adapter.py"
    if not path.exists():
        path = ROOT / "gateway" / "platforms" / f"{platform}.py"
    if not path.exists():
        path = ROOT / "gateway" / "platforms" / platform / "adapter.py"
    assert path.exists(), f"no adapter found for {platform}"
    return path.read_text(encoding="utf-8")


# Two ways in, one mechanism underneath: most adapters call the base class
# helper, a few call gateway.status.acquire_scoped_lock directly. Both end in
# the same lock file, so both count.
ACQUIRE = ("_acquire_platform_lock", "acquire_scoped_lock")
RELEASE = ("_release_platform_lock", "release_scoped_lock")


@pytest.mark.parametrize("platform", sorted(LOCKED))
def test_a_locked_platform_still_takes_its_lock(platform):
    source = _adapter_source(platform)
    assert any(name in source for name in ACQUIRE), (
        f"{platform} no longer takes a platform lock. Two adapters on one "
        "account will both answer every message."
    )


@pytest.mark.parametrize("platform", sorted(LOCKED))
def test_a_locked_platform_gives_the_lock_back(platform):
    source = _adapter_source(platform)
    assert any(name in source for name in RELEASE), (
        f"{platform} takes a lock it never releases; a clean disconnect leaves "
        "the platform unusable until the holder's process dies"
    )


def test_the_three_quiet_platforms_lock_on_the_right_identity():
    """The identity has to be what a second client would be duplicating.

    Keyed wrongly, the lock is worse than none: two adapters on one mailbox
    take two different locks, each believes it is alone, and the reassurance is
    false. That is precisely how the WhatsApp session lock failed — it was
    keyed on a session path that had itself forked in two.
    """
    from gateway.config import PlatformConfig

    captured = {}

    def fake_acquire(self, scope, identity, desc):
        captured[scope] = identity
        return False  # stop before any network call

    import asyncio

    from gateway.platforms.base import BasePlatformAdapter

    original = BasePlatformAdapter._acquire_platform_lock
    BasePlatformAdapter._acquire_platform_lock = fake_acquire
    try:
        from plugins.platforms.email.adapter import EmailAdapter
        from plugins.platforms.mattermost.adapter import MattermostAdapter
        from plugins.platforms.simplex.adapter import SimplexAdapter

        email = EmailAdapter(
            PlatformConfig(
                enabled=True,
                extra={
                    "address": "bot@example.com",
                    "password": "x",
                    "imap_host": "imap.example.com",
                    "smtp_host": "smtp.example.com",
                },
            )
        )
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(email.connect())

        mm = MattermostAdapter(
            PlatformConfig(enabled=True, token="tok", extra={"url": "https://mm.example.com"})
        )
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(mm.connect())

        sx = SimplexAdapter(
            PlatformConfig(enabled=True, extra={"ws_url": "ws://127.0.0.1:5225"})
        )
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(sx.connect())
    finally:
        BasePlatformAdapter._acquire_platform_lock = original

    # The mailbox, not the host: two accounts on one IMAP server are two
    # identities and must not serialise against each other.
    assert "bot@example.com" in captured["email-mailbox"]
    assert "imap.example.com" in captured["email-mailbox"]

    # The token, because that is the bot account. Two bots on one server are
    # two identities.
    assert "tok" in captured["mattermost-session"]
    assert "mm.example.com" in captured["mattermost-session"]

    # The daemon address: one process, one profile, one database.
    assert captured["simplex-daemon"] == "ws://127.0.0.1:5225"


def test_the_unaudited_list_is_not_mistaken_for_a_clean_bill():
    """A platform cannot be in two of the three sets at once.

    Chiefly so that moving one out of UNAUDITED is a deliberate edit in this
    file rather than something that happens by accident.
    """
    assert not LOCKED & UNAUDITED
    assert not LOCKED & INTENTIONALLY_UNLOCKED
    assert not UNAUDITED & INTENTIONALLY_UNLOCKED


def test_every_platform_on_disk_is_accounted_for():
    """A new platform must be classified, not silently absent."""
    on_disk = {
        p.name
        for p in (ROOT / "plugins" / "platforms").iterdir()
        if p.is_dir() and (p / "adapter.py").exists()
    }
    unclassified = on_disk - LOCKED - UNAUDITED - INTENTIONALLY_UNLOCKED
    assert not unclassified, (
        f"{sorted(unclassified)} are not classified. Decide whether a second "
        "adapter on the same account does harm, and record the answer here."
    )