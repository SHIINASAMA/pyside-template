import enum
import json
import os
import platform
import shutil
import subprocess
import sys
from abc import abstractmethod, ABC
from pathlib import Path
from packaging.version import Version as BuiltinVersion

from httpx import AsyncClient
import psutil

from app.resources.version import __version__
from app.builtin.args import pop_arg, pop_arg_pair
from app.builtin.paths import AppPaths
import app.builtin.config as cfg


def get_sysname() -> str:
    sysname = platform.system().lower()
    if sysname == "windows":
        sysname = "windows"
    elif sysname == "darwin":
        sysname = "macos"
    elif sysname == "linux":
        sysname = "linux"
    else:
        raise RuntimeError(f"Unknown system: {sysname}")
    return sysname


def get_arch() -> str:
    arch = platform.machine().lower()
    if arch in ["x86_64", "amd64"]:
        arch = "x64"
    elif arch in ["aarch64", "arm64"]:
        arch = "arm64"
    else:
        raise RuntimeError(f"Unknown architecture: {arch}")
    return arch


class ReleaseType(enum.Enum):
    STABLE = "stable"
    BETA = "beta"
    ALPHA = "alpha"
    DEV = "dev"
    NIGHTLY = "nightly"


class Version(BuiltinVersion):
    def __init__(self, version_string: str):
        version_part = version_string.split("-")
        super().__init__(version_part[0])
        if len(version_part) == 1:
            self.release_type = ReleaseType.STABLE
            return
        if version_part[1] == "stable":
            self.release_type = ReleaseType.STABLE
        elif version_part[1] == "beta":
            self.release_type = ReleaseType.BETA
        elif version_part[1] == "alpha":
            self.release_type = ReleaseType.ALPHA
        elif version_part[1] == "dev":
            self.release_type = ReleaseType.DEV
        elif version_part[1] == "nightly":
            self.release_type = ReleaseType.NIGHTLY
        else:
            raise RuntimeError(f"Unknown release type: {version_part[1]}")

    def __str__(self):
        return f"{super().__str__()}-{self.release_type.value}"

    def get_number_version(self):
        """Get the version as a tuple of integers."""
        return super().__str__()


