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

from hermes_constants import find_tree_venv, venv_python_path

_log = logging.getLogger(__name__)

_TIMEOUT = 60
_CHUNK = 1 << 20


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


IDLE_STATE: Dict[str, Any] = {
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
    "pid": None,
    "updated_at": None,
}

# How long a running job may go without touching the file before it is read as
# dead. The heartbeat below writes every few seconds regardless of stage, so
# this is not a guess about how long a stage takes — it is slack for a machine
# that suspended or a disk that stalled.
STALE_AFTER = 90.0
_HEARTBEAT_INTERVAL = 5.0


def state_path() -> Path:
    """Where progress lives, so it is not lost with the process that made it."""
    return atlas_home() / "update-state.json"


def _write_state(state: Dict[str, Any]) -> None:
    """Atomically, because a reader polling every second will catch a partial
    write otherwise and report an update as gone."""
    path = state_path()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        # Progress reporting must never be the thing that fails an update.
        _log.debug("tidak bisa menulis status pembaruan", exc_info=True)


def _process_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False

    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, owned by someone else. Not ours to judge.
        return True
    except Exception:
        # Windows, mostly: fall back to the heartbeat, which is why it exists.
        return True

    return True


def read_state() -> Dict[str, Any]:
    """The current state of the update, whichever process is running it.

    Resolves a job that died mid-flight rather than reporting it as running
    forever: a progress bar for a process that is gone is worse than an error,
    because the customer waits instead of retrying.
    """
    try:
        raw = json.loads(state_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(IDLE_STATE)
    except Exception:
        _log.debug("status pembaruan tidak terbaca", exc_info=True)
        return dict(IDLE_STATE)

    state = dict(IDLE_STATE)
    state.update({key: raw.get(key, state[key]) for key in state})

    if not state["running"]:
        return state

    beat = state.get("updated_at") or state.get("started_at") or 0
    fresh = (time.time() - float(beat)) < STALE_AFTER
    # No pid yet means a claim written by the gateway in the moment between
    # accepting the request and the runner starting. Freshness is all there is
    # to go on there, and it is enough: the runner stamps its own pid within a
    # second, and a spawn that fails writes the failure itself.
    owned = state.get("pid") is None or _process_alive(state.get("pid"))

    if fresh and owned:
        return state

    interrupted = dict(state)
    interrupted.update(
        {
            "running": False,
            "done": True,
            "ok": False,
            "error": "Pembaruan terhenti sebelum selesai. Instalasi Anda tidak berubah — coba lagi.",
            "finished_at": time.time(),
        }
    )
    _write_state(interrupted)

    return interrupted


class UpdateJob:
    """One update, with progress written where any process can read it.

    Deliberately a singleton in the module below: two concurrent updates
    renaming the same directories would race for the rollback copy, and the
    loser would restore over the winner's work.

    The state used to live only in memory, in the gateway the desktop app
    spawns and kills on quit. That made the progress bar a property of a
    settings tab: leave the tab and it was gone, close the app and the update
    itself died halfway through a tree swap. It is a file now, and the update
    runs in its own process — see `spawn_detached`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = dict(IDLE_STATE)
        self._beat: Optional[threading.Thread] = None
        self._stop_beat = threading.Event()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _set(self, **fields: Any) -> None:
        with self._lock:
            self._state.update(fields)
            self._state["updated_at"] = time.time()
            state = dict(self._state)

        _write_state(state)

    def progress(self, stage: str, percent: int, message: str = "") -> None:
        self._set(stage=stage, percent=max(0, min(100, percent)), message=message)

    def _heartbeat(self) -> None:
        """Touches the file on a timer so liveness never depends on a stage
        being chatty. The download reports per chunk; extracting a payload or
        smoke-testing an interpreter can say nothing for a while."""
        while not self._stop_beat.wait(_HEARTBEAT_INTERVAL):
            with self._lock:
                if not self._state["running"]:
                    return

                self._state["updated_at"] = time.time()
                state = dict(self._state)

            _write_state(state)

    def begin(self) -> bool:
        """Claims the job for THIS process. False when one is already running.

        A running claim carrying no pid is the gateway holding the place for
        the runner it just spawned — that one is adopted, not refused.
        """
        existing = read_state()

        if existing["running"] and existing.get("pid"):
            return False

        with self._lock:
            if self._state["running"]:
                return False

            self._state = dict(IDLE_STATE)
            self._state.update(
                {
                    "running": True,
                    "stage": "starting",
                    "percent": 0,
                    "started_at": time.time(),
                    "updated_at": time.time(),
                    "pid": os.getpid(),
                }
            )
            state = dict(self._state)

        _write_state(state)
        self._stop_beat.clear()
        self._beat = threading.Thread(target=self._heartbeat, name="ninegate-update-beat", daemon=True)
        self._beat.start()

        return True

    def claim(self) -> bool:
        """Holds the place for a runner about to be spawned.

        Written before the process exists so the first poll after the request
        shows an update starting rather than the *previous* run's result — which
        reads as "already finished" and is how a customer concludes nothing
        happened. Carries no pid: the runner stamps its own.
        """
        if read_state()["running"]:
            return False

        with self._lock:
            self._state = dict(IDLE_STATE)
            self._state.update(
                {
                    "running": True,
                    "stage": "starting",
                    "message": "Menyiapkan pembaruan…",
                    "started_at": time.time(),
                    "updated_at": time.time(),
                }
            )
            state = dict(self._state)

        _write_state(state)

        return True

    def fail_claim(self, error: str) -> None:
        """Releases a claim whose runner never started."""
        self._set(running=False, done=True, ok=False, error=error, finished_at=time.time())

    def finish(self, *, ok: bool, error: Optional[str] = None, **fields: Any) -> None:
        self._stop_beat.set()
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


def _smoke_test_python(tree: Path) -> str:
    """The interpreter to prove the new tree with.

    The venv inside the tree, when there is one, because that is the
    interpreter the installation actually runs on: the service unit's
    ExecStart names it directly, and it is the only one that has the
    dependencies. Testing anything else answers a question nobody asked —
    a system python3 that happens to import the tree says nothing about
    whether the gateway can start.

    `ATLAS_PYTHON` stays the escape hatch for installations that keep their
    interpreter outside the tree, and a bare python3 is the last resort.
    """
    venv = find_tree_venv(tree)
    if venv is not None:
        candidate = venv_python_path(venv)
        if candidate.exists():
            return str(candidate)
    return os.environ.get("ATLAS_PYTHON") or shutil.which("python3") or "python3"


def _smoke_test(tree: Path) -> None:
    """Proves the new tree can at least be imported before we keep it.

    Cheap, and it catches the failure that matters: an archive that unpacked
    but is incomplete. Without it a broken update is discovered by the
    customer, on their next message, with the old version already gone.
    """
    python = _smoke_test_python(tree)
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


def _carry_over_venv(source_tree: Path, target_tree: Path) -> Optional[Path]:
    """Moves the virtual environment from one tree into the other.

    The interpreter an installation runs on lives *inside* the source tree
    (`<tree>/.venv`) — the service unit's ExecStart, VIRTUAL_ENV and PATH all
    name that path — but it is build output, not release content, so no
    tarball we publish contains one. A swap that only renames trees therefore
    moves the interpreter out from under the running service: the unit's
    ExecStart no longer exists, and `hermes gateway` cannot start again.

    Nothing downstream caught it. The smoke test passed on a system python3,
    and passing is what licenses deleting the backup — so the venv went from
    "set aside" to "gone" on the strength of a check that never looked at it.
    Recreating one costs a full dependency install the update never budgeted
    for, over whatever connection the customer has.

    Moved, not copied: the venv is hundreds of megabytes and both trees are
    on the same filesystem, so a rename is instant and leaves no window in
    which two trees each hold one.
    """
    venv = find_tree_venv(source_tree)
    if venv is None:
        return None

    destination = target_tree / venv.name
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    try:
        venv.rename(destination)
    except OSError:
        # Different filesystems, which the staging directory's placement
        # inside the home makes unlikely but does not forbid.
        shutil.move(str(venv), str(destination))
    return destination


def _swap(new: Path, live: Path, backup: Path) -> None:
    """Puts `new` at `live`, keeping whatever was there as `backup`.

    Renames, not copies: atomic, instant, and there is never a moment where
    `live` is half of each version.

    The venv travels with the tree rather than being left in the backup —
    see `_carry_over_venv`. It is moved into `new` *before* `new` becomes
    `live`, so the installation is never visible without its interpreter.
    """
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    if live.exists():
        live.rename(backup)
        _carry_over_venv(backup, new)
    new.rename(live)


def _restore(live: Path, backup: Path) -> None:
    """Puts the previous tree back after a failed update.

    The venv has to make the return trip too. `_swap` moved it into the tree
    that is about to be deleted here, so restoring without it would roll back
    onto an installation with no interpreter — the same breakage as the
    failure being rolled back from, reached by the path meant to be the way
    out of it.
    """
    if not backup.exists():
        return
    if live.exists():
        _carry_over_venv(live, backup)
        shutil.rmtree(live, ignore_errors=True)
    backup.rename(live)


def _desktop_already_installed(home: Path, desktop_meta: Dict[str, Any]) -> bool:
    """Whether the exact desktop application in the manifest is already here.

    Read from `installed.json`, which is written only after an install has
    succeeded end to end — so it records what is on disk, not what was
    attempted. A missing, unreadable or older marker answers False and the
    update proceeds as it always did: a needless download costs time, a wrongly
    skipped one costs the customer an application that never arrives.
    """
    try:
        installed = json.loads((home / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False

    if not isinstance(installed, dict):
        return False
    previous = (installed.get("desktop") or {}).get(desktop_platform())
    if not isinstance(previous, dict):
        return False

    have = str(previous.get("sha256") or "")
    return bool(have) and have == str(desktop_meta.get("sha256") or "")


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
        if desktop_meta.get("sha256") and _desktop_already_installed(home, desktop_meta):
            # The desktop application is 117–140 MB and changes far less often
            # than the agent tree it ships beside — macOS is built on a hosted
            # runner and Windows on the build box, so a run of agent-only
            # releases republishes the same bytes each time. Downloading them
            # again to write the identical file back is the largest single
            # transfer in an update, and it buys nothing.
            #
            # sha256 identity, not version identity: it compares the exact
            # bytes recorded as installed, so a rebuilt application with the
            # same version number is still fetched.
            _log.info("aplikasi desktop sudah versi ini — melewati unduhan")
        elif desktop_meta.get("sha256"):
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


# ---------------------------------------------------------------------------
# Running it somewhere that outlives the window
# ---------------------------------------------------------------------------


def _runner_python() -> str:
    """The interpreter to run the update with.

    `sys.executable` is already running from the tree that is about to be
    renamed, which is fine on POSIX — the process keeps its inode — and it is
    the same interpreter the gateway itself is using. The venv is carried
    across the swap, so the path is valid again on the other side.
    """
    import sys

    if sys.executable:
        return sys.executable

    venv = find_tree_venv(source_dir())

    return str(venv_python_path(venv)) if venv else "python3"


def spawn_detached(gateway: str, key: str) -> None:
    """Starts the update in its own process, outside this one's lifetime.

    WHY NOT A THREAD
    ================
    It was a thread in the gateway, and the desktop app spawns that gateway as
    a child and SIGTERMs it on quit. So closing the window during an update
    killed the update — not at a safe point, but wherever it had got to, which
    could be between the rename of the old tree and the restore of the venv.
    The one operation that must not be interrupted was tied to the lifetime of
    a window the customer has every reason to close while it runs.

    Detached, the update finishes whatever the app does, and any process that
    can read `update-state.json` can report on it — which is how the progress
    bar survives closing and reopening the app.
    """
    home = atlas_home()
    home.mkdir(parents=True, exist_ok=True)
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    # By environment, not argv: a command line is readable by every process on
    # the machine, and this is a live subscription credential.
    env["NINEGATE_GATEWAY_URL"] = gateway
    env["NINEGATE_API_KEY"] = key
    # `-m` needs the tree on the path, and the cwd below is deliberately not it.
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(source_dir()), env.get("PYTHONPATH", "")]))

    kwargs: Dict[str, Any] = {}

    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        # Its own session, so a signal aimed at the gateway's process group
        # does not reach it.
        kwargs["start_new_session"] = True

    with open(logs / "update.log", "ab") as log:
        subprocess.Popen(
            [_runner_python(), "-m", "hermes_cli.ninegate_update", "--apply"],
            # Not the source tree: that directory is renamed mid-update, and a
            # process whose cwd has been renamed is a bad place to be.
            cwd=str(home),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            **kwargs,
        )


def main() -> int:
    """Entry point for the detached runner."""
    import sys

    if "--apply" not in sys.argv[1:]:
        print("penggunaan: python -m hermes_cli.ninegate_update --apply", file=sys.stderr)

        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    gateway = (os.environ.get("NINEGATE_GATEWAY_URL") or "").strip().rstrip("/")
    key = (os.environ.get("NINEGATE_API_KEY") or "").strip()

    if not gateway or not key:
        JOB.fail_claim("Pembaruan tidak bisa dimulai: gateway atau API key tidak tersedia.")

        return 2

    if not JOB.begin():
        _log.info("pembaruan lain sedang berjalan — keluar")

        return 0

    run_update(gateway, key)

    return 0 if JOB.snapshot().get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
