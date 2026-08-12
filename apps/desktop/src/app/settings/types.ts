import type { Dispatch, SetStateAction } from 'react'

import type { HermesGateway } from '@/hermes'
import type { IconComponent } from '@/lib/icons'
import type { EnvVarInfo } from '@/types/hermes'

// Billing, Gateway, Providers and Tools & Keys are gone from this build, so
// they are gone from the type: a view that cannot be rendered should not be
// nameable. See the note on SETTINGS_VIEWS in ./index.tsx.
export type SettingsView =
  | 'about'
  | 'keybinds'
  | 'nineGate'
  | 'notifications'
  | 'plugins'
  | 'sessions'
  | `config:${string}`
export type EnvPatch = Partial<Pick<EnvVarInfo, 'is_set' | 'redacted_value'>>

export interface SettingsPageProps {
  gateway?: HermesGateway | null
  onClose: () => void
  onConfigSaved?: () => void
  onMainModelChanged?: (provider: string, model: string) => void
}

export interface ProviderGroup {
  name: string
  priority: number
  entries: [string, EnvVarInfo][]
  hasAnySet: boolean
}

export interface DesktopConfigSection {
  id: string
  label: string
  icon: IconComponent
  keys: string[]
}

export interface EnvRowProps {
  varKey: string
  info: EnvVarInfo
  edits: Record<string, string>
  revealed: Record<string, string>
  saving: string | null
  setEdits: Dispatch<SetStateAction<Record<string, string>>>
  onSave: (key: string) => void
  onClear: (key: string) => void
  onReveal: (key: string) => void
  compact?: boolean
}
