import sys
from app.builtin.config import APP_NAME, APP_DISPLAY_NAME, ORG_NAME


def init_app():
    from qdarktheme import enable_hi_dpi
    from PySide6.QtWidgets import QApplication

    # enable hdpi
    enable_hi_dpi()

    # init QApplication
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(ORG_NAME)

    return app
