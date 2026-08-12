/**
 * The Hermes surfaces Atlas removed stay removed.
 *
 * This is a tripwire, not a unit test. Every check below corresponds to
 * something that was once decided at RUNTIME — the renderer asked the backend
 * "is this a locked build?" and hid pages when the answer came back. That
 * answer arrives after the window is painted, so a customer saw the provider
 * pages, the billing tab, the theme marketplace and the upstream update button
 * appear and then vanish, every launch. On a menu launch the answer was wrong
 * to begin with: the flag it was seeded from lives in ~/.atlas/.env, which the
 * application process never reads.
 *
 * The fix was to stop asking. What makes that stick is not the deletion — it
 * is this file, because the fork merges from upstream, and upstream still has
 * every one of these surfaces. A merge that brings one back turns these red
 * instead of shipping it.
 *
 * Written against the source text on purpose. The point is that the code is
 * not there, which is not a claim any amount of rendering can make.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = join(__dirname)
const ELECTRON = join(__dirname, '..', 'electron')

function sourceFiles(dir: string): string[] {
  const out: string[] = []

  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name)

    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === 'dist') {
        continue
      }

      out.push(...sourceFiles(path))
    } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
      out.push(path)
    }
  }

  return out
}

const RENDERER = sourceFiles(SRC)

describe('the lock is not a runtime question any more', () => {
  it('no source asks the backend whether this is Atlas', () => {
    const offenders = RENDERER.filter(file => {
      const text = readFileSync(file, 'utf8')

      return /\buseNineGate\b|\bisNineGateLocked\b/.test(text)
    }).map(file => file.slice(SRC.length + 1))

    // Both helpers are gone from lib/ninegate.ts. Anything that reintroduces
    // them reintroduces the flash they caused.
    expect(offenders).toEqual([])
  })

  it('the status the app does fetch carries no locked bit', () => {
    const text = readFileSync(join(SRC, 'lib', 'ninegate.ts'), 'utf8')

    // What remains is data nobody can hardcode: gateway, key, quota, plan.
    // Matched on the field, not the word — the file explains in prose why the
    // bit is gone, and that explanation is the point of keeping it.
    expect(text).not.toMatch(/^\s*locked[?]?:/m)
    expect(text).not.toMatch(/payload\.locked|status\.locked/)
    expect(text).toContain('fetchNineGateStatus')
  })

  it('the preload does not pass a locked-build flag to the renderer', () => {
    const text = readFileSync(join(ELECTRON, 'preload.ts'), 'utf8')

    // It read process.env.ATLAS_LOCKED, which is set in ~/.atlas/.env and is
    // therefore absent from a launch through the applications menu — the only
    // way most customers ever start the app.
    expect(text).not.toContain('ATLAS_LOCKED')
    expect(text).not.toContain('lockedBuild')
  })
})

describe('the removed pages are not in the build', () => {
  const gone = [
    'app/settings/providers-settings.tsx',
    'app/settings/keys-settings.tsx',
    'app/settings/custom-endpoints-settings.tsx',
    'app/settings/model-settings.tsx',
    'app/settings/fallback-models-field.tsx',
    'app/settings/billing/index.tsx',
    'app/command-palette/marketplace-theme-page.tsx'
  ]

  for (const path of gone) {
    it(`${path} does not exist`, () => {
      expect(existsSync(join(SRC, path))).toBe(false)
    })
  }

  it('the settings nav cannot name a view it cannot render', () => {
    const text = readFileSync(join(SRC, 'app', 'settings', 'index.tsx'), 'utf8')
    const views = text.slice(text.indexOf('const SETTINGS_VIEWS'), text.indexOf('const DEFAULT_VIEW'))

    for (const view of ['providers', 'billing', 'gateway', 'keys']) {
      expect(views).not.toContain(`'${view}'`)
    }
  })

  it('the default settings view is a section that exists', async () => {
    const text = readFileSync(join(SRC, 'app', 'settings', 'index.tsx'), 'utf8')
    const match = /const DEFAULT_VIEW = 'config:([a-z]+)'/.exec(text)
    const { SECTIONS } = await import('./app/settings/constants')

    // It was `config:model`, a section deleted with the Model tab: opening
    // Settings landed on the old model page and then jumped away once the
    // backend answered. A default that names nothing is a slow redirect.
    expect(match).not.toBeNull()
    expect(SECTIONS.map(section => section.id)).toContain(match![1])
  })
})

describe('the upstream update path is not reachable', () => {
  it('the poller never checks', () => {
    const text = readFileSync(join(SRC, 'store', 'updates.ts'), 'utf8')
    const body = text.slice(text.indexOf('export function startUpdatePoller'))

    // What it finds is github.com/NousResearch/hermes-agent. Applying it would
    // pull Nous code over an Atlas install and take the NineGate lock with it.
    expect(body.slice(0, body.indexOf('\n}') + 2)).not.toMatch(/check|setInterval|addEventListener/)
  })

  it('About offers the gateway update card and nothing else', () => {
    const text = readFileSync(join(SRC, 'app', 'settings', 'about-settings.tsx'), 'utf8')

    expect(text).toContain('<NineGateUpdateCard />')
    expect(text).not.toContain('startActiveUpdate')
    expect(text).not.toContain('openUpdatesWindow')
  })
})
