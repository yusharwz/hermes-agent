"""Pins a locked build to the NineGate gateway and nothing else.

WHY THIS EXISTS
===============
Atlas is sold as part of a NineGate subscription. Every model call is supposed
to go through the NineGate gateway, because that is the only place quota is
metered, plan access is enforced, and usage is attributed to the account that
is paying for it. An Atlas that can be pointed at a customer's own OpenAI key
is not a cheaper Atlas — it is an Atlas that bills nobody, reports nothing, and
cannot be supported, because the thing it is talking to is invisible to us.

Configuration alone cannot express that. The installer writes ``.env`` with the
gateway in it, but ``.env`` is a text file in the customer's home directory,
``cli-config.yaml`` accepts ``provider: custom`` with any ``base_url``, and the
CLI takes ``--base-url`` and ``--api-key`` flags. All of those are features for
the upstream agent, where pointing at your own provider is the entire point.
For a locked build they are ways out of the paid path, so this module closes
them at a level none of them sits above.

GATED, DELIBERATELY
===================
Nothing here does anything unless ``ATLAS_LOCKED`` is set, which only the Atlas
installer writes. The upstream agent, and any developer running this tree
directly, is bit-for-bit unaffected — this is a distribution policy, not a
change to what the agent is.

WHAT IT ACTUALLY DOES
=====================
``engage()`` runs once, as early as possible, and:

  1. Removes every credential-shaped variable from the environment. This is an
     allowlist, not a denylist of known providers: a denylist has to be updated
     every time a provider is added to the agent, and the one time it is
     forgotten is a silent hole. Anything matching a credential shape goes,
     except the four the gateway needs.

  2. Pins those four to the gateway, overwriting whatever was there.

``clamp()`` is the same decision applied to values that arrive later — from a
config file, a CLI flag, or ``/model`` at runtime — and is called at the points
where those land on the agent.

The environment is the right place for step 1 because every provider client in
the tree, including the media, search and tool registries that have their own
credential lookups, ultimately reads a ``*_API_KEY`` from it. Cutting them off
there covers the ones this module has never heard of.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------

LOCK_ENV = "ATLAS_LOCKED"

#: Written by the installer alongside the API key.
GATEWAY_ENV = "NINEGATE_GATEWAY_URL"
KEY_ENV = "NINEGATE_API_KEY"

#: Where a locked build talks, when the installer did not say.
DEFAULT_GATEWAY = "https://ninegate.dritech.co.id"

#: The four the gateway needs, in the two dialects the agent speaks.
#: ``ANTHROPIC_BASE_URL`` has no ``/v1`` because the Anthropic SDK appends its
#: own path; OpenAI's does not. Getting that backwards produces a 404 that
#: looks like an outage.
_OPENAI_KEY = "OPENAI_API_KEY"
_OPENAI_URL = "OPENAI_BASE_URL"
_ANTHROPIC_KEY = "ANTHROPIC_AUTH_TOKEN"
_ANTHROPIC_URL = "ANTHROPIC_BASE_URL"

_PINNED = (_OPENAI_KEY, _OPENAI_URL, _ANTHROPIC_KEY, _ANTHROPIC_URL)

#: Kept because the agent's own machinery reads them and they carry no
#: provider credential.
_NEVER_STRIP = frozenset(_PINNED) | frozenset({
    KEY_ENV,
    GATEWAY_ENV,
    LOCK_ENV,
})

#: Every environment variable that can route MODEL INFERENCE, taken from
#: ``hermes_cli.provider_catalog`` — the same catalog the model picker and the
#: provider settings pages are built from.
#:
#: Written down rather than imported, because :func:`engage` runs at ``import
#: agent`` and pulling the whole provider stack in at that point would cost
#: every entry point — CLI, cron, ACP — a large import it usually does not
#: need. The list is not left to drift: a test walks the live catalog and fails
#: if it gains an entry that is not here.
#:
#: What is NOT in here matters as much as what is. Tool credentials — Brave,
#: Tavily, and the rest — are the customer's own subscriptions for capabilities
#: NineGate does not resell, and stripping them would break web search on a
#: locked build for no benefit: a search key cannot route a model anywhere.
#:
#: ``GITHUB_TOKEN`` and ``GH_TOKEN`` are the deliberate exceptions. The catalog
#: lists them because GitHub Copilot serves models, but they are also the
#: credential ``git``, the ``gh`` CLI and the GitHub MCP server all use.
#: Removing them would break ordinary work; the endpoint clamp in
#: ``init_agent`` already stops Copilot being reached.
_PROVIDER_ENV_VARS = frozenset({
    "AI_GATEWAY_API_KEY",
    "AI_GATEWAY_BASE_URL",
    "ALIBABA_CODING_PLAN_API_KEY",
    "ALIBABA_CODING_PLAN_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_TOKEN",
    "ARCEEAI_API_KEY",
    "ARCEE_BASE_URL",
    "AZURE_FOUNDRY_API_KEY",
    "AZURE_FOUNDRY_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "COPILOT_API_BASE_URL",
    "COPILOT_GITHUB_TOKEN",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "DEEPINFRA_API_KEY",
    "DEEPINFRA_BASE_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "FIREWORKS_API_KEY",
    "GEMINI_API_KEY",
    "GEMINI_BASE_URL",
    "GLM_API_KEY",
    "GLM_BASE_URL",
    "GMI_API_KEY",
    "GMI_BASE_URL",
    "GOOGLE_API_KEY",
    "HF_BASE_URL",
    "HF_TOKEN",
    "KILOCODE_API_KEY",
    "KILOCODE_BASE_URL",
    "KIMI_API_KEY",
    "KIMI_BASE_URL",
    "KIMI_CN_API_KEY",
    "KIMI_CODING_API_KEY",
    "LM_API_KEY",
    "LM_BASE_URL",
    "MINIMAX_API_KEY",
    "MINIMAX_BASE_URL",
    "MINIMAX_CN_API_KEY",
    "MINIMAX_CN_BASE_URL",
    "NOUS_API_KEY",
    "NOVITA_API_KEY",
    "NOVITA_BASE_URL",
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENCODE_GO_API_KEY",
    "OPENCODE_GO_BASE_URL",
    "OPENCODE_ZEN_API_KEY",
    "OPENCODE_ZEN_BASE_URL",
    "OPENROUTER_API_KEY",
    "QWEN_API_KEY",
    "STEPFUN_API_KEY",
    "STEPFUN_BASE_URL",
    "TOKENHUB_API_KEY",
    "TOKENHUB_BASE_URL",
    "UPSTAGE_API_KEY",
    "UPSTAGE_BASE_URL",
    "XAI_API_KEY",
    "XAI_BASE_URL",
    "XIAOMI_API_KEY",
    "XIAOMI_BASE_URL",
    "ZAI_API_KEY",
    "Z_AI_API_KEY",
})

_engaged = False


def is_locked() -> bool:
    """True when this build is a NineGate distribution."""
    value = os.environ.get(LOCK_ENV, "").strip().lower()
    return value not in ("", "0", "false", "no", "off")


def gateway_url() -> str:
    """The gateway root, without a trailing slash or an API version."""
    raw = (os.environ.get(GATEWAY_ENV) or "").strip() or DEFAULT_GATEWAY
    root = raw.rstrip("/")
    # Tolerated because the installer writes the OpenAI-dialect URL with /v1
    # and someone will inevitably copy that into the gateway variable too.
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root


def subscription_key() -> str:
    """The customer's NineGate key, which is the only credential in play."""
    for name in (KEY_ENV, _OPENAI_KEY, _ANTHROPIC_KEY):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def engage() -> None:
    """Applies the lock to this process. Safe to call more than once."""
    global _engaged
    if _engaged or not is_locked():
        return
    _engaged = True

    root = gateway_url()
    key = subscription_key()

    for name in _PROVIDER_ENV_VARS:
        if name in _NEVER_STRIP:
            continue
        # Deleted rather than blanked: a lot of client libraries treat an empty
        # string as "configured, but wrong" and raise, where absent means "fall
        # through to the one we pinned".
        os.environ.pop(name, None)

    os.environ[_OPENAI_KEY] = key
    os.environ[_OPENAI_URL] = f"{root}/v1"
    os.environ[_ANTHROPIC_KEY] = key
    os.environ[_ANTHROPIC_URL] = root


