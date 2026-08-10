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

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
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
# Media backends — image, video, speech, transcription.
#
# These were missing, and the gap was not random. _PROVIDER_ENV_VARS below is
# derived from the model-provider catalogue, which lists the backends that
# serve *text*. A vendor that only generates images, or only speaks, is not in
# that catalogue and so was never stripped: on a locked build a customer with
# ELEVENLABS_API_KEY in their environment kept a working voice that billed
# their own ElevenLabs account and was invisible to metering.
#
# The names come from the plugins' own `requires_env` declarations and from the
# credential lookups in the speech tools. tests/agent/test_ninegate_leash.py
# walks the plugin tree and fails if a backend declares a credential that is
# not listed here, so adding a media plugin cannot quietly reopen this.
_MEDIA_ENV_VARS = frozenset({
    "ELEVENLABS_API_KEY",
    "FAL_KEY",
    "GROQ_API_KEY",
    "KREA_API_KEY",
    "MISTRAL_API_KEY",
})

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

    for name in _PROVIDER_ENV_VARS | _MEDIA_ENV_VARS:
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



# ---------------------------------------------------------------------------
# Which models the subscription actually has
# ---------------------------------------------------------------------------
#
# WHY THIS IS NOT A CONFIG VALUE
# ==============================
# The installer used to write the plan's first model into ``config.yaml`` and
# leave it there. That is a snapshot of a list that lives on the server: change
# the customer's plan, or rename a model in 9Router, and the next prompt asks
# for a model the gateway no longer serves. It fails as "model not found",
# which reads like a broken application rather than a plan that moved.
#
# So the catalogue is read from the gateway, not from a file, and the model in
# use is checked against it. A pinned model that is still on the plan is left
# exactly alone — this is not a mechanism for overriding the customer's choice.
# One that has vanished is replaced with the plan's combo.
#
# WHY THE COMBO IS THE FALLBACK
# =============================
# A combo is a pool 9Router picks between, so it survives any single model
# being renamed or withdrawn — which makes it the one entry that is still valid
# after the kind of change that breaks a pinned id. Every plan has one.

_MODELS_PATH = "/v1/models"

# How the gateway writes a combo grant in a plan's allow-list.
COMBO_PREFIX = "combo:"

# How long a fetched catalogue is trusted.
#
# Short, because a plan change has to take effect without the customer
# restarting anything. Not zero, because this is consulted on the request path
# and a fetch per prompt would add a round trip to every message for a list
# that changes a few times a year.
_CATALOG_TTL_SECONDS = 60.0

# Long enough to cross a slow link, short enough that a gateway which has gone
# away does not hold up a prompt. On timeout the cached list is reused and, if
# there is none, model selection is left untouched.
_CATALOG_TIMEOUT_SECONDS = 8.0

_catalog_lock = threading.Lock()
_catalog: Optional[list] = None
_catalog_fetched_at = 0.0


