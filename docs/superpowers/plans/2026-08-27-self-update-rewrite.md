# pyside-template Self-Update Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken three-process self-update mechanism with a working two-process model on Linux/Windows and Sparkle on macOS.

**Architecture:** The old `app/builtin/update.py` monolith (which mixes Version parsing, platform detection, GitHub/GitLab API, and a broken 3-process file-copy dance) is replaced by a clean `app/builtin/updater/` package with single-responsibility modules. On Linux/Windows, the app detects `--updater` at startup and enters a lightweight updater mode that waits for the old process, replaces files, and relaunches. On macOS, Sparkle via PyObjC handles updates (deferred to a separate plan). Checksum verification (sha256) is added to downloads.

**Tech Stack:** Python 3.13+, httpx, packaging, pytest, PySide6, qasync

**Spec:** `docs/superpowers/plans/2026-08-27-self-update-rewrite.md` (this document); design notes in Obsidian `projects/pyside-template/自更新重构方案.md`

## Global Constraints

- `requires-python = ">=3.13"` (pyproject.toml)
- Existing tests in `app/test/` use `pytest` with `anyio` for async
- No new third-party dependencies allowed (glom removed, psutil removed)
- macOS .app bundle self-update is out of scope (deferred to Sparkle plan)
- `app/builtin/config.py` constants remain module-level mutable globals
- `app/builtin/paths.py` AppPaths stays as `@singleton`

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `app/builtin/updater/__init__.py` | Package init, re-exports public API |
| Create | `app/builtin/updater/platform.py` | `get_sysname()`, `get_arch()` |
| Create | `app/builtin/updater/base.py` | `Version`, `ReleaseType`, `Updater` ABC |
| Create | `app/builtin/updater/github.py` | `GithubUpdater` (no glom) |
| Create | `app/builtin/updater/gitlab.py` | `GitlabUpdater` (no glom) |
| Create | `app/builtin/updater/downloader.py` | `download_with_checksum()`, `fetch_checksum()` |
| Create | `app/builtin/updater/extractor.py` | `extract()` |
| Create | `app/builtin/updater/run_update.py` | `run_updater_mode()` entry point |
| Modify | `app/__main__.py` | Add `--updater` detection, import from new package |
| Modify | `app/main_window.py` | Use new updater API + downloader |
| Modify | `app/builtin/update_widget.py` | Use new downloader + extractor |
| Delete | `app/builtin/update.py` | Replaced by updater/base.py + platform.py |
| Delete | `app/builtin/github_updater.py` | Replaced by updater/github.py |
| Delete | `app/builtin/gitlab_updater.py` | Replaced by updater/gitlab.py |
| Delete | `app/builtin/utils.py` | `get_updater()` → updater/__init__.py, `init_app()` → stays or moves |
| Modify | `app/builtin/config.py` | Add `UPDATER_TIMEOUT` default (already exists) |
| Create | `app/test/test_updater_base.py` | Tests for Version, ReleaseType, platform |
| Create | `app/test/test_updater_github.py` | Tests for GithubUpdater.fetch |
| Create | `app/test/test_updater_downloader.py` | Tests for download + checksum |
| Create | `app/test/test_run_update.py` | Tests for updater mode entry |
| Modify | `app/test/test_update.py` | Update imports to new package paths |
| Modify | `pyproject.toml` | Remove `glom` from dependencies |
| Modify | `.github/workflows/release.yml` | Add sha256 checksum generation |

---

### Task 1: Create updater/platform.py and updater/base.py

**Files:**
- Create: `app/builtin/updater/__init__.py`
- Create: `app/builtin/updater/platform.py`
- Create: `app/builtin/updater/base.py`
- Create: `app/test/test_updater_base.py`

**Interfaces:**
- Produces: `get_sysname() -> str`, `get_arch() -> str`
- Produces: `Version(version_string: str)`, `ReleaseType` enum, `Updater` ABC with `check_for_update() -> bool`, `timeout`, `current_version`, `remote_version`, `description`, `download_url`, `filename`, `release_type`, `is_enable`, `is_updated`, `proxy`
- Produces: `get_updater() -> Updater` (factory), `running_in_bundle() -> bool`

- [ ] **Step 1: Create package init**

```python
# app/builtin/updater/__init__.py
from app.builtin.updater.base import Version, ReleaseType, Updater, get_updater, running_in_bundle
from app.builtin.updater.platform import get_sysname, get_arch

__all__ = [
    "Version", "ReleaseType", "Updater",
    "get_updater", "running_in_bundle",
    "get_sysname", "get_arch",
]
```

- [ ] **Step 2: Create platform.py**

```python
# app/builtin/updater/platform.py
import platform


def get_sysname() -> str:
    sysname = platform.system().lower()
    if sysname == "windows":
        return "windows"
    elif sysname == "darwin":
        return "macos"
    elif sysname == "linux":
        return "linux"
    else:
        raise RuntimeError(f"Unknown system: {sysname}")


def get_arch() -> str:
    arch = platform.machine().lower()
    if arch in ("x86_64", "amd64"):
        return "x64"
    elif arch in ("aarch64", "arm64"):
        return "arm64"
    else:
        raise RuntimeError(f"Unknown architecture: {arch}")
```

- [ ] **Step 3: Create base.py**

Extract `Version`, `ReleaseType`, `Updater` from old `update.py`. Remove the three-process methods (`apply_update`, `copy_self_and_exit`, `clean_old_package`). Remove `psutil` and `args` imports. Move `get_updater()` and `running_in_bundle()` here.