class Updater(ABC):
    timeout: int = 30

    _copy_self_cmd = "--updater-copy-self"
    _updated_cmd = "--updater-updated"
    _disable_cmd = "--updater-disable"
    _old_pid_cmd = "--updater-old-pid"
    _old_dir_cmd = "--updater-old-dir"

    current_version: Version

    def __init__(self):
        # Three attributes can be set by updater.json
        self.current_version = Updater._load_current_version()
        self.release_type = self.current_version.release_type
        self.proxy = None

        # must set in self.fetch()
        self.remote_version = None
        self.description = ""
        self.download_url = ""
        self.filename = ""

        # cmd line args
        self.is_updated = False
        self.is_enable = True
        if pop_arg(Updater._copy_self_cmd, False):
            Updater.copy_self_and_exit()
        if pop_arg(Updater._updated_cmd, False):
            self.is_updated = True
            Updater.clean_old_package()
        if pop_arg(Updater._disable_cmd, False):
            self.is_enable = False

    def load_from_file_and_override(self, file: str | Path):
        """Load updater configuration from a JSON file."""
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)

        version: str = data.get("version", None)
        if version is not None:
            self.current_version = Version(version)
        self.proxy = data.get("proxy", None)
        self.release_type = ReleaseType(data.get("channel", "stable"))

    @abstractmethod
    def create_async_client(self) -> AsyncClient:
        pass

    @abstractmethod
    async def fetch(self):
        pass

    @staticmethod
    def _load_current_version():
        """Get version from app"""
        return Version(__version__)

    def check_for_update(self):
        assert isinstance(self.remote_version, Version)
        return (
            self.release_type == self.remote_version.release_type
            and self.remote_version > self.current_version
        )

    @staticmethod
    def apply_update():
        """
        Call `New Executable` to copy itself to current work directory and run it.
        Will call `sys.exit(0)` automatically.
        """
        pid = os.getpid()
        paths = AppPaths()
        if sys.platform == "darwin":
            new_executable_name = f"{paths.update_dir}/{cfg.APP_NAME}.app"
            subprocess.Popen(
                [
                    "open",
                    new_executable_name,
                    "--args",
                    Updater._copy_self_cmd,
                    Updater._old_pid_cmd,
                    str(pid),
                    Updater._old_dir_cmd,
                    os.getcwd(),
                ],
                preexec_fn=os.setpgrp,
                env=os.environ.copy(),
                cwd=paths.update_dir,
            )
        elif sys.platform == "linux":
            new_executable_name = Path(f"{paths.update_dir}/{cfg.APP_NAME}")
            work_dir = Path(f"{paths.update_dir}")
            if new_executable_name.is_dir():
                # Onedir
                work_dir = new_executable_name
                new_executable_name = new_executable_name / cfg.APP_NAME
            subprocess.Popen(
                [
                    new_executable_name,
                    Updater._copy_self_cmd,
                    Updater._old_pid_cmd,
                    str(pid),
                    Updater._old_dir_cmd,
                    os.getcwd(),
                ],
                preexec_fn=os.setpgrp,
                env=os.environ.copy(),
                cwd=work_dir,
            )
        else:  # win32
            new_executable_name = Path(f"{paths.update_dir}/{cfg.APP_NAME}")
            new_executable_name_with_exe = Path(
                f"{paths.update_dir}/{cfg.APP_NAME}.exe"
            )
            work_dir = Path(f"{paths.update_dir}")
            if new_executable_name.is_dir():
                # Onedir
                work_dir = new_executable_name
                new_executable_name = new_executable_name / f"{cfg.APP_NAME}.exe"
            elif new_executable_name_with_exe.is_file():
                # Onefile
                new_executable_name = new_executable_name_with_exe
            subprocess.Popen(
                [
                    f"{new_executable_name}",
                    Updater._copy_self_cmd,
                    Updater._old_pid_cmd,
                    str(pid),
                    Updater._old_dir_cmd,
                    os.getcwd(),
                ],
                creationflags=subprocess.DETACHED_PROCESS,
                env=os.environ.copy(),
                cwd=work_dir,
            )

        sys.exit(0)

    @staticmethod
    def copy_self_and_exit():
        """Copy current executable to raw directory and run it with --updated argument."""
        # Wait for the old executable to exit
        old_pid = int(pop_arg_pair(Updater._old_pid_cmd))
        old_dir = pop_arg_pair(Updater._old_dir_cmd)
        try:
            old_process = psutil.Process(old_pid)
            old_process.wait()
        except psutil.NoSuchProcess:
            pass

        parent_dir = Path(old_dir)
        current_dir = Path(os.getcwd())
        filelist = parent_dir / "filelist.txt"
        # delete files by ../filelist.txt if it exists, workdir is parent directory
        if filelist.exists():
            with open(filelist, "r", encoding="utf-8") as f:
                for line in f:
                    path = line.strip()
                    if not path:
                        continue
                    abs_path = parent_dir / path
                    try:
                        if abs_path.is_file():
                            abs_path.unlink()
                        elif abs_path.is_dir():
                            shutil.rmtree(abs_path)
                    except Exception:
                        continue

        # Copy current directory to parent directory
        if sys.platform == "darwin":
            old_bundle = f"{parent_dir}/{cfg.APP_NAME}.app"
            new_bundle = f"{os.getcwd()}/{cfg.APP_NAME}.app"
            shutil.rmtree(old_bundle)
            subprocess.run(f"ditto {new_bundle} {old_bundle}", check=True)
        else:
            for item in current_dir.iterdir():
                target = parent_dir / item.name
                try:
                    if item.is_file():
                        shutil.copy2(item, target)
                    elif item.is_dir():
                        if target.exists():
                            shutil.rmtree(target)
                        shutil.copytree(item, target)
                except Exception:
                    continue

        # Run copied executable with --updated argument
        options = [
            Updater._updated_cmd,
            Updater._old_pid_cmd,
            str(os.getpid()),
        ]
        if sys.platform == "win32":
            new_executable = f"{parent_dir}/{cfg.APP_NAME}.exe"
            subprocess.Popen(
                [new_executable] + options,
                creationflags=subprocess.DETACHED_PROCESS,
                env=os.environ.copy(),
            )
        elif sys.platform == "darwin":
            # f"/Applications/{CFG.APP_NAME}.app"
            new_executable = f"{parent_dir}/{cfg.APP_NAME}.app"
            subprocess.Popen(
                ["open", new_executable, "--args"] + options,
                preexec_fn=os.setpgrp,
                env=os.environ.copy(),
            )
        else:
            new_executable = f"{parent_dir}/{cfg.APP_NAME}"
            subprocess.Popen(
                [new_executable] + options,
                preexec_fn=os.setpgrp,
                env=os.environ.copy(),
            )
        sys.exit(0)

    @staticmethod
    def clean_old_package():
        """Delete Package directory"""
        # Wait for the old executable to exit
        old_pid = int(pop_arg_pair(Updater._old_pid_cmd))
        try:
            old_process = psutil.Process(old_pid)
            old_process.wait()
        except psutil.NoSuchProcess:
            pass

        # Remove files in package_dir
        paths = AppPaths()
        package_dir = paths.update_dir
        if package_dir.exists() and package_dir.is_dir():
            for entry in os.scandir(package_dir):
                entry_path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry_path, ignore_errors=True)
                else:
                    try:
                        entry_path.unlink()
                    except FileNotFoundError:
                        pass
