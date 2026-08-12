/**
 * An update in progress stays in progress, whatever the UI does.
 *
 * The three faults these cover, all of them one design mistake — the state
 * lived in a hook inside the About tab:
 *
 *   1. Switching tabs, or closing Settings, unmounted the hook. The progress
 *      bar vanished and the "Perbarui sekarang" button came back. Pressing it
 *      POSTed a second update, and the backend answered 409 — reported as
 *      "clicking update throws an error".
 *   2. Nothing refreshed the version when an update finished, so the button
 *      stayed live and the same update could be run again.
 *   3. Nothing announced completion anywhere but that tab, which is rarely
 *      where the customer is by the time a download finishes.
 *
 * The store below is module-level and the poller runs at the app shell, so
 * "unmounting a component" is modelled here as what it now is: nothing at all.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $restartPrompt,
  $updateInfo,
  $updateProgress,
  __resetNineGateUpdateWatch,
  startNineGateUpdate,
  stopWatchingNineGateUpdate,
  watchNineGateUpdate
} from './ninegate-update'

const RUNNING = {
  running: true,
  stage: 'download',
  percent: 40,
  message: 'Mengunduh Atlas…',
  done: false,
  ok: false,
  error: null,
  restart_required: false,
  installer_path: null,
  version: '7bfe6e8'
}

const FINISHED = {
  ...RUNNING,
  running: false,
  percent: 100,
  stage: 'finish',
  message: 'Atlas diperbarui ke versi 7bfe6e8.',
  done: true,
  ok: true,
  restart_required: true
}

const INFO = { current: '5d81a6c', latest: '7bfe6e8', update_available: true, desktop_changed: true }
const INFO_CURRENT = { current: '7bfe6e8', latest: '7bfe6e8', update_available: false, desktop_changed: false }

let api: ReturnType<typeof vi.fn>

/** Answers each endpoint from a queue, so a test can script a sequence. */
function serve(progress: unknown[], info: unknown[] = [INFO]) {
  api = vi.fn(async ({ path, method }: { path: string; method?: string }) => {
    if (path === '/api/ninegate/update/progress') {
      return progress.length > 1 ? progress.shift() : progress[0]
    }

    if (path === '/api/ninegate/update') {
      return method === 'POST' ? { started: true } : info.length > 1 ? info.shift() : info[0]
    }

    throw new Error(`unexpected path ${path}`)
  })

  Object.defineProperty(window, 'hermesDesktop', { configurable: true, value: { api } })
}

const settle = async (ms = 0) => {
  await vi.advanceTimersByTimeAsync(ms)
}

beforeEach(() => {
  __resetNineGateUpdateWatch()
  vi.useFakeTimers()
})

afterEach(() => {
  stopWatchingNineGateUpdate()
  vi.useRealTimers()
})

describe('the progress belongs to the app, not to a tab', () => {
  it('keeps reporting while nothing is mounted', async () => {
    serve([{ ...RUNNING, percent: 40 }, { ...RUNNING, percent: 70 }, { ...RUNNING, percent: 95 }])

    watchNineGateUpdate()
    await settle()
    expect($updateProgress.get()?.percent).toBe(40)

    // No component was ever rendered here. This is the whole point: the
    // poller is not something a settings tab owns.
    await settle(1_000)
    expect($updateProgress.get()?.percent).toBe(70)

    await settle(1_000)
    expect($updateProgress.get()?.percent).toBe(95)
    expect($updateProgress.get()?.running).toBe(true)
  })

  it('picks up an update that was already running when the app opened', async () => {
    serve([RUNNING])

    watchNineGateUpdate()
    await settle()

    // The app was closed and reopened mid-update; the backend kept going.
    expect($updateProgress.get()?.running).toBe(true)
    expect($updateProgress.get()?.percent).toBe(40)
  })

  it('starts only one poller however often it is asked', async () => {
    serve([RUNNING])

    watchNineGateUpdate()
    watchNineGateUpdate()
    watchNineGateUpdate()
    await settle()

    const callsAfterFirstTick = api.mock.calls.filter(([arg]) => arg.path.endsWith('/progress')).length

    expect(callsAfterFirstTick).toBe(1)
  })

  it('keeps the last known state when a poll fails', async () => {
    serve([RUNNING])

    watchNineGateUpdate()
    await settle()
    expect($updateProgress.get()?.percent).toBe(40)

    // The backend is restarted BY the update it is reporting on, so a failed
    // poll is expected. Clearing here would blank the bar mid-update.
    api.mockRejectedValueOnce(new Error('ECONNREFUSED'))
    await settle(1_000)

    expect($updateProgress.get()?.percent).toBe(40)
    expect($updateProgress.get()?.running).toBe(true)
  })
})

describe('finishing', () => {
  it('re-asks the version and prompts for a restart', async () => {
    serve([RUNNING, FINISHED], [INFO, INFO_CURRENT])

    watchNineGateUpdate()
    await settle()
    expect($restartPrompt.get()).toBeNull()

    await settle(1_000)

    // The card must stop offering an update that has been applied.
    expect($updateInfo.get().updateAvailable).toBe(false)
    expect($updateInfo.get().current).toBe('7bfe6e8')

    // And the customer is told, wherever they are.
    expect($restartPrompt.get()).toEqual({ installerPath: null, version: '7bfe6e8' })
  })

  it('does not prompt for an update that finished before this window existed', async () => {
    // A completed update found on the FIRST read describes something that
    // ended while the app was closed — the launch already loaded the new
    // version, so asking to restart into it is noise.
    serve([FINISHED], [INFO_CURRENT])

    watchNineGateUpdate()
    await settle()

    expect($updateProgress.get()?.done).toBe(true)
    expect($restartPrompt.get()).toBeNull()
  })

  it('does not prompt when the update did not ask for a restart', async () => {
    serve([RUNNING, { ...FINISHED, restart_required: false }], [INFO, INFO_CURRENT])

    watchNineGateUpdate()
    await settle()
    await settle(1_000)

    expect($restartPrompt.get()).toBeNull()
    expect($updateInfo.get().updateAvailable).toBe(false)
  })

  it('carries the Windows installer path into the prompt', async () => {
    serve(
      [RUNNING, { ...FINISHED, installer_path: 'C:\\Users\\y\\.atlas\\bin\\Atlas-Setup.exe' }],
      [INFO, INFO_CURRENT]
    )

    watchNineGateUpdate()
    await settle()
    await settle(1_000)

    // A running .exe cannot be replaced, so the restart is a handover to this.
    expect($restartPrompt.get()?.installerPath).toBe('C:\\Users\\y\\.atlas\\bin\\Atlas-Setup.exe')
  })

  it('slows down once nothing is running', async () => {
    serve([FINISHED])

    watchNineGateUpdate()
    await settle()
    const afterSeed = api.mock.calls.length

    await settle(1_000)
    expect(api.mock.calls.length).toBe(afterSeed)

    await settle(15_000)
    expect(api.mock.calls.length).toBeGreaterThan(afterSeed)
  })
})

describe('starting one', () => {
  it('reports a refused start rather than looking idle', async () => {
    serve([{ ...RUNNING, running: false, done: false }])
    api.mockImplementation(async ({ method }: { method?: string }) => {
      if (method === 'POST') {
        throw new Error('HTTP 409: Pembaruan sedang berjalan.')
      }

      return RUNNING
    })

    await startNineGateUpdate()

    expect($updateProgress.get()?.done).toBe(true)
    expect($updateProgress.get()?.error).toContain('409')
  })
})
