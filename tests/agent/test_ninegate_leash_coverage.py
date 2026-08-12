"""The lock must not quietly shrink when upstream is merged in.

WHY A SEPARATE FILE FROM test_ninegate_leash.py
===============================================
That file tests what the leash DOES: strip a key, refuse an endpoint, clamp a
model. Every one of its assertions is about code that exists. None of them fire
when a merge introduces a *new* path that never reaches the leash at all, or
deletes a call that used to.

That is the failure this file is for. It is a structural tripwire, not a
behaviour test: it reads the tree and fails when the shape of the enforcement
changes, so a merge from NousResearch/hermes-agent that walks a guard off can be
seen in a test result instead of in a customer's bill.

HOW TO RESPOND WHEN ONE OF THESE FAILS
======================================
Not by editing the baseline until it passes. Each failure names a file that used
to be guarded and no longer is, or a new call site that bypasses a funnel. Work
out which of the two happened, restore the guard if it was lost, and only widen
a baseline once the new path is understood to be safe — with the reason written
next to it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "release", "dist", "__pycache__", "website"}


def _sources() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


def _shipped_sources() -> list[Path]:
    """Everything except the tests, which describe the guards rather than are them."""
    return [p for p in _sources() if "tests" not in p.relative_to(ROOT).parts]


# ---------------------------------------------------------------------------
# The enforcement points
# ---------------------------------------------------------------------------

# Every shipped file that reaches for the leash. Recorded as a set rather than a
# count so a failure names the file that lost its guard, and so adding a new
# guarded path is not itself a failure.
LEASH_CALLERS = {
    "agent/__init__.py",
    "agent/agent_init.py",
    "agent/agent_runtime_helpers.py",
    "agent/auxiliary_client.py",
    "agent/ninegate_leash.py",
    "agent/turn_context.py",
    "agent/video_gen_provider.py",
    "hermes_cli/config.py",
    "hermes_cli/inventory.py",
    "hermes_cli/models.py",
    "hermes_cli/moa_config.py",
    "hermes_cli/web_server.py",
    "plugins/image_gen/openai/__init__.py",
    "tools/transcription_tools.py",
    "tools/tts_streaming.py",
    # Diagnostics rather than enforcement: it reads the gateway's request id off
    # a failed response so the error a customer quotes can be matched to the
    # gateway's own log of it. Listed anyway, because this set is "files that
    # reach for the leash" and an accurate set is what makes the test above
    # mean anything — and because a merge that drops the id should be seen.
    "run_agent.py",
}


def test_no_enforcement_point_has_gone_missing():
    found = {
        str(p.relative_to(ROOT))
        for p in _shipped_sources()
        if "ninegate_leash" in p.read_text(encoding="utf-8", errors="ignore")
    }
    lost = LEASH_CALLERS - found
    assert not lost, (
        "these files enforced the NineGate lock and no longer mention it: "
        f"{sorted(lost)}. A merge has removed a guard — restore it rather than "
        "editing this list."
    )


def test_new_enforcement_points_are_noticed():
    """Not a failure, but not silent either.

    A new guarded file is usually good news. It is listed here so that the set
    above stays an accurate description of where the lock lives, which is what
    makes the test above meaningful.
    """
    found = {
        str(p.relative_to(ROOT))
        for p in _shipped_sources()
        if "ninegate_leash" in p.read_text(encoding="utf-8", errors="ignore")
    }
    added = found - LEASH_CALLERS
    assert not added, (
        f"new files enforce the lock: {sorted(added)}. Add them to LEASH_CALLERS "
        "so a later merge cannot drop them unnoticed."
    )


# ---------------------------------------------------------------------------
# The funnels
# ---------------------------------------------------------------------------

# `get_default_model_for_provider` answers with a VENDOR model id. On a locked
# build that is not a harmless guess — it looks like a successful resolution, so
# it survives the empty-model safety nets downstream and is cached as the
# session's "last known good" model, which later recovery turns restore. That is
# the bug resolve_default_model() exists to close.
#
# One direct call remains, and it is reviewed: hermes_cli/models.py resolves
# `/model <provider>` typed as a bare name, and every /model switch funnels
# through agent_runtime_helpers.switch_model(), which clamps under is_locked()
# before anything reaches a client.
DIRECT_DEFAULT_MODEL_CALLERS = {
    "hermes_cli/models.py",
}


def test_the_vendor_default_is_reached_only_through_the_guarded_helper():
    offenders = set()
    for path in _shipped_sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "get_default_model_for_provider" not in text:
            continue
        # Its own definition and the one call inside resolve_default_model are
        # the helper, not a bypass of it.
        stripped = re.sub(
            r"def resolve_default_model\(.*?(?=\n(?:def|class|@)\s)",
            "",
            text,
            flags=re.S,
        )
        stripped = stripped.replace("def get_default_model_for_provider", "")
        if "get_default_model_for_provider" in stripped:
            offenders.add(str(path.relative_to(ROOT)))

    unexpected = offenders - DIRECT_DEFAULT_MODEL_CALLERS
    assert not unexpected, (
        f"{sorted(unexpected)} ask a vendor catalogue for a default model "
        "directly. Use resolve_default_model(), which returns the plan's combo "
        "on a locked build and an empty string when the plan cannot be read — "
        "or, if the path is genuinely clamped downstream, record it here with "
        "the funnel that clamps it."
    )


def test_the_guarded_helper_still_consults_the_leash():
    """The funnel is only worth anything while it still checks."""
    from hermes_cli import models

    source = Path(models.__file__).read_text(encoding="utf-8")
    body = re.search(
        r"def resolve_default_model\(.*?(?=\n(?:def|class|@)\s)", source, re.S
    )
    assert body, "resolve_default_model has gone"
    assert "is_locked()" in body.group(0)
    assert "clamp_model" in body.group(0)


def test_a_locked_build_gets_no_vendor_id_from_the_helper(monkeypatch):
    """The behaviour the structure above is protecting."""
    from agent import ninegate_leash as leash
    from hermes_cli import models

    monkeypatch.setattr(leash, "is_locked", lambda: True)
    monkeypatch.setattr(leash, "clamp_model", lambda model: "")

    assert models.resolve_default_model("openai") == ""


# ---------------------------------------------------------------------------
# The strip list
# ---------------------------------------------------------------------------


def test_the_leash_still_strips_something():
    """A merge that empties the strip list would pass every behaviour test that
    only asserts specific names, because each of those names would simply stop
    being tested. This asserts the list is not empty at all."""
    from agent import ninegate_leash as leash

    provider = leash._PROVIDER_ENV_VARS
    media = leash._MEDIA_ENV_VARS

    assert len(provider) > 40, (
        f"only {len(provider)} provider credentials are stripped on a locked "
        "build; the list has shrunk and customer keys are reaching vendors "
        "directly"
    )
    assert len(media) >= 5, (
        f"only {len(media)} media credentials are stripped; five vendor keys "
        "escaped this list once already"
    )
    # The overlap between the strip lists and _NEVER_STRIP is deliberate:
    # ANTHROPIC_BASE_URL and friends route inference AND are how the gateway is
    # reached, so they are listed as strippable and then exempted. What must
    # hold is that the exemption still exists — without it, engaging the lock
    # would delete the customer's own gateway credentials and lock them out of
    # the product they are paying for.
    for pinned in leash._PINNED:
        assert pinned in leash._NEVER_STRIP
    for own in (leash.KEY_ENV, leash.GATEWAY_ENV, leash.LOCK_ENV):
        assert own in leash._NEVER_STRIP
