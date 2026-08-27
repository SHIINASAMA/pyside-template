import asyncio
import os

import subprocess
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMessageBox, QMainWindow, QApplication
from httpx import HTTPError
from qasync import asyncSlot
from qdarktheme import setup_theme

import app.resources.resource  # type: ignore
from app.builtin.update_widget import UpdateWidget
from app.builtin.updater import get_updater
from app.builtin.updater.downloader import fetch_checksum, download_with_checksum
from app.builtin.updater.extractor import extract
from app.resources.main_window_ui import Ui_MainWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.ui.pushButton.clicked.connect(self.click_push_button)

        # ThemeManager.instance().setup_theme("auto")
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
            # Debug mode
            pass
        else:
            # Production mode
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
                    self,
                    self.tr("Warning"),
                    self.tr("Failed to check for updates"),
                )
            except FileNotFoundError:
                QMessageBox.warning(
                    self,
                    self.tr("Warning"),
                    self.tr("No update files found"),
                )
            except Exception as e:
                QMessageBox.warning(
                    self,
                    self.tr("Warning"),
                    self.tr("Excepted unknown error: {}").format(str(e)),
                )
        else:
            QMessageBox.information(
                self,
                self.tr("Info"),
                self.tr("Update completed"),
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
