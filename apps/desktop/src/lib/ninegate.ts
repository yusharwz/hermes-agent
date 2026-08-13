/**
 * The customer's NineGate subscription, as the desktop app sees it.
 *
 * There used to be a `locked` bit here, and a hook that fetched it so each
 * surface could decide whether to draw itself. That is gone: this build IS the
 * locked one, so every one of those decisions is now made in the source rather
 * than at runtime. Asking a backend that the app is still starting meant the
 * first render was a guess — the removed pages appeared, then vanished — and a
 * guess that is right eventually is still a flash.
 *
 * What remains is data no one can hardcode: which gateway this install talks
 * to, which key is active, and how much of the allowance is left.
 */

export type QuotaWindow = {
  limit: number
  used: number
  remaining: number
  reset_at: string
}

export type NineGateQuota = {
  five_hour?: QuotaWindow
  weekly?: QuotaWindow
}

export type NineGateStatus = {
  gateway: string
  keyPresent: boolean
  keyRedacted: string | null
  /** Null when the gateway could not be reached — the page omits the section. */
  quota: NineGateQuota | null
  plan: string | null
}

type StatusPayload = {
  gateway?: string
  key_present?: boolean
  key_redacted?: string | null
  quota?: NineGateQuota | null
  plan?: string | null
}

export async function fetchNineGateStatus(): Promise<NineGateStatus> {
  const payload = await window.atlasDesktop.api<StatusPayload>({ path: '/api/ninegate' })

  return {
    gateway: payload.gateway ?? '',
    keyPresent: Boolean(payload.key_present),
    keyRedacted: payload.key_redacted ?? null,
    plan: payload.plan ?? null,
    quota: payload.quota ?? null
  }
}