```python
# app/builtin/updater/base.py
import enum
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from packaging.version import Version as BuiltinVersion
from httpx import AsyncClient

from app.resources.version import __version__


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
        type_map = {t.value: t for t in ReleaseType}
        suffix = version_part[1]
        if suffix not in type_map:
            raise RuntimeError(f"Unknown release type: {suffix}")
        self.release_type = type_map[suffix]

    def __str__(self):
        return f"{super().__str__()}-{self.release_type.value}"

    def get_number_version(self) -> str:
        return super().__str__()


class Updater(ABC):
    timeout: int = 30
    current_version: Version

    def __init__(self):
        self.current_version = self._load_current_version()
        self.release_type = self.current_version.release_type
        self.proxy = None
        self.remote_version: Version | None = None
        self.description: str = ""
        self.download_url: str = ""
        self.filename: str = ""
        self.is_updated: bool = False
        self.is_enable: bool = True

    @staticmethod
    def _load_current_version() -> Version:
        return Version(__version__)

    def check_for_update(self) -> bool:
        assert isinstance(self.remote_version, Version)
        return (
            self.release_type == self.remote_version.release_type
            and self.remote_version > self.current_version
        )

    @abstractmethod
    def create_async_client(self) -> AsyncClient: ...

    @abstractmethod
    async def fetch(self): ...


# --- Factory ---

_updater_instance = None


def get_updater():
    global _updater_instance
    import app.builtin.config as cfg
    from app.builtin.updater.github import GithubUpdater
    from app.builtin.updater.gitlab import GitlabUpdater

    match cfg.UPDATER_REMOTE_TYPE:
        case "GitHub":
            cls = GithubUpdater
        case "GitLab":
            cls = GitlabUpdater
        case _:
            raise ValueError(f"Unsupported updater remote type: {cfg.UPDATER_REMOTE_TYPE}")

    if _updater_instance is None or type(_updater_instance) is not cls:
        _updater_instance = cls()

    _updater_instance.base_url = cfg.UPDATER_URL
    _updater_instance.project_name = cfg.UPDATER_PROJECT_NAME
    _updater_instance.app_name = cfg.UPDATER_APP_NAME
    _updater_instance.timeout = cfg.UPDATER_TIMEOUT
    return _updater_instance


def running_in_bundle() -> bool:
    if sys.platform != "darwin":
        return False
    exe_path = Path(sys.executable).resolve()
    return ".app/Contents/MacOS" in str(exe_path)
```

- [ ] **Step 4: Write tests for base.py**

```python
# app/test/test_updater_base.py
import pytest
from app.builtin.updater.base import Version, ReleaseType


class TestVersion:
    def test_parse_stable(self):
        v = Version("1.2.3")
        assert v.release_type == ReleaseType.STABLE

    def test_parse_beta(self):
        v = Version("1.2.3-beta")
        assert v.release_type == ReleaseType.BETA

    def test_parse_alpha(self):
        v = Version("1.0.0-alpha")
        assert v.release_type == ReleaseType.ALPHA

    def test_compare(self):
        assert Version("2.0.0") > Version("1.0.0")
        assert Version("1.0.1") > Version("1.0.0")
        assert Version("1.0.0") == Version("1.0.0")

    def test_compare_different_channel(self):
        assert not (Version("2.0.0-beta") > Version("1.0.0"))


class TestGetSysname:
    def test_returns_valid(self):
        from app.builtin.updater.platform import get_sysname
        assert get_sysname() in ("linux", "macos", "windows")


class TestGetArch:
    def test_returns_valid(self):
        from app.builtin.updater.platform import get_arch
        assert get_arch() in ("x64", "arm64")
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/kaoru/Developer/pyside-template && uv run pytest app/test/test_updater_base.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add app/builtin/updater/ app/test/test_updater_base.py
git commit -m "refactor: create updater/ package with Version, ReleaseType, platform detection"
```

---

### Task 2: Create updater/github.py and updater/gitlab.py

**Files:**
- Create: `app/builtin/updater/github.py`
- Create: `app/builtin/updater/gitlab.py`
- Create: `app/test/test_updater_github.py`

**Interfaces:**
- Consumes: `Version`, `ReleaseType`, `Updater` from base.py, `get_sysname`, `get_arch` from platform.py
- Produces: `GithubUpdater`, `GitlabUpdater` — both implement `Updater` ABC, set `remote_version`, `description`, `download_url`, `filename` after `fetch()`

- [ ] **Step 1: Create github.py**

```python
# app/builtin/updater/github.py
from httpx import AsyncClient
from app.builtin.updater.base import Updater, Version
from app.builtin.updater.platform import get_arch, get_sysname
from app.builtin.paths import AppPaths


class GithubUpdater(Updater):
    base_url: str = "https://api.github.com"
    project_name: str = ""
    app_name: str = "App"
    token = None
    _headers = None

    def create_async_client(self) -> AsyncClient:
        if not self._headers:
            headers = {"Accept": "application/vnd.github+json"}
            if self.token:
                headers["Authorization"] = f"token {self.token}"
            self._headers = headers
        return AsyncClient(proxy=self.proxy, headers=self._headers, timeout=self.timeout)

    async def fetch(self):
        async with self.create_async_client() as client:
            r = await client.get(
                url=f"{self.base_url}/repos/{self.project_name}/releases",
                params={"per_page": "100", "page": "1"},
                follow_redirects=True,
            )
            r.raise_for_status()
            releases = []
            for release in r.json():
                version = Version(release["tag_name"])
                if version.release_type == self.release_type:
                    releases.append(release)
            latest_release = max(
                releases, key=lambda x: Version(x["tag_name"]), default=None
            )
            if latest_release is None:
                self.remote_version = Version("0.0.0.0")
                return
            self.remote_version = Version(latest_release["tag_name"])
            self.description = latest_release["body"]

            arch = get_arch()
            sysname = get_sysname()
            package_name = f"{self.app_name}-{sysname}-{arch}"

            self.download_url = None
            for asset in latest_release.get("assets", []):
                if package_name in asset["name"]:
                    package_name = asset["name"]
                    self.download_url = asset["browser_download_url"]
                    break

            if self.download_url is None:
                raise FileNotFoundError(
                    f"Package {package_name} not found in release assets."
                )

            r = await client.head(url=self.download_url, follow_redirects=True)
            r.raise_for_status()

            paths = AppPaths()
            self.filename = f"{paths.update_dir}/{package_name}"
```

