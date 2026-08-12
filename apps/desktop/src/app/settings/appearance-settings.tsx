import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import { LanguageSwitcher } from '@/components/language-switcher'
import { Button } from '@/components/ui/button'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import { Palette } from '@/lib/icons'
import { $backdrop, setBackdrop } from '@/store/backdrop'
import { $embedAllowed, $embedMode, clearEmbedAllowed, type EmbedMode, setEmbedMode } from '@/store/embed-consent'
import { $reactionsEnabled, setReactionsEnabled } from '@/store/reactions-enabled'
import { $toolViewMode, setToolViewMode } from '@/store/tool-view'
import { $translucency, setTranslucency } from '@/store/translucency'
import { $zoomPercent, setZoomPercent } from '@/store/zoom'
import { useTheme } from '@/themes/context'

import { MODE_OPTIONS } from './constants'
import { PetSettings } from './pet-settings'
import { ListRow, SectionHeading, SettingsContent } from './primitives'

const UI_SCALE_PRESETS = ['90', '100', '110', '125', '150', '175'] as const

type UiScalePreset = (typeof UI_SCALE_PRESETS)[number]

function matchUiScalePreset(percent: number): UiScalePreset | null {
  return UI_SCALE_PRESETS.find(preset => Number(preset) === percent) ?? null
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs)

    return () => clearTimeout(handle)
  }, [value, delayMs])

  return debounced
}

const compactNumber = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })

export function AppearanceSettings() {
  const { t, isSavingLocale } = useI18n()
  const { mode, setMode } = useTheme()
  const toolViewMode = useStore($toolViewMode)
  const zoomPercent = useStore($zoomPercent)
  const embedMode = useStore($embedMode)
  const embedAllowed = useStore($embedAllowed)
  const translucency = useStore($translucency)
  const reactionsEnabled = useStore($reactionsEnabled)
  const backdrop = useStore($backdrop)
  const a = t.settings.appearance


  const modeOptions = MODE_OPTIONS.map(({ id, icon }) => ({ icon, id, label: t.settings.modeOptions[id].label }))

  const toolOptions = [
    { id: 'product', label: a.product },
    { id: 'technical', label: a.technical }
  ] as const

  const embedOptions = [
    { id: 'ask', label: a.embedsAsk },
    { id: 'always', label: a.embedsAlways },
    { id: 'off', label: a.embedsOff }
  ] as const satisfies readonly { id: EmbedMode; label: string }[]

  const uiScaleOptions = UI_SCALE_PRESETS.map(preset => ({ id: preset, label: `${preset}%` }))

  const matchedScalePreset = matchUiScalePreset(zoomPercent)

  return (
    <SettingsContent>
      <div>
        <SectionHeading icon={Palette} title={a.title} />
        <p className="max-w-2xl text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)">
          {a.intro}
        </p>

        <div className="mt-2">
          <ListRow
            action={<LanguageSwitcher />}
            description={isSavingLocale ? t.language.saving : t.language.description}
            title={t.language.label}
          />

          {/*
            Light or dark, and nothing else.

            Atlas ships a single skin, so the chooser that went here — the
            installed-theme grid, the search box, the VS Code Marketplace
            results and the remove buttons — has nothing to choose between.
            It used to be rendered and then hidden on a backend answer, which
            meant a customer saw a marketplace for palettes this build does
            not carry, until the answer arrived. It is not built now.
          */}
          <ListRow
            description={a.modeDesc}
            title={
              <div className="flex items-center justify-between gap-3">
                <span>{a.modeTitle}</span>
                <SegmentedControl
                  onChange={id => {
                    triggerHaptic('crisp')
                    setMode(id)
                  }}
                  options={modeOptions}
                  value={mode}
                />
              </div>
            }
            wide
          />

          <ListRow
            action={
              <SegmentedControl
                onChange={id => {
                  triggerHaptic('selection')
                  setZoomPercent(Number(id))
                }}
                options={uiScaleOptions}
                value={matchedScalePreset ?? ('' as UiScalePreset)}
              />
            }
            description={a.uiScaleDesc(zoomPercent)}
            title={a.uiScaleTitle}
          />

          <ListRow
            action={
              <div className="flex items-center gap-3">
                <input
                  aria-label={a.translucencyTitle}
                  className="h-1 w-40 cursor-pointer appearance-none rounded-full bg-(--ui-stroke-tertiary)"
                  max={100}
                  min={0}
                  onChange={event => {
                    triggerHaptic('selection')
                    setTranslucency(Number(event.target.value))
                  }}
                  step={5}
                  style={{ accentColor: 'var(--dt-primary)' }}
                  type="range"
                  value={translucency}
                />
                <span className="w-9 text-right text-[length:var(--conversation-caption-font-size)] tabular-nums text-(--ui-text-tertiary)">
                  {translucency}%
                </span>
              </div>
            }
            description={a.translucencyDesc}
            title={a.translucencyTitle}
          />

          <ListRow
            action={
              <SegmentedControl
                onChange={id => {
                  triggerHaptic('selection')
                  setBackdrop(id === 'on')
                }}
                options={[
                  { id: 'off', label: t.common.off },
                  { id: 'on', label: t.common.on }
                ]}
                value={backdrop ? 'on' : 'off'}
              />
            }
            description={a.backdropDesc}
            title={a.backdropTitle}
          />

          <ListRow
            action={
              <SegmentedControl
                onChange={id => {
                  triggerHaptic('selection')
                  setReactionsEnabled(id === 'on')
                }}
                options={[
                  { id: 'off', label: t.common.off },
                  { id: 'on', label: t.common.on }
                ]}
                value={reactionsEnabled ? 'on' : 'off'}
              />
            }
            description={a.reactionsDesc}
            title={a.reactionsTitle}
          />

          <ListRow
            action={
              <SegmentedControl
                onChange={id => {
                  triggerHaptic('selection')
                  setToolViewMode(id)
                }}
                options={toolOptions}
                value={toolViewMode}
              />
            }
            description={a.toolViewDesc}
            title={a.toolViewTitle}
          />

          <ListRow
            action={
              <div className="flex flex-col items-end gap-1.5">
                <SegmentedControl
                  onChange={id => {
                    triggerHaptic('selection')
                    setEmbedMode(id)
                  }}
                  options={embedOptions}
                  value={embedMode}
                />
                {embedAllowed.length > 0 && (
                  <Button
                    onClick={() => {
                      triggerHaptic('selection')
                      clearEmbedAllowed()
                    }}
                    size="inline"
                    variant="text"
                  >
                    {a.embedsReset(embedAllowed.length)}
                  </Button>
                )}
              </div>
            }
            description={a.embedsDesc}
            title={a.embedsTitle}
          />
        </div>
      </div>

      <div className="mt-6">
        <PetSettings />
      </div>
    </SettingsContent>
  )
}