def _fetch_catalog() -> Optional[list]:
    """The raw ``data`` array from the gateway, or None if it could not be read."""
    key = subscription_key()
    if not key:
        return None

    request = urllib.request.Request(
        f"{gateway_url()}{_MODELS_PATH}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=_CATALOG_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        # Offline, gateway down, or a body that is not JSON. None means "no
        # opinion" — callers keep whatever model they already had, which is the
        # only safe answer when we cannot see the catalogue.
        return None

    data = payload.get("data")
    return data if isinstance(data, list) else None


_refreshing = False


def _refresh_catalog() -> None:
    """Fetches and stores the catalogue. Safe to call from any thread."""
    global _catalog, _catalog_fetched_at, _refreshing

    fetched = _fetch_catalog()

    with _catalog_lock:
        if fetched is not None:
            _catalog = fetched
            _catalog_fetched_at = time.monotonic()
        # A failed fetch deliberately does not clear the previous answer: a
        # momentary network blip should not look like "the plan has no models",
        # which would push everyone onto the fallback for no reason.
        _refreshing = False


def catalog(*, refresh: bool = False, blocking: bool = True) -> list:
    """Models this subscription may use. Empty when the gateway is unreachable.

    ``blocking=False`` answers from whatever is cached and refreshes in the
    background instead of waiting. That is for the request path: a turn should
    not stall behind an HTTP call to find out which models exist, and being one
    TTL behind on a plan change costs a minute, where blocking costs every user
    a round trip on the first turn after each TTL expiry.
    """
    global _refreshing

    if not is_locked():
        return []

    with _catalog_lock:
        stale = _catalog is None or (time.monotonic() - _catalog_fetched_at) >= _CATALOG_TTL_SECONDS
        if not (stale or refresh):
            return list(_catalog or [])

        if not blocking:
            snapshot = list(_catalog or [])
            already = _refreshing
            _refreshing = True

    if not blocking:
        if not already:
            # Daemon so a hung fetch can never keep the process alive at exit.
            threading.Thread(target=_refresh_catalog, name="ninegate-catalog", daemon=True).start()
        return snapshot

    _refresh_catalog()

    with _catalog_lock:
        return list(_catalog or [])


def invalidate_catalog() -> None:
    """Forces the next read to go to the gateway. Call after a plan may have changed."""
    global _catalog_fetched_at
    with _catalog_lock:
        _catalog_fetched_at = 0.0


def is_combo(model_id: str) -> bool:
    """True for a 9Router combo — a pool of models rather than one model.

    A combo carries no provider prefix ("NineGate-Low" against
    "ag/gemini-3-flash"). The gateway also reports ``owned_by: "combo"``, which
    is checked first where the entry is available, because the shape rule is a
    convention and the field is a statement.
    """
    return "/" not in (model_id or "").strip()


def auto_model(models: Optional[list] = None) -> str:
    """The plan's combo — what "Auto" means. Empty when the plan has none."""
    entries = models if models is not None else catalog()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("owned_by") or "").strip().lower() == "combo":
            return str(entry.get("id") or "")

    # No explicit marker: fall back to the shape. Older gateway builds did not
    # set owned_by on combos.
    for entry in entries:
        if isinstance(entry, dict) and is_combo(str(entry.get("id") or "")):
            return str(entry.get("id") or "")

    return ""


# Model kinds the gateway catalogues beyond plain text. Asking for one the
# gateway does not know is an error, not an empty list, so the names matter.
MEDIA_KINDS = ("image", "tts", "stt", "embedding", "image-to-text", "web")

_media_lock = threading.Lock()
_media_cache: dict = {}


