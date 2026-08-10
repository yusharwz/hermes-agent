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
import threading
import time

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


# ---------------------------------------------------------------------------
# Which model the plan actually serves
# ---------------------------------------------------------------------------
#
# The failure these prevent is not hypothetical: a plan was edited in 9Router,
# the model written into config.yaml at install time was no longer on it, and
# every prompt came back "model not found". The customer sees a broken app.


@pytest.fixture
def catalog_reset():
    """Clears the module-level catalogue cache around each test."""
    leash._catalog = None
    leash._catalog_fetched_at = 0.0
    yield
    leash._catalog = None
    leash._catalog_fetched_at = 0.0


PLAN = [
    {"id": "NineGate-Low", "owned_by": "combo"},
    {"id": "ag/gemini-3.1-pro-low", "owned_by": "ag"},
    {"id": "ag/gemini-3-flash", "owned_by": "ag"},
]


def _serve(monkeypatch, models):
    """Makes the gateway answer with this catalogue, counting the fetches."""
    calls = []

    def fake_fetch():
        calls.append(1)
        return models

    monkeypatch.setattr(leash, "_fetch_catalog", fake_fetch)
    return calls


def test_the_combo_is_what_auto_means(locked, catalog_reset, monkeypatch):
    _serve(monkeypatch, PLAN)
    assert leash.auto_model() == "NineGate-Low"


def test_a_combo_is_recognised_without_the_owned_by_field(locked, catalog_reset, monkeypatch):
    # Older gateway builds do not set owned_by, so the shape rule has to stand
    # on its own: a bare name is a combo, a prefixed one is a single model.
    _serve(monkeypatch, [{"id": "ag/gemini-3-flash"}, {"id": "mix-low"}])
    assert leash.auto_model() == "mix-low"


def test_a_model_still_on_the_plan_is_left_alone(locked, catalog_reset, monkeypatch):
    # The important half. This must never become a mechanism that quietly
    # overrides a choice the customer made.
    _serve(monkeypatch, PLAN)
    assert leash.clamp_model("ag/gemini-3-flash") == "ag/gemini-3-flash"


def test_a_model_dropped_from_the_plan_becomes_auto(locked, catalog_reset, monkeypatch):
    _serve(monkeypatch, PLAN)
    assert leash.clamp_model("ag/model-withdrawn-last-week") == "NineGate-Low"


def test_no_model_at_all_becomes_auto(locked, catalog_reset, monkeypatch):
    _serve(monkeypatch, PLAN)
    assert leash.clamp_model("") == "NineGate-Low"


def test_an_unreachable_gateway_keeps_the_current_model(locked, catalog_reset, monkeypatch):
    # Offline is not evidence that a model was withdrawn. Substituting here
    # would change which model someone's work runs on because their wifi
    # dropped.
    monkeypatch.setattr(leash, "_fetch_catalog", lambda: None)
    assert leash.clamp_model("ag/gemini-3-flash") == "ag/gemini-3-flash"


def test_a_plan_with_no_combo_leaves_the_model_alone(locked, catalog_reset, monkeypatch):
    # Nothing safe to fall back to, so the request goes out as asked and the
    # gateway's own error is what the customer sees — which is honest.
    _serve(monkeypatch, [{"id": "ag/gemini-3-flash", "owned_by": "ag"}])
    assert leash.clamp_model("ag/gone") == "ag/gone"


def test_an_unlocked_build_never_rewrites_a_model(unlocked, catalog_reset, monkeypatch):
    calls = _serve(monkeypatch, PLAN)
    assert leash.clamp_model("my-provider/my-model") == "my-provider/my-model"
    assert leash.catalog() == []
    # Not merely the right answer — an unlocked build must not be calling a
    # gateway it has nothing to do with.
    assert calls == []


