import { useCallback } from 'react'

/**
 * `/skin` — one answer, because Atlas ships one skin.
 *
 * The command used to cycle, list and switch palettes. There is nothing to
 * cycle here, and leaving it would make `/skin` a back door into palettes the
 * settings page no longer offers: the theme registry still holds built-ins the
 * UI has stopped listing, and a command that applies one by name reaches them
 * all. Answering plainly is better than reporting a switch to the theme
 * already in use.
 */
export function useSkinCommand() {
  return useCallback(
    () => 'Atlas ships a single theme. Use Settings → Appearance to switch between light and dark.',
    []
  )
}
