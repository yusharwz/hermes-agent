/**
 * "Atlas is updated — restart now, or later?"
 *
 * Rendered at the app shell, not inside Settings. The update runs detached and
 * finishes when it finishes, which is routinely after the customer has gone
 * back to a chat and forgotten they started it. A completion notice that only
 * exists on a settings tab is a completion notice most people never see, and
 * the visible consequence was an "Update" button that still looked pressable —
 * so the update got run again.
 *
 * Both buttons are real answers. "Later" is not a dismissal: the new version is
 * already on disk and loads on the next launch either way, so refusing to
 * restart costs nothing and interrupting someone mid-sentence does.
 */
import { useStore } from '@nanostores/react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { CheckCircle2 } from '@/lib/icons'
import { $restartPrompt, dismissRestartPrompt } from '@/store/ninegate-update'
import { notifyError } from '@/store/notifications'

export function UpdateRestartModal() {
  const prompt = useStore($restartPrompt)
  const [restarting, setRestarting] = useState(false)

  if (!prompt) {
    return null
  }

  // Windows hands over to a downloaded installer instead of relaunching: a
  // running .exe cannot be replaced, so the update left one for us to run.
  const handover = Boolean(prompt.installerPath)

  const restart = async () => {
    setRestarting(true)

    try {
      await window.hermesDesktop.restartApp(prompt.installerPath)
    } catch (error) {
      setRestarting(false)
      notifyError(error, 'Atlas tidak bisa dimulai ulang. Tutup dan buka kembali secara manual.')
    }
  }

  return (
    <Dialog onOpenChange={open => !open && dismissRestartPrompt()} open>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="size-5 text-emerald-600 dark:text-emerald-400" />
            {prompt.version ? `Atlas ${prompt.version} siap` : 'Pembaruan Atlas selesai'}
          </DialogTitle>
          <DialogDescription>
            {handover
              ? 'Pembaruan sudah diunduh. Atlas akan ditutup dan pemasangnya dijalankan untuk menyelesaikan.'
              : 'Versi baru sudah terpasang. Mulai ulang Atlas sekarang untuk memakainya, atau nanti — versi baru akan aktif saat Atlas dibuka lagi.'}
          </DialogDescription>
        </DialogHeader>

        <DialogFooter className="gap-2 sm:gap-2">
          <Button disabled={restarting} onClick={() => dismissRestartPrompt()} variant="outline">
            Nanti saja
          </Button>
          <Button autoFocus disabled={restarting} onClick={() => void restart()}>
            {restarting ? 'Memulai ulang…' : handover ? 'Tutup & pasang' : 'Mulai ulang sekarang'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
