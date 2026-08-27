import logging
import asyncio
import sys
import os

from PySide6.QtCore import QTranslator, QLockFile
from qasync import QApplication, run

from app.builtin.locale import detect_system_ui_language
from app.builtin.utils import init_app
from app.builtin.updater import get_updater, running_in_bundle
from app.builtin.updater import set_sparkle_updater
from app.builtin.paths import AppPaths
from app.main_window import MainWindow

logger = logging.getLogger(__name__)


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
    # init QApplication
    app = init_app()
    paths = AppPaths()

    # init updater, updater will remove some arguments
    # and do update logic
    updater = get_updater()

    if running_in_bundle():
        # macOS .app bundle — try Sparkle first
        try:
            from app.builtin.updater.sparkle import SparkleUpdater
            import app.builtin.config as cfg
            if cfg.SPARKLE_APPCAST_URL:
                sparkle = SparkleUpdater()
                set_sparkle_updater(sparkle)
                logger.info("Using SparkleUpdater for macOS updates")
            else:
                logger.info("SPARKLE_APPCAST_URL not set, falling back to HTTP updater")
                # Keep the two-process HTTP updater enabled as a working fallback
                # so a .app bundle can still self-update without a Sparkle appcast.
                updater.is_enable = enable_updater
        except Exception:
            logger.info("Sparkle unavailable, falling back to HTTP updater")
            updater.is_enable = enable_updater
    else:
        updater.is_enable = enable_updater

    # override updater config
    config_file = paths.update_dir / "updater.json"
    if os.getenv("DEBUG", "0") == "1" and config_file.exists() and config_file.is_file():
        updater.load_from_file_and_override(config_file)

    # check if the app is already running
    lock_file = QLockFile(str(paths.base_dir) + "/App.lock")
    if not lock_file.lock():
        sys.exit(0)

    # i18n
    translator = QTranslator()
    lang_code = detect_system_ui_language()
    translator.load(f":/i18n/{lang_code}.qm")
    app.installTranslator(translator)

    # start event loop
    run(task())


def main_no_updater():
    main(enable_updater=False)


def run_module():
    main()


if __name__ == "__main__":
    main()
