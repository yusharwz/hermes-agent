"""The lock that keeps a NineGate build on the NineGate gateway.

These are worth more than most tests in this tree, because what they protect is
revenue rather than behaviour: every hole here is an Atlas installation serving
a paying customer's work through somebody else's account, invisible to metering
and to support. A regression would not crash anything, which is exactly why it
would survive.
"""

from __future__ import annotations

import importlib
import os

import pytest

from agent import ninegate_leash as leash


GATEWAY = "https://gw.example.test"


@pytest.fixture
def locked(monkeypatch):
    """A locked build, with the module's one-shot guard reset."""
    monkeypatch.setenv(leash.LOCK_ENV, "1")
    monkeypatch.setenv(leash.GATEWAY_ENV, GATEWAY)
    monkeypatch.setenv(leash.KEY_ENV, "ng_live_abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setattr(leash, "_engaged", False)
    return leash


@pytest.fixture
def unlocked(monkeypatch):
    monkeypatch.delenv(leash.LOCK_ENV, raising=False)
    monkeypatch.setattr(leash, "_engaged", False)
    return leash


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


def test_an_unlocked_build_is_untouched(unlocked, monkeypatch):
    """The upstream agent must behave exactly as it did before this existed."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-mine")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")

    unlocked.engage()

    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-mine"
    assert os.environ["OPENAI_BASE_URL"] == "http://localhost:1234/v1"
    assert unlocked.clamp("http://localhost:1234/v1", "sk-mine") == (
        "http://localhost:1234/v1",
        "sk-mine",
    )
    assert unlocked.rejects("https://api.openai.com/v1") is False


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_the_lock_needs_a_real_value(monkeypatch, value):
    monkeypatch.setenv(leash.LOCK_ENV, value)
    assert leash.is_locked() is False


# ---------------------------------------------------------------------------
# Stripping the environment
# ---------------------------------------------------------------------------


def test_a_customers_own_provider_keys_are_removed(locked, monkeypatch):
    for name in (
        "OPENROUTER_API_KEY",
        "XAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "TOGETHER_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.setenv(name, "sk-belongs-to-the-customer")

    locked.engage()

    for name in ("OPENROUTER_API_KEY", "XAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
        assert name not in os.environ, f"{name} survived the lock"

    # Specifically checked: the Anthropic SDK prefers ANTHROPIC_API_KEY over
    # ANTHROPIC_AUTH_TOKEN, so a leftover copy would silently outrank the
    # pinned one and send the customer's work to their own account.
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_the_strip_list_still_covers_the_whole_provider_catalog(locked):
    """The tripwire for the one thing a written-down list gets wrong.

    The list exists so that engage() stays cheap at import time. The cost of
    that is drift: a provider added upstream would route around a lock that
    never heard of it. This walks the live catalog — the same one the model
    picker is built from — and fails the moment the two disagree.
    """
    from hermes_cli.provider_catalog import provider_catalog

    # Copilot's credential, which is also what git, the gh CLI and the GitHub
    # MCP server authenticate with. Covered by the endpoint clamp instead.
    expected_gaps = {"GITHUB_TOKEN", "GH_TOKEN"}

    missing = set()
    for descriptor in provider_catalog():
        for name in descriptor.api_key_env_vars or ():
            if name not in locked._PROVIDER_ENV_VARS:
                missing.add(name)
        base_url = getattr(descriptor, "base_url_env_var", "")
        if base_url and base_url not in locked._PROVIDER_ENV_VARS:
            missing.add(base_url)

    assert missing <= expected_gaps, (
        f"provider catalog gained {sorted(missing - expected_gaps)}; "
        "add them to _PROVIDER_ENV_VARS in agent/ninegate_leash.py"
    )


def test_tool_credentials_survive(locked, monkeypatch):
    """A search key cannot route a model, and stripping it breaks web search.

    These are the customer's own subscriptions for capabilities NineGate does
    not resell. An earlier version of this module matched on the SHAPE of a
    name and would have deleted every one of them.
    """
    keep = {
        "BRAVE_API_KEY": "brave-theirs",
        "TAVILY_API_KEY": "tvly-theirs",
        "EXA_API_KEY": "exa-theirs",
        "SERPER_API_KEY": "serper-theirs",
        "ELEVENLABS_API_KEY": "el-theirs",
    }
    for name, value in keep.items():
        monkeypatch.setenv(name, value)

    locked.engage()

    for name, value in keep.items():
        assert os.environ.get(name) == value, f"{name} was stripped and should not have been"


def test_the_machines_own_credentials_are_left_alone(locked, monkeypatch):
    """Stripping these breaks things that have nothing to do with inference."""
    keep = {
        # Listed by the catalog as a Copilot credential, but also what git, the
        # gh CLI and the GitHub MCP server use. The clamp covers Copilot.
        "GITHUB_TOKEN": "ghp_x",
        "GH_TOKEN": "ghp_y",
        "SSH_AUTH_SOCK": "/tmp/ssh",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
        "HTTPS_PROXY": "http://corp:8080",
        "NO_PROXY": "localhost",
        "npm_config_registry": "https://registry.npmjs.org",
    }
    for name, value in keep.items():
        monkeypatch.setenv(name, value)

    locked.engage()

    for name, value in keep.items():
        assert os.environ.get(name) == value, f"{name} was stripped and should not have been"


# ---------------------------------------------------------------------------
# Refusing writes that would outlive the pin
# ---------------------------------------------------------------------------


def test_the_endpoint_cannot_be_persisted(locked):
    for name in ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL", "OPENROUTER_API_KEY", "XAI_BASE_URL"):
        assert locked.refuses_env_write(name) is True, f"{name} should not be writable"


def test_the_subscription_key_stays_writable(locked):
    """Changing which subscription a machine runs on is a supported thing."""
    assert locked.refuses_env_write(locked.KEY_ENV) is False
    assert locked.refuses_env_write("ninegate_api_key") is False


def test_tool_keys_stay_writable(locked):
    """Otherwise configuring web search on a locked build becomes impossible."""
    for name in ("BRAVE_API_KEY", "TAVILY_API_KEY", "GITHUB_TOKEN"):
        assert locked.refuses_env_write(name) is False, f"{name} should be writable"


def test_nothing_is_refused_on_an_unlocked_build(unlocked):
    assert unlocked.refuses_env_write("OPENAI_BASE_URL") is False


def test_the_gateway_variables_are_pinned(locked, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-customers-own")

    locked.engage()

    key = "ng_live_abcdefghijklmnopqrstuvwxyz"
    assert os.environ["OPENAI_BASE_URL"] == f"{GATEWAY}/v1"
    assert os.environ["OPENAI_API_KEY"] == key
    # No /v1: the Anthropic SDK appends its own path, and getting this backwards
    # produces a 404 that reads like an outage.
    assert os.environ["ANTHROPIC_BASE_URL"] == GATEWAY
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == key


def test_engaging_twice_is_harmless(locked):
    locked.engage()
    first = dict(os.environ)
    locked.engage()
    assert os.environ["OPENAI_BASE_URL"] == first["OPENAI_BASE_URL"]


# ---------------------------------------------------------------------------
# Clamping values that arrive later
# ---------------------------------------------------------------------------


def test_a_config_file_cannot_redirect_a_locked_build(locked):
    base_url, api_key = locked.clamp("https://api.deepseek.com/v1", "sk-theirs")
    assert base_url == f"{GATEWAY}/v1"
    assert api_key == "ng_live_abcdefghijklmnopqrstuvwxyz"


def test_the_anthropic_dialect_gets_the_root(locked):
    base_url, _ = locked.clamp("https://api.anthropic.com", "sk-ant-theirs", anthropic=True)
    assert base_url == GATEWAY


@pytest.mark.parametrize(
    "supplied",
    [
        "https://api.openai.com/v1",
        "http://localhost:11434/v1",
        # A prefix that merely starts with the gateway's own hostname is still
        # somewhere else — "https://gw.example.test.attacker.example".
        f"{GATEWAY}.attacker.example/v1",
    ],
)
def test_off_gateway_endpoints_are_rejected(locked, supplied):
    assert locked.rejects(supplied) is True


@pytest.mark.parametrize("supplied", [GATEWAY, f"{GATEWAY}/v1", f"{GATEWAY}/v1/chat/completions"])
def test_the_gateway_itself_is_accepted(locked, supplied):
    assert locked.rejects(supplied) is False


def test_the_installers_openai_style_url_is_tolerated(monkeypatch):
    """Someone will copy OPENAI_BASE_URL into the gateway variable. They should."""
    monkeypatch.setenv(leash.LOCK_ENV, "1")
    monkeypatch.setenv(leash.GATEWAY_ENV, f"{GATEWAY}/v1")
    assert leash.gateway_url() == GATEWAY


def test_the_refusal_names_the_gateway_and_the_way_out(locked):
    message = locked.refusal("https://api.openai.com/v1")
    assert GATEWAY in message
    assert "atlas login" in message
