from app.builtin.github_updater import GithubUpdater
from app.builtin.gitlab_updater import GitlabUpdater
import app.builtin.config as cfg

import sys
from pathlib import Path

from qdarktheme import enable_hi_dpi
from PySide6.QtWidgets import QApplication


_updater_instance = None


def get_updater():
    global _updater_instance

    match cfg.UPDATER_REMOTE_TYPE:
        case "GitHub":
            cls = GithubUpdater
        case "GitLab":
            cls = GitlabUpdater
        case _:
            raise ValueError(
                f"Unsupported updater remote type: {cfg.UPDATER_REMOTE_TYPE}"
            )

    if _updater_instance is None or type(_updater_instance) is not cls:
        _updater_instance = cls()

    _updater_instance.base_url = cfg.UPDATER_URL
    _updater_instance.project_name = cfg.UPDATER_PROJECT_NAME
    _updater_instance.app_name = cfg.UPDATER_APP_NAME
    _updater_instance.timeout = cfg.UPDATER_TIMEOUT
    return _updater_instance


def running_in_bundle() -> bool:
    if sys.platform != "darwin":
        return False

    exe_path = Path(sys.executable).resolve()
    return ".app/Contents/MacOS" in str(exe_path)


def init_app():
    # enable hdpi
    enable_hi_dpi()

    # init QApplication
    app = QApplication(sys.argv)
    app.setApplicationName(cfg.APP_NAME)
    app.setApplicationDisplayName(cfg.APP_DISPLAY_NAME)
    app.setOrganizationName(cfg.ORG_NAME)

    return app
