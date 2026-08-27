# app/test/test_updater_github.py
from unittest.mock import MagicMock, AsyncMock, patch
import anyio

# AppPaths() (used inside GithubUpdater.fetch) requires a live QCoreApplication.
from PySide6.QtCore import QCoreApplication

_qapp = QCoreApplication([])

from app.builtin.updater.github import GithubUpdater
from app.builtin.updater.base import Version, ReleaseType
from app.builtin.updater.platform import get_sysname, get_arch


def _platform_asset_name(tag: str = "2.0.0") -> str:
    # Mirror the package_name GithubUpdater derives from the host platform so the
    # substring asset match succeeds on whatever machine runs the suite.
    return f"App-{get_sysname()}-{get_arch()}-{tag}.tar.gz"


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
            mock_client.__aexit__ = AsyncMock(return_value=False)

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
                    {"name": _platform_asset_name("2.0.0"), "browser_download_url": "https://example.com/app.tar.gz"}
                ]}
            ])

            mock_head_response = MagicMock()
            mock_head_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_release_response)
            mock_client.head = AsyncMock(return_value=mock_head_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch.object(u, "create_async_client", return_value=mock_client):
                await u.fetch()

            assert u.remote_version == Version("2.0.0")
            assert u.description == "new version"
            assert "2.0.0" in u.filename

        anyio.run(run)
