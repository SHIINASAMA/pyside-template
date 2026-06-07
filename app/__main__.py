import asyncio
import sys
import os

from PySide6.QtCore import QTranslator, QLockFile
from qasync import QApplication, run

from app.builtin.locale import detect_system_ui_language
from app.builtin.utils import get_updater, init_app, running_in_bundle
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
    # init QApplication
    app = init_app()
    paths = AppPaths()

    # init updater, updater will remove some arguments
    # and do update logic
    updater = get_updater()
    # self-updating is not available on macOS
    updater.is_enable = False if running_in_bundle() else enable_updater

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
