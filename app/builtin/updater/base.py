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

    def load_from_file_and_override(self, file: str | Path):
        """Load updater configuration from a JSON file."""
        import json
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)
        version: str = data.get("version", None)
        if version is not None:
            self.current_version = Version(version)
        self.proxy = data.get("proxy", None)
        self.release_type = ReleaseType(data.get("channel", "stable"))

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
