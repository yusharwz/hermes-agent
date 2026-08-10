import { beforeEach, describe, expect, it } from 'vitest'

import { modePref, skinPref } from './context'
import { DEFAULT_SKIN_NAME } from './presets'

/**
 * The per-profile contract, asserted over `mode`.
 *
 * Skin used to be tested alongside it, with 'ember' and 'midnight' as two
 * values to hold apart. Atlas ships one skin now, so there is no second value
 * to assign and that half of the table cannot be written any more. What is
 * still worth pinning about skin is the normalisation, which is what carries
 * an existing install through the upgrade — that gets its own block below.
 */
describe("per-profile 'mode'", () => {
  const pref = modePref as unknown as { resolve: (profile: string) => string; assign: (profile: string, value: string) => void }

  beforeEach(() => window.localStorage.clear())

  it('falls back to the default when unassigned', () => {
    // Dark, deliberately: Atlas is a dark application unless told otherwise.
    expect(pref.resolve('default')).toBe('dark')
    expect(pref.resolve('work')).toBe('dark')
  })

  it('keeps each profile on its own value', () => {
    pref.assign('work', 'light')
    pref.assign('default', 'system')
    expect(pref.resolve('work')).toBe('light')
    expect(pref.resolve('default')).toBe('system')
  })

  it('lets unassigned profiles inherit the default profile as the global fallback', () => {
    pref.assign('default', 'light')
    expect(pref.resolve('never-themed')).toBe('light')
  })

  it('normalizes an unknown stored value back to the default', () => {
    pref.assign('work', 'dusk')
    expect(pref.resolve('work')).toBe('dark')
  })
})

describe("per-profile 'skin'", () => {
  const pref = skinPref as unknown as { resolve: (profile: string) => string; assign: (profile: string, value: string) => void }

  beforeEach(() => window.localStorage.clear())

  it('falls back to the only skin when unassigned', () => {
    expect(pref.resolve('default')).toBe(DEFAULT_SKIN_NAME)
    expect(pref.resolve('work')).toBe(DEFAULT_SKIN_NAME)
  })

  it.each(['nous', 'midnight', 'ember', 'cyberpunk', 'slate', 'nous-light', 'gold'])(
    'migrates the retired skin %s onto the default',
    retired => {
      // The upgrade path. Someone running the previous build has one of these
      // persisted; resolving it to nothing would boot them to an unpainted UI.
      pref.assign('work', retired)
      expect(pref.resolve('work')).toBe(DEFAULT_SKIN_NAME)
    }
  )

  it('normalizes an unknown stored value back to the default', () => {
    pref.assign('work', 'nope')
    expect(pref.resolve('work')).toBe(DEFAULT_SKIN_NAME)
  })
})
