/**
 * Skins pushed by the backend, and why this build ignores them.
 *
 * The backend resolves an active skin (built-in, or `$ATLAS_HOME/skins/*.yaml`)
 * and announces it on `gateway.ready` / `skin.changed`. This used to fold that
 * payload into the desktop: register the converted theme so it appeared
 * wherever a built-in does — Appearance, Cmd-K, `/skin` — and repaint on a
 * genuine name change.
 *
 * Atlas ships one skin, so an arriving skin has nothing to add and a real way
 * to do harm. The CLI config on an upgraded machine can still name a retired
 * theme, and converting it here would register that palette back into an app
 * that deliberately stopped carrying it — putting a colour scheme on screen
 * that no surface offers a way to leave. The desktop registry is the authority
 * on what this build looks like; the backend does not get to extend it.
 *
 * The atoms stay because the ThemeProvider drains them, and the ingest stays
 * as a named no-op because the gateway event handlers call it. Both are
 * cheaper to keep honest here than to unpick across every call site — and this
 * file is where someone looks when they wonder why a `skin.changed` did
 * nothing.
 */

import type { AtlasSkin } from '@atlas/shared/skin'
import { atom } from 'nanostores'

import type { DesktopTheme } from './types'

/** Always empty. `listAllThemes` still merges it; there is nothing to merge. */
export const $backendThemes = atom<Record<string, DesktopTheme>>({})

/** Always null. The ThemeProvider still drains it; nothing ever fills it. */
export const $pendingSkinApply = atom<string | null>(null)

/** Test-only: reset the registry between cases. */
export function __resetBackendSkinSync(): void {
  $backendThemes.set({})
  $pendingSkinApply.set(null)
}

/**
 * Accepts a skin from the backend and does nothing with it.
 *
 * Deliberately not an error and not a warning: a customer whose config names a
 * skin has done nothing wrong, and the event arrives on every connect.
 */
export function ingestBackendSkin(_skin: AtlasSkin | undefined | null, _options: { apply: boolean }): void {}
