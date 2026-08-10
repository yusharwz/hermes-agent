import { useCallback } from 'react'

import { isNineGateLocked } from '@/lib/ninegate'

import { useTheme } from './context'
import { DEFAULT_SKIN_NAME } from './presets'

// Retired skin names land on the shipping skin so old muscle memory still
// resolves to something rather than reporting an unknown theme.
const ALIASES: Record<string, string> = {
  ares: DEFAULT_SKIN_NAME,
  cyberpunk: DEFAULT_SKIN_NAME,
  default: DEFAULT_SKIN_NAME,
  ember: DEFAULT_SKIN_NAME,
  gold: DEFAULT_SKIN_NAME,
  hermes: DEFAULT_SKIN_NAME,
  midnight: DEFAULT_SKIN_NAME,
  nous: DEFAULT_SKIN_NAME,
  'nous-light': DEFAULT_SKIN_NAME,
  slate: DEFAULT_SKIN_NAME
}

export function useSkinCommand() {
  const { availableThemes, setTheme, themeName } = useTheme()

  return useCallback(
    (rawArg: string) => {
      const arg = rawArg.trim()

      // Atlas ships one skin, so there is nothing to cycle or list. Answering
      // plainly beats a command that reports switching to the theme already in
      // use, and it keeps `/skin` from being a back door into palettes the
      // settings page no longer offers.
      if (isNineGateLocked()) {
        return 'Atlas ships a single theme. Use Settings → Appearance to switch between light and dark.'
      }

      if (!availableThemes.length) {
        return 'No desktop themes are available.'
      }

      const activeIndex = Math.max(
        0,
        availableThemes.findIndex(t => t.name === themeName)
      )

      if (!arg || arg === 'next') {
        const next = availableThemes[(activeIndex + 1) % availableThemes.length]
        setTheme(next.name)

        return `Desktop theme switched to ${next.label}.`
      }

      if (arg === 'list' || arg === 'ls' || arg === 'status') {
        const rows = availableThemes.map(t => `${t.name === themeName ? '*' : ' '} ${t.name.padEnd(10)} ${t.label}`)

        return ['Desktop themes:', ...rows, '', 'Use /skin <name>, or /skin to cycle.'].join('\n')
      }

      const normalized = arg.toLowerCase()
      const targetName = ALIASES[normalized] || normalized

      const target = availableThemes.find(
        t => t.name.toLowerCase() === targetName || t.label.toLowerCase() === normalized
      )

      if (!target) {
        return `Unknown desktop theme: ${arg}\nAvailable: ${availableThemes.map(t => t.name).join(', ')}`
      }

      setTheme(target.name)

      return `Desktop theme switched to ${target.label}.`
    },
    [availableThemes, setTheme, themeName]
  )
}
