"""The bridge port is one decision, and it must have one default.

Same shape as the DM policy in test_whatsapp_dm_policy_default.py: a value the
Python adapter and the Node bridge each carried their own copy of, free to
drift, with nothing to notice when they did.

WHY IT MATTERS MORE THAN A PORT NUMBER USUALLY WOULD
====================================================
A customer may run this agent and upstream Hermes on the same machine. That is
the point of separate homes, separate service units and separate binaries — and
it worked until WhatsApp, where both defaulted to 3000. Starting a bridge used
to mean freeing the port by signalling whatever was listening on it, so the
second product to start would stop the first, whose bridge would restart, and
so on. A WhatsApp session torn down and re-established in a loop is what
"device_removed" and a restricted number look like from the outside.

Port 3000 is also the busiest port on any machine with Node on it, so the
collision did not need a second copy of this product to happen at all.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "scripts" / "whatsapp-bridge" / "bridge.js"
ADAPTER = ROOT / "plugins" / "platforms" / "whatsapp" / "adapter.py"


def test_bridge_and_adapter_agree_on_the_default_port():
    from hermes_constants import WHATSAPP_BRIDGE_PORT_DEFAULT

    bridge_default = re.search(
        r"getArg\(\s*'port'\s*,\s*'(\d+)'\s*\)", BRIDGE.read_text(encoding="utf-8")
    )
    assert bridge_default, "bridge.js no longer reads --port as expected"
    assert int(bridge_default.group(1)) == WHATSAPP_BRIDGE_PORT_DEFAULT


def test_the_default_is_not_the_port_hermes_uses():
    """3000 is upstream's, and it is not ours to take."""
    from hermes_constants import WHATSAPP_BRIDGE_PORT_DEFAULT

    assert WHATSAPP_BRIDGE_PORT_DEFAULT != 3000


def test_the_adapter_reads_the_default_rather_than_repeating_it():
    """A literal here is how the two got out of step in the first place."""
    source = ADAPTER.read_text(encoding="utf-8")
    assert not re.search(r'bridge_port["\']\s*,\s*3000', source), (
        "adapter.py must take the default from hermes_constants, not restate it"
    )
    assert source.count("WHATSAPP_BRIDGE_PORT_DEFAULT") >= 3


def test_an_adapter_with_no_configured_port_uses_the_shared_default():
    from gateway.config import PlatformConfig
    from hermes_constants import WHATSAPP_BRIDGE_PORT_DEFAULT
    from plugins.platforms.whatsapp.adapter import WhatsAppAdapter

    adapter = WhatsAppAdapter(PlatformConfig(enabled=True))
    assert adapter._bridge_port == WHATSAPP_BRIDGE_PORT_DEFAULT


def test_an_explicit_port_still_wins():
    from gateway.config import PlatformConfig
    from plugins.platforms.whatsapp.adapter import WhatsAppAdapter

    adapter = WhatsAppAdapter(PlatformConfig(enabled=True, extra={"bridge_port": 3050}))
    assert adapter._bridge_port == 3050


def test_the_bridge_reports_which_session_it_serves():
    """The adapter reuses a running bridge; it needs to know whose it is."""
    source = BRIDGE.read_text(encoding="utf-8")
    health = source[source.index("app.get('/health'"):]
    health = health[: health.index("});")]
    assert "session: SESSION_DIR" in health, (
        "/health must report the session directory, or the adapter cannot tell "
        "its own bridge from another install's"
    )
