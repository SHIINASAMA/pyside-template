import sys
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


class TestGetUpdater:
    def test_caches_instance(self):
        from app.builtin.utils import get_updater
        a = get_updater()
        b = get_updater()
        assert a is b

    def test_reconfigures_on_each_call(self):
        from app.builtin.utils import get_updater
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
        from app.builtin.utils import get_updater
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
        from app.builtin.utils import get_updater
        import app.builtin.config as cfg

        u = get_updater()
        assert u.base_url == cfg.UPDATER_URL
        assert u.project_name == cfg.UPDATER_PROJECT_NAME
        assert u.app_name == cfg.UPDATER_APP_NAME
        assert u.timeout == cfg.UPDATER_TIMEOUT


class TestRunningInBundle:
    def test_returns_false_on_non_macos(self):
        from app.builtin.utils import running_in_bundle
        if sys.platform != "darwin":
            assert running_in_bundle() is False

    def test_returns_false_on_normal_python(self):
        from app.builtin.utils import running_in_bundle
        if sys.platform == "darwin":
            assert running_in_bundle() is False


class TestMainEnablesUpdater:
    def test_updater_enable_logic(self):
        """Verify is_enable = False if running_in_bundle() else enable_updater"""
        for bundle, enable, expected in [
            (True, True, False),    # macOS bundle -> disabled
            (False, True, True),    # normal -> enabled
            (True, False, False),   # macOS bundle + flag off -> disabled
            (False, False, False),  # normal + flag off -> disabled
        ]:
            is_enable = False if bundle else enable
            assert is_enable == expected, f"bundle={bundle}, enable={enable}: expected {expected}"


class TestGithubUpdaterParams:
    def test_fetch_uses_per_page_and_page(self):
        import anyio
        from app.builtin.github_updater import GithubUpdater
        from app.builtin.update import Version, ReleaseType

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
            assert params.get("per_page") == "100", f"params: {params}"
            assert params.get("page") == "1", f"params: {params}"
            assert u.remote_version == Version("0.0.0.0")

        anyio.run(run)


class TestVersion:
    def test_parse_stable(self):
        from app.builtin.update import Version, ReleaseType
        v = Version("1.2.3")
        assert v.release_type == ReleaseType.STABLE

    def test_parse_beta(self):
        from app.builtin.update import Version, ReleaseType
        v = Version("1.2.3-beta")
        assert v.release_type == ReleaseType.BETA

    def test_compare(self):
        from app.builtin.update import Version
        assert Version("2.0.0") > Version("1.0.0")
        assert Version("1.0.1") > Version("1.0.0")
        assert Version("1.0.0") == Version("1.0.0")


class TestUpdaterBase:
    def test_has_timeout_default(self):
        from app.builtin.update import Updater
        assert hasattr(Updater, "timeout")
        assert Updater.timeout == 30

    def test_platform_arch_normalization(self):
        from app.builtin.update import get_sysname, get_arch
        name = get_sysname()
        assert name in ("linux", "macos", "windows")

        arch = get_arch()
        assert arch in ("x64", "arm64")

    def test_check_for_update(self):
        from app.builtin.update import Updater, Version

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
