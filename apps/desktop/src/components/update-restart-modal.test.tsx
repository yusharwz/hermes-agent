/**
 * The completion notice a customer actually sees.
 *
 * An update runs detached and finishes when it finishes — routinely after the
 * customer has gone back to a chat. A "done" line on the About tab is a line
 * nobody reads, and the visible consequence was an update that looked like it
 * had never run, so it got run again.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $restartPrompt } from '@/store/ninegate-update'

import { UpdateRestartModal } from './update-restart-modal'

const restartApp = vi.fn().mockResolvedValue({ ok: true })

beforeEach(() => {
  $restartPrompt.set(null)
  restartApp.mockClear()
  Object.defineProperty(window, 'atlasDesktop', { configurable: true, value: { restartApp } })
})

afterEach(cleanup)

describe('UpdateRestartModal', () => {
  it('stays out of the way until an update finishes', () => {
    render(<UpdateRestartModal />)

    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('names the version and offers both answers', () => {
    $restartPrompt.set({ installerPath: null, version: '7bfe6e8' })
    render(<UpdateRestartModal />)

    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(screen.getByText(/7bfe6e8/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Mulai ulang sekarang/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Nanti saja/ })).toBeTruthy()
  })

  it('restarts on request', () => {
    $restartPrompt.set({ installerPath: null, version: '7bfe6e8' })
    render(<UpdateRestartModal />)

    fireEvent.click(screen.getByRole('button', { name: /Mulai ulang sekarang/ }))

    expect(restartApp).toHaveBeenCalledWith(null)
  })

  it('hands over to the Windows installer instead of relaunching', () => {
    // A running .exe cannot be replaced, so the update left an installer and
    // the restart is a handover to it — different button, different promise.
    $restartPrompt.set({ installerPath: 'C:\\Users\\y\\.atlas\\bin\\Atlas-Setup.exe', version: '7bfe6e8' })
    render(<UpdateRestartModal />)

    const button = screen.getByRole('button', { name: /Tutup & pasang/ })
    fireEvent.click(button)

    expect(restartApp).toHaveBeenCalledWith('C:\\Users\\y\\.atlas\\bin\\Atlas-Setup.exe')
  })

  it('takes "later" for an answer', () => {
    $restartPrompt.set({ installerPath: null, version: '7bfe6e8' })
    render(<UpdateRestartModal />)

    fireEvent.click(screen.getByRole('button', { name: /Nanti saja/ }))

    // Nothing is restarted, and the modal does not come back: the new version
    // is already on disk and loads on the next launch either way.
    expect(restartApp).not.toHaveBeenCalled()
    expect($restartPrompt.get()).toBeNull()
  })
})
