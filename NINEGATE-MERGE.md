# Merging upstream into the NineGate fork

This fork descends from `NousResearch/hermes-agent` and may still take security
fixes from it. This file is the procedure for doing that without the lock
quietly coming undone.

It lives in its own file rather than in `AGENTS.md` for the obvious reason:
`AGENTS.md` is upstream's, and every merge would conflict on it.

## The shape of the repository

**Upstream was severed on 13 Aug 2026 (Phase 3.1).** There is no longer a remote,
a tracking ref, or a local branch pointing at `NousResearch/hermes-agent`.

| remote | points at | what it is |
| --- | --- | --- |
| `origin` | `yusharwz/atlas-agent` | ours, and the only remote |

| branch | tracks | what it is |
| --- | --- | --- |
| `ninegate-lock` | `origin` | **the product**, every change lands here |

| tag | what it is |
| --- | --- |
| `upstream-merge-base` | `470cf66b039c` — the last upstream commit merged in, anchored at sever time (1822 commits behind upstream then) |

What the sever bought, and why it is not negotiable back:

- **`origin` used to *be* upstream**, which meant a bare `git pull` was an
  upstream merge wearing the clothes of a routine sync. That is how this
  repository ended up on `main` mid-session five times with `origin/main`
  fast-forwarded in underneath a running test suite, producing numbers that
  looked like results. `main` no longer exists; `git checkout main` fails with
  *pathspec did not match*, and `git merge origin/main` fails with *not
  something we can merge*. The tree cannot be moved onto upstream by accident.
- **An upstream merge is now an explicit, typed-out act.** It requires naming
  the upstream URL on the command line. Nothing in the repository will reach
  for it on its own — see "Taking a fix from upstream" below.
- **A test result is only meaningful with `git branch --show-current` beside
  it.** Check it before believing anything.

## Taking a fix from upstream

Severing did not make upstream unreachable — it made reaching for it
deliberate. Fetch by URL into a scratch ref outside `refs/remotes/`, so no
tracking ref is created and no future `git fetch` re-arms the old path:

**Since Phase 3.2 a raw upstream patch no longer applies.** The tree is natively
Atlas at rest, so `git cherry-pick <upstream sha>` fails on its own context
lines in any file that mentions the name — 4.651 of 8.192 tracked files, more
than half. Proven, not assumed: applying one raw gives
`error: hermes_cli/main.py: does not exist in index`.

Put the patch through the same transform the tree went through, then apply it:

```bash
cd ~/src/atlas-fork
git branch --show-current          # must be ninegate-lock. Always.

UP=git@github.com:NousResearch/hermes-agent.git

# What has upstream done since the anchored base?
git fetch "$UP" main:refs/upstream-review/main
git log --oneline upstream-merge-base..refs/upstream-review/main

# Take the fix you came for, ported into Atlas vocabulary.
git format-patch --stdout <sha>^..<sha> > /tmp/up.patch
(cd <ninegate>/packages/installer &&
   npm run atlas:port-upstream -- --in /tmp/up.patch --out /tmp/up-atlas.patch)
git am /tmp/up-atlas.patch

# NOT `git am -3`. The `index <sha>..<sha>` lines name upstream's un-renamed
# blobs; this repository does not have them and they would not match the
# renamed content anyway, so three-way fails for a reason that has nothing to
# do with the port. When context has genuinely moved, use
#   git apply --reject /tmp/up-atlas.patch
# and resolve the .rej files by hand.

# A full merge is no longer a thing you can do in one command — every file
# would conflict. Port commit by commit, then re-anchor the base:
#   git tag -f -a upstream-merge-base -m "merged <date>" refs/upstream-review/main

# Always clean up. Leaving this ref behind rebuilds the surface just severed.
git update-ref -d refs/upstream-review/main
```

**What the port cannot do for you.** It renames by rule, and two kinds of
`hermes` are model vocabulary rather than branding: a bare generation
(`hermes-3`) and the same thing written as a regex (`hermes[-_ ]?[34]`). The
rules protect the first; nothing can see the second. If a ported patch touches
`atlas_cli/model_switch.py` or `agent/coding_context.py`, read those hunks by
hand — and trust `tests/atlas_cli/test_nous_atlas_non_agentic.py`, which is
what caught it the first time.

Do not re-add a remote named `upstream` or `origin` for this. A remote carries
a fetch refspec, and a refspec is exactly the thing that turns "someone ran
git fetch" back into "the tree moved".

## What is actually at risk

