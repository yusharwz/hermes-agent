import QRCode from 'qrcode'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Loader2 } from '@/lib/icons'

/**
 * Linking and unlinking WhatsApp, without leaving the application.
 *
 * The card used to say "start the WhatsApp bridge that ships with Atlas, scan
 * the QR code on first run" — a terminal, a command, and a QR read out of a
 * log file. Every step already existed as an HTTP endpoint; this is the
 * interface that was missing.
 *
 * THE STATES THAT MATTER
 * ======================
 * Pairing is not one flow. It is a link that can also be broken, and broken
 * from the other end, by a phone this application never hears from. The first
 * version modelled only "not paired yet" and "paired", which left a customer
 * who unlinked from their phone with an app insisting it was connected, an
 * expired-session error, and no way to get a new code.
 *
 *   checking   asking the backend; offering nothing yet, because offering the
 *              wrong thing for a moment is how the last version misled people
 *   idle       nothing linked — the numbers field and a QR
 *   pairing    bridge running, code on screen, rotating every few seconds
 *   scanned    phone accepted it, not yet saved
 *   linked     credentials on disk — offer to disconnect
 *   expired    the attempt timed out — offer another code, not a dead end
 *
 * `linked` is re-read from the backend on a timer rather than remembered here.
 * The phone can end the link at any moment, and the only honest source is the
 * session on disk.
 */

type PairingStatus = {
  pairing_id: string
  status: string
  qr_payload: string | null
  expires_at: number | null
  /** Comma-separated, not a list: the backend normalises with str(). */
  allowed_users: string | null
  account_name: string | null
  account_phone: string | null
  error: string | null
}

type LinkState = {
  linked: boolean
  account_name: string | null
  account_phone: string | null
}

const POLL_MS = 1200

/** How often the standing link is re-checked while this card is open. */
const LINK_POLL_MS = 5000

