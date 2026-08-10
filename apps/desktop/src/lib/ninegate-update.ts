import { useEffect, useState } from 'react'

/**
 * Whether a newer Atlas is published for this subscription.
 *
 * The upstream updater talks to GitHub. On a locked build that is a private
 * repository it cannot reach, and if it could, applying the result would be a
 * `git pull` over an installation that was never a checkout — so the About tab
 * shipped with no update button at all. The gateway publishes release metadata
 * now, and this is what reads it.
 */

export type NineGateUpdate = {
  /** False on an unlocked build; the upstream updater owns that case. */
  locked: boolean
  /** Version the installer recorded. Null when this install predates the marker. */
  current: string | null
  /** Version the gateway is serving, or null when it could not be reached. */
  latest: string | null
  updateAvailable: boolean
  /**
   * True when the desktop application itself changed, not only the agent.
   *
   * Worth surfacing separately: replacing the running application is the half
   * that needs a restart, and a customer who is told that up front is not
   * surprised by it halfway through.
   */
  desktopChanged: boolean
  builtAt: string | null
  /** Set when the check could not complete. The UI says so rather than guessing. */
  error: string | null
  /** False until the first answer arrives. */
  resolved: boolean
}

const UNKNOWN: NineGateUpdate = {
  builtAt: null,
  current: null,
  desktopChanged: false,
  error: null,
  latest: null,
  locked: false,
  resolved: false,
  updateAvailable: false
}

type Payload = {
  locked?: boolean
  current?: string | null
  latest?: string | null
  update_available?: boolean
  desktop_changed?: boolean
  built_at?: string | null
  error?: string | null
}

export async function fetchNineGateUpdate(): Promise<NineGateUpdate> {
  const payload = await window.hermesDesktop.api<Payload>({ path: '/api/ninegate/update' })

  return {
    builtAt: payload.built_at ?? null,
    current: payload.current ?? null,
    desktopChanged: Boolean(payload.desktop_changed),
    error: payload.error ?? null,
    latest: payload.latest ?? null,
    locked: Boolean(payload.locked),
    resolved: true,
    updateAvailable: Boolean(payload.update_available)
  }
}

export function useNineGateUpdate(): {
  state: NineGateUpdate
  checking: boolean
  check: () => Promise<void>
} {
  const [state, setState] = useState<NineGateUpdate>(UNKNOWN)
  const [checking, setChecking] = useState(false)

  const check = async () => {
    setChecking(true)

    try {
      setState(await fetchNineGateUpdate())
    } catch {
      // An older backend has no such endpoint. Reporting "no update" would be
      // a claim we cannot support, so this is an error the card can show.
      setState({ ...UNKNOWN, error: 'tidak bisa memeriksa pembaruan', locked: true, resolved: true })
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        const next = await fetchNineGateUpdate()

        if (!cancelled) {setState(next)}
      } catch {
        if (!cancelled) {
          setState({ ...UNKNOWN, error: 'tidak bisa memeriksa pembaruan', locked: true, resolved: true })
        }
      }
    })()

    return () => void (cancelled = true)
  }, [])

  return { check, checking, state }
}

export type UpdateProgress = {
  running: boolean
  stage: string
  percent: number
  message: string
  done: boolean
  ok: boolean
  error: string | null
  restartRequired: boolean
  /** Windows only: the installer to launch, because a running .exe cannot be replaced. */
  installerPath: string | null
  version: string | null
}

type ProgressPayload = {
  running?: boolean
  stage?: string
  percent?: number
  message?: string
  done?: boolean
  ok?: boolean
  error?: string | null
  restart_required?: boolean
  installer_path?: string | null
  version?: string | null
}

function toProgress(payload: ProgressPayload): UpdateProgress {
  return {
    done: Boolean(payload.done),
    error: payload.error ?? null,
    installerPath: payload.installer_path ?? null,
    message: payload.message ?? '',
    ok: Boolean(payload.ok),
    percent: Math.max(0, Math.min(100, Number(payload.percent ?? 0))),
    restartRequired: Boolean(payload.restart_required),
    running: Boolean(payload.running),
    stage: payload.stage ?? '',
    version: payload.version ?? null
  }
}

export async function startNineGateUpdate(): Promise<void> {
  await window.hermesDesktop.api({ method: 'POST', path: '/api/ninegate/update' })
}

export async function fetchUpdateProgress(): Promise<UpdateProgress> {
  return toProgress(await window.hermesDesktop.api<ProgressPayload>({ path: '/api/ninegate/update/progress' }))
}

/**
 * Drives one update and follows it to the end.
 *
 * Polls rather than streams because the interesting failure is the backend
 * going away mid-update — a socket that closes tells you nothing about whether
 * the swap happened, while the next poll reads the job's own record of it.
 */
export function useUpdateRunner(): {
  progress: UpdateProgress | null
  start: () => Promise<void>
  starting: boolean
} {
  const [progress, setProgress] = useState<UpdateProgress | null>(null)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    if (!progress?.running) {return}

    const timer = setInterval(() => {
      void fetchUpdateProgress()
        .then(setProgress)
        .catch(() => {
          // The backend restarts as part of its own update. A failed poll is
          // expected there, so it is ignored rather than reported as a fault.
        })
    }, 1000)

    return () => clearInterval(timer)
  }, [progress?.running])

  const start = async () => {
    setStarting(true)

    try {
      await startNineGateUpdate()
      setProgress(await fetchUpdateProgress())
    } catch (error) {
      setProgress({
        done: true,
        error: error instanceof Error ? error.message : 'Pembaruan tidak bisa dimulai.',
        installerPath: null,
        message: '',
        ok: false,
        percent: 0,
        restartRequired: false,
        running: false,
        stage: '',
        version: null
      })
    } finally {
      setStarting(false)
    }
  }

  return { progress, start, starting }
}