The fork is still called *atlas* inside — `atlas_cli`, `atlas_constants`.
The rename to Atlas happens later, at rebrand. So merging upstream is normal at
this level, and a "atlas" appearing in a diff is not a problem.

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
cd ~/src/atlas-fork
git branch --show-current          # must be ninegate-lock. Always.
git status --porcelain             # must be empty

# 1. See what is coming, before taking it. Upstream is fetched by URL into a
#    scratch ref — there is no upstream remote, on purpose.
UP=git@github.com:NousResearch/hermes-agent.git
git fetch "$UP" main:refs/upstream-review/main
git log --oneline upstream-merge-base..refs/upstream-review/main   # since the last merge
git diff HEAD...refs/upstream-review/main --stat -- \
    agent/ninegate_leash.py agent/agent_init.py atlas_cli/models.py \
    scripts/whatsapp-bridge/bridge.js

# 2. Take it — ported, commit by commit. See the section above.
git format-patch --stdout <sha>^..<sha> > /tmp/up.patch
(cd <ninegate>/packages/installer &&
   npm run atlas:port-upstream -- --in /tmp/up.patch --out /tmp/up-atlas.patch)
git am /tmp/up-atlas.patch
git tag -f -a upstream-merge-base -m "merged $(date -I)" refs/upstream-review/main
git update-ref -d refs/upstream-review/main

# 3. Prove the lock survived. Do this BEFORE anything else.
bash <ninegate>/scripts/verify-fork-integrity.sh

# 4. Full suite, one run, alone. Per-file isolation — NOT monolithic pytest,
#    which reports ~1000 order-pollution failures that are not real.
rm -rf /tmp/pytest-of-*
~/.hermes/hermes-agent/venv/bin/python scripts/run_tests_parallel.py -q

# 5. Prove the port did not leave upstream vocabulary behind — or eat a
#    protected span. No rebrand step: the tree is already Atlas.
cd <ninegate>/packages/installer
npm run atlas:verify -- --dir ~/src/atlas-fork
```

Step 3 and step 5 ask different questions. `verify-fork-integrity.sh` asks
whether the **lock** is still enforced. `atlas:verify` asks whether the tree
still speaks Atlas throughout — no upstream vocabulary left un-ported, and no
protected span (model id, upstream URL, copyright line) rewritten by mistake.
Both, in that order.

Baseline for step 4 is **48 failures across 16 files**, and about four of those
are flaky under parallel load — they pass when run alone. Compare the failing
FILE SET, not the number.

## When verify-fork-integrity fails

Not by editing the baseline until it passes. Each failure names a file that used
to be guarded and no longer is, or a new call site that bypasses a funnel.

1. `git log -p upstream-merge-base..refs/upstream-review/main -- <the file it named>`
   — see what upstream did.
2. Restore the guard, or route the new path through the existing funnel.
3. Widen a baseline **only** once the new path is understood to be safe, and
   write the reason next to it.

The baselines live in `tests/agent/test_ninegate_leash_coverage.py`.

## Recording where we are

The `upstream-merge-base` tag **is** the record — it is not a note about where
we are, it is the ref the next review is computed from. Re-point it in the same
commit as the merge (`git tag -f -a upstream-merge-base …`), or the next
session's `git log upstream-merge-base..` silently re-reviews commits already
taken.

`verify-fork-integrity.sh` reads that tag and prints it. With upstream severed
it can no longer report "how far behind" without a network fetch, and it does
not attempt one.

Last recorded: **`470cf66b039c`** — anchored 13 Aug 2026 at sever time, 1822
commits behind upstream/main as of that date.

## Known non-regressions

Things that fail and are not the merge's fault. Do not chase them:

- Collection errors in `tests/acp*`, `tests/tools/test_mcp_tool.py`,
  `tests/tools/test_mcp_oauth_metadata.py` — optional modules not installed.
  Excluded in the command above.
- **Not "seven pre-existing red tests".** That figure was a subset run and is
  wrong; it was quoted as a release gate for weeks. A clean full-suite run in an
  isolated clone measured **996 failed / 22890 passed**. Nearly all of it is
  order pollution — the same files pass 131/131 when run alone — because the
  suite reads the real `~/.atlas` while live units write to it. Until the
  harness is isolated, "green" is unreachable on this machine: compare the
  **diff of the failure set** between a base clone and a head clone, each with
  its own `--basetemp`, and never read the absolute number as a verdict.
- `bridge.native.test.mjs` fails in a rebranded tree — the rebrand drops
  `node_modules`, so Baileys is not there. It passes in this tree.
- The bundle carries `atlas-agent.nousresearch.com` in the remote-install
  message. That is a protected attribution span, deliberately preserved.