def _fetch_kind(kind: str) -> Optional[list]:
    key = subscription_key()
    if not key:
        return None

    request = urllib.request.Request(
        f"{gateway_url()}{_MODELS_PATH}/{kind}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=_CATALOG_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None

    data = payload.get("data")
    return data if isinstance(data, list) else None


def models_for_kind(kind: str) -> list:
    """Model ids the plan grants for a media kind — image, tts, stt, and so on.

    Empty means the plan does not include that capability, or the gateway
    could not be reached. Callers should treat both the same way: offer the
    feature only when there is something to offer, rather than advertising a
    backend whose every call will come back "model not found".
    """
    if not is_locked() or kind not in MEDIA_KINDS:
        return []

    with _media_lock:
        entry = _media_cache.get(kind)
        if entry and (time.monotonic() - entry[0]) < _CATALOG_TTL_SECONDS:
            return list(entry[1])

    fetched = _fetch_kind(kind)

    with _media_lock:
        if fetched is not None:
            ids = [str(m.get("id") or "") for m in fetched if isinstance(m, dict) and m.get("id")]
            _media_cache[kind] = (time.monotonic(), ids)
        entry = _media_cache.get(kind)
        return list(entry[1]) if entry else []


def plan_models() -> list:
    """Every model id the plan grants, from /v1/usage.

    A second source, needed because the kind catalogue does not cover
    everything: 9Router serves video models but catalogues none of them under
    any kind, so a plan that grants xai/grok-imagine-video looks empty to
    models_for_kind("video") even though the model works. The allow-list knows.

    Combo entries arrive prefixed ("combo:NineGate-Low"); the prefix is
    stripped so callers compare against the same ids the model endpoints use.
    """
    key = subscription_key()
    if not is_locked() or not key:
        return []

    with _media_lock:
        entry = _media_cache.get("__plan__")
        if entry and (time.monotonic() - entry[0]) < _CATALOG_TTL_SECONDS:
            return list(entry[1])

    request = urllib.request.Request(
        f"{gateway_url()}/v1/usage",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=_CATALOG_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        with _media_lock:
            entry = _media_cache.get("__plan__")
            return list(entry[1]) if entry else []

    raw = ((payload.get("plan") or {}).get("allowed_models")) or []
    ids = []
    for item in raw:
        text = str(item or "").strip()
        if not text or text.endswith("*"):
            # A wildcard grants a family rather than naming a model, so it
            # cannot be offered as one.
            continue
        ids.append(text[len(COMBO_PREFIX):] if text.startswith(COMBO_PREFIX) else text)

    with _media_lock:
        _media_cache["__plan__"] = (time.monotonic(), ids)

    return list(ids)


def default_model_for_kind(kind: str) -> str:
    """The model a media backend should use, or empty when the plan has none."""
    models = models_for_kind(kind)
    return models[0] if models else ""


def video_models() -> list:
    """Models the plan grants that are not catalogued under any other kind.

    9Router serves video but catalogues none of it: there is no "video" model
    kind, and grok-imagine-video appears in no /v1/models response — yet a
    request for it succeeds. So the plan's allow-list is the only place that
    knows, and the way to tell a video model from the rest is subtraction.

    Everything the plan grants, minus everything some kind already claims.
    Derived rather than guessed: matching on names containing "video" would
    work today and break the first time a vendor ships one that does not.

    The proper fix is upstream — video belongs in the kind catalogue like image
    and stt do. Until then this keeps the capability reachable instead of
    invisible.
    """
    granted = set(plan_models())
    if not granted:
        return []

    claimed = {str(entry.get("id") or "") for entry in catalog() if isinstance(entry, dict)}
    for kind in MEDIA_KINDS:
        claimed.update(models_for_kind(kind))

    return sorted(granted - claimed)


def clamp_media_model(kind: str, model: Optional[str]) -> str:
    """Same contract as clamp_model, for a media kind.

    A model still on the plan is kept. One that is not — including a hard-coded
    default from a backend written against a single vendor, which is how these
    plugins are built — becomes the plan's first model for that kind.
    """
    current = (model or "").strip()

    if not is_locked():
        return current

    models = models_for_kind(kind)
    if not models:
        return current

    return current if current in models else models[0]


def clamp_model(model: Optional[str], *, blocking: bool = True) -> str:
    """Keeps a model that is still on the plan; swaps a vanished one for Auto.

    Returns the input unchanged on an unlocked build, when the catalogue cannot
    be read, or when the plan has no combo to fall back to — every one of those
    is a case where substituting would be a guess, and a guess here changes
    which model a customer's work runs on.
    """
    current = (model or "").strip()

    if not is_locked():
        return current

    entries = catalog(blocking=blocking)
    if not entries:
        return current

    available = {str(entry.get("id") or "") for entry in entries if isinstance(entry, dict)}

    if current and current in available:
        return current

    fallback = auto_model(entries)
    return fallback or current


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

    return (
        name in _PINNED
        or name in (GATEWAY_ENV, LOCK_ENV)
        or name in _PROVIDER_ENV_VARS
        or name in _MEDIA_ENV_VARS
    )


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
