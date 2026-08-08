"""Agent internals -- extracted modules from run_agent.py.

These modules contain pure utility functions and self-contained classes
that were previously embedded in the 3,600-line run_agent.py. Extracting
them makes run_agent.py focused on the AIAgent orchestrator class.
"""

from . import jiter_preload as _jiter_preload  # noqa: F401

# Applied here because this package is imported before any client is built, by
# every entry point there is — CLI, gateway, ACP adapter, cron. A locked build
# has its environment pinned to the NineGate gateway before anything can read
# a credential out of it; an unlocked one is untouched.
from . import ninegate_leash as _ninegate_leash  # noqa: F401

_ninegate_leash.engage()
