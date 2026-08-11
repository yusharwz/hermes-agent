import { useCallback, useEffect, useMemo, useRef } from 'react'
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
import { useNineGate } from '@/lib/ninegate'
import { notifyError } from '@/store/notifications'

import { useRouteEnumParam } from '../hooks/use-route-enum-param'
import { OverlayIconButton } from '../overlays/overlay-chrome'
import { OverlayMain, OverlayNav, type OverlayNavGroup, OverlaySplitLayout } from '../overlays/overlay-split-layout'
import { OverlayView } from '../overlays/overlay-view'
import { SKILLS_ROUTE } from '../routes'

import { AboutSettings } from './about-settings'
import { AppearanceSettings } from './appearance-settings'
import { BillingSettings } from './billing'
import { ConfigSettings } from './config-settings'
import { LOCKED_HIDDEN_SECTIONS, SECTIONS } from './constants'
import { GatewaySettings } from './gateway-settings'
import { KeybindSettings } from './keybind-settings'
import { KEYS_VIEWS, KeysSettings, type KeysView } from './keys-settings'
import { NineGateSettings } from './ninegate-settings'
import { NotificationsSettings } from './notifications-settings'
import { PluginsSettings } from './plugins-settings'
import { PROVIDER_VIEWS, ProvidersSettings, type ProviderView } from './providers-settings'
import { SessionsSettings } from './sessions-settings'
import type { SettingsPageProps, SettingsView as SettingsViewId } from './types'

const SETTINGS_VIEWS: readonly SettingsViewId[] = [
  ...SECTIONS.map(s => `config:${s.id}` as SettingsViewId),
  'providers',
  'nineGate',
  'gateway',
  'keybinds',
  'keys',
  'notifications',
  'billing',
  'plugins',
  'sessions',
  'about'
]

export function SettingsView({ onClose, onConfigSaved, onMainModelChanged }: SettingsPageProps) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { hash, pathname, search } = useLocation()

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

  const [activeView, setActiveView] = useRouteEnumParam('tab', SETTINGS_VIEWS, 'config:model' as SettingsViewId)
  // Providers subnav (Accounts vs API keys) lives in its own param so each
  // sub-view is deep-linkable and survives a refresh.
  const [providerView, setProviderView] = useRouteEnumParam<ProviderView>('pview', PROVIDER_VIEWS, 'accounts')
  const [keysView] = useRouteEnumParam<KeysView>('kview', KEYS_VIEWS, 'tools')
  // Drives what the settings nav is allowed to offer — see lib/ninegate.ts.
  const nineGate = useNineGate()

  /**
   * A locked build has no Providers page, but `?tab=providers` is still a
   * valid enum value — bookmarks, the command palette and older deep links all
   * still produce it. Left alone it falls through the render chain and lands
   * on whatever comes next, which was Archived Chats: not an error, just the
   * wrong page, which is harder to notice and harder to report.
   *
   * Redirected once the lock is known. Waiting for `resolved` matters: acting
   * on the default would bounce an unlocked developer build away from a page
   * it is entitled to.
   */
  useEffect(() => {
    if (!nineGate.resolved || !nineGate.locked) {return}

    // Every view removed above. A tab that no longer exists must redirect, not
    // fall through the render chain — that is how ?tab=providers ended up
    // showing Archived Chats.
    const removed = new Set(['providers', 'billing', 'gateway', 'keys', 'config:model', 'config:voice'])

    if (removed.has(activeView)) {
      setActiveView('nineGate')
    }
  }, [nineGate.resolved, nineGate.locked, activeView, setActiveView])

  // Jump to a section + its sub-view in one navigate. Two sequential setters
  // would each read the same stale `search` and the second would clobber the
  // first's `tab` — so the sub-view never opened on narrow screens.
  const openSubView = useCallback(
    (tab: SettingsViewId, param: string, value: string, fallback: string) => {
      const params = new URLSearchParams(search)
      params.set('tab', tab)

      if (value === fallback) {
        params.delete(param)
      } else {
        params.set(param, value)
      }

      const qs = params.toString()
      navigate({ hash, pathname, search: qs ? `?${qs}` : '' }, { replace: true })
    },
    [hash, navigate, pathname, search]
  )

  const openProviderView = useCallback(
    (view: ProviderView) => openSubView('providers', 'pview', view, 'accounts'),
    [openSubView]
  )

  const openKeysView = useCallback((view: KeysView) => openSubView('keys', 'kview', view, 'tools'), [openSubView])

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
      /**
       * Sections a locked build does not own.
       *
       * model   — the model is chosen in the composer; everything that was on
       *           this page (provider, fallback chain) belonged to the
       *           multi-provider world.
       * voice   — every TTS/STT backend here wants the customer's own vendor
       *           key, which is not how a NineGate subscription works.
       *
       * Filtered here rather than deleted from SECTIONS so an unlocked
       * developer build keeps them.
       */
      ...SECTIONS.filter(s => !(nineGate.locked && LOCKED_HIDDEN_SECTIONS.has(s.id))).map(s => {
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
      // Billing, Providers, Gateway and Tools & Keys are not in this build.
      //
      // They were filtered out here at render time, which left them in the
      // bundle: the nav drew them and then dropped them, so a customer saw a
      // flash of the exact pages this distribution does not have — for longer
      // on a slow connection, because the filter waited on a backend answer.
      //
      // Hiding is the wrong tool when the answer is never "sometimes". The
      // provider is fixed, the key is the subscription's, a custom endpoint
      // would be ignored, the gateway is chosen by the installer, and billing
      // belongs to an account on someone else's service. None of them can ever
      // apply here, so none of them is built.
      // The one account page a locked build has. Hidden on an unlocked one,
      // where there is no subscription to show and the provider pages below
      // are the real thing.
      ...(nineGate.locked
        ? [{
            active: activeView === 'nineGate',
            gapBefore: true,
            icon: Zap,
            id: 'nineGate',
            label: 'Langganan NineGate',
            onSelect: () => setActiveView('nineGate')
          }]
        : []),
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
    [activeView, keysView, providerView, t, setActiveView, openProviderView, openKeysView, nineGate.locked]
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
          ) : activeView === 'gateway' && !nineGate.locked ? (
            <GatewaySettings />
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
          ) : activeView === 'providers' && !nineGate.locked ? (
            <ProvidersSettings
              onClose={onClose}
              onConfigSaved={onConfigSaved}
              onMainModelChanged={onMainModelChanged}
              onViewChange={setProviderView}
              view={providerView}
            />
          ) : activeView === 'keys' && !nineGate.locked ? (
            <KeysSettings view={keysView} />
          ) : activeView === 'notifications' ? (
            <NotificationsSettings />
          ) : activeView === 'billing' && !nineGate.locked ? (
            <BillingSettings />
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
