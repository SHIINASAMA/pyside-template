from PySide6.QtCore import Qt
from qasync import asyncSlot

from app.builtin.async_widget import AsyncWidget
from app.builtin.updater.base import Updater
from app.resources.builtin.update_widget_ui import Ui_UpdateWidget


class UpdateWidget(AsyncWidget):
    need_restart: bool

    def __init__(self, parent, updater: Updater):
        super().__init__(parent)
        self.updater = updater
        self.need_restart = False
        flags = self.windowFlags()
        flags = flags | Qt.WindowType.Window
        flags = flags & ~Qt.WindowType.WindowMaximizeButtonHint
        flags = flags & ~Qt.WindowType.WindowMinimizeButtonHint
        flags = flags & ~Qt.WindowType.WindowCloseButtonHint
        self.setWindowFlags(flags)
        self.ui = Ui_UpdateWidget()
        self.ui.setupUi(self)

        self.ui.label.setText(
            self.tr("Found new version: {}").format(self.updater.remote_version)
        )
        self.ui.textBrowser.setMarkdown(self.updater.description)

        self.ui.cancel_btn.clicked.connect(self.on_cancel)
        self.ui.update_btn.clicked.connect(self.on_update)

    def on_cancel(self):
        self.close()

    @asyncSlot()
    async def on_update(self):
        self.ui.cancel_btn.setEnabled(False)
        self.ui.update_btn.setEnabled(False)
        self.ui.label.setText(self.tr("Preparing update..."))
        self.need_restart = True
        self.close()
from PySide6.QtCore import Qt
from qasync import asyncSlot

from app.builtin.async_widget import AsyncWidget
from app.builtin.updater.base import Updater
from app.resources.builtin.update_widget_ui import Ui_UpdateWidget


class UpdateWidget(AsyncWidget):
    need_restart: bool

    def __init__(self, parent, updater: Updater):
        super().__init__(parent)
        self.updater = updater
        self.need_restart = False
        flags = self.windowFlags()
        flags = flags | Qt.WindowType.Window
        flags = flags & ~Qt.WindowType.WindowMaximizeButtonHint
        flags = flags & ~Qt.WindowType.WindowMinimizeButtonHint
        flags = flags & ~Qt.WindowType.WindowCloseButtonHint
        self.setWindowFlags(flags)
        self.ui = Ui_UpdateWidget()
        self.ui.setupUi(self)

        self.ui.label.setText(
            self.tr("Found new version: {}").format(self.updater.remote_version)
        )
        self.ui.textBrowser.setMarkdown(self.updater.description)

        self.ui.cancel_btn.clicked.connect(self.on_cancel)
        self.ui.update_btn.clicked.connect(self.on_update)

    def on_cancel(self):
        self.close()

    @asyncSlot()
    async def on_update(self):
        self.ui.cancel_btn.setEnabled(False)
        self.ui.update_btn.setEnabled(False)
        self.ui.label.setText(self.tr("Preparing update..."))
        self.need_restart = True
        self.close()