- [ ] **Step 2: Create gitlab.py**

```python
# app/builtin/updater/gitlab.py
import os
from urllib.parse import urlparse
from httpx import AsyncClient
from app.builtin.updater.base import Updater, Version
from app.builtin.updater.platform import get_arch, get_sysname
from app.builtin.paths import AppPaths


class GitlabUpdater(Updater):
    base_url: str = "https://gitlab.com"
    project_name: str = ""
    app_name: str = "App"
    token = None
    _headers = None

    def create_async_client(self) -> AsyncClient:
        if not self._headers:
            headers = {}
            if self.token:
                headers["PRIVATE-TOKEN"] = self.token
            self._headers = headers
        return AsyncClient(proxy=self.proxy, headers=self._headers, timeout=self.timeout)

    async def fetch(self):
        async with self.create_async_client() as client:
            r = await client.get(
                url=f"{self.base_url}/api/v4/projects",
                params={"search": self.project_name, "search_namespaces": "true"},
            )
            r.raise_for_status()
            projects = r.json()
            if not projects:
                raise FileNotFoundError(
                    f"Project {self.project_name} not found on GitLab: {self.base_url}"
                )
            project_id = projects[0]["id"]
            r = await client.get(
                url=f"{self.base_url}/api/v4/projects/{project_id}/releases",
                params={"per_page": 1},
            )
            r.raise_for_status()

            releases = []
            for release in r.json():
                version = Version(release["tag_name"])
                if version.release_type == self.release_type:
                    releases.append(release)
            latest_release = max(
                releases, key=lambda x: Version(x["tag_name"]), default=None
            )
            if latest_release is None:
                self.remote_version = Version("0.0.0.0")
                return

            self.remote_version = Version(latest_release["tag_name"])
            self.description = latest_release["description"]

            arch = get_arch()
            sysname = get_sysname()
            package_name = f"{self.app_name}-{sysname}-{arch}"

            self.download_url = None
            for link in latest_release.get("assets", {}).get("links", []):
                if package_name in link["name"]:
                    package_name = link["name"]
                    self.download_url = link["url"]
                    break
            if self.download_url is None:
                raise FileNotFoundError(
                    f"Package {package_name} not found in release assets."
                )

            r = await client.head(url=self.download_url)
            r.raise_for_status()

            path = urlparse(self.download_url).path
            paths = AppPaths()
            self.filename = f"{paths.update_dir}/{os.path.basename(path)}"
```

- [ ] **Step 3: Write tests for github.py**

```python
# app/test/test_updater_github.py
from unittest.mock import MagicMock, AsyncMock, patch
import anyio
from app.builtin.updater.github import GithubUpdater
from app.builtin.updater.base import Version, ReleaseType


class TestGithubUpdaterFetch:
    def test_fetch_uses_per_page_and_page(self):
        class FakeResponse:
            raise_for_status = MagicMock()
            json = MagicMock(return_value=[])

        async def run():
            u = GithubUpdater()
            u.current_version = Version("1.0.0")
            u.release_type = ReleaseType.STABLE
            u.base_url = "https://api.github.com"
            u.project_name = "test/repo"
            u.app_name = "App"

            mock_response = FakeResponse()
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()

            with patch.object(u, "create_async_client", return_value=mock_client):
                await u.fetch()

            call_kwargs = mock_client.get.call_args[1]
            params = call_kwargs.get("params", {})
            assert params.get("per_page") == "100"
            assert params.get("page") == "1"
            assert u.remote_version == Version("0.0.0.0")

        anyio.run(run)

    def test_fetch_finds_matching_release(self):
        async def run():
            u = GithubUpdater()
            u.current_version = Version("1.0.0")
            u.release_type = ReleaseType.STABLE
            u.base_url = "https://api.github.com"
            u.project_name = "test/repo"
            u.app_name = "App"

            mock_release_response = MagicMock()
            mock_release_response.raise_for_status = MagicMock()
            mock_release_response.json = MagicMock(return_value=[
                {"tag_name": "2.0.0", "body": "new version", "assets": [
                    {"name": "App-linux-x64-2.0.0.tar.gz", "browser_download_url": "https://example.com/app.tar.gz"}
                ]}
            ])

            mock_head_response = MagicMock()
            mock_head_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_release_response)
            mock_client.head = AsyncMock(return_value=mock_head_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()

            with patch.object(u, "create_async_client", return_value=mock_client):
                await u.fetch()

            assert u.remote_version == Version("2.0.0")
            assert u.description == "new version"
            assert "2.0.0" in u.filename

        anyio.run(run)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kaoru/Developer/pyside-template && uv run pytest app/test/test_updater_github.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add app/builtin/updater/github.py app/builtin/updater/gitlab.py app/test/test_updater_github.py
git commit -m "refactor: add github.py and gitlab.py without glom dependency"
```

---

### Task 3: Create downloader.py and extractor.py

**Files:**
- Create: `app/builtin/updater/downloader.py`
- Create: `app/builtin/updater/extractor.py`
- Create: `app/test/test_updater_downloader.py`

**Interfaces:**
- Produces: `download_with_checksum(url: str, dest: Path, expected_sha256: str | None, progress_callback: Callable | None) -> Path`
- Produces: `fetch_checksum(url: str, client: AsyncClient) -> str | None`
- Produces: `extract(archive_path: Path, dest_dir: Path) -> Path`

