/**
 * One update, watched from one place.
 *
 * This state used to live in `useUpdateRunner()`, a hook inside the About tab.
 * Everything followed from that: switching tabs unmounted it, so the progress
 * bar vanished and the button came back; pressing it POSTed a second update
 * and the backend answered 409 ("Pembaruan sedang berjalan"), which is what a
 * customer sees as "clicking update throws an error". Reopening Settings, or
 * the app, was the same story.
 *
 * The fix is not a bigger hook. The authority on whether an update is running
 * is the backend — it now writes progress to `~/.atlas/update-state.json` and
 * runs the work in a detached process, so the answer survives this window
 * closing. What belongs here is a single poller that asks, and atoms every
 * surface can read without owning the polling.
 *
 * @see atlas_cli/ninegate_update.py — where the state actually lives
 */

import { atom } from 'nanostores'

export type NineGateUpdateInfo = {
  /** Version the installer recorded. Null when this install predates the marker. */
  current: null | string
  /** Version the gateway is serving, or null when it could not be reached. */
  latest: null | string
  updateAvailable: boolean
  /**
   * True when the desktop application itself changed, not only the agent.
   *
   * Worth surfacing separately: replacing the running application is the half
   * that needs a restart, and a customer told that up front is not surprised
   * by it halfway through.
   */
  desktopChanged: boolean
  builtAt: null | string
  /** Set when the check could not complete. The UI says so rather than guessing. */
  error: null | string
  /** False until the first answer arrives. */
  resolved: boolean
}

export type UpdateProgress = {
  running: boolean
  stage: string
  percent: number
  message: string
  done: boolean
  ok: boolean
  error: null | string
  restartRequired: boolean
  /** Windows only: the installer to launch, because a running .exe cannot be replaced. */
  installerPath: null | string
  version: null | string
}

const UNKNOWN: NineGateUpdateInfo = {
  builtAt: null,
  current: null,
  desktopChanged: false,
  error: null,
  latest: null,
  resolved: false,
  updateAvailable: false
}

export const $updateInfo = atom<NineGateUpdateInfo>(UNKNOWN)
export const $updateProgress = atom<null | UpdateProgress>(null)
export const $updateChecking = atom<boolean>(false)
export const $updateStarting = atom<boolean>(false)

/**
 * Set when an update finishes while this window is open, and only then.
 *
 * Deliberately not driven by "the last update succeeded and wanted a restart":
 * that is still true the next time the app launches, and by then the launch
 * has already loaded the new version — a modal asking to restart into what is
 * running is noise that teaches people to dismiss modals.
 */
export const $restartPrompt = atom<null | { installerPath: null | string; version: null | string }>(null)

export function dismissRestartPrompt(): void {
  $restartPrompt.set(null)
}

type InfoPayload = {
  current?: null | string
  latest?: null | string
  update_available?: boolean
  desktop_changed?: boolean
  built_at?: null | string
  error?: null | string
}

type ProgressPayload = {
  running?: boolean
  stage?: string
  percent?: number
  message?: string
  done?: boolean
  ok?: boolean
  error?: null | string
  restart_required?: boolean
  installer_path?: null | string
  version?: null | string
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

export async function refreshUpdateInfo(): Promise<void> {
  $updateChecking.set(true)

  try {
    const payload = await window.atlasDesktop.api<InfoPayload>({ path: '/api/ninegate/update' })

    $updateInfo.set({
      builtAt: payload.built_at ?? null,
      current: payload.current ?? null,
      desktopChanged: Boolean(payload.desktop_changed),
      error: payload.error ?? null,
      latest: payload.latest ?? null,
      resolved: true,
      updateAvailable: Boolean(payload.update_available)
    })
  } catch {
    // An older backend has no such endpoint. Reporting "no update" would be a
    // claim we cannot support, so this is an error the card can show.
    $updateInfo.set({ ...UNKNOWN, error: 'tidak bisa memeriksa pembaruan', resolved: true })
  } finally {
    $updateChecking.set(false)
  }
}

async function fetchProgress(): Promise<UpdateProgress> {
  return toProgress(await window.atlasDesktop.api<ProgressPayload>({ path: '/api/ninegate/update/progress' }))
}

/**
 * Folds a fresh reading in, and notices the moment an update finished.
 *
 * `seed` is the first read of a session. A finished-and-ok state found there
 * describes an update that ended before this window existed — do not celebrate
 * it, and do not ask for a restart the launch already performed.
 */
function apply(next: UpdateProgress, { seed = false } = {}): void {
  const previous = $updateProgress.get()
  $updateProgress.set(next)

  const justFinished = !seed && Boolean(previous?.running) && !next.running && next.done

  if (!justFinished) {
    return
  }

  // The installed version changed under us: re-ask, so the card stops
  // offering an update that has already been applied.
  void refreshUpdateInfo()

  if (next.ok && next.restartRequired) {
    $restartPrompt.set({ installerPath: next.installerPath, version: next.version })
  }
}

export async function startNineGateUpdate(): Promise<void> {
  $updateStarting.set(true)

  try {
    await window.atlasDesktop.api({ method: 'POST', path: '/api/ninegate/update' })
    apply(await fetchProgress())
  } catch (error) {
    // Includes the 409 from a second press. Rare now that the button knows an
    // update is running, but a second window can still race this one.
    $updateProgress.set({
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
    $updateStarting.set(false)
  }
}

/** Fast while something is happening, slow while nothing is. */
const RUNNING_INTERVAL_MS = 1_000
const IDLE_INTERVAL_MS = 15_000

let watching = false
let timer: null | ReturnType<typeof setTimeout> = null

/**
 * Starts the one poller, at the app shell rather than on a settings tab.
 *
 * Idempotent, and it keeps polling slowly when idle: a second window — or the
 * `atlas` CLI — can start an update this window did not, and finding out about
 * it 15 seconds later is the difference between a visible progress bar and a
 * button that answers 409.
 */
export function watchNineGateUpdate(): void {
  if (watching || typeof window === 'undefined') {
    return
  }

  watching = true
  let seeded = false

  const tick = async (): Promise<void> => {
    try {
      apply(await fetchProgress(), { seed: !seeded })
      seeded = true
    } catch {
      // The backend restarts as part of its own update, and the app's backend
      // is a child that comes and goes. A failed poll says nothing about the
      // update, so the last known state stands rather than being cleared.
    }

    if (!watching) {
      return
    }

    timer = setTimeout(() => void tick(), $updateProgress.get()?.running ? RUNNING_INTERVAL_MS : IDLE_INTERVAL_MS)
  }

  void tick()
  void refreshUpdateInfo()
}

export function stopWatchingNineGateUpdate(): void {
  watching = false

  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

/** Test-only: forget that a poller was ever started. */
export function __resetNineGateUpdateWatch(): void {
  stopWatchingNineGateUpdate()
  $updateInfo.set(UNKNOWN)
  $updateProgress.set(null)
  $restartPrompt.set(null)
  $updateChecking.set(false)
  $updateStarting.set(false)
}
