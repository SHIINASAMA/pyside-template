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
        # Packaging compares numerically; cross-channel guard is in check_for_update()
        assert Version("2.0.0-beta") > Version("1.0.0")


class TestGetSysname:
    def test_returns_valid(self):
        from app.builtin.updater.platform import get_sysname
        assert get_sysname() in ("linux", "macos", "windows")


class TestGetArch:
    def test_returns_valid(self):
        from app.builtin.updater.platform import get_arch
        assert get_arch() in ("x64", "arm64")
