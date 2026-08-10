import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Loader2 } from '@/lib/icons'
import { cn } from '@/lib/utils'

/**
 * Pairing WhatsApp without leaving the application.
 *
 * The card used to say "start the WhatsApp bridge that ships with Hermes, scan
 * the QR code on first run" — which meant a terminal, a command, and reading a
 * QR code out of a log file. Every step of that already existed as an HTTP
 * endpoint on the backend; nothing here is new machinery, it is the interface
 * that was missing:
 *
 *   POST   …/onboarding/start        spawns the bridge in pairing mode
 *   GET    …/onboarding/{id}         status + the QR payload, polled
 *   POST   …/onboarding/{id}/apply   saves the allow-list and restarts the gateway
 *   DELETE …/onboarding/{id}         cancels and kills the bridge
 *
 * The QR is drawn here rather than sent as an image because the payload is a
 * short string that rotates every twenty seconds or so: sending it as text and
 * rendering locally means a refresh costs nothing, and the code on screen is
 * never a stale picture of one that has already expired.
 */

type PairingStatus = {
  pairing_id: string
  status: string
  qr_payload: string | null
  expires_at: number | null
  allowed_users: string[] | null
  account_name: string | null
  account_phone: string | null
  error: string | null
}

const POLL_MS = 1200

export function WhatsAppPairing() {
  const [allowed, setAllowed] = useState('')
  const [session, setSession] = useState<PairingStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [qrSvg, setQrSvg] = useState<string | null>(null)
  const cancelled = useRef(false)

  useEffect(() => () => void (cancelled.current = true), [])

  // ── Draw the QR whenever a new payload arrives ─────────────────────────
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

  // ── Follow the pairing until it settles ────────────────────────────────
  useEffect(() => {
    const id = session?.pairing_id

    if (!id || session?.status === 'connected' || session?.status === 'failed') {return}

    const timer = setInterval(() => {
      void window.hermesDesktop
        .api<PairingStatus>({ path: `/api/messaging/whatsapp/onboarding/${id}` })
        .then(next => {
          if (!cancelled.current) {setSession(next)}
        })
        .catch(() => {
          // A 404 or 410 means the session expired on the backend. Stopping
          // the poll and saying so beats spinning against a dead id.
          if (!cancelled.current) {
            setFailure('Sesi pemindaian berakhir. Mulai lagi untuk mendapatkan kode baru.')
            setSession(null)
          }
        })
    }, POLL_MS)

    return () => clearInterval(timer)
  }, [session?.pairing_id, session?.status])

  const start = async () => {
    setBusy(true)
    setFailure(null)

    try {
      const started = await window.hermesDesktop.api<PairingStatus>({
        body: {
          // A comma-separated string, not an array: the backend normalises it
          // with str(value or ""), so a list arrives as its Python repr.
          allowed_users: allowed,
          // 'bot' or 'self-chat' are the only values accepted; anything else
          // is a 400. 'qr' describes how you pair, not what you pair as.
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
        body: { allowed_users: (session.allowed_users ?? []).join(',') },
        method: 'POST',
        path: `/api/messaging/whatsapp/onboarding/${session.pairing_id}/apply`
      })
      setSession({ ...session, status: 'applied' })
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Tidak bisa menyimpan sambungan.')
    } finally {
      setBusy(false)
    }
  }

  const cancel = async () => {
    if (!session) {return}
    const id = session.pairing_id
    setSession(null)
    setQrSvg(null)

    try {
      await window.hermesDesktop.api({ method: 'DELETE', path: `/api/messaging/whatsapp/onboarding/${id}` })
    } catch {
      // The session times out on its own; a failed cancel is not worth an error.
    }
  }

  const connected = session?.status === 'connected' || session?.status === 'applied'

  return (
    <div className="mt-4 rounded-lg border border-border/70 bg-muted/20 p-4">
      <h4 className="text-sm font-medium">Sambungkan WhatsApp</h4>

      {!session ? (
        <>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Isi nomor yang boleh memakai asisten ini, lalu pindai kodenya. Semuanya di sini —
            tidak perlu membuka terminal.
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
            Tampilkan kode QR
          </Button>
        </>
      ) : connected ? (
        <>
          <p className="mt-1 text-sm text-emerald-600 dark:text-emerald-400">
            Tersambung{session.account_name ? ` sebagai ${session.account_name}` : ''}
            {session.account_phone ? ` (${session.account_phone})` : ''}.
          </p>
          {session.status === 'applied' ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Tersimpan. WhatsApp aktif setelah gateway selesai dimulai ulang.
            </p>
          ) : (
            <div className="mt-3 flex gap-2">
              <Button disabled={busy} onClick={() => void finish()} size="sm">
                {busy ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : null}
                Simpan dan aktifkan
              </Button>
              <Button disabled={busy} onClick={() => void cancel()} size="sm" variant="outline">
                Batal
              </Button>
            </div>
          )}
        </>
      ) : (
        <>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Buka WhatsApp di ponsel → <strong>Perangkat tertaut</strong> → <strong>Tautkan perangkat</strong>,
            lalu pindai kode ini.
          </p>

          <div
            className={cn(
              'mt-3 flex h-[248px] w-[248px] items-center justify-center rounded-lg bg-white p-1',
              !qrSvg && 'animate-pulse'
            )}
          >
            {qrSvg ? (
              // The SVG is produced locally by the qrcode library from a short
              // string, never from anything a remote party wrote.
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
        </>
      )}

      {failure ? <p className="mt-3 text-xs text-destructive">{failure}</p> : null}
      {session?.error ? <p className="mt-3 text-xs text-destructive">{session.error}</p> : null}
    </div>
  )
}
