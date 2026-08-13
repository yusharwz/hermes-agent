import { getGlobalModelOptions, type AtlasGateway, type ModelOptionsResponse } from '@/atlas'
import type { ModelOptionProvider } from '@/types/atlas'

/**
 * True only when a persisted **manual** composer pick has been removed from the
 * catalog (its provider still ships models, but no longer this one) — so a new
 * chat would keep 404'ing the dead model. Deliberately conservative to never
 * clobber a still-valid pick: an unknown/absent provider, an empty model list
 * (re-auth / unconfigured), or a not-yet-loaded catalog all return false.
 */
export function manualPickRemoved(
  providers: ModelOptionProvider[] | undefined,
  provider: string,
  model: string
): boolean {
  if (!providers?.length || !provider || !model) {
    return false
  }

  const row = providers.find(p => p.slug === provider || p.name === provider)

  if (!row) {
    return false
  }

  const models = row.models ?? []

  // Empty list means the provider is present but unconfigured / awaiting
  // re-auth, not that the model was dropped — leave the pick alone.
  if (models.length === 0) {
    return false
  }

  return !models.includes(model)
}

interface ModelOptionsRequest {
  /** When false, include ambient/unconfigured providers (onboarding/setup
   *  surfaces). Chat pickers default to true so only explicitly configured
   *  providers are listed (#56974). */
  explicitOnly?: boolean
  gateway?: AtlasGateway
  refresh?: boolean
  sessionId?: null | string
}

/**
 * Query options for any surface that lists models.
 *
 * A locked build's catalogue is not a local fact — it is the customer's plan,
 * held on the server, and it changes when their subscription is edited. The
 * shared 60-second staleTime is right for settings that only this app writes;
 * it is wrong for a list somebody else owns. A stale list here means offering
 * a model the plan has dropped, which is where "model not found" comes from.
 *
 * So the list is refetched whenever a surface mounts and whenever the window
 * is focused — which is precisely when someone returns to Atlas after
 * changing their plan in the NineGate dashboard.
 */
export function modelOptionsFreshness(): { refetchOnWindowFocus?: boolean; staleTime?: number } {
  return { refetchOnWindowFocus: true, staleTime: 0 }
}

export function modelOptionsQueryKey(profile: null | string | undefined, sessionId?: null | string) {
  const profileKey = (profile ?? '').trim() || 'default'

  return ['model-options', profileKey, sessionId || 'global'] as const
}

export function requestModelOptions({
  explicitOnly = true,
  gateway,
  refresh = false,
  sessionId
}: ModelOptionsRequest): Promise<ModelOptionsResponse> {
  if (gateway) {
    const params: Record<string, unknown> = {}

    if (sessionId) {
      params.session_id = sessionId
    }

    if (refresh) {
      params.refresh = true
    }

    if (explicitOnly) {
      params.explicit_only = true
    }

    return gateway.request<ModelOptionsResponse>('model.options', params)
  }

  return getGlobalModelOptions({ explicitOnly, ...(refresh ? { refresh: true } : {}) })
}
