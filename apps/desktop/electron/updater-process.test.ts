import assert from 'node:assert/strict'
import type { SpawnOptions } from 'node:child_process'
import path from 'node:path'

import { test } from 'vitest'

import { resolveStagedUpdaterBinary, spawnUpdaterProcess } from './updater-process'

test('spawnUpdaterProcess hides the updater console and detaches the child on Windows', () => {
  const calls: Array<{ args: string[]; command: string; options: SpawnOptions }> = []
  let unrefCalls = 0

  const child = {
    pid: 4242,
    unref: () => {
      unrefCalls += 1
    }
  }

  const result = spawnUpdaterProcess(
    'atlas-setup.exe',
    ['--update', '--branch', 'main'],
    { cwd: 'C:\\Atlas', detached: true, stdio: 'ignore' },
    {
      isWindows: true,
      spawnProcess: (command, args, options) => {
        calls.push({ args, command, options })

        return child
      }
    }
  )

  assert.equal(result, child)
  assert.equal(unrefCalls, 1)
  assert.deepEqual(calls, [
    {
      args: ['--update', '--branch', 'main'],
      command: 'atlas-setup.exe',
      options: { cwd: 'C:\\Atlas', detached: true, stdio: 'ignore', windowsHide: true }
    }
  ])
})

test('spawnUpdaterProcess preserves updater options off Windows', () => {
  let capturedOptions: SpawnOptions | undefined

  spawnUpdaterProcess(
    'atlas-setup',
    ['--update'],
    { detached: true, stdio: 'ignore' },
    {
      isWindows: false,
      spawnProcess: (_command, _args, options) => {
        capturedOptions = options

        return { unref: () => {} }
      }
    }
  )

  assert.deepEqual(capturedOptions, { detached: true, stdio: 'ignore' })
})

test('resolveStagedUpdaterBinary hands Windows the staged installer it finds', () => {
  const home = 'C:\\Users\\atlas\\AppData\\Local\\atlas'
  const staged = path.join(home, 'atlas-setup.exe')
  const probed: string[] = []

  const resolved = resolveStagedUpdaterBinary(home, {
    fileExists: (candidate) => {
      probed.push(candidate)

      return candidate === staged
    },
    isWindows: true
  })

  assert.equal(resolved, staged)
  assert.deepEqual(probed, [staged])
})

test('resolveStagedUpdaterBinary returns null off Windows even when atlas-setup is staged (#74836)', () => {
  const home = '/Users/atlas/.atlas'
  let probes = 0

  const resolved = resolveStagedUpdaterBinary(home, {
    // The installer stages atlas-setup on macOS/Linux too, so "it exists" is
    // the normal case — and precisely the one that must not win.
    fileExists: () => {
      probes += 1

      return true
    },
    isWindows: false
  })

  assert.equal(resolved, null)
  assert.equal(probes, 0)
})

test('resolveStagedUpdaterBinary returns null on Windows when nothing is staged', () => {
  const resolved = resolveStagedUpdaterBinary('C:\\Users\\atlas\\AppData\\Local\\atlas', {
    fileExists: () => false,
    isWindows: true
  })

  assert.equal(resolved, null)
})
