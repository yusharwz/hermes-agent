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
  /**
   * False until the backend has answered.
   *
   * Callers that REMOVE something when locked must wait for this. The default
   * is "unlocked", so acting before the answer arrives shows the thing for a
   * frame or two — and a provider chooser that flashes up and vanishes looks
   * exactly like the bug it was supposed to fix.
   */
  resolved: boolean
  /** Null when the gateway could not be reached — the page omits the section. */
  quota: NineGateQuota | null
  plan: string | null
}

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

const UNLOCKED: NineGateStatus = {
  gateway: '',
  keyPresent: false,
  keyRedacted: null,
  locked: false,
  plan: null,
  quota: null,
  resolved: false
}

type StatusPayload = {
  locked?: boolean
  gateway?: string
  key_present?: boolean
  key_redacted?: string | null
  quota?: NineGateQuota | null
  plan?: string | null
}

/**
 * Last answer from the backend, readable synchronously.
 *
 * Hooks are not available everywhere the lock matters. Backend skin ingestion
 * and the model resolver both run outside React, on events rather than on a
 * render, and both have to know whether this is a locked build. This is that
 * answer, refreshed by every fetch below.
 *
 * Null means "not asked yet", which callers must treat as unlocked for the
 * same reason `resolved` exists: guessing "locked" before the answer arrives
 * would break an unlocked developer build for the first few hundred
 * milliseconds of every boot.
 */
let cachedLocked: boolean | null = null

/** Whether this is a locked NineGate build, for code that cannot use a hook. */
export function isNineGateLocked(): boolean {
  return cachedLocked === true
}

/**
 * Asks the backend as soon as this module loads, rather than waiting for the
 * first component to mount.
 *
 * The non-React callers are driven by gateway events, and a gateway event can
 * arrive before any settings screen has ever been opened. Priming here settles
 * the answer during module evaluation — long before the websocket connects,
 * since connecting needs the same desktop bridge this call does.
 */
if (typeof window !== 'undefined') {
  void fetchNineGateStatus().catch(() => {
    cachedLocked = false
  })
}

export async function fetchNineGateStatus(): Promise<NineGateStatus> {
  const payload = await window.hermesDesktop.api<StatusPayload>({ path: '/api/ninegate' })
  cachedLocked = Boolean(payload.locked)

  return {
    gateway: payload.gateway ?? '',
    keyPresent: Boolean(payload.key_present),
    keyRedacted: payload.key_redacted ?? null,
    locked: Boolean(payload.locked),
    plan: payload.plan ?? null,
    quota: payload.quota ?? null,
    resolved: true
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

        if (!cancelled) {setStatus(next)}
      } catch {
        // An older backend has no /api/ninegate. That build predates the lock,
        // so unlocked is the correct answer rather than an error to surface —
        // but it IS an answer, so callers stop waiting.
        cachedLocked = false

        if (!cancelled) {setStatus({ ...UNLOCKED, resolved: true })}
      }
    })()

    return () => void (cancelled = true)
  }, [])

  return status
}
