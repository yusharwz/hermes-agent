import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { triggerHaptic } from '@/lib/haptics'
import { Globe, Loader2 } from '@/lib/icons'
import { fetchNineGateStatus } from '@/lib/ninegate'
import { notifyError } from '@/store/notifications'

/**
 * The first thing a fresh Atlas install shows.
 *
 * A locked build with no subscription key cannot answer anything, and the
 * failure it produces without this is the worst kind: the app opens, looks
 * completely normal, accepts a message, and then returns an authentication
 * error from a gateway the customer has never heard of. Asking up front turns
 * that into a thirty-second paste.
 *
 * It deliberately does NOT reuse the provider onboarding flow next door. That
 * one asks which provider you would like and offers to sign you into several —
 * questions a locked build has already answered, and offering them would
 * advertise choices that do not exist here.
 *
 * Blocking rather than dismissible, because there is nothing behind it to use.
 * The one way past is a key that the gateway has confirmed.
 */
export function NineGateLoginOverlay({ enabled }: { enabled: boolean }) {
  const [needed, setNeeded] = useState(false)
  const [gateway, setGateway] = useState('')
  const [entry, setEntry] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!enabled) {return}
    let cancelled = false

    void (async () => {
      try {
        const status = await fetchNineGateStatus()

        if (cancelled) {return}
        // Only a LOCKED build with no key. An unlocked developer build has its
        // own onboarding, and a locked one that is already signed in has
        // nothing to ask.
        setNeeded(status.locked && !status.keyPresent)
        setGateway(status.gateway)
      } catch {
        // An older backend has no /api/ninegate. Nothing to gate on.
      }
    })()

    return () => void (cancelled = true)
  }, [enabled])

  const submit = async () => {
    const key = entry.trim()

    if (!key || busy) {return}

    setBusy(true)

    try {
      await window.hermesDesktop.api({
        body: { api_key: key },
        method: 'POST',
        path: '/api/ninegate/login'
      })
      triggerHaptic('success')
      setNeeded(false)
    } catch (err) {
      notifyError(err, 'API key ditolak.')
    } finally {
      setBusy(false)
    }
  }

  if (!needed) {return null}

  return (
    <div className="fixed inset-0 z-100 flex items-center justify-center bg-(--ui-bg-overlay) p-6 backdrop-blur-sm">
      <div className="flex w-full max-w-md flex-col gap-4 rounded-xl border border-(--ui-border) bg-(--ui-bg-elevated) p-6 shadow-2xl">
        <div className="flex items-center gap-2">
          <Globe className="size-5" />
          <h2 className="text-base font-semibold">Masuk ke Atlas</h2>
        </div>

        <p className="text-sm text-(--ui-text-secondary)">
          Tempelkan API key dari portal NineGate Anda. Atlas memakai key ini untuk semua
          model, dan pemakaiannya dihitung ke langganan Anda.
        </p>

        <Input
          autoComplete="off"
          autoFocus
          onChange={event => setEntry(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') {void submit()}
          }}
          placeholder="ng_live_…"
          spellCheck={false}
          // Visible on purpose: a mistyped or truncated paste is the single
          // most common failure here, and hiding it removes the only way to
          // catch that before submitting.
          type="text"
          value={entry}
        />

        <Button disabled={!entry.trim() || busy} onClick={() => void submit()}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : null}
          Masuk
        </Button>

        {gateway ? (
          <p className="text-xs text-(--ui-text-tertiary)">
            Gateway: <span className="tabular-nums">{gateway}</span>
          </p>
        ) : null}
      </div>
    </div>
  )
}
