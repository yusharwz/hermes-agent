// Resolve electronDist at runtime (#38673, #47917): electron-builder 26.8.x can
// re-unpack a broken Electron.app; reusing the installed dist dodges that.
// npm workspace hoisting is non-deterministic — require.resolve finds electron
// wherever it landed. Dist present → -c.electronDist=<abs>/dist; absent → let
// electron-builder fetch via @electron/get (electronVersion + ELECTRON_MIRROR).

import fs from "node:fs"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)

function electronDistDir() {
  try {
    return path.join(path.dirname(require.resolve("electron/package.json")), "dist")
  } catch {
    return null
  }
}

function distBinary(dist) {
  if (process.platform === "darwin") {
    return path.join(dist, "Electron.app", "Contents", "MacOS", "Electron")
  }
  if (process.platform === "win32") {
    return path.join(dist, "electron.exe")
  }
  return path.join(dist, "electron")
}

function electronBuilderCli() {
  const pkgJson = require.resolve("electron-builder/package.json")
  const bin = require(pkgJson).bin
  const rel = typeof bin === "string" ? bin : bin["electron-builder"]
  return path.join(path.dirname(pkgJson), rel)
}

/**
 * Whether this run targets the machine it is running on.
 *
 * The installed Electron dist is for the HOST platform, so reusing it is only
 * correct when host and target agree. Cross-building — `--win` from Linux, say
 * — handed electron-builder a Linux dist and it then failed trying to rename
 * an `electron.exe` that was never there.
 *
 * Absent an explicit flag, electron-builder targets the host, so no flag means
 * native.
 */
function targetsHost(argv) {
  const requested = ["--win", "--windows", "--mac", "--macos", "--linux"].filter((flag) =>
    argv.includes(flag)
  )
  if (requested.length === 0) return true

  const host =
    process.platform === "win32" ? ["--win", "--windows"]
    : process.platform === "darwin" ? ["--mac", "--macos"]
    : ["--linux"]

  // Every requested target must be the host's, not merely one of them: a
  // `--linux --win` run still needs Electron fetched for Windows.
  return requested.every((flag) => host.includes(flag))
}

const forHost = targetsHost(process.argv.slice(2))
const dist = electronDistDir()
const args = []
if (forHost && dist && fs.existsSync(distBinary(dist))) {
  args.push(`-c.electronDist=${dist}`)
} else if (!forHost) {
  console.warn(
    "[run-electron-builder] cross-building; letting electron-builder fetch the " +
      "target platform's Electron rather than reusing this machine's."
  )
} else {
  console.warn(
    "[run-electron-builder] no local electron dist; electron-builder will fetch " +
      "via @electron/get (electronVersion + ELECTRON_MIRROR)."
  )
}
args.push(...process.argv.slice(2))

const result = spawnSync(process.execPath, [electronBuilderCli(), ...args], {
  stdio: "inherit",
})
if (result.error) {
  console.error(`[run-electron-builder] spawn failed: ${result.error.message}`)
  process.exit(1)
}
process.exit(result.status == null ? 1 : result.status)
