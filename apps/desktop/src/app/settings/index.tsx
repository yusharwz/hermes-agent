import { useEffect, useMemo, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { Tip } from '@/components/ui/tooltip'
import { getHermesConfigDefaults, getHermesConfigRecord, saveHermesConfig } from '@/hermes'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import {
  Archive,
  Bell,
  Download,
  Info,
  Keyboard,
  Package,
  RefreshCw,
  Upload,
  Zap
} from '@/lib/icons'
import { notifyError } from '@/store/notifications'

import { useRouteEnumParam } from '../hooks/use-route-enum-param'
import { OverlayIconButton } from '../overlays/overlay-chrome'
import { OverlayMain, OverlayNav, type OverlayNavGroup, OverlaySplitLayout } from '../overlays/overlay-split-layout'
import { OverlayView } from '../overlays/overlay-view'
import { SKILLS_ROUTE } from '../routes'

import { AboutSettings } from './about-settings'
import { AppearanceSettings } from './appearance-settings'
import { ConfigSettings } from './config-settings'
import { SECTIONS } from './constants'
import { KeybindSettings } from './keybind-settings'
import { NineGateSettings } from './ninegate-settings'
import { NotificationsSettings } from './notifications-settings'
import { PluginsSettings } from './plugins-settings'
import { SessionsSettings } from './sessions-settings'
import type { SettingsPageProps, SettingsView as SettingsViewId } from './types'

/**
 * Every view this build has. Billing, Providers, Gateway and Tools & Keys are
 * absent rather than filtered.
 *
 * They used to be listed here and dropped at render time on a backend answer,
 * which meant the nav drew them before it knew — a flash of the exact pages
 * Atlas does not have, lasting as long as the backend took to accept a
 * connection. Hiding is the wrong tool when the answer is never "sometimes":
 * the provider is fixed, the key belongs to the subscription, a custom
 * endpoint would be ignored, the gateway is chosen by the installer, and
 * billing lives in an account on someone else's service.
 *
 * An old `?tab=providers` bookmark now names a view that is not in this list,
 * and useRouteEnumParam coerces an unknown value to the default below. That is
 * the whole redirect: no effect, nothing to wait for, nowhere to fall through.
 */
const SETTINGS_VIEWS: readonly SettingsViewId[] = [
  ...SECTIONS.map(s => `config:${s.id}` as SettingsViewId),
  'nineGate',
  'keybinds',
  'notifications',
  'plugins',
  'sessions',
  'about'
]

/**
 * The first item in the nav, and a section that exists.
 *
 * It was `config:model` — a page deleted with the Model tab. Opening Settings
 * therefore landed on a section with no fields, rendering the old model page
 * for as long as the lock took to resolve, and then jumping elsewhere. The
 * default has to name something in SETTINGS_VIEWS or it is just a slower way
 * of arriving somewhere unintended.
 */
const DEFAULT_VIEW = 'config:chat' as SettingsViewId

export function SettingsView({ onClose, onConfigSaved, onMainModelChanged }: SettingsPageProps) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { search } = useLocation()

  // MCP moved out of Settings into Capabilities (/skills?tab=mcp). Keep old
  // `/settings?tab=mcp` deep links working — `useRouteEnumParam` would silently
  // coerce the unknown tab to the default view otherwise. Preserve `server=` so
  // an old bookmark still lands on (and highlights) the selected server.
  useEffect(() => {
    const params = new URLSearchParams(search)

    if (params.get('tab') === 'mcp') {
      const server = params.get('server')
      const suffix = server ? `&server=${encodeURIComponent(server)}` : ''
      navigate(`${SKILLS_ROUTE}?tab=mcp${suffix}`, { replace: true })
    }
  }, [navigate, search])

  const [activeView, setActiveView] = useRouteEnumParam('tab', SETTINGS_VIEWS, DEFAULT_VIEW)

  const importInputRef = useRef<HTMLInputElement | null>(null)

  const exportConfig = async () => {
    try {
      const cfg = await getHermesConfigRecord()
      const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'hermes-config.json'
      a.click()
      URL.revokeObjectURL(url)
      triggerHaptic('success')
    } catch (err) {
      notifyError(err, t.settings.exportFailed)
    }
  }

  const resetConfig = async () => {
    if (!window.confirm(t.settings.resetConfirm)) {
      return
    }

    try {
      await saveHermesConfig(await getHermesConfigDefaults())
      triggerHaptic('success')
      onConfigSaved?.()
    } catch (err) {
      notifyError(err, t.settings.resetFailed)
    }
  }

  const navGroups: OverlayNavGroup[] = useMemo(
    () => [
      ...SECTIONS.map(s => {
        const view = `config:${s.id}` as SettingsViewId

        return {
          active: activeView === view,
          icon: s.icon,
          id: view,
          label: t.settings.sections[s.id] ?? s.label,
          onSelect: () => setActiveView(view)
        }
      }),
      {
        active: activeView === 'notifications',
        icon: Bell,
        id: 'notifications',
        label: t.settings.nav.notifications,
        onSelect: () => setActiveView('notifications')
      },
      // The account page this build does have: the subscription that pays for
      // every model it can reach.
      {
        active: activeView === 'nineGate',
        gapBefore: true,
        icon: Zap,
        id: 'nineGate',
        label: 'Langganan NineGate',
        onSelect: () => setActiveView('nineGate')
      },
      {
        active: activeView === 'keybinds',
        icon: Keyboard,
        id: 'keybinds',
        label: t.settings.nav.keybinds,
        onSelect: () => setActiveView('keybinds')
      },
      {
        active: activeView === 'plugins',
        icon: Package,
        id: 'plugins',
        label: t.settings.nav.plugins,
        onSelect: () => setActiveView('plugins')
      },
      {
        active: activeView === 'sessions',
        icon: Archive,
        id: 'sessions',
        label: t.settings.nav.archivedChats,
        onSelect: () => setActiveView('sessions')
      },
      {
        active: activeView === 'about',
        gapBefore: true,
        icon: Info,
        id: 'about',
        label: t.settings.nav.about,
        onSelect: () => setActiveView('about')
      }
    ],
    [activeView, t, setActiveView]
  )

  const navFooter = (
    <>
      <Tip label={t.settings.exportConfig}>
        <OverlayIconButton onClick={() => void exportConfig()}>
          <Download />
        </OverlayIconButton>
      </Tip>
      <Tip label={t.settings.importConfig}>
        <OverlayIconButton
          onClick={() => {
            triggerHaptic('open')
            importInputRef.current?.click()
          }}
        >
          <Upload />
        </OverlayIconButton>
      </Tip>
      <Tip label={t.settings.resetToDefaults}>
        <OverlayIconButton
          className="hover:text-destructive"
          onClick={() => {
            triggerHaptic('warning')
            void resetConfig()
          }}
        >
          <RefreshCw />
        </OverlayIconButton>
      </Tip>
    </>
  )

  return (
    <OverlayView closeLabel={t.settings.closeSettings} onClose={onClose}>
      <OverlaySplitLayout>
        <OverlayNav footer={navFooter} groups={navGroups} />

        <OverlayMain className="px-0 pb-0">
          {activeView === 'config:appearance' ? (
            <AppearanceSettings />
          ) : activeView === 'about' ? (
            <AboutSettings />
          ) : activeView === 'keybinds' ? (
            <KeybindSettings />
          ) : activeView.startsWith('config:') ? (
            <ConfigSettings
              activeSectionId={activeView.slice('config:'.length)}
              importInputRef={importInputRef}
              onConfigSaved={onConfigSaved}
              onMainModelChanged={onMainModelChanged}
            />
          ) : activeView === 'nineGate' ? (
            <NineGateSettings />
          ) : activeView === 'notifications' ? (
            <NotificationsSettings />
          ) : activeView === 'plugins' ? (
            <PluginsSettings />
          ) : (
            <SessionsSettings />
          )}
        </OverlayMain>
      </OverlaySplitLayout>
    </OverlayView>
  )
}

export { SettingsView as SettingsPage }
