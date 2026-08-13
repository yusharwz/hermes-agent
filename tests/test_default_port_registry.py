"""Every default listening port is distinct, and every binder reads the registry.

Three subsystems defaulted to 8645, two to 8646 and two to 8765. A duplicate is
invisible at the callsite — each file names one port, once, and looks correct —
so it surfaces as "address already in use" on the machine of whoever enabled
both. Except when it doesn't:

    Feishu's webhook and Honcho's OAuth loopback both defaulted to 8765, and
    Honcho's is a redirect URI (http://127.0.0.1:8765/callback) registered with
    the provider. With Feishu holding the socket, the browser hands an OAuth
    authorization code to the Feishu webhook handler. Nothing raises.

The registry in atlas_constants is the single source of truth. These tests are
what make it one: without the second test a callsite could drift back to a
literal, and the registry would describe intentions rather than behaviour.
"""

import ast
import importlib
from collections import Counter
from pathlib import Path

import pytest

import atlas_constants

ROOT = Path(atlas_constants.__file__).resolve().parent


#: (module, attribute holding the default, registry key)
#: Every port-binding default that was found colliding, plus the two that kept
#: their original numbers — those are listed precisely because "unchanged" is
#: the case a careless edit is most likely to reintroduce a literal into.
BINDERS = [
    ("gateway.platforms.bluebubbles", "DEFAULT_WEBHOOK_PORT", "bluebubbles_webhook"),
    ("atlas_cli.proxy.server", "DEFAULT_PORT", "proxy"),
    ("plugins.platforms.wecom.callback_adapter", "DEFAULT_PORT", "wecom_callback"),
    ("gateway.platforms.msgraph_webhook", "DEFAULT_PORT", "msgraph_webhook"),
    ("plugins.platforms.line.adapter", "DEFAULT_WEBHOOK_PORT", "line_webhook"),
    ("plugins.memory.honcho.oauth_flow", "LOOPBACK_PORT", "honcho_oauth_loopback"),
    ("plugins.platforms.feishu.adapter", "_DEFAULT_WEBHOOK_PORT", "feishu_webhook"),
]


def test_every_default_port_is_distinct():
    """The whole point. Two equal values here is the bug class, restored."""
    counts = Counter(atlas_constants.DEFAULT_PORTS.values())
    duplicates = {
        port: sorted(k for k, v in atlas_constants.DEFAULT_PORTS.items() if v == port)
        for port, n in counts.items()
        if n > 1
    }
    assert not duplicates, (
        f"these defaults collide: {duplicates}. Two subsystems on one port means "
        "the second fails to bind — or, if one of them is an OAuth redirect, "
        "silently receives the other's traffic. Give one of them a free number "
        "in atlas_constants.DEFAULT_PORTS."
    )


@pytest.mark.parametrize("module_name,attribute,registry_key", BINDERS)
def test_binder_reads_the_registry(module_name, attribute, registry_key):
    """The module's default must BE the registry value, not merely equal it today."""
    module = importlib.import_module(module_name)
    assert getattr(module, attribute) == atlas_constants.DEFAULT_PORTS[registry_key]


@pytest.mark.parametrize("module_name,attribute,registry_key", BINDERS)
def test_binder_does_not_hardcode_a_port_literal(module_name, attribute, registry_key):
    """Equality is not enough — a literal that happens to match still drifts.

    Read the source rather than the value: the failure this guards against is a
    future edit replacing the imported name with the number it resolves to,
    which no runtime assertion can distinguish from correct code.
    """
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if attribute not in names:
            continue
        assert not isinstance(node.value, ast.Constant), (
            f"{module_name}.{attribute} is assigned the literal "
            f"{getattr(node.value, 'value', '?')!r}. Import it from "
            f"atlas_constants.DEFAULT_{registry_key.upper()}_PORT instead, so a "
            "collision is caught here rather than on a customer's machine."
        )
        return

    pytest.fail(f"no top-level assignment to {attribute} found in {module_name}")


def test_registry_covers_every_constant_named_default_port():
    """A constant added to atlas_constants but not to DEFAULT_PORTS is invisible
    to test_every_default_port_is_distinct, which would quietly stop being a
    collision check for the new port."""
    declared = {
        name: value
        for name, value in vars(atlas_constants).items()
        if name.startswith("DEFAULT_")
        and name.endswith("_PORT")
        and isinstance(value, int)
    }
    registered = set(atlas_constants.DEFAULT_PORTS.values())
    missing = {n: v for n, v in declared.items() if v not in registered}
    assert not missing, (
        f"these constants are not in DEFAULT_PORTS: {missing}. Register them, or "
        "the distinctness check silently does not cover them."
    )