- [ ] **Step 1: Create downloader.py**

```python
# app/builtin/updater/downloader.py
import hashlib
from pathlib import Path
from typing import Callable
from httpx import AsyncClient


async def fetch_checksum(url: str, client: AsyncClient) -> str | None:
    """Fetch sha256 checksum from a .sha256 file URL. Returns hash string or None."""
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
        text = r.text.strip()
        # Format: "<hash>  <filename>" or just "<hash>"
        return text.split()[0] if text else None
    except Exception:
        return None


async def download_with_checksum(
    url: str,
    dest: Path,
    expected_sha256: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """Download a file, optionally verify sha256. Returns dest path."""
    sha = hashlib.sha256()
    async with AsyncClient(follow_redirects=True) as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))
            downloaded = 0

            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes(8192):
                    f.write(chunk)
                    sha.update(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

    if expected_sha256 and sha.hexdigest() != expected_sha256:
        dest.unlink(missing_ok=True)
        raise ValueError(
            f"Checksum mismatch: expected {expected_sha256}, got {sha.hexdigest()}"
        )

    return dest
```

- [ ] **Step 2: Create extractor.py**

```python
# app/builtin/updater/extractor.py
import os
from pathlib import Path


def extract(archive_path: Path, dest_dir: Path) -> Path:
    """Extract a zip or tar.gz archive into dest_dir. Returns dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    if archive_path.name.endswith(".zip") or archive_path.suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    elif archive_path.name.endswith((".tar.gz", ".tgz")):
        import tarfile
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(dest_dir)
    else:
        raise RuntimeError(f"Unsupported archive format: {archive_path.name}")

    return dest_dir
```

- [ ] **Step 3: Write tests**

```python
# app/test/test_updater_downloader.py
import hashlib
import zipfile
from pathlib import Path
import pytest
from app.builtin.updater.extractor import extract


class TestExtractor:
    def test_extract_zip(self, tmp_path):
        archive = tmp_path / "test.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("hello.txt", "hello world")

        dest = tmp_path / "out"
        result = extract(archive, dest)
        assert (result / "hello.txt").read_text() == "hello world"

    def test_extract_unsupported(self, tmp_path):
        archive = tmp_path / "test.rar"
        archive.write_text("fake")
        dest = tmp_path / "out"
        with pytest.raises(RuntimeError, match="Unsupported"):
            extract(archive, dest)


class TestDownloaderChecksum:
    def test_sha256_calculation(self, tmp_path):
        """Test that we can compute sha256 of a file (unit test, no network)."""
        data = b"hello world"
        expected = hashlib.sha256(data).hexdigest()
        f = tmp_path / "test.bin"
        f.write_bytes(data)
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual == expected
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kaoru/Developer/pyside-template && uv run pytest app/test/test_updater_downloader.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add app/builtin/updater/downloader.py app/builtin/updater/extractor.py app/test/test_updater_downloader.py
git commit -m "feat: add downloader with sha256 checksum and extractor modules"
```

---

### Task 4: Create run_update.py (Linux/Windows updater mode)

**Files:**
- Create: `app/builtin/updater/run_update.py`
- Create: `app/test/test_run_update.py`

**Interfaces:**
- Produces: `run_updater_mode()` — called when `--updater` is in sys.argv
- Produces: `parse_update_args() -> UpdateArgs`, `wait_for_process_exit(pid, timeout)`, `replace_files_linux(src, dst)`, `replace_files_windows(src, dst)`, `launch_app(target, launch_name)`, `cleanup(staging_dir)`

- [ ] **Step 1: Create run_update.py**

```python
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
            ["rsync", "-a", "--delete", f"{source}/", f"{target}/"],
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
```

- [ ] **Step 2: Write tests**

```python
# app/test/test_run_update.py
import os
import sys
from pathlib import Path
from unittest.mock import patch
from app.builtin.updater.run_update import (
    parse_update_args, wait_for_process_exit, replace_files, cleanup,
)


class TestParseUpdateArgs:
    def test_parse_all_flags(self):
        fake_argv = [
            "app", "--updater",
            "--updater-source", "/tmp/staging",
            "--updater-target", "/opt/app",
            "--updater-launch", "App",
            "--updater-old-pid", "12345",
            "--backup",
            "--updater-timeout", "60",
        ]
        with patch.object(sys, "argv", fake_argv):
            args = parse_update_args()
        assert args.source == Path("/tmp/staging")
        assert args.target == Path("/opt/app")
        assert args.launch == "App"
        assert args.old_pid == 12345
        assert args.backup is True
        assert args.timeout == 60

    def test_parse_defaults(self):
        fake_argv = ["app", "--updater"]
        with patch.object(sys, "argv", fake_argv):
            args = parse_update_args()
        assert args.old_pid == 0
        assert args.backup is False
        assert args.timeout == 30


class TestWaitForProcessExit:
    def test_nonexistent_pid_exits_immediately(self):
        # PID -1 does not exist, should return quickly
        wait_for_process_exit(-1, timeout=1)


class TestCleanup:
    def test_removes_directory(self, tmp_path):
        d = tmp_path / "staging"
        d.mkdir()
        (d / "file.txt").write_text("test")
        cleanup(d)
        assert not d.exists()
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/kaoru/Developer/pyside-template && uv run pytest app/test/test_run_update.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add app/builtin/updater/run_update.py app/test/test_run_update.py
git commit -m "feat: add updater mode entry point for Linux/Windows two-process model"
```

---

### Task 5: Rewrite __main__.py, main_window.py, update_widget.py

**Files:**
- Modify: `app/__main__.py`
- Modify: `app/main_window.py`
- Modify: `app/builtin/update_widget.py`

