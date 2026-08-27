from app.builtin.updater.base import Version, ReleaseType, Updater, get_updater, running_in_bundle
from app.builtin.updater.platform import get_sysname, get_arch

__all__ = [
    "Version", "ReleaseType", "Updater",
    "get_updater", "running_in_bundle",
    "get_sysname", "get_arch",
]

_sparkle_updater = None


def get_sparkle_updater():
    """Return the current SparkleUpdater instance, or None."""
    return _sparkle_updater


def set_sparkle_updater(updater):
    """Set the SparkleUpdater instance (called from __main__ on macOS)."""
    global _sparkle_updater
    _sparkle_updater = updater
