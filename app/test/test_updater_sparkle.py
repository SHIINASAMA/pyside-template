"""Tests for the Sparkle updater wrapper (all PyObjC mocked)."""

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spu_class(mock_controller: MagicMock) -> MagicMock:
    """Return a mock SPUStandardUpdaterController class whose
    ``alloc().init()`` returns *mock_controller*."""
    spu_cls = MagicMock(name="SPUStandardUpdaterController")
    spu_cls.alloc.return_value.init.return_value = mock_controller
    return spu_cls


def _make_foundation_nsud(mock_defaults: MagicMock) -> MagicMock:
    """Return a mock Foundation module with NSUserDefaults wired up."""
    foundation = MagicMock(name="Foundation")
    foundation.NSUserDefaults.standardUserDefaults.return_value = mock_defaults
    return foundation


def _construct_updater(
    mock_controller: MagicMock | None = None,
    mock_defaults: MagicMock | None = None,
):
    """Create a SparkleUpdater with all PyObjC deps mocked."""
    if mock_controller is None:
        mock_controller = MagicMock(name="controller")
    if mock_defaults is None:
        mock_defaults = MagicMock(name="defaults")

    import app.builtin.updater.sparkle as mod

    appkit = MagicMock(name="AppKit")
    appkit.SPUStandardUpdaterController = _make_spu_class(mock_controller)

    foundation = _make_foundation_nsud(mock_defaults)

    with patch.object(mod.sys, "platform", "darwin"), \
         patch("app.builtin.updater.sparkle.running_in_bundle", return_value=True), \
         patch("app.builtin.updater.sparkle._load_sparkle_framework"), \
         patch("app.builtin.updater.sparkle._ensure_automatic_checks_disabled"), \
         patch.dict("sys.modules", {"AppKit": appkit, "Foundation": foundation}):
        updater = mod.SparkleUpdater()
    return updater, mock_controller, mock_defaults


# ---------------------------------------------------------------------------
# Init guards
# ---------------------------------------------------------------------------

class TestSparkleUpdaterInit:
    def test_raises_on_non_darwin(self):
        if sys.platform == "darwin":
            pytest.skip("runs only on non-macOS")
        from app.builtin.updater.sparkle import SparkleUpdater
        with pytest.raises(RuntimeError, match="only available on macOS"):
            SparkleUpdater()

    def test_raises_outside_bundle(self):
        import app.builtin.updater.sparkle as mod
        with patch.object(mod.sys, "platform", "darwin"), \
             patch("app.builtin.updater.sparkle.running_in_bundle", return_value=False):
            with pytest.raises(RuntimeError, match="requires a .app bundle"):
                mod.SparkleUpdater()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class TestSparkleUpdaterInterface:
    def test_check_for_updates_calls_controller(self):
        ctrl = MagicMock(name="controller")
        updater, ctrl_ref, _ = _construct_updater(mock_controller=ctrl)
        updater.check_for_updates()
        ctrl_ref.checkForUpdates_.assert_called_once_with(None)

    def test_automatically_checks_reads_defaults(self):
        defaults = MagicMock(name="defaults")
        defaults.boolForKey_.return_value = True
        ctrl = MagicMock()
        import app.builtin.updater.sparkle as mod
        appkit = MagicMock()
        appkit.SPUStandardUpdaterController = _make_spu_class(ctrl)
        foundation = _make_foundation_nsud(defaults)
        with patch.object(mod.sys, "platform", "darwin"), \
             patch("app.builtin.updater.sparkle.running_in_bundle", return_value=True), \
             patch("app.builtin.updater.sparkle._load_sparkle_framework"), \
             patch("app.builtin.updater.sparkle._ensure_automatic_checks_disabled"), \
             patch.dict("sys.modules", {"AppKit": appkit, "Foundation": foundation}):
            updater = mod.SparkleUpdater()
            assert updater.automatically_checks is True
            defaults.boolForKey_.assert_called_with("SUEnableAutomaticChecks")

    def test_automatically_checks_writes_defaults(self):
        defaults = MagicMock(name="defaults")
        defaults.boolForKey_.return_value = False
        ctrl = MagicMock()
        import app.builtin.updater.sparkle as mod
        appkit = MagicMock()
        appkit.SPUStandardUpdaterController = _make_spu_class(ctrl)
        foundation = _make_foundation_nsud(defaults)
        with patch.object(mod.sys, "platform", "darwin"), \
             patch("app.builtin.updater.sparkle.running_in_bundle", return_value=True), \
             patch("app.builtin.updater.sparkle._load_sparkle_framework"), \
             patch("app.builtin.updater.sparkle._ensure_automatic_checks_disabled"), \
             patch.dict("sys.modules", {"AppKit": appkit, "Foundation": foundation}):
            updater = mod.SparkleUpdater()
            updater.automatically_checks = True
            defaults.setBool_forKey_.assert_called_with(True, "SUEnableAutomaticChecks")

    def test_current_version_reads_bundle(self):
        import app.builtin.updater.sparkle as mod
        mock_nsud = MagicMock()
        mock_foundation = MagicMock()
        mock_bundle = MagicMock()
        mock_bundle.infoDictionary.return_value.objectForKey_.return_value = "1.2.3"
        mock_foundation.NSBundle.mainBundle.return_value = mock_bundle

        ctrl = MagicMock()
        appkit = MagicMock()
        appkit.SPUStandardUpdaterController = _make_spu_class(ctrl)

        with patch.object(mod.sys, "platform", "darwin"), \
             patch("app.builtin.updater.sparkle.running_in_bundle", return_value=True), \
             patch("app.builtin.updater.sparkle._load_sparkle_framework"), \
             patch("app.builtin.updater.sparkle._ensure_automatic_checks_disabled"), \
             patch.dict("sys.modules", {"AppKit": appkit, "Foundation": mock_foundation}):
            updater = mod.SparkleUpdater()
            assert updater.current_version == "1.2.3"


# ---------------------------------------------------------------------------
# Delegate
# ---------------------------------------------------------------------------

class TestSparkleDelegate:
    def test_all_callbacks_exist(self):
        from app.builtin.updater.sparkle import _SparkleDelegate
        d = _SparkleDelegate()
        for name in (
            "updater_didAbortWithError_",
            "updater_failedToDownloadUpdate_error_",
            "updater_didFindValidUpdate_",
            "updaterDidNotFindUpdate_",
            "updater_didFinishUpdateCycleFor_",
        ):
            assert callable(getattr(d, name, None)), f"missing callback: {name}"

    def test_did_abort_logs_warning(self, caplog):
        from app.builtin.updater.sparkle import _SparkleDelegate
        d = _SparkleDelegate()
        with caplog.at_level(logging.WARNING):
            d.updater_didAbortWithError_(MagicMock(), MagicMock())
        assert "aborted" in caplog.text.lower()