**Interfaces:**
- Consumes: `get_updater()` from `app.builtin.updater`
- Consumes: `run_updater_mode()` from `app.builtin.updater.run_update`
- Consumes: `download_with_checksum()`, `fetch_checksum()` from `app.builtin.updater.downloader`
- Consumes: `extract()` from `app.builtin.updater.extractor`

- [ ] **Step 1: Rewrite __main__.py**

```python
# app/__main__.py
import asyncio
import os
import sys

from PySide6.QtCore import QTranslator, QLockFile
from qasync import QApplication, run

from app.builtin.locale import detect_system_ui_language
from app.builtin.utils import init_app, running_in_bundle
from app.builtin.updater import get_updater
from app.builtin.paths import AppPaths
from app.main_window import MainWindow


async def task():
    app_close_event = asyncio.Event()
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    app.aboutToQuit.connect(app_close_event.set)

    main_window = MainWindow()
    main_window.show()
    await main_window.async_init()
    await app_close_event.wait()


def main(enable_updater: bool = True):
    # Updater mode: if --updater is in argv, run updater and exit
    if "--updater" in sys.argv:
        from app.builtin.updater.run_update import run_updater_mode
        run_updater_mode()
        return

    # Normal mode
    app = init_app()
    paths = AppPaths()

    updater = get_updater()
    updater.is_enable = False if running_in_bundle() else enable_updater

    config_file = paths.update_dir / "updater.json"
    if os.getenv("DEBUG", "0") == "1" and config_file.exists() and config_file.is_file():
        updater.load_from_file_and_override(config_file)

    lock_file = QLockFile(str(paths.base_dir) + "/App.lock")
    if not lock_file.lock():
        sys.exit(0)

    translator = QTranslator()
    lang_code = detect_system_ui_language()
    translator.load(f":/i18n/{lang_code}.qm")
    app.installTranslator(translator)

    run(task())


def main_no_updater():
    main(enable_updater=False)


def run_module():
    main()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Rewrite main_window.py**

Replace `updater.apply_update()` with spawn of `--updater` mode. Use new downloader for checksum verification.

```python
# app/main_window.py
import asyncio
import os
import subprocess
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMessageBox, QMainWindow
from httpx import HTTPError
from qasync import asyncSlot
from qdarktheme import setup_theme

import app.resources.resource  # type: ignore
from app.builtin.update_widget import UpdateWidget
from app.builtin.updater import get_updater
from app.builtin.updater.downloader import fetch_checksum, download_with_checksum
from app.builtin.updater.extractor import extract
from app.builtin.paths import AppPaths
from app.resources.main_window_ui import Ui_MainWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.ui.pushButton.clicked.connect(self.click_push_button)

        self.ui.themeComboBox.addItem(self.tr("Auto"), "auto")
        self.ui.themeComboBox.addItem(self.tr("Light"), "light")
        self.ui.themeComboBox.addItem(self.tr("Dark"), "dark")
        self.ui.themeComboBox.currentIndexChanged.connect(self.change_theme)
        self.ui.themeComboBox.setCurrentIndex(0)
        self.change_theme(0)

        self.setWindowTitle(self.tr("MainWindow"))
        self.setWindowIcon(QIcon(":/logo.png"))

    async def async_init(self):
        if os.getenv("DEBUG", "0") == "1":
            pass
        else:
            await self.check_update()

    async def check_update(self):
        updater = get_updater()
        if not updater.is_enable:
            return
        if not updater.is_updated:
            try:
                await updater.fetch()
                if updater.check_for_update():
                    update_widget = UpdateWidget(self, updater)
                    await update_widget.async_show()
                    if update_widget.need_restart:
                        await self._perform_update(updater)
            except HTTPError:
                QMessageBox.warning(
                    self, self.tr("Warning"), self.tr("Failed to check for updates"),
                )
            except FileNotFoundError:
                QMessageBox.warning(
                    self, self.tr("Warning"), self.tr("No update files found"),
                )
            except Exception as e:
                QMessageBox.warning(
                    self, self.tr("Warning"),
                    self.tr("Excepted unknown error: {}").format(str(e)),
                )
        else:
            QMessageBox.information(
                self, self.tr("Info"), self.tr("Update completed"),
            )

    async def _perform_update(self, updater):
        """Download, verify, extract, then spawn updater mode and exit."""
        paths = AppPaths()
        staging_dir = paths.update_dir / "staging"
        if staging_dir.exists():
            import shutil
            shutil.rmtree(staging_dir)

        # Fetch checksum
        sha256_url = updater.download_url + ".sha256"
        expected_sha256 = await fetch_checksum(
            sha256_url, updater.create_async_client()
        )

        # Download
        await download_with_checksum(
            updater.download_url, updater.filename, expected_sha256
        )

        # Extract
        extract(updater.filename, staging_dir)

        # Find executable in staging
        launch_name = self._find_launch_name(staging_dir)
        if not launch_name:
            QMessageBox.warning(
                self, self.tr("Warning"), self.tr("Cannot find executable in update package"),
            )
            return

        # Spawn updater mode
        exe = sys.executable
        args = [
            exe, "--updater",
            "--updater-source", str(staging_dir),
            "--updater-target", str(Path(exe).parent),
            "--updater-launch", launch_name,
            "--updater-old-pid", str(os.getpid()),
            "--backup",
        ]

        subprocess.Popen(args)
        QApplication.quit()

    def _find_launch_name(self, staging_dir):
        """Find the app executable in the staging directory."""
        import app.builtin.config as cfg
        if sys.platform == "darwin":
            app_path = staging_dir / f"{cfg.APP_NAME}.app"
            if app_path.exists():
                return f"{cfg.APP_NAME}.app"
        elif sys.platform == "win32":
            exe = staging_dir / f"{cfg.APP_NAME}.exe"
            if exe.exists():
                return cfg.APP_NAME
            # Check subdirectory (onedir)
            for d in staging_dir.iterdir():
                if d.is_dir():
                    exe = d / f"{cfg.APP_NAME}.exe"
                    if exe.exists():
                        return cfg.APP_NAME
        else:
            exe = staging_dir / cfg.APP_NAME
            if exe.exists():
                return cfg.APP_NAME
            for d in staging_dir.iterdir():
                if d.is_dir():
                    exe = d / cfg.APP_NAME
                    if exe.exists():
                        return cfg.APP_NAME
        return None

    @asyncSlot()
    async def click_push_button(self):
        async def async_task():
            await asyncio.sleep(1)
            QMessageBox.information(self, self.tr("Hello"), self.tr("Hello World!"))

        self.ui.pushButton.setEnabled(False)
        await async_task()
        self.ui.pushButton.setEnabled(True)

    def change_theme(self, index):
        theme = self.ui.themeComboBox.itemData(index)
        setup_theme(theme)
