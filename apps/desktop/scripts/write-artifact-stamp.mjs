/**
 * write-artifact-stamp.mjs — electron-builder afterAllArtifactBuild hook.
 *
 * WHY THIS EXISTS
 * ===============
 * The release server collects desktop applications BY FILENAME:
 * `Atlas-*-win-x64.exe`, `Atlas-*-arm64.dmg`, and so on. A filename carries the
 * product version (0.17.0) and nothing else, so a .exe built on the 9th and an
 * agent tarball built on the 11th are indistinguishable to the collector — and
 * it labelled both with the source commit it happened to be holding. Customers
 * on Windows and macOS were handed a build older than the version the manifest
 * claimed they were getting.
 *
 * The commit is not unknown: `write-build-stamp.mjs` already resolves it and
 * writes apps/desktop/build/install-stamp.json, which electron-builder packs
 * into the application via extraResources. The gap is only that the fact is
 * sealed INSIDE the artifact, where a collector would have to mount a .dmg or
 * unpack an NSIS installer to read it.
 *
 * So this hook copies that same fact to a sidecar next to each artifact:
 *
 *   Atlas-<version>-win-x64.exe
 *   Atlas-<version>-win-x64.exe.stamp.json
 *
 * Same file, same build, one open. It is deliberately a copy of the existing
 * stamp rather than a second resolution of the commit: two places that both
 * work out "which commit is this" is exactly how they come to disagree.
 *
 * An artifact WITHOUT a sidecar is one of unknown provenance, and the collector
 * refuses to publish it. That is the intended failure direction: a platform
 * that silently goes missing gets noticed, a platform that silently ships the
 * wrong build does not.
 */

import { copyFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

import { isMain } from './utils.mjs'

const DESKTOP_ROOT = path.resolve(import.meta.dirname, '..')
const STAMP_FILE = path.join(DESKTOP_ROOT, 'build', 'install-stamp.json')

/** The suffix the release collector looks for. Kept in one place. */
export const STAMP_SUFFIX = '.stamp.json'

/**
 * Which artifacts a customer actually downloads.
 *
 * electron-builder also emits blockmaps, latest*.yml and unpacked directories.
 * Stamping those would be noise, and `.blockmap` in particular would produce
 * `Atlas-<version>-win-x64.exe.blockmap.stamp.json`, which reads like a second
 * Windows build.
 */
const INSTALLABLE = /\.(exe|dmg|AppImage|deb|rpm|msi|zip)$/i

export function isInstallable(file) {
  return INSTALLABLE.test(file)
}

export function stampPathFor(artifact) {
  return artifact + STAMP_SUFFIX
}

export default async function afterAllArtifactBuild(buildResult) {
  const artifacts = (buildResult?.artifactPaths || []).filter(isInstallable)
  if (artifacts.length === 0) {
    return []
  }

  if (!existsSync(STAMP_FILE)) {
    // `npm run build` writes it and `npm run builder` runs after `npm run
    // build` in every dist:* script. Reaching here means somebody packaged a
    // tree that was never built, and an unstamped artifact will be refused
    // downstream anyway — so say why now, while the context is still here.
    throw new Error(
      `[write-artifact-stamp] ${path.relative(DESKTOP_ROOT, STAMP_FILE)} is missing. ` +
        'Run `npm run build` before packaging: without it the release collector ' +
        'cannot tell which commit these artifacts were built from and will refuse them.',
    )
  }

  // Parsed, not just copied, so a truncated or half-written stamp fails here
  // rather than at collection time on the server.
  const stamp = JSON.parse(readFileSync(STAMP_FILE, 'utf8'))
  if (!stamp || typeof stamp.commit !== 'string' || stamp.commit.length === 0) {
    throw new Error(`[write-artifact-stamp] ${STAMP_FILE} has no commit`)
  }

  const written = []
  for (const artifact of artifacts) {
    const sidecar = stampPathFor(artifact)
    copyFileSync(STAMP_FILE, sidecar)
    written.push(sidecar)
    console.log(
      `[write-artifact-stamp] ${path.basename(sidecar)} -> ${stamp.commit.slice(0, 12)}` +
        (stamp.dirty ? ' [DIRTY]' : '') +
        (stamp.source === 'fallback' ? ' [FALLBACK]' : ''),
    )
  }

  // Returned so electron-builder treats them as part of the build's output
  // rather than stray files in release/.
  return written
}

/**
 * Re-stamp artifacts that are already on disk.
 *
 * The hook covers every build that goes through `npm run builder`. This covers
 * the one case it cannot: artifacts downloaded from a CI run that predates the
 * hook, which would otherwise be unpublishable with no way to fix them short of
 * paying for another macOS runner.
 *
 * Requires the commit to be given explicitly — guessing it is precisely the
 * mistake this whole file exists to stop.
 */
export function stampExisting(artifacts, { commit, branch = null, builtAt = null } = {}) {
  if (typeof commit !== 'string' || !/^[0-9a-f]{7,40}$/i.test(commit)) {
    throw new Error('stampExisting requires the full commit the artifacts were built from')
  }
  const payload = {
    schemaVersion: 1,
    commit,
    branch,
    builtAt: builtAt || new Date().toISOString(),
    dirty: false,
    source: 'manual',
  }
  const written = []
  for (const artifact of artifacts) {
    const sidecar = stampPathFor(artifact)
    writeFileSync(sidecar, JSON.stringify(payload, null, 2) + '\n', 'utf8')
    written.push(sidecar)
  }
  return written
}

function main(argv) {
  const commitAt = argv.indexOf('--commit')
  const commit = commitAt === -1 ? null : argv[commitAt + 1]
  const artifacts = argv.filter((arg, i) => i !== commitAt && i !== commitAt + 1 && !arg.startsWith('--'))

  if (!commit || artifacts.length === 0) {
    console.error(
      'usage: node scripts/write-artifact-stamp.mjs --commit <sha> <artifact>...\n' +
        '\n' +
        'Stamps artifacts built before this hook existed, or collected from a CI\n' +
        'run by hand. The commit is not guessed: pass the one the artifacts were\n' +
        'actually built from, or leave them unstamped and let the release\n' +
        'collector refuse them.',
    )
    process.exit(2)
  }

  for (const sidecar of stampExisting(artifacts, { commit })) {
    console.log(`[write-artifact-stamp] ${sidecar} -> ${commit.slice(0, 12)}`)
  }
}

if (isMain(import.meta.url)) {
  main(process.argv.slice(2))
}
