"""The DM policy is one decision, and it must have one default.

Evidence from three live deployments of this same bridge code: two that never
set ``WHATSAPP_DM_POLICY`` ran for weeks without the number being restricted —
including one on a brand-new personal number — and one that set it to
``pairing`` was restricted twice, escalating 2h to 6h.

The mechanism: ``pairing`` short-circuits the bridge's allowlist check
(bridge.js), so every unknown sender is forwarded, and the gateway answers each
with a pairing code. That is an automated reply to a stranger who never got a
human response — what WhatsApp restricts numbers for.

The adapter defaulted to ``pairing`` while the bridge defaulted to ``open``.
The disagreement stayed invisible because the bridge filters first, so the
adapter's default only ever saw senders the bridge had already allowed.
"""

import os
import re
from pathlib import Path

import pytest


BRIDGE = Path(__file__).resolve().parents[2] / "scripts" / "whatsapp-bridge" / "bridge.js"
ADAPTER = (
    Path(__file__).resolve().parents[2]
    / "plugins" / "platforms" / "whatsapp" / "adapter.py"
)


def test_bridge_and_adapter_agree_on_the_default():
    bridge_default = re.search(
        r"WHATSAPP_DM_POLICY\s*\|\|\s*'([a-z]+)'", BRIDGE.read_text(encoding="utf-8")
    )
    adapter_default = re.search(
        r'getenv\(\s*"WHATSAPP_DM_POLICY"\s*,\s*"([a-z]+)"\s*\)',
        ADAPTER.read_text(encoding="utf-8"),
    )
    assert bridge_default, "bridge.js no longer reads WHATSAPP_DM_POLICY as expected"
    assert adapter_default, "adapter.py no longer reads WHATSAPP_DM_POLICY as expected"
    assert bridge_default.group(1) == adapter_default.group(1) == "open", (
        "bridge and adapter must default the DM policy to the same value, and "
        "that value must not be the one that answers strangers"
    )


def test_pairing_admits_every_sender():
    """Not a bug in itself — it is what pairing means. Pinned because the
    consequence is what makes the default above matter."""
    from gateway.config import PlatformConfig
    from plugins.platforms.whatsapp.adapter import WhatsAppAdapter

    adapter = WhatsAppAdapter(PlatformConfig(enabled=True, extra={"dm_policy": "pairing"}))
    assert adapter._is_dm_intake_allowed("6299999999999@s.whatsapp.net") is True


def test_default_policy_does_not_admit_strangers(monkeypatch):
    from gateway.config import PlatformConfig
    from plugins.platforms.whatsapp.adapter import WhatsAppAdapter

    monkeypatch.delenv("WHATSAPP_DM_POLICY", raising=False)
    monkeypatch.delenv("GATEWAY_ALLOW_ALL_USERS", raising=False)
    monkeypatch.delenv("WHATSAPP_ALLOW_ALL_USERS", raising=False)

    adapter = WhatsAppAdapter(PlatformConfig(enabled=True))
    assert adapter._dm_policy == "open"
    assert adapter._is_dm_intake_allowed("6299999999999@s.whatsapp.net") is False


def test_saved_policy_does_not_contradict_a_saved_allowlist():
    """The desktop apply-settings flow wrote ``pairing`` unconditionally, two
    lines above the allowlist it then saved — setting a list and disabling it
    in the same transaction."""
    src = (
        Path(__file__).resolve().parents[2] / "hermes_cli" / "web_server.py"
    ).read_text(encoding="utf-8")

    assert 'save_env_value("WHATSAPP_DM_POLICY", "pairing")' not in src, (
        "the DM policy must not be persisted as 'pairing' unconditionally"
    )
    assert '"allowlist" if allowed_users else "pairing"' in src