```

- [ ] **Step 3: Rewrite update_widget.py**

Remove the embedded download/extract logic. The widget now only handles UI state; actual download + spawn happens in `MainWindow._perform_update()`.

```python
# app/builtin/update_widget.py
from PySide6.QtCore import Qt
from qasync import asyncSlot

from app.builtin.async_widget import AsyncWidget
from app.builtin.updater.base import Updater
from app.resources.builtin.update_widget_ui import Ui_UpdateWidget


class UpdateWidget(AsyncWidget):
    need_restart: bool

    def __init__(self, parent, updater: Updater):
        super().__init__(parent)
        self.updater = updater
        self.need_restart = False
        flags = self.windowFlags()
        flags = flags | Qt.WindowType.Window
        flags = flags & ~Qt.WindowType.WindowMaximizeButtonHint
        flags = flags & ~Qt.WindowType.WindowMinimizeButtonHint
        flags = flags & ~Qt.WindowType.WindowCloseButtonHint
        self.setWindowFlags(flags)
        self.ui = Ui_UpdateWidget()
        self.ui.setupUi(self)

        self.ui.label.setText(
            self.tr("Found new version: {}").format(self.updater.remote_version)
        )
        self.ui.textBrowser.setMarkdown(self.updater.description)

        self.ui.cancel_btn.clicked.connect(self.on_cancel)
        self.ui.update_btn.clicked.connect(self.on_update)

    def on_cancel(self):
        self.close()

    @asyncSlot()
    async def on_update(self):
        self.ui.cancel_btn.setEnabled(False)
        self.ui.update_btn.setEnabled(False)
        self.ui.label.setText(self.tr("Preparing update..."))
        self.need_restart = True
        self.close()
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kaoru/Developer/pyside-template && uv run pytest app/test/ -v`
Expected: ALL PASS (old test imports will fail until Task 6, that's expected)

- [ ] **Step 5: Commit**

```bash
git add app/__main__.py app/main_window.py app/builtin/update_widget.py
git commit -m "refactor: rewrite main app to use new updater/ package and two-process model"
```

---

### Task 6: Delete old modules, update tests, clean up pyproject.toml

**Files:**
- Delete: `app/builtin/update.py`
- Delete: `app/builtin/github_updater.py`
- Delete: `app/builtin/gitlab_updater.py`
- Delete: `app/builtin/utils.py`
- Modify: `app/test/test_update.py` — update all imports
- Modify: `app/test/test_multiply.py` — no change needed
- Modify: `pyproject.toml` — remove `glom` from dependencies

**Interfaces:**
- All imports from `app.builtin.update`, `app.builtin.github_updater`, `app.builtin.gitlab_updater`, `app.builtin.utils` must be updated to `app.builtin.updater.*`

- [ ] **Step 1: Delete old modules**

```bash
cd /Users/kaoru/Developer/pyside-template
rm app/builtin/update.py app/builtin/github_updater.py app/builtin/gitlab_updater.py
```

Note: `app/builtin/utils.py` has `init_app()` which is still used by `__main__.py`. Keep it or move `init_app()` to a better location. Decision: keep `utils.py` with only `init_app()` for now, remove the updater-related code.

- [ ] **Step 2: Rewrite utils.py to only keep init_app()**

```python
# app/builtin/utils.py
import sys
from app.builtin.config import APP_NAME, APP_DISPLAY_NAME, ORG_NAME


def init_app():
    from qdarktheme import enable_hi_dpi
    from PySide6.QtWidgets import QApplication

    enable_hi_dpi()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(ORG_NAME)
    return app
```

- [ ] **Step 3: Rewrite test_update.py imports**

```python
# app/test/test_update.py
import sys
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


class TestGetUpdater:
    def test_caches_instance(self):
        from app.builtin.updater import get_updater
        a = get_updater()
        b = get_updater()
        assert a is b

    def test_reconfigures_on_each_call(self):
        from app.builtin.updater import get_updater
        import app.builtin.config as cfg

        u = get_updater()

        original = cfg.UPDATER_TIMEOUT
        cfg.UPDATER_TIMEOUT = 999
        try:
            u2 = get_updater()
            assert u2 is u
            assert u2.timeout == 999
        finally:
            cfg.UPDATER_TIMEOUT = original

    def test_recreates_on_type_change(self):
        from app.builtin.updater import get_updater
        import app.builtin.config as cfg

        u = get_updater()
        assert u.__class__.__name__ == "GithubUpdater"

        original_type = cfg.UPDATER_REMOTE_TYPE
        original_url = cfg.UPDATER_URL
        cfg.UPDATER_REMOTE_TYPE = "GitLab"
        cfg.UPDATER_URL = "https://gitlab.com"
        try:
            u2 = get_updater()
            assert u2 is not u
            assert u2.__class__.__name__ == "GitlabUpdater"
        finally:
            cfg.UPDATER_REMOTE_TYPE = original_type
            cfg.UPDATER_URL = original_url

    def test_sets_all_config(self):
        from app.builtin.updater import get_updater
        import app.builtin.config as cfg

        u = get_updater()
        assert u.base_url == cfg.UPDATER_URL
        assert u.project_name == cfg.UPDATER_PROJECT_NAME
        assert u.app_name == cfg.UPDATER_APP_NAME
        assert u.timeout == cfg.UPDATER_TIMEOUT


