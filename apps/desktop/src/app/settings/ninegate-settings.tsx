import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { triggerHaptic } from '@/lib/haptics'
import { Activity, Check, Globe, KeyRound, Loader2 } from '@/lib/icons'
import { fetchNineGateStatus, type NineGateStatus, type QuotaWindow } from '@/lib/ninegate'
import { notify, notifyError } from '@/store/notifications'

import { ListRow, SectionHeading, SettingsContent, SettingsSkeleton } from './primitives'

/**
 * The one account page a locked Atlas has.
 *
 * It replaces three pages that a NineGate build cannot honour — provider
 * accounts, provider API keys, custom endpoints — with the single thing that
 * is actually the customer's to change: which subscription this installation
 * runs on.
 *
 * The key is never shown in full, only ever the last few characters. There is
 * no "reveal" button, and that is a deliberate departure from how the provider
 * key pages behave. Those exist so you can check a key you typed; this one you
 * pasted from a portal that still has it, so revealing it would only put a
 * live credential on screen with nothing gained.
 */
export function NineGateSettings() {
  const [status, setStatus] = useState<NineGateStatus | null>(null)
  const [entry, setEntry] = useState('')
  const [busy, setBusy] = useState<'login' | 'logout' | null>(null)

  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        const next = await fetchNineGateStatus()
        if (!cancelled) setStatus(next)
      } catch (err) {
        if (!cancelled) notifyError(err, 'Gagal memuat status langganan.')
      }
    })()

    return () => void (cancelled = true)
  }, [])

  const signIn = async () => {
    const key = entry.trim()
    if (!key) return

    setBusy('login')
    try {
      // The backend checks the key against the gateway before saving it. A
      // truncated paste looks exactly like a working key until the next
      // message fails, by which point the old one is gone.
      const result = await window.hermesDesktop.api<{ ok: boolean; key_redacted: string }>({
        body: { api_key: key },
        method: 'POST',
        path: '/api/ninegate/login'
      })

      setStatus(current =>
        current ? { ...current, keyPresent: true, keyRedacted: result.key_redacted } : current
      )
      setEntry('')
      triggerHaptic('success')
      notify({ kind: 'success', message: 'API key tersimpan. Atlas siap dipakai.' })
    } catch (err) {
      notifyError(err, 'API key ditolak.')
    } finally {
      setBusy(null)
    }
  }

  const signOut = async () => {
    if (!window.confirm('Keluar akan menghapus API key dari perangkat ini. Lanjutkan?')) return

    setBusy('logout')
    try {
      await window.hermesDesktop.api({ method: 'POST', path: '/api/ninegate/logout' })
      setStatus(current => (current ? { ...current, keyPresent: false, keyRedacted: null } : current))
      notify({ message: 'API key dihapus dari perangkat ini.' })
    } catch (err) {
      notifyError(err, 'Gagal keluar.')
    } finally {
      setBusy(null)
    }
  }

  if (!status) return <SettingsSkeleton />

  return (
    <SettingsContent>
      <SectionHeading icon={Globe} title="Langganan NineGate" />

      {/* Shown rather than hidden: when something is wrong, the first useful
          question is "what is it talking to", and an answer on screen saves a
          round trip through support. */}
      <ListRow action={<span className="tabular-nums">{status.gateway || '—'}</span>} title="Gateway" />

      <ListRow
        action={
          status.keyPresent ? (
            <span className="flex items-center gap-1.5">
              <Check className="size-3.5" />
              {status.keyRedacted}
            </span>
          ) : (
            <span>Belum diisi</span>
          )
        }
        title="API key"
      />

      {/* Just the remaining allowance and when it comes back. The per-request
          history lives in the NineGate web portal; what someone opens this
          page to learn is whether they can keep working and, if not, for how
          long. */}
      {status.quota ? (
        <>
          <SectionHeading icon={Activity} title="Kuota" />
          {status.quota.five_hour ? <QuotaRow label="5 jam" window={status.quota.five_hour} /> : null}
          {status.quota.weekly ? <QuotaRow label="Mingguan" window={status.quota.weekly} /> : null}
        </>
      ) : null}

      <SectionHeading
        icon={KeyRound}
        title={status.keyPresent ? 'Ganti API key' : 'Masukkan API key'}
      />

      <p className="text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
        Ambil API key dari portal NineGate Anda. Semua model dilayani lewat gateway di atas
        dan pemakaian dihitung ke langganan pemilik key tersebut.
      </p>

      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          autoComplete="off"
          onChange={event => setEntry(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') void signIn()
          }}
          placeholder="ng_live_…"
          spellCheck={false}
          // A password field would hide a value the customer is trying to
          // confirm they pasted correctly, which is the single most common
          // failure at this step.
          type="text"
          value={entry}
        />
        <Button disabled={!entry.trim() || busy !== null} onClick={() => void signIn()}>
          {busy === 'login' ? <Loader2 className="size-4 animate-spin" /> : null}
          {status.keyPresent ? 'Ganti' : 'Simpan'}
        </Button>
      </div>

      {status.keyPresent ? (
        <>
          <SectionHeading icon={KeyRound} title="Keluar" />
          <p className="text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
            Menghapus API key dari perangkat ini. Atlas tetap terhubung ke NineGate — keluar
            bukan cara untuk memakai penyedia lain.
          </p>
          <Button disabled={busy !== null} onClick={() => void signOut()} variant="destructive">
            {busy === 'logout' ? <Loader2 className="size-4 animate-spin" /> : null}
            Keluar
          </Button>
        </>
      ) : null}
    </SettingsContent>
  )
}

/**
 * One allowance window: how much is left, and when it refills.
 *
 * The reset is shown as a wall-clock time rather than "in 3 hours", because
 * someone deciding whether to keep working wants to know if that is before or
 * after lunch. A relative figure also goes stale on a page left open.
 */
function QuotaRow({ label, window: w }: { label: string; window: QuotaWindow }) {
  const pct = w.limit > 0 ? Math.max(0, Math.min(100, Math.round((w.remaining / w.limit) * 100))) : 0
  const reset = new Date(w.reset_at)
  const resetText = Number.isNaN(reset.getTime())
    ? '—'
    : reset.toLocaleString('id-ID', { day: 'numeric', hour: '2-digit', minute: '2-digit', month: 'short' })

  return (
    <ListRow
      action={
        <span className="flex items-center gap-2 tabular-nums">
          <span className={pct <= 10 ? 'text-(--ui-danger)' : undefined}>
            {w.remaining.toLocaleString('id-ID')} token
          </span>
          <span className="text-(--ui-text-tertiary)">({pct}%)</span>
        </span>
      }
      description={`Terisi ulang ${resetText}`}
      title={label}
    />
  )
}
