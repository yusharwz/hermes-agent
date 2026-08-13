"""The WhatsApp mode is one decision spread across three layers.

``WHATSAPP_MODE`` decides whether the agent answers everyone (``bot``) or only
the operator's own self-chat (``self-chat``). Three layers act on it:

  bridge.js                 getArg('mode', process.env.WHATSAPP_MODE || …)
  whatsapp_common.py        os.getenv("WHATSAPP_MODE", …)
  whatsapp-pairing.tsx      posts mode: 'bot' when pairing from the app

That is the same shape as the DM policy drift documented in
test_whatsapp_dm_policy_default.py — where the adapter defaulted to ``pairing``
and the bridge to ``open``, and the disagreement stayed invisible for weeks
because the bridge filtered first. The failure mode here is the mirror image
and worse: if the two fallbacks ever disagree, an install that never paired
through the app gets a bridge forwarding every stranger's message to a gateway
that believes it is in self-chat and strips no prefix — the automated-reply
pattern that gets numbers restricted.

The app's ``'bot'`` is deliberately NOT a third default: it is persisted with
``save_env_value("WHATSAPP_MODE", mode)`` in web_server.py, so it sets the one
source both readers then agree on. What is asserted here is that it stays a
value both layers accept, and that the two fallbacks stay equal.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "scripts" / "whatsapp-bridge" / "bridge.js"
COMMON = ROOT / "gateway" / "platforms" / "whatsapp_common.py"
PAIRING = ROOT / "apps" / "desktop" / "src" / "app" / "messaging" / "whatsapp-pairing.tsx"

#: The only two values any layer may use. web_server.py gates on this same set
#: (``mode if mode in {"bot", "self-chat"} else ""``), and the pairing UI's own
#: comment records that ``qr`` was once sent and rejected.
ACCEPTED = {"bot", "self-chat"}


def _bridge_mode_default() -> str:
    source = BRIDGE.read_text(encoding="utf-8")
    match = re.search(r"process\.env\.WHATSAPP_MODE\s*\|\|\s*'([^']+)'", source)
    assert match, "bridge.js no longer falls back for WHATSAPP_MODE — check by hand"
    return match.group(1)


def _python_mode_default() -> str:
    source = COMMON.read_text(encoding="utf-8")
    match = re.search(r'os\.getenv\(\s*"WHATSAPP_MODE"\s*,\s*"([^"]+)"\s*\)', source)
    assert match, "whatsapp_common.py no longer falls back for WHATSAPP_MODE"
    return match.group(1)


def test_bridge_and_python_agree_on_the_mode_fallback():
    bridge, python = _bridge_mode_default(), _python_mode_default()
    assert bridge == python, (
        f"bridge.js falls back to {bridge!r} but whatsapp_common.py falls back to "
        f"{python!r}. One install, two beliefs about who the agent answers."
    )


def test_the_mode_fallback_is_an_accepted_value():
    assert _python_mode_default() in ACCEPTED
    assert _bridge_mode_default() in ACCEPTED


def test_pairing_ui_sends_an_accepted_mode():
    """The app posts a literal; web_server drops anything outside the set, which
    would leave a paired session with no mode written at all."""
    source = PAIRING.read_text(encoding="utf-8")
    match = re.search(r"mode:\s*'([^']+)'", source)
    assert match, "the pairing UI no longer sends a mode — check the endpoint contract"
    assert match.group(1) in ACCEPTED, (
        f"the pairing UI sends mode={match.group(1)!r}, which web_server.py filters "
        f"out; only {sorted(ACCEPTED)} survive to be saved."
    )
