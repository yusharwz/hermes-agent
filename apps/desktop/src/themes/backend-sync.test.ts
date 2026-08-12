import { beforeEach, describe, expect, it } from 'vitest'

import { $backendThemes, $pendingSkinApply, __resetBackendSkinSync, ingestBackendSkin } from './backend-sync'

const skin = (name: string) => ({
  name,
  colors: { background: '#101020', ui_accent: '#ff33aa', banner_text: '#eeeeee' }
})

/**
 * A skin from the backend changes nothing here.
 *
 * This used to register the converted palette and repaint on a name change.
 * Atlas ships one skin, and an upgraded machine's CLI config can still name a
 * retired one — folding that in would put a colour scheme on screen that no
 * surface offers a way to leave.
 *
 * These cases are the tripwire. They are written against the events that
 * actually arrive (a connect-time seed, an explicit `skin.changed`, a switch
 * back to `default`), so a merge that restores the ingest turns them red
 * instead of quietly restoring the palettes.
 */
describe('ingestBackendSkin', () => {
  beforeEach(() => __resetBackendSkinSync())

  it('does not register a skin the backend pushes', () => {
    ingestBackendSkin(skin('neon'), { apply: false })

    expect($backendThemes.get().neon).toBeUndefined()
  })

  it('does not repaint on an explicit skin.changed', () => {
    ingestBackendSkin(skin('neon'), { apply: true })

    expect($pendingSkinApply.get()).toBeNull()
  })

  it('does not repaint on a name change either', () => {
    ingestBackendSkin(skin('neon'), { apply: true })
    ingestBackendSkin(skin('forest'), { apply: true })

    expect($pendingSkinApply.get()).toBeNull()
  })

  it('leaves the registry empty across a connect seed and a runtime change', () => {
    ingestBackendSkin(skin('neon'), { apply: false })
    ingestBackendSkin(skin('mono'), { apply: true })
    ingestBackendSkin(skin('default'), { apply: true })

    expect($backendThemes.get()).toEqual({})
    expect($pendingSkinApply.get()).toBeNull()
  })

  it('ignores empty payloads without throwing', () => {
    ingestBackendSkin(undefined, { apply: true })
    ingestBackendSkin({ name: '' }, { apply: true })

    expect($pendingSkinApply.get()).toBeNull()
  })
})
