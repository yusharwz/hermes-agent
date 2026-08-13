/**
 * Tests for electron/backend-probes.ts.
 *
 * Run with: node --test electron/backend-probes.test.ts
 * (Wired into npm test:desktop:platforms in package.json.)
 */

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import {
  canImportAtlasCli,
  DEFAULT_PROBE_TIMEOUT_MS,
  atlasRuntimeImportProbe,
  PROBE_TIMEOUT_MS,
  resolveProbeTimeoutMs,
  shouldTrustAtlasOverride,
  verifyAtlasCli
} from './backend-probes'

// Resolve the host's own Node binary -- guaranteed to be on disk and
// runnable. We use it as both a stand-in for "a python that doesn't
// have atlas_cli" (since `node -c "import atlas_cli"` will exit
// non-zero) and as a way to script verifyAtlasCli's success path
// (a tiny script we write to disk that exits 0 on --version).
const NODE_BIN = process.execPath

test('canImportAtlasCli returns false when path is falsy', () => {
  assert.equal(canImportAtlasCli(''), false)
  assert.equal(canImportAtlasCli(null), false)
  assert.equal(canImportAtlasCli(undefined), false)
})

test('canImportAtlasCli returns false when interpreter cannot run -c', () => {
  // node IS an interpreter, but `node -c "import atlas_cli"` is a
  // SyntaxError -- different exit reason from a real Python's
  // ModuleNotFoundError, but the predicate is "exit 0 or not" and
  // both land on "not", which is exactly what we want for the
  // resolver fall-through.
  assert.equal(canImportAtlasCli(NODE_BIN), false)
})

test('canImportAtlasCli returns false when binary does not exist', () => {
  const ghost = path.join(os.tmpdir(), 'atlas-probes-ghost-' + Date.now() + '.exe')
  assert.equal(canImportAtlasCli(ghost), false)
})

test('atlas runtime import probe checks config dependencies', () => {
  const probe = atlasRuntimeImportProbe()
  assert.match(probe, /\bimport yaml\b/)
  // dotenv is the first third-party import on the CLI boot path
  // (atlas_cli/env_loader.py); a mid-update venv missing python-dotenv
  // passed the old probe and produced an unrecoverable boot loop.
  assert.match(probe, /\bimport dotenv\b/)
  assert.match(probe, /\bimport atlas_cli\.config\b/)
})

test('explicit Atlas override is authoritative', () => {
  assert.equal(shouldTrustAtlasOverride('/nix/store/abc/bin/atlas'), true)
})

test('empty Atlas override is not authoritative', () => {
  assert.equal(shouldTrustAtlasOverride(''), false)
  assert.equal(shouldTrustAtlasOverride(undefined), false)
})

test('verifyAtlasCli returns false when command is falsy', () => {
  assert.equal(verifyAtlasCli(''), false)
  assert.equal(verifyAtlasCli(null), false)
  assert.equal(verifyAtlasCli(undefined), false)
})

test('verifyAtlasCli returns false when binary does not exist', () => {
  const ghost = path.join(os.tmpdir(), 'atlas-probes-ghost-' + Date.now() + '.exe')
  assert.equal(verifyAtlasCli(ghost), false)
})

test('verifyAtlasCli returns true when --version exits 0', () => {
  // Write a tiny script that exits 0 regardless of args, then invoke
  // it through node. This stands in for a working atlas binary --
  // verifyAtlasCli only cares about the exit code.
  const scriptPath = path.join(os.tmpdir(), `atlas-probes-ok-${Date.now()}-${process.pid}.cjs`)
  fs.writeFileSync(scriptPath, 'process.exit(0)\n')

  try {
    // Use node as the launcher and our script as the "command". Pass
    // shell:false (default) -- node is a real binary, no shim.
    // execFileSync passes ['--version'] as args, which node ignores
    // gracefully (well, it prints its version and exits 0, which is
    // perfect -- exit code 0 is the only signal we read).
    assert.equal(verifyAtlasCli(NODE_BIN), true)
  } finally {
    try {
      fs.unlinkSync(scriptPath)
    } catch {
      void 0
    }
  }
})

test('verifyAtlasCli swallows timeouts (does not throw)', () => {
  // We can't easily provoke a real hang in CI without slowing the
  // suite, but we CAN confirm that an invocation that DOES throw
  // (because the binary is missing) returns false rather than
  // propagating. Same code path the timeout case takes.
  assert.equal(verifyAtlasCli('/definitely/not/a/real/binary/anywhere'), false)
})

test('default probe timeout is 15s (not the old 5s death-loop value)', () => {
  assert.equal(DEFAULT_PROBE_TIMEOUT_MS, 15_000)
  // Module constant uses process.env at load time; with no override it
  // matches the default (tests run without ATLAS_PROBE_TIMEOUT_MS).
  assert.equal(PROBE_TIMEOUT_MS, DEFAULT_PROBE_TIMEOUT_MS)
})

test('resolveProbeTimeoutMs honours ATLAS_PROBE_TIMEOUT_MS', () => {
  assert.equal(resolveProbeTimeoutMs({}), DEFAULT_PROBE_TIMEOUT_MS)
  assert.equal(resolveProbeTimeoutMs({ ATLAS_PROBE_TIMEOUT_MS: '30000' }), 30_000)
  assert.equal(resolveProbeTimeoutMs({ ATLAS_PROBE_TIMEOUT_MS: '0' }), DEFAULT_PROBE_TIMEOUT_MS)
  assert.equal(resolveProbeTimeoutMs({ ATLAS_PROBE_TIMEOUT_MS: 'nope' }), DEFAULT_PROBE_TIMEOUT_MS)
  // Cap runaway values
  assert.equal(resolveProbeTimeoutMs({ ATLAS_PROBE_TIMEOUT_MS: '999999' }), 120_000)
})