class TestRunningInBundle:
    def test_returns_false_on_non_macos(self):
        from app.builtin.updater import running_in_bundle
        if sys.platform != "darwin":
            assert running_in_bundle() is False

    def test_returns_false_on_normal_python(self):
        from app.builtin.updater import running_in_bundle
        if sys.platform == "darwin":
            assert running_in_bundle() is False


class TestMainEnablesUpdater:
    def test_updater_enable_logic(self):
        for bundle, enable, expected in [
            (True, True, False),
            (False, True, True),
            (True, False, False),
            (False, False, False),
        ]:
            is_enable = False if bundle else enable
            assert is_enable == expected


class TestVersion:
    def test_parse_stable(self):
        from app.builtin.updater.base import Version, ReleaseType
        v = Version("1.2.3")
        assert v.release_type == ReleaseType.STABLE

    def test_parse_beta(self):
        from app.builtin.updater.base import Version, ReleaseType
        v = Version("1.2.3-beta")
        assert v.release_type == ReleaseType.BETA

    def test_compare(self):
        from app.builtin.updater.base import Version
        assert Version("2.0.0") > Version("1.0.0")
        assert Version("1.0.1") > Version("1.0.0")
        assert Version("1.0.0") == Version("1.0.0")


class TestUpdaterBase:
    def test_has_timeout_default(self):
        from app.builtin.updater.base import Updater
        assert hasattr(Updater, "timeout")
        assert Updater.timeout == 30

    def test_platform_arch_normalization(self):
        from app.builtin.updater.platform import get_sysname, get_arch
        name = get_sysname()
        assert name in ("linux", "macos", "windows")
        arch = get_arch()
        assert arch in ("x64", "arm64")

    def test_check_for_update(self):
        from app.builtin.updater.base import Updater, Version

        class FakeUpdater(Updater):
            def create_async_client(self):
                pass
            async def fetch(self):
                pass

        u = FakeUpdater()
        u.current_version = Version("1.0.0")
        u.release_type = u.current_version.release_type
        u.remote_version = Version("2.0.0")
        assert u.check_for_update() is True

        u.remote_version = Version("0.9.0")
        assert u.check_for_update() is False

        u.remote_version = Version("2.0.0-beta")
        assert u.check_for_update() is False
```

- [ ] **Step 4: Remove glom from pyproject.toml**

Remove `"glom>=24.11.0",` from the `dependencies` list in `pyproject.toml`.

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/kaoru/Developer/pyside-template && uv run pytest app/test/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete old updater modules, remove glom dependency, update all imports"
```

---

### Task 7: Update CI for checksums

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Add checksum generation step**

After the "Package artifact" steps and before "Upload artifact", add a step for each platform that generates `.sha256` files:

```yaml
      - name: Generate checksums
        run: |
          cd release
          for f in *.zip *.tar.gz *.dmg; do
            [ -f "$f" ] && sha256sum "$f" > "$f.sha256"
          done
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add sha256 checksum generation for release assets"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/kaoru/Developer/pyside-template && uv run pytest app/test/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 2: Verify no imports from old modules remain**

Run: `cd /Users/kaoru/Developer/pyside-template && grep -r "from app.builtin.update import\|from app.builtin.github_updater\|from app.builtin.gitlab_updater\|from app.builtin.utils import.*get_updater" app/ --include="*.py"`
Expected: No matches (only `app/builtin/utils.py` should exist with `init_app`)

- [ ] **Step 3: Verify glom is gone**

Run: `cd /Users/kaoru/Developer/pyside-template && grep "glom" pyproject.toml`
Expected: No matches

- [ ] **Step 4: Verify psutil is gone from updater code**

Run: `cd /Users/kaoru/Developer/pyside-template && grep "psutil" app/builtin/updater/ --include="*.py"`
Expected: No matches

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: final cleanup for self-update rewrite"
```

---

## Compatibility Notes

### 1. Old releases without .sha256 files

Releases published before this change will not have `.sha256` checksum files. The `fetch_checksum()` function already returns `None` on failure, and `download_with_checksum()` accepts `expected_sha256=None` — so verification is gracefully skipped. **No migration needed.**

### 2. Import path migration

Old code may import from the deleted modules (`app.builtin.update`, `app.builtin.github_updater`, `app.builtin.gitlab_updater`, `app.builtin.utils`). To ease migration, add backward-compatible re-exports in the old module locations (or a `_compat.py` shim). However, since pyside-template is a template repo (not a library), users who forked it will copy the new code anyway. **Decision: no re-export shim. Just clean delete.**

### 3. Python version floor

`pyproject.toml` declares `requires-python = ">=3.13"` — so `X | Y` union syntax, `match/case`, and other 3.10+ features are safe. No compatibility shims needed for the Python version.

### 4. psutil removal

The old updater used `psutil.Process(pid).wait()` for process monitoring. The new `run_update.py` uses `os.kill(pid, 0)` polling — a POSIX standard that works on Linux and macOS. On Windows, `os.kill(pid, 0)` also works for existence checks (it sends `CTRL_C_EVENT` for signal 0, which suffices). **No psutil needed.**

### 5. config.py constants unchanged

