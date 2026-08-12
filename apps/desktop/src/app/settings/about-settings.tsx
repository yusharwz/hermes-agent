import { useStore } from '@nanostores/react'
import { useEffect } from 'react'

import { BrandMark } from '@/components/brand-mark'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { useI18n } from '@/i18n'
import { CheckCircle2, RefreshCw } from '@/lib/icons'
import { cn } from '@/lib/utils'
import {
  $updateChecking,
  $updateInfo,
  $updateProgress,
  $updateStarting,
  refreshUpdateInfo,
  startNineGateUpdate
} from '@/store/ninegate-update'
import { $desktopVersion, refreshDesktopVersion } from '@/store/updates'

import { SectionHeading, SettingsContent } from './primitives'
import { UninstallSection } from './uninstall-section'

export function AboutSettings() {
  const { t } = useI18n()
  const a = t.settings.about
  const version = useStore($desktopVersion)

  // The version atom is loaded once at app boot, which makes About show a
  // stale number after an update (the running binary is current, the
  // displayed string is not). Re-read on mount so opening About always
  // reflects the running build.
  useEffect(() => {
    void refreshDesktopVersion()
  }, [])

  return (
    <SettingsContent>
      <div className="flex flex-col items-center gap-3 pt-6 pb-2 text-center">
        <BrandMark className="size-16" />
        <div>
          <h2 className="text-lg font-semibold tracking-tight">{a.heading}</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {version?.appVersion ? a.version(version.appVersion) : a.versionUnavailable}
          </p>
        </div>
      </div>

      {/* The upstream update mechanism is not in this build.
          ===================================================
          It checked, downloaded and applied from
          github.com/NousResearch/hermes-agent. Clicking it on an Atlas
          install would pull Nous code over the top: not a cosmetic leak but a
          live path to breaking the customer's installation, and one that
          strips the NineGate lock along with everything else built on it.

          Atlas updates come from the gateway instead, which serves the same
          manifest the installer recorded — see the card below. */}
      <NineGateUpdateCard />

      <div className="mx-auto mt-4 w-full max-w-2xl">
        <UninstallSection />
      </div>
    </SettingsContent>
  )
}

/**
 * The update card on a NineGate build.
 *
 * The upstream one below talks to GitHub, which a locked build cannot use: the
 * repository is private, and applying a result would be a `git pull` over an
 * installation that was never a checkout. This reads the gateway's release
 * metadata instead — the same manifest the installer records at install time.
 *
 * An install that predates the version marker reports "unknown" rather than
 * "up to date". Claiming currency we cannot prove is the one answer that
 * leaves a customer sitting on an old build believing they are current.
 */
function NineGateUpdateCard() {
  // Read, not owned. The poller runs at the app shell and the backend holds
  // the truth, so this card shows the same thing whether it was mounted before
  // the update started, during it, or after the app was closed and reopened.
  const state = useStore($updateInfo)
  const progress = useStore($updateProgress)
  const checking = useStore($updateChecking)
  const starting = useStore($updateStarting)

  if (!state.resolved) {
    return null
  }

  const busy = starting || Boolean(progress?.running)

  const tone = state.error ? 'error' : state.updateAvailable ? 'available' : 'idle'

  const headline = state.error
    ? 'Tidak bisa memeriksa pembaruan'
    : state.updateAvailable
      ? state.current
        ? `Pembaruan tersedia — versi ${state.latest}`
        : `Versi terbaru: ${state.latest}`
      : 'Atlas Anda sudah versi terbaru'

  const detail = state.error
    ? `${state.error}. Periksa koneksi Anda, lalu coba lagi.`
    : state.updateAvailable
      ? state.current
        ? `Terpasang ${state.current}. ${
            state.desktopChanged
              ? 'Pembaruan ini termasuk aplikasinya, jadi Atlas akan dimulai ulang setelah selesai.'
              : 'Pembaruan ini hanya menyentuh agen — aplikasi tidak perlu dimulai ulang.'
          }`
        : 'Versi yang terpasang tidak tercatat, jadi kami tidak bisa memastikan Anda sudah mutakhir. Menjalankan pembaruan akan menyamakannya.'
      : `Terpasang ${state.current ?? '—'}.`

  return (
    <div className="mx-auto mt-4 w-full max-w-2xl">
      <SectionHeading icon={RefreshCw} title="Pembaruan" />

      <div
        className={cn(
          'rounded-xl border px-4 py-3 text-sm',
          tone === 'available' && 'border-primary/30 bg-primary/5 text-foreground',
          tone === 'error' && 'border-destructive/35 bg-destructive/5 text-destructive',
          tone === 'idle' && 'border-border/70 bg-muted/20 text-foreground'
        )}
      >
        <div className="flex items-start gap-2">
          {tone === 'available' ? (
            <Codicon className="mt-0.5 size-4 shrink-0 text-primary" name="cloud-download" size="1rem" />
          ) : tone === 'error' ? null : (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
          )}
          <div className="min-w-0">
            <p className="font-medium">{headline}</p>
            <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
          </div>
        </div>

        {/* Progress, once an update is actually running. A percentage on a
            two-minute download is the difference between "working" and
            "frozen" — the installer learned that the hard way. */}
        {progress && (progress.running || progress.done) ? (
          <div className="mt-3">
            {progress.running ? (
              <>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-[width] duration-300"
                    style={{ width: `${progress.percent}%` }}
                  />
                </div>
                <p className="mt-1.5 text-xs text-muted-foreground">
                  {progress.percent}% · {progress.message || progress.stage}
                </p>
              </>
            ) : progress.ok ? (
              /* The restart itself is asked for by the modal at the app shell,
                 which the customer sees wherever they happen to be. This line
                 is what remains true afterwards, for someone who opens About
                 later. */
              <p className="text-xs text-emerald-600 dark:text-emerald-400">
                Selesai. {progress.restartRequired
                  ? progress.installerPath
                    ? 'Tutup Atlas lalu jalankan pemasang yang sudah diunduh untuk menyelesaikan.'
                    : 'Versi baru aktif setelah Atlas dimulai ulang.'
                  : 'Versi baru sudah aktif.'}
              </p>
            ) : (
              <p className="text-xs text-destructive">
                {progress.error} Instalasi Anda dikembalikan ke versi sebelumnya.
              </p>
            )}
          </div>
        ) : null}

        <div className="mt-3 flex flex-wrap items-center gap-3">
          {/* The button is gone once there is nothing to install, and
              disabled while something is — an update that is already running
              answers a second request with 409, and a customer should never be
              able to ask for that. */}
          {state.updateAvailable && !state.error ? (
            <Button disabled={busy} onClick={() => void startNineGateUpdate()} size="sm">
              {busy ? 'Memperbarui…' : 'Perbarui sekarang'}
            </Button>
          ) : null}
          <Button disabled={checking || busy} onClick={() => void refreshUpdateInfo()} size="sm" variant="outline">
            {checking ? 'Memeriksa…' : 'Periksa lagi'}
          </Button>
        </div>
      </div>
    </div>
  )
}