export function WhatsAppPairing() {
  const [allowed, setAllowed] = useState('')
  const [link, setLink] = useState<LinkState | null>(null)
  const [session, setSession] = useState<PairingStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [qrSvg, setQrSvg] = useState<string | null>(null)
  const cancelled = useRef(false)

  useEffect(() => () => void (cancelled.current = true), [])

  const readLink = useCallback(async () => {
    try {
      const next = await window.hermesDesktop.api<LinkState>({ path: '/api/messaging/whatsapp/link' })

      if (!cancelled.current) {setLink(next)}
    } catch {
      // An older backend has no such route. "Not linked" still offers a way
      // forward, where rendering nothing would strand the customer.
      if (!cancelled.current) {setLink({ account_name: null, account_phone: null, linked: false })}
    }
  }, [])

  // ── Follow the standing link, which the phone can end at any time ───────
  useEffect(() => {
    void readLink()
    const timer = setInterval(() => void readLink(), LINK_POLL_MS)

    return () => clearInterval(timer)
  }, [readLink])

  // ── Draw the QR whenever a new payload arrives ──────────────────────────
  useEffect(() => {
    const payload = session?.qr_payload

    if (!payload) {
      setQrSvg(null)

      return
    }

    let stale = false
    void QRCode.toString(payload, { errorCorrectionLevel: 'M', margin: 1, type: 'svg', width: 240 })
      .then(svg => {
        if (!stale) {setQrSvg(svg)}
      })
      .catch(() => {
        if (!stale) {setQrSvg(null)}
      })

    return () => void (stale = true)
  }, [session?.qr_payload])

  // ── Follow a pairing attempt until it settles ───────────────────────────
  useEffect(() => {
    const id = session?.pairing_id

    if (!id || session?.status === 'connected' || session?.status === 'failed') {return}

    const timer = setInterval(() => {
      void window.hermesDesktop
        .api<PairingStatus>({ path: `/api/messaging/whatsapp/onboarding/${id}` })
        .then(next => {
          if (cancelled.current) {return}
          setSession(next)

          if (next.status === 'connected') {void readLink()}
        })
        .catch(() => {
          // 404 or 410: the attempt timed out on the backend. That is a reason
          // to offer another code, not to leave an error and no way forward.
          if (!cancelled.current) {
            setSession(null)
            setExpired(true)
          }
        })
    }, POLL_MS)

    return () => clearInterval(timer)
  }, [session?.pairing_id, session?.status, readLink])

  const start = async () => {
    setBusy(true)
    setFailure(null)
    setExpired(false)

    try {
      const started = await window.hermesDesktop.api<PairingStatus>({
        body: {
          // A comma-separated string, not an array: the backend normalises it
          // with str(value or ""), so a list arrives as its Python repr.
          allowed_users: allowed,
          // 'bot' or 'self-chat' are the only values accepted.
          mode: 'bot'
        },
        method: 'POST',
        path: '/api/messaging/whatsapp/onboarding/start'
      })

      setSession(started)
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Tidak bisa memulai pemindaian.')
    } finally {
      setBusy(false)
    }
  }

  const finish = async () => {
    if (!session) {return}
    setBusy(true)

    try {
      await window.hermesDesktop.api({
        body: { allowed_users: session.allowed_users ?? allowed },
        method: 'POST',
        path: `/api/messaging/whatsapp/onboarding/${session.pairing_id}/apply`
      })
      setSession(null)
      await readLink()
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Tidak bisa menyimpan sambungan.')
    } finally {
      setBusy(false)
    }
  }

  const cancel = async () => {
    const id = session?.pairing_id
    setSession(null)
    setQrSvg(null)

    if (!id) {return}

    try {
      await window.hermesDesktop.api({ method: 'DELETE', path: `/api/messaging/whatsapp/onboarding/${id}` })
    } catch {
      // It times out on its own; a failed cancel is not worth an error.
    }
  }

  const disconnect = async () => {
    setBusy(true)
    setFailure(null)

    try {
      await window.hermesDesktop.api({ method: 'DELETE', path: '/api/messaging/whatsapp/link' })
      setSession(null)
      setQrSvg(null)
      await readLink()
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Tidak bisa memutuskan sambungan.')
    } finally {
      setBusy(false)
    }
  }

  const card = 'mt-4 rounded-lg border border-border/70 bg-muted/20 p-4'

  // Still asking. Rendering "not connected" first would flash the wrong offer
  // at somebody who is in fact connected — the same mistake, one layer down.
  if (link === null) {
    return (
      <div className={card}>
        <h4 className="text-sm font-medium">Sambungkan WhatsApp</h4>
        <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          Memeriksa status sambungan…
        </p>
      </div>
    )
  }

  // ── Linked ─────────────────────────────────────────────────────────────
  if (link.linked && !session) {
    return (
      <div className={card}>
        <h4 className="text-sm font-medium">WhatsApp tersambung</h4>
        <p className="mt-1 text-sm text-emerald-600 dark:text-emerald-400">
          {link.account_name ?? 'Akun tertaut'}
          {link.account_phone ? ` · ${link.account_phone}` : ''}
        </p>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          Kalau Anda memutuskan tautan dari ponsel, status di sini ikut berubah dalam beberapa detik
          dan Anda bisa memindai kode baru.
        </p>

        <Button className="mt-3" disabled={busy} onClick={() => void disconnect()} size="sm" variant="outline">
          {busy ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : null}
          Putuskan sambungan
        </Button>

        {failure ? <p className="mt-3 text-xs text-destructive">{failure}</p> : null}
      </div>
    )
  }

  // ── Scanning ───────────────────────────────────────────────────────────
  if (session && session.status !== 'connected') {
    return (
      <div className={card}>
        <h4 className="text-sm font-medium">Pindai kode ini</h4>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          Buka WhatsApp di ponsel → <strong>Perangkat tertaut</strong> →{' '}
          <strong>Tautkan perangkat</strong>.
        </p>

        <div className="mt-3 flex h-[248px] w-[248px] items-center justify-center rounded-lg bg-white p-1">
          {qrSvg ? (
            // Produced locally by the qrcode library from a short string —
            // never from anything a remote party wrote.
            <div className="[&>svg]:h-full [&>svg]:w-full" dangerouslySetInnerHTML={{ __html: qrSvg }} />
          ) : (
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          )}
        </div>

        <p className="mt-2 text-xs text-muted-foreground">
          {session.qr_payload ? 'Kode berganti sendiri setiap beberapa detik.' : 'Menyiapkan bridge…'}
        </p>

        <Button className="mt-3" onClick={() => void cancel()} size="sm" variant="outline">
          Batal
        </Button>

        {session.error ? <p className="mt-3 text-xs text-destructive">{session.error}</p> : null}
      </div>
    )
  }

  // ── Scanned, not yet saved ─────────────────────────────────────────────
  if (session?.status === 'connected') {
    return (
      <div className={card}>
        <h4 className="text-sm font-medium">Terpindai</h4>
        <p className="mt-1 text-sm text-emerald-600 dark:text-emerald-400">
          {session.account_name ?? 'Akun tertaut'}
          {session.account_phone ? ` · ${session.account_phone}` : ''}
        </p>

        <div className="mt-3 flex gap-2">
          <Button disabled={busy} onClick={() => void finish()} size="sm">
            {busy ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : null}
            Simpan dan aktifkan
          </Button>
          <Button disabled={busy} onClick={() => void cancel()} size="sm" variant="outline">
            Batal
          </Button>
        </div>

        {failure ? <p className="mt-3 text-xs text-destructive">{failure}</p> : null}
      </div>
    )
  }

  // ── Nothing linked ─────────────────────────────────────────────────────
  return (
    <div className={card}>
      <h4 className="text-sm font-medium">Sambungkan WhatsApp</h4>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        Isi nomor yang boleh memakai asisten ini, lalu pindai kodenya. Semuanya di sini — tidak
        perlu membuka terminal.
      </p>

      <label className="mt-3 block text-xs font-medium" htmlFor="wa-allowed">
        Nomor yang diizinkan
      </label>
      <input
        className="mt-1 w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-sm outline-none focus:border-primary"
        id="wa-allowed"
        onChange={event => setAllowed(event.target.value)}
        placeholder="6281234567890, 6289876543210"
        spellCheck={false}
        value={allowed}
      />
      <p className="mt-1 text-[11px] text-muted-foreground">
        Pisahkan dengan koma. Kosongkan bila hanya Anda sendiri yang memakainya.
      </p>

      <Button className="mt-3" disabled={busy} onClick={() => void start()} size="sm">
        {busy ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : null}
        {expired ? 'Tampilkan kode QR lagi' : 'Tampilkan kode QR'}
      </Button>

      {expired ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Kode sebelumnya kedaluwarsa sebelum sempat dipindai.
        </p>
      ) : null}

      {failure ? <p className="mt-3 text-xs text-destructive">{failure}</p> : null}
    </div>
  )
}
