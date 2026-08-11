"""Matrix must not run two clients on one identity.

Every other stateful platform adapter takes a scoped lock before it connects
— Telegram on its bot token, Discord on its, WhatsApp on its session path.
Matrix did not, and it is the platform where a duplicate hurts most: an access
token *is* a device, ``/sync`` delivers each to-device message once to whoever
asks first, and Olm/Megolm room keys for encrypted rooms arrive that way. Two
adapters on one token split the room keys between them, so neither can read
the traffic the other received — before counting duplicate replies and two
writers on one ``crypto.db``.
"""

from unittest.mock import patch

import pytest


def _make_adapter(token="syt_test_token", homeserver="https://hs.example"):
    from gateway.config import PlatformConfig
    from plugins.platforms.matrix.adapter import MatrixAdapter

    adapter = MatrixAdapter(PlatformConfig(enabled=True, token=token))
    adapter._homeserver = homeserver
    adapter._access_token = token
    return adapter


@pytest.mark.asyncio
async def test_connect_refuses_when_another_client_holds_the_session():
    adapter = _make_adapter()

    with patch.object(adapter, "_acquire_platform_lock", return_value=False) as acquire, \
         patch.object(adapter, "_connect_locked") as body:
        assert await adapter.connect() is False

    acquire.assert_called_once()
    scope, identity, _desc = acquire.call_args[0]
    assert scope == "matrix-session"
    assert identity == "syt_test_token", "the token is the identity — it is the device"
    body.assert_not_called(), "no network call may happen before the lock is held"


@pytest.mark.asyncio
async def test_lock_is_released_when_the_connect_body_fails():
    """Otherwise a failed connect strands the lock and the retry refuses
    itself for as long as the process lives."""
    adapter = _make_adapter()

    with patch.object(adapter, "_acquire_platform_lock", return_value=True), \
         patch.object(adapter, "_release_platform_lock") as release, \
         patch.object(adapter, "_connect_locked", return_value=False):
        assert await adapter.connect() is False

    release.assert_called_once()


@pytest.mark.asyncio
async def test_lock_is_released_when_the_connect_body_raises():
    adapter = _make_adapter()

    async def _boom(**_kwargs):
        raise RuntimeError("homeserver unreachable")

    with patch.object(adapter, "_acquire_platform_lock", return_value=True), \
         patch.object(adapter, "_release_platform_lock") as release, \
         patch.object(adapter, "_connect_locked", side_effect=_boom):
        with pytest.raises(RuntimeError):
            await adapter.connect()

    release.assert_called_once()


@pytest.mark.asyncio
async def test_lock_is_held_while_connected():
    adapter = _make_adapter()

    with patch.object(adapter, "_acquire_platform_lock", return_value=True), \
         patch.object(adapter, "_release_platform_lock") as release, \
         patch.object(adapter, "_connect_locked", return_value=True):
        assert await adapter.connect() is True

    release.assert_not_called()


@pytest.mark.asyncio
async def test_password_login_keys_on_the_account():
    """A password login mints a fresh token per connect, so the token cannot
    be the identity — the account is what a second client would duplicate."""
    adapter = _make_adapter(token="")
    adapter._access_token = ""
    adapter._user_id = "@bot:hs.example"

    with patch.object(adapter, "_acquire_platform_lock", return_value=False) as acquire:
        await adapter.connect()

    _scope, identity, _desc = acquire.call_args[0]
    assert identity == "https://hs.example|@bot:hs.example"


def test_disconnect_releases_the_lock():
    """Read off the source rather than driven, because disconnect tears down a
    live client; what matters is that the release is on the path at all."""
    import inspect

    from plugins.platforms.matrix.adapter import MatrixAdapter

    src = inspect.getsource(MatrixAdapter.disconnect)
    assert "_release_platform_lock" in src
