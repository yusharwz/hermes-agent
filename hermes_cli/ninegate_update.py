"""Applying an Atlas update on a locked build.

WHY THIS IS NOT `hermes update`
===============================
The upstream updater is a git pull. A NineGate installation was never a
checkout — it is a source tarball the installer unpacked — so there is nothing
to pull, and the repository it would pull from is private. The gateway
publishes the same artefacts the installer uses, and this applies them.

THE SHAPE OF THE RISK
=====================
An updater is the one feature that can leave a customer worse off than not
having it. Everything here is arranged around that:

  * Nothing installed is touched until every artefact has been downloaded AND
    its checksum verified. A half-downloaded update never becomes a
    half-installed one.
  * The swap is a rename, not a copy. It is atomic and instant, so there is no
    window where the tree is partly old and partly new.
  * The previous version is kept, not deleted, until the new one has been
    smoke-tested. Failure after the swap restores it.
  * The version marker is written last. A marker claiming a version that is
    not on disk is worse than no marker, because the app then stops offering
    the update that would fix it.

WHAT "EVERYTHING" MEANS PER PLATFORM
====================================
The agent — the Python tree and the skills payload — updates in place on all
three systems, and that is where nearly every change lands.

The desktop application is different, and the difference is the operating
system's, not ours:

  Linux/macOS  the running process holds its own inode, so renaming a new
               binary over the old one is safe. The app keeps running on the
               old code until it is restarted, which it is told to do.
  Windows      a running .exe cannot be replaced. The installer can do it,
               because it is a separate process that waits for Atlas to exit,
               so the new installer is downloaded and handed over rather than
               pretending we can swap it ourselves.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

_log = logging.getLogger(__name__)

_TIMEOUT = 60
_CHUNK = 1 << 20


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


class UpdateJob:
    """One update, running on a thread, with progress the UI can poll.

    Deliberately a singleton in the module below: two concurrent updates
    renaming the same directories would race for the rollback copy, and the
    loser would restore over the winner's work.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "running": False,
            "stage": "",
            "percent": 0,
            "message": "",
            "done": False,
            "ok": False,
            "error": None,
            "restart_required": False,
            "installer_path": None,
            "version": None,
            "started_at": None,
            "finished_at": None,
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _set(self, **fields: Any) -> None:
        with self._lock:
            self._state.update(fields)

    def progress(self, stage: str, percent: int, message: str = "") -> None:
        self._set(stage=stage, percent=max(0, min(100, percent)), message=message)

    def begin(self) -> bool:
        """Claims the job. False when one is already running."""
        with self._lock:
            if self._state["running"]:
                return False
            self._state.update(
                {
                    "running": True,
                    "stage": "starting",
                    "percent": 0,
                    "message": "",
                    "done": False,
                    "ok": False,
                    "error": None,
                    "restart_required": False,
                    "installer_path": None,
                    "version": None,
                    "started_at": time.time(),
                    "finished_at": None,
                }
            )
            return True

    def finish(self, *, ok: bool, error: Optional[str] = None, **fields: Any) -> None:
        self._set(
            running=False,
            done=True,
            ok=ok,
            error=error,
            percent=100 if ok else self.snapshot()["percent"],
            finished_at=time.time(),
            **fields,
        )


JOB = UpdateJob()


# ---------------------------------------------------------------------------
# Paths and platform
# ---------------------------------------------------------------------------


def atlas_home() -> Path:
    return Path(os.environ.get("ATLAS_HOME") or (Path.home() / ".atlas"))


def source_dir() -> Path:
    """Where the agent's Python tree lives, matching the installer's layout."""
    return Path(os.environ.get("ATLAS_SRC") or (atlas_home() / "atlas-agent"))


def desktop_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        return "windows-x64"
    if system == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x64"
    return "linux-x64"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _request(url: str, key: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})


