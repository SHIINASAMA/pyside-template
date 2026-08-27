"""macOS Sparkle updater wrapper via PyObjC.

Wraps ``SPUStandardUpdaterController`` so the app can perform native
macOS updates without subclassing the generic :class:`Updater` ABC.

All PyObjC / Sparkle imports are deferred so this module can be safely
imported on Linux or Windows (or when PyObjC is not installed).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.builtin.updater.base import running_in_bundle

logger = logging.getLogger(__name__)


def _load_sparkle_framework() -> None:
    """Load Sparkle.framework from the app bundle into the process."""
    import objc  # noqa: F811  – lazy import
    from Foundation import NSBundle  # noqa: F811

    # Walk up from sys.executable to find <App>.app/Contents/Frameworks
    exe = Path(sys.executable).resolve()
    app_bundle = exe.parent.parent  # …/Contents/MacOS → …/Contents
    fw_path = app_bundle / "Frameworks" / "Sparkle.framework"
    if not fw_path.is_dir():
        raise RuntimeError(f"Sparkle.framework not found at {fw_path}")

    bundle = NSBundle.bundleWithPath_(str(fw_path))
    if bundle is None:
        raise RuntimeError(f"Failed to load bundle at {fw_path}")

    # Force-load the ObjC classes so they are visible to Python.
    bundle.loadAndReturnError_(None)


def _ensure_automatic_checks_disabled() -> None:
    """Set SUEnableAutomaticChecks = False *before* controller creation.

    This prevents Sparkle from overwriting the default on first launch
    (wifi-lens pitfall #1).
    """
    from Foundation import NSUserDefaults  # noqa: F811

    defaults = NSUserDefaults.standardUserDefaults()
    defaults.setBool_forKey_(False, "SUEnableAutomaticChecks")


class _SparkleDelegate:
    """Minimal delegate implementing every required Sparkle callback."""

    def updater_didAbortWithError_(self, updater: object, error: object) -> None:
        logger.warning("Sparkle aborted: %s", error)

    def updater_failedToDownloadUpdate_error_(
        self, updater: object, update: object, error: object
    ) -> None:
        logger.warning("Sparkle failed to download update: %s", error)

    def updater_didFindValidUpdate_(self, updater: object, update: object) -> None:
        logger.info("Sparkle found valid update")

    def updaterDidNotFindUpdate_(self, updater: object) -> None:
        logger.info("Sparkle did not find an update")

    def updater_didFinishUpdateCycleFor_(
        self, updater: object, update_cycle: object
    ) -> None:
        logger.info("Sparkle finished update cycle: %s", update_cycle)


class SparkleUpdater:
    """Native macOS updater backed by Sparkle.framework.

    This is **not** a subclass of :class:`Updater`.  The application
    chooses this on macOS ``.app`` bundles; on other platforms or when
    Sparkle is unavailable, a fallback HTTP updater is used instead.

    Raises
    ------
    ImportError
        If PyObjC is not installed.
    RuntimeError
        If the process is not running inside a ``.app`` bundle or
        Sparkle.framework cannot be loaded.
    """

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("SparkleUpdater is only available on macOS")
        if not running_in_bundle():
            raise RuntimeError("SparkleUpdater requires a .app bundle")

        # wifi-lens pitfall #1: disable auto-checks *before* controller init.
        _ensure_automatic_checks_disabled()
        _load_sparkle_framework()

        from AppKit import SPUStandardUpdaterController  # noqa: F811

        self._delegate = _SparkleDelegate()
        self._controller = SPUStandardUpdaterController.alloc().init()
        self._controller.setDelegate_(self._delegate)

        logger.info("SparkleUpdater initialised")

    # -- public API -----------------------------------------------------------

    def check_for_updates(self) -> None:
        """Trigger an interactive update check."""
        self._controller.checkForUpdates_(None)

    @property
    def automatically_checks(self) -> bool:
        """Whether Sparkle checks for updates automatically."""
        from Foundation import NSUserDefaults  # noqa: F811

        defaults = NSUserDefaults.standardUserDefaults()
        return bool(defaults.boolForKey_("SUEnableAutomaticChecks"))

    @automatically_checks.setter
    def automatically_checks(self, value: bool) -> None:
        from Foundation import NSUserDefaults  # noqa: F811

        defaults = NSUserDefaults.standardUserDefaults()
        defaults.setBool_forKey_(value, "SUEnableAutomaticChecks")

    @property
    def current_version(self) -> str:
        """Return ``CFBundleShortVersionString`` from the main bundle."""
        from Foundation import NSBundle  # noqa: F811

        info = NSBundle.mainBundle().infoDictionary()
        return str(info.objectForKey_("CFBundleShortVersionString"))