`UPDATER_REMOTE_TYPE`, `UPDATER_URL`, `UPDATER_PROJECT_NAME`, `UPDATER_APP_NAME`, `UPDATER_TIMEOUT` remain as-is in `config.py`. No breaking change for users who customized these.

### 6. UpdateWidget API change

The old `UpdateWidget` did download+extract internally and set `self.need_restart`. The new `UpdateWidget` only sets `self.need_restart = True` on button click — actual download/extract/spawn happens in `MainWindow._perform_update()`. If any user code subclassed `UpdateWidget` or called its `download()`/`extract()` methods directly, it will break. **Mitigation: document the change in CHANGE.md.**

### 7. `--updater` flag collision

The `--updater` flag is only detected in `sys.argv` at startup and immediately branches to `run_updater_mode()`. It is not parsed by argparse/click. No collision risk with existing flags.

### 8. macOS .app bundle: no change in behavior

macOS bundle self-update was already disabled (`running_in_bundle() → is_enable = False`). This behavior is preserved. The Sparkle integration for macOS is deferred to a separate plan.

---

## Compatibility Notes

### 1. Old releases without .sha256 files

Releases published before this change will not have `.sha256` checksum files. The `fetch_checksum()` function already returns `None` on failure, and `download_with_checksum()` accepts `expected_sha256=None` — so verification is gracefully skipped. **No migration needed.**

### 2. Import path migration

Old code may import from the deleted modules (`app.builtin.update`, `app.builtin.github_updater`, `app.builtin.gitlab_updater`, `app.builtin.utils`). To ease migration, add backward-compatible re-exports in the old module locations (or a `_compat.py` shim). However, since pyside-template is a template repo (not a library), users who forked it will copy the new code anyway. **Decision: no re-export shim. Just clean delete.**

### 3. Python version floor

`pyproject.toml` declares `requires-python = ">=3.13"` — so `X | Y` union syntax, `match/case`, and other 3.10+ features are safe. No compatibility shims needed for the Python version.

### 4. psutil removal

The old updater used `psutil.Process(pid).wait()` for process monitoring. The new `run_update.py` uses `os.kill(pid, 0)` polling — a POSIX standard that works on Linux and macOS. On Windows, `os.kill(pid, 0)` also works for existence checks (it sends `CTRL_C_EVENT` for signal 0, which suffices). **No psutil needed.**

### 5. config.py constants unchanged

`UPDATER_REMOTE_TYPE`, `UPDATER_URL`, `UPDATER_PROJECT_NAME`, `UPDATER_APP_NAME`, `UPDATER_TIMEOUT` remain as-is in `config.py`. No breaking change for users who customized these.

### 6. UpdateWidget API change

The old `UpdateWidget` did download+extract internally and set `self.need_restart`. The new `UpdateWidget` only sets `self.need_restart = True` on button click — actual download/extract/spawn happens in `MainWindow._perform_update()`. If any user code subclassed `UpdateWidget` or called its `download()`/`extract()` methods directly, it will break. **Mitigation: document the change in CHANGE.md.**

### 7. `--updater` flag collision

The `--updater` flag is only detected in `sys.argv` at startup and immediately branches to `run_updater_mode()`. It is not parsed by argparse/click. No collision risk with existing flags.

### 8. macOS .app bundle: no change in behavior

macOS bundle self-update was already disabled (`running_in_bundle() → is_enable = False`). This behavior is preserved. The Sparkle integration for macOS is deferred to a separate plan.

---

## Compatibility Notes

### 1. Old releases without .sha256 files

Releases published before this change will not have `.sha256` checksum files. The `fetch_checksum()` function already returns `None` on failure, and `download_with_checksum()` accepts `expected_sha256=None` — so verification is gracefully skipped. **No migration needed.**

### 2. Import path migration

Old code may import from the deleted modules (`app.builtin.update`, `app.builtin.github_updater`, `app.builtin.gitlab_updater`, `app.builtin.utils`). To ease migration, add backward-compatible re-exports in the old module locations (or a `_compat.py` shim). However, since pyside-template is a template repo (not a library), users who forked it will copy the new code anyway. **Decision: no re-export shim. Just clean delete.**

### 3. Python version floor

`pyproject.toml` declares `requires-python = ">=3.13"` — so `X | Y` union syntax, `match/case`, and other 3.10+ features are safe. No compatibility shims needed for the Python version.

### 4. psutil removal

The old updater used `psutil.Process(pid).wait()` for process monitoring. The new `run_update.py` uses `os.kill(pid, 0)` polling — a POSIX standard that works on Linux and macOS. On Windows, `os.kill(pid, 0)` also works for existence checks (it sends `CTRL_C_EVENT` for signal 0, which suffices). **No psutil needed.**

### 5. config.py constants unchanged

`UPDATER_REMOTE_TYPE`, `UPDATER_URL`, `UPDATER_PROJECT_NAME`, `UPDATER_APP_NAME`, `UPDATER_TIMEOUT` remain as-is in `config.py`. No breaking change for users who customized these.

### 6. UpdateWidget API change

The old `UpdateWidget` did download+extract internally and set `self.need_restart`. The new `UpdateWidget` only sets `self.need_restart = True` on button click — actual download/extract/spawn happens in `MainWindow._perform_update()`. If any user code subclassed `UpdateWidget` or called its `download()`/`extract()` methods directly, it will break. **Mitigation: document the change in CHANGE.md.**

### 7. `--updater` flag collision

The `--updater` flag is only detected in `sys.argv` at startup and immediately branches to `run_updater_mode()`. It is not parsed by argparse/click. No collision risk with existing flags.

### 8. macOS .app bundle: no change in behavior

macOS bundle self-update was already disabled (`running_in_bundle() → is_enable = False`). This behavior is preserved. The Sparkle integration for macOS is deferred to a separate plan.