def fetch_manifest(gateway: str, key: str) -> Dict[str, Any]:
    with urllib.request.urlopen(_request(f"{gateway}/v1/atlas/manifest", key), timeout=_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def download_verified(
    url: str,
    key: str,
    target: Path,
    expected_sha256: str,
    on_progress: Optional[Callable[[int], None]] = None,
) -> None:
    """Downloads to `target` and refuses to keep bytes that do not match.

    A mismatch deletes the file. Leaving it means the next attempt resumes on
    top of corrupt bytes and fails identically, forever — which is a fault the
    installer hit for real before it did the same thing.
    """
    digest = hashlib.sha256()
    written = 0

    with urllib.request.urlopen(_request(url, key), timeout=_TIMEOUT) as response:
        total = int(response.headers.get("content-length") or 0)
        with target.open("wb") as handle:
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                if on_progress and total:
                    on_progress(int(written * 100 / total))

    actual = digest.hexdigest()
    if expected_sha256 and actual != expected_sha256:
        target.unlink(missing_ok=True)
        raise RuntimeError(
            f"Berkas yang diunduh tidak cocok checksum ({target.name}). "
            "Unduhan dibatalkan dan berkas dihapus; instalasi Anda tidak diubah."
        )


# ---------------------------------------------------------------------------
# The update itself
# ---------------------------------------------------------------------------


def _extract_tar(archive: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        # Refuse any member that would land outside the target. A tarball from
        # our own gateway is not the threat model this guards; a tarball from
        # anywhere else, one day, is.
        root = into.resolve()
        for member in tar.getmembers():
            destination = (root / member.name).resolve()
            if not str(destination).startswith(str(root)):
                raise RuntimeError(f"Arsip memuat jalur di luar target: {member.name}")
        tar.extractall(into)


def _smoke_test(tree: Path) -> None:
    """Proves the new tree can at least be imported before we keep it.

    Cheap, and it catches the failure that matters: an archive that unpacked
    but is incomplete. Without it a broken update is discovered by the
    customer, on their next message, with the old version already gone.
    """
    python = os.environ.get("ATLAS_PYTHON") or shutil.which("python3") or "python3"
    result = subprocess.run(
        [python, "-c", "import agent, hermes_cli; print('ok')"],
        cwd=str(tree),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Versi baru gagal dimuat setelah dipasang. "
            f"Detail: {(result.stderr or '').strip()[:400]}"
        )


def _swap(new: Path, live: Path, backup: Path) -> None:
    """Puts `new` at `live`, keeping whatever was there as `backup`.

    Renames, not copies: atomic, instant, and there is never a moment where
    `live` is half of each version.
    """
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    if live.exists():
        live.rename(backup)
    new.rename(live)


def _restore(live: Path, backup: Path) -> None:
    if not backup.exists():
        return
    if live.exists():
        shutil.rmtree(live, ignore_errors=True)
    backup.rename(live)


def run_update(gateway: str, key: str, job: UpdateJob = JOB) -> None:
    """Downloads, verifies, installs, and rolls back on failure."""
    home = atlas_home()
    home.mkdir(parents=True, exist_ok=True)

    staging = Path(tempfile.mkdtemp(prefix="atlas-update-", dir=str(home)))
    live_source = source_dir()
    backup_source = live_source.parent / (live_source.name + ".rollback")
    swapped = False

    try:
        job.progress("manifest", 2, "Memeriksa versi terbaru…")
        manifest = fetch_manifest(gateway, key)
        version = str(manifest.get("version") or "")
        job._set(version=version)

        # ── Download everything BEFORE touching the installation ──
        source_meta = manifest.get("source") or {}
        payload_meta = manifest.get("payload") or {}
        desktop_meta = (manifest.get("desktop") or {}).get(desktop_platform()) or {}

        source_archive = staging / "source.tar.gz"
        job.progress("download", 5, "Mengunduh Atlas…")
        download_verified(
            f"{gateway}/v1/atlas/source",
            key,
            source_archive,
            str(source_meta.get("sha256") or ""),
            lambda pct: job.progress("download", 5 + int(pct * 0.35), "Mengunduh Atlas…"),
        )

        payload_archive = staging / "payload.tar.gz"
        job.progress("download", 40, "Mengunduh keahlian dan vault…")
        download_verified(
            f"{gateway}/v1/atlas/payload",
            key,
            payload_archive,
            str(payload_meta.get("sha256") or ""),
            lambda pct: job.progress("download", 40 + int(pct * 0.10), "Mengunduh keahlian dan vault…"),
        )

        desktop_archive: Optional[Path] = None
        if desktop_meta.get("sha256"):
            desktop_archive = staging / str(desktop_meta.get("file") or "atlas-desktop")
            job.progress("download", 50, "Mengunduh aplikasi Atlas…")
            download_verified(
                f"{gateway}/v1/atlas/desktop?platform={desktop_platform()}",
                key,
                desktop_archive,
                str(desktop_meta.get("sha256")),
                lambda pct: job.progress("download", 50 + int(pct * 0.25), "Mengunduh aplikasi Atlas…"),
            )

        # ── Everything is on disk and verified. Now the installation moves ──
        job.progress("install", 78, "Memasang versi baru…")
        unpacked = staging / "tree"
        _extract_tar(source_archive, unpacked)

        # The tarball may or may not carry a single top-level directory.
        entries = [p for p in unpacked.iterdir() if not p.name.startswith(".")]
        new_tree = entries[0] if len(entries) == 1 and entries[0].is_dir() else unpacked

        _swap(new_tree, live_source, backup_source)
        swapped = True

        job.progress("verify", 86, "Memeriksa versi baru…")
        _smoke_test(live_source)

        job.progress("install", 90, "Memasang keahlian dan vault…")
        _extract_tar(payload_archive, home)

        restart_required = False
        installer_path = None

        if desktop_archive is not None:
            job.progress("install", 94, "Memasang aplikasi Atlas…")
            restart_required, installer_path = _install_desktop(desktop_archive, home)

        # ── Last, and only now ──
        job.progress("finish", 98, "Mencatat versi…")
        marker = home / "installed.json"
        marker.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        shutil.rmtree(backup_source, ignore_errors=True)
        job.finish(
            ok=True,
            restart_required=restart_required,
            installer_path=installer_path,
            message=f"Atlas diperbarui ke versi {version}.",
        )

    except Exception as exc:
        if swapped:
            _log.warning("pembaruan gagal setelah penukaran — mengembalikan versi lama")
            try:
                _restore(live_source, backup_source)
            except Exception:
                _log.exception("rollback gagal")
                job.finish(
                    ok=False,
                    error=(
                        f"Pembaruan gagal DAN pemulihan gagal: {exc}. "
                        f"Versi lama ada di {backup_source}. Jalankan installer Atlas untuk memperbaiki."
                    ),
                )
                return

        job.finish(ok=False, error=str(exc) or "Pembaruan gagal.")
        _log.exception("pembaruan gagal")

    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _install_desktop(artifact: Path, home: Path) -> tuple[bool, Optional[str]]:
    """Puts the new desktop application in place.

    Returns (restart_required, installer_path). On Windows the swap belongs to
    the installer, so the path is handed back for the app to launch.
    """
    system = platform.system().lower()
    target_dir = home / "bin"
    target_dir.mkdir(parents=True, exist_ok=True)

    if system == "windows":
        # A running .exe cannot be replaced. The installer is a separate
        # process that waits for Atlas to exit, so it does the swap.
        installer = target_dir / "Atlas-Setup.exe"
        shutil.move(str(artifact), str(installer))
        return True, str(installer)

    if system == "darwin":
        # The .dmg has to be mounted and the bundle copied out. The running
        # process holds its own bundle's inodes, so replacing the directory is
        # safe; it keeps running on the old code until restarted.
        mount = tempfile.mkdtemp(prefix="atlas-dmg-")
        try:
            subprocess.run(
                ["hdiutil", "attach", "-nobrowse", "-quiet", "-mountpoint", mount, str(artifact)],
                check=True,
                capture_output=True,
                timeout=300,
            )
            bundles = list(Path(mount).glob("*.app"))
            if not bundles:
                raise RuntimeError("Berkas .dmg tidak memuat aplikasi.")

            destination = Path("/Applications") / bundles[0].name
            staged = Path(tempfile.mkdtemp(prefix="atlas-app-")) / bundles[0].name
            shutil.copytree(bundles[0], staged, symlinks=True)

            backup = destination.parent / (destination.name + ".rollback")
            _swap(staged, destination, backup)
            shutil.rmtree(backup, ignore_errors=True)
        finally:
            subprocess.run(["hdiutil", "detach", mount, "-quiet"], capture_output=True, timeout=120)
            shutil.rmtree(mount, ignore_errors=True)

        return True, None

    # Linux: an AppImage is one file, and renaming over it is atomic. The
    # running process keeps the old inode and carries on until restarted.
    app = target_dir / "Atlas.AppImage"
    backup = target_dir / "Atlas.AppImage.rollback"

    if app.exists():
        backup.unlink(missing_ok=True)
        app.rename(backup)

    shutil.move(str(artifact), str(app))
    app.chmod(0o755)
    backup.unlink(missing_ok=True)

    return True, None