def test_the_catalogue_is_cached_between_calls(locked, catalog_reset, monkeypatch):
    calls = _serve(monkeypatch, PLAN)
    leash.clamp_model("ag/gemini-3-flash")
    leash.clamp_model("ag/gemini-3-flash")
    leash.clamp_model("ag/gemini-3-flash")
    assert len(calls) == 1, "consulted on the request path — one fetch per TTL, not per prompt"


def test_invalidating_forces_a_refetch(locked, catalog_reset, monkeypatch):
    calls = _serve(monkeypatch, PLAN)
    leash.clamp_model("ag/gemini-3-flash")
    leash.invalidate_catalog()
    leash.clamp_model("ag/gemini-3-flash")
    assert len(calls) == 2


def test_a_failed_refresh_keeps_the_last_known_plan(locked, catalog_reset, monkeypatch):
    _serve(monkeypatch, PLAN)
    leash.clamp_model("ag/gemini-3-flash")

    # The gateway goes away. The previously fetched list must survive, or every
    # model looks withdrawn and everyone is pushed onto the fallback at once.
    monkeypatch.setattr(leash, "_fetch_catalog", lambda: None)
    leash.invalidate_catalog()
    assert leash.clamp_model("ag/gemini-3-flash") == "ag/gemini-3-flash"


def test_a_plan_change_is_picked_up_without_a_restart(locked, catalog_reset, monkeypatch):
    # The whole point of item 9: the plan moves on the server and the running
    # app follows it.
    _serve(monkeypatch, PLAN)
    assert leash.clamp_model("ag/gemini-3-flash") == "ag/gemini-3-flash"

    _serve(monkeypatch, [{"id": "NineGate-High", "owned_by": "combo"}, {"id": "cc/claude-opus-5"}])
    leash.invalidate_catalog()
    assert leash.clamp_model("ag/gemini-3-flash") == "NineGate-High"


# ---------------------------------------------------------------------------
# The request path must not wait on the network
# ---------------------------------------------------------------------------
#
# clamp_model runs once per turn so a session that was already open when the
# plan changed moves onto the combo instead of failing every turn. That put it
# on the hot path, where a blocking HTTP call would add a round trip to a
# user's message for a list that changes a few times a year.


def test_the_turn_path_answers_from_cache_without_blocking(locked, catalog_reset, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow_fetch():
        started.set()
        release.wait(5)
        return PLAN

    monkeypatch.setattr(leash, "_fetch_catalog", slow_fetch)

    # Nothing cached yet: the answer is "no opinion", immediately, and the
    # model is left exactly as it was.
    before = time.monotonic()
    assert leash.clamp_model("ag/gemini-3-flash", blocking=False) == "ag/gemini-3-flash"
    assert time.monotonic() - before < 1.0, "the request path blocked on a fetch"

    assert started.wait(3), "no background refresh was started"
    release.set()

    # Once the background fetch lands, the next turn gets the real answer.
    for _ in range(50):
        if leash.catalog(blocking=False):
            break
        time.sleep(0.05)

    assert leash.clamp_model("ag/model-withdrawn", blocking=False) == "NineGate-Low"


def test_a_single_refresh_runs_even_under_repeated_turns(locked, catalog_reset, monkeypatch):
    calls = []
    release = threading.Event()

    def slow_fetch():
        calls.append(1)
        release.wait(5)
        return PLAN

    monkeypatch.setattr(leash, "_fetch_catalog", slow_fetch)

    # Ten turns in quick succession must not start ten fetches.
    for _ in range(10):
        leash.clamp_model("ag/gemini-3-flash", blocking=False)

    release.set()
    time.sleep(0.2)
    assert len(calls) == 1, f"started {len(calls)} concurrent refreshes"


def test_blocking_callers_still_wait(locked, catalog_reset, monkeypatch):
    # Startup clamps with blocking=True, where correctness matters more than
    # latency: an agent created against a dead model fails on its first turn.
    _serve(monkeypatch, PLAN)
    assert leash.clamp_model("ag/model-withdrawn") == "NineGate-Low"
