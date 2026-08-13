import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { __resetBackendSkinSync, ingestBackendSkin } from './backend-sync'
import { ThemeProvider } from './context'

// A skin file the backend announces must not reach the painted theme. The
// live-authoring loop it used to serve — Atlas writes a skin, every surface
// repaints — is not part of this build; see themes/backend-sync.ts.
const bloomberg = (foreground: string) => ({
  name: 'bloomberg',
  colors: { background: '#000000', ui_text: foreground, ui_accent: '#ff8000' }
})

const cssVar = (name: string) => window.document.documentElement.style.getPropertyValue(name)

describe('ThemeProvider ← backend skin sync', () => {
  beforeEach(() => {
    window.localStorage.clear()
    __resetBackendSkinSync()
  })

  afterEach(cleanup)

  it('does not paint an activated backend skin', () => {
    render(
      <ThemeProvider>
        <div />
      </ThemeProvider>
    )

    const before = cssVar('--theme-foreground')
    act(() => ingestBackendSkin(bloomberg('#ff9f0a'), { apply: true }))

    expect(cssVar('--theme-foreground')).toBe(before)
    expect(cssVar('--theme-foreground')).not.toBe('#ff9f0a')
  })

  it('does not paint an in-place edit of a skin file either', () => {
    render(
      <ThemeProvider>
        <div />
      </ThemeProvider>
    )

    const before = cssVar('--theme-foreground')
    act(() => ingestBackendSkin(bloomberg('#ff9f0a'), { apply: true }))
    act(() => ingestBackendSkin(bloomberg('#ff2d95'), { apply: true }))

    expect(cssVar('--theme-foreground')).toBe(before)
  })

  it('leaves the painted theme alone when a skin is seeded on reconnect', () => {
    render(
      <ThemeProvider>
        <div />
      </ThemeProvider>
    )

    const before = cssVar('--theme-foreground')
    act(() =>
      ingestBackendSkin({ name: 'forest', colors: { background: '#001100', ui_text: '#66ff66' } }, { apply: false })
    )

    expect(cssVar('--theme-foreground')).toBe(before)
  })
})
