# Merging upstream into the NineGate fork

This fork tracks `NousResearch/hermes-agent` and is expected to keep merging
from it. This file is the procedure for doing that without the lock quietly
coming undone.

It lives in its own file rather than in `AGENTS.md` for the obvious reason:
`AGENTS.md` is upstream's, and every merge would conflict on it.

## The shape of the repository

| remote | points at | what it is |
| --- | --- | --- |
| `origin` | `NousResearch/hermes-agent` | **upstream**, despite the name |
| `fork` | `yusharwz/hermes-agent` | ours |

| branch | tracks | what it is |
| --- | --- | --- |
| `main` | `origin` (upstream) | a mirror of upstream, no NineGate work on it |
| `ninegate-lock` | `fork` | **the product**, every change lands here |

Two consequences worth holding on to:

- **`git pull` on `main` is an upstream merge.** It is not a routine sync. This
  is how the repository has twice ended up on `main` mid-session with
  `origin/main` fast-forwarded in underneath a running test suite, producing
  numbers that looked like results.
- **A test result is only meaningful with `git branch --show-current` beside
  it.** Check it before believing anything.

## What is actually at risk

The fork is still called *hermes* inside — `hermes_cli`, `hermes_constants`.
The rename to Atlas happens later, at rebrand. So merging upstream is normal at
this level, and a "hermes" appearing in a diff is not a problem.

What must not come back with a merge is upstream's freedom:

- a code path that reaches a vendor endpoint without passing `clamp()`;
- a provider or media credential that survives the strip;
- a guard deleted because upstream refactored the file it lived in;
- a default that exists twice — Python and the Node bridge — drifting apart.

None of these announce themselves. A merge that removes one `clamp()` call
leaves a tree that imports, starts, answers, and bills the customer's own API
key.

## The procedure

```bash
cd ~/.hermes/hermes-agent
git branch --show-current          # must be ninegate-lock. Always.
git status --porcelain             # must be empty

# 1. See what is coming, before taking it.
git fetch origin main
git log --oneline HEAD..origin/main            # incremental since the last merge
git diff HEAD...origin/main --stat -- \
    agent/ninegate_leash.py agent/agent_init.py hermes_cli/models.py \
    scripts/whatsapp-bridge/bridge.js

# 2. Merge.
git merge origin/main

# 3. Prove the lock survived. Do this BEFORE anything else.
bash <ninegate>/scripts/verify-fork-integrity.sh

# 4. Full suite, one run, alone.
rm -rf /tmp/pytest-of-*
PYTHONPATH=<pytest-lib> ~/.atlas/atlas-agent/.venv/bin/python -m pytest tests/ -q \
  -p no:randomly --ignore=tests/acp --ignore=tests/acp_adapter \
  --ignore=tests/tools/test_mcp_tool.py --ignore=tests/tools/test_mcp_oauth_metadata.py

# 5. Only now: rebrand, verify the rename, build.
cd <ninegate>/packages/installer
npm run atlas:rebrand -- --src ~/.hermes/hermes-agent --out <atlas-agent checkout>
npm run atlas:verify -- --dir <atlas-agent checkout>
```

Step 3 and step 5's `atlas:verify` ask different questions at different times.
`verify-fork-integrity.sh` reads **this** tree and asks whether the lock is
still enforced. `atlas:verify` reads the **rebranded output** and asks whether
the rename missed a "hermes" or rewrote a span it was meant to protect. Both,
in that order.

## When verify-fork-integrity fails

Not by editing the baseline until it passes. Each failure names a file that used
to be guarded and no longer is, or a new call site that bypasses a funnel.

1. `git log -p HEAD..origin/main -- <the file it named>` — see what upstream did.
2. Restore the guard, or route the new path through the existing funnel.
3. Widen a baseline **only** once the new path is understood to be safe, and
   write the reason next to it.

The baselines live in `tests/agent/test_ninegate_leash_coverage.py`.

## Recording where we are

`verify-fork-integrity.sh` prints the merge base with `origin/main` and how far
behind it is. Note it in the merge commit message, so the next merge can be
read commit by commit rather than as one unreadable diff against whatever
upstream looks like months from now.

Last recorded: **`470cf66b039c`** (11 Aug 2026, 1755 commits behind upstream).

## Known non-regressions

Things that fail and are not the merge's fault. Do not chase them:

- Collection errors in `tests/acp*`, `tests/tools/test_mcp_tool.py`,
  `tests/tools/test_mcp_oauth_metadata.py` — optional modules not installed.
  Excluded in the command above.
- Seven pre-existing red tests: `discord_send` ×3, `send_multiple_images`,
  `session_store_prune`, `wecom` ×2.
- `bridge.native.test.mjs` fails in a rebranded tree — the rebrand drops
  `node_modules`, so Baileys is not there. It passes in this tree.
- The bundle carries `hermes-agent.nousresearch.com` in the remote-install
  message. That is a protected attribution span, deliberately preserved.
