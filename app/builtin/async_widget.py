import asyncio

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal


class AsyncWidget(QWidget):
    _closed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

    def closeEvent(self, event):
        self._closed.emit()
        super().closeEvent(event)

    async def async_show(self):
        future = asyncio.get_running_loop().create_future()

        def resolve_future():
            if not future.done():
                future.set_result(None)

        self._closed.connect(resolve_future)
        super().show()
        await future