def clamp(base_url: Optional[str], api_key: Optional[str], *, anthropic: bool = False) -> Tuple[str, str]:
    """Replaces a requested endpoint and key with the gateway's.

    Returns the arguments unchanged on an unlocked build, so callers can apply
    it unconditionally instead of scattering ``if is_locked()`` through the
    call sites — a guard that is only correct while every site remembers it.
    """
    if not is_locked():
        return (base_url or "", api_key or "")

    root = gateway_url()
    return (root if anthropic else f"{root}/v1", subscription_key())


def rejects(base_url: Optional[str]) -> bool:
    """True when this URL is somewhere a locked build must not talk to."""
    if not is_locked():
        return False

    target = (base_url or "").strip().lower()
    if not target:
        return False

    root = gateway_url().lower()
    return not (target == root or target.startswith(f"{root}/"))


def refuses_env_write(key: str) -> bool:
    """True when persisting this variable would undo the lock.

    The pin in :func:`engage` only runs at import. A value written into ``.env``
    — and into the live process — after that would survive it, so the writer
    every surface shares (``hermes env``, the desktop app's ``PUT /api/env``,
    the web dashboard) consults this before saving.

    ``NINEGATE_API_KEY`` is deliberately writable: changing which subscription
    an installation runs on is a thing customers legitimately do, and is what
    the desktop app's login page is for. It is the endpoint that must not move,
    not the credential.
    """
    if not is_locked():
        return False

    name = (key or "").strip().upper()
    if name == KEY_ENV:
        return False

    return name in _PINNED or name in (GATEWAY_ENV, LOCK_ENV) or name in _PROVIDER_ENV_VARS


def env_write_refusal(key: str) -> str:
    return (
        f"{key} tidak bisa disimpan: Atlas terkunci ke NineGate dan semua model "
        f"dilayani lewat {gateway_url()} memakai API key langganan Anda. "
        f"Untuk mengganti API key, buka Pengaturan → Langganan NineGate."
    )


#: Shown when a customer tries to point a locked build somewhere else. It names
#: the gateway rather than just refusing, because the usual reason someone sees
#: this is a copied config file from a colleague's unlocked setup, and knowing
#: what the value should be is the difference between a fix and a support
#: ticket.
def refusal(base_url: Optional[str]) -> str:
    return (
        f"Atlas terkunci ke NineGate dan tidak bisa memakai endpoint lain "
        f"({(base_url or '').strip() or 'kosong'}). "
        f"Semua model dilayani lewat {gateway_url()} memakai API key langganan Anda. "
        f"Ganti key lewat: atlas login"
    )
