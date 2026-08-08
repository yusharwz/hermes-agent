/**
 * What the desktop app is allowed to show when this build is a NineGate one.
 *
 * A locked Atlas serves every model through the NineGate gateway on the
 * customer's subscription key. The agent enforces that on its own — the
 * environment is pinned at boot and the shared env writer refuses to persist a
 * competing endpoint — so nothing here is a security boundary. What this is
 * for is the interface.
 *
 * Leaving the provider pages visible on a locked build would show a customer
 * an "Add OpenAI key" form that saves nothing, a provider list they cannot
 * switch to, and a custom-endpoint editor whose entries are ignored. Every one
 * of those is a support ticket about a broken app, and none of them is a
 * feature they bought. So the pages come out, and one page that IS theirs —
 * their subscription and its key — goes in.
 */
import { useEffect, useState } from 'react'

export type NineGateStatus = {
  locked: boolean
  gateway: string
  keyPresent: boolean
  keyRedacted: string | null
}

const UNLOCKED: NineGateStatus = {
  gateway: '',
  keyPresent: false,
  keyRedacted: null,
  locked: false
}

type StatusPayload = {
  locked?: boolean
  gateway?: string
  key_present?: boolean
  key_redacted?: string | null
}

export async function fetchNineGateStatus(): Promise<NineGateStatus> {
  const payload = await window.hermesDesktop.api<StatusPayload>({ path: '/api/ninegate' })
  return {
    gateway: payload.gateway ?? '',
    keyPresent: Boolean(payload.key_present),
    keyRedacted: payload.key_redacted ?? null,
    locked: Boolean(payload.locked)
  }
}

/**
 * Answers "unlocked" until the backend says otherwise.
 *
 * The bias is deliberate and it is the safe direction for a *UI* gate: the
 * worst case is that a provider page flickers into view for one frame on a
 * locked build, which is untidy. Defaulting the other way would hide the
 * provider pages from every unlocked developer build for as long as the
 * request took, which is a real regression for the upstream app.
 */
export function useNineGate(): NineGateStatus {
  const [status, setStatus] = useState<NineGateStatus>(UNLOCKED)

  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        const next = await fetchNineGateStatus()
        if (!cancelled) setStatus(next)
      } catch {
        // An older backend has no /api/ninegate. That build predates the lock,
        // so unlocked is the correct answer rather than an error to surface.
      }
    })()

    return () => void (cancelled = true)
  }, [])

  return status
}
