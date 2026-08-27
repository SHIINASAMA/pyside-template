# app/builtin/updater/run_update.py
"""Updater mode entry point.

When the main app spawns itself with --updater, the new process enters this
module instead of normal app startup. It waits for the old process to exit,
replaces files, launches the new app, and cleans up.
"""
import os
import signal
import subprocess
import sys
import shutil
import time
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class UpdateArgs:
    source: Path       # staging dir with new files
    target: Path       # current install dir
    launch: str        # executable name to launch
    old_pid: int       # PID of old process to wait for
    backup: bool       # whether to backup before replacing
    timeout: int       # seconds to wait for old process


def parse_update_args() -> UpdateArgs:
    """Parse --updater-* flags from sys.argv."""
    def get_flag(name: str, default: str = "") -> str:
        key = f"--updater-{name}"
        for i, arg in enumerate(sys.argv):
            if arg == key and i + 1 < len(sys.argv):
                return sys.argv[i + 1]
        return default

    return UpdateArgs(
        source=Path(get_flag("source")),
        target=Path(get_flag("target")),
        launch=get_flag("launch"),
        old_pid=int(get_flag("old-pid", "0")),
        backup="--backup" in sys.argv,
        timeout=int(get_flag("timeout", "30")),
    )


def wait_for_process_exit(pid: int, timeout: int = 30) -> None:
    """Poll until old process exits or timeout, then force-kill."""
    if pid <= 0:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.5)

    log.warning("Process %d did not exit in %ds, sending SIGTERM", pid, timeout)
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def replace_files(source: Path, target: Path) -> None:
    """Replace target directory contents with source using platform tool."""
    if sys.platform == "darwin" or sys.platform == "linux":
        subprocess.run(
            ["rsync", "-a", "--delete", "--checksum", f"{source}/", f"{target}/"],
            check=True,
        )
    else:
        # Windows
        subprocess.run(
            ["robocopy", str(source), str(target), "/MIR", "/R:3", "/W:5"],
            check=True,
        )


def launch_app(target: Path, launch_name: str) -> None:
    """Launch the new app executable."""
    if sys.platform == "darwin":
        app_path = target / launch_name
        subprocess.Popen(["open", str(app_path)])
    elif sys.platform == "win32":
        exe = target / f"{launch_name}.exe"
        subprocess.Popen([str(exe)], creationflags=subprocess.DETACHED_PROCESS)
    else:
        exe = target / launch_name
        subprocess.Popen([str(exe)], preexec_fn=os.setpgrp)


def cleanup(staging_dir: Path) -> None:
    """Remove staging directory."""
    shutil.rmtree(staging_dir, ignore_errors=True)


def run_updater_mode() -> None:
    """Main entry for updater mode. Called when --updater is detected."""
    args = parse_update_args()
    log.info("Updater mode: source=%s target=%s", args.source, args.target)

    # Validate paths
    if not args.source.exists():
        log.error("Source directory does not exist: %s", args.source)
        sys.exit(1)
    if not args.target.exists():
        log.error("Target directory does not exist: %s", args.target)
        sys.exit(1)

    # Step 1: Wait for old process
    log.info("Waiting for old process %d to exit...", args.old_pid)
    wait_for_process_exit(args.old_pid, args.timeout)

    # Step 2: Backup (optional)
    backup_dir = None
    if args.backup:
        backup_dir = args.target.with_suffix(".backup")
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(args.target, backup_dir)
        log.info("Backup created: %s", backup_dir)

    # Step 3: Replace files
    try:
        replace_files(args.source, args.target)
        log.info("Files replaced successfully")
    except Exception:
        log.exception("Failed to replace files")
        if backup_dir and backup_dir.exists():
            log.info("Restoring from backup...")
            shutil.rmtree(args.target)
            shutil.copytree(backup_dir, args.target)
        sys.exit(1)

    # Step 4: Launch new app
    log.info("Launching new app: %s/%s", args.target, args.launch)
    launch_app(args.target, args.launch)

    # Step 5: Cleanup
    cleanup(args.source)
    if backup_dir and backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)

    log.info("Update complete")
    sys.exit(0)


if __name__ == "__main__":
    run_updater_mode()
