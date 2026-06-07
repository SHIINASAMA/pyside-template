from typing import Literal

APP_NAME = "App"
APP_DISPLAY_NAME = "App"
ORG_NAME = "PySide Template"

RemoteType = Literal["GitHub", "GitLab"]

UPDATER_REMOTE_TYPE: RemoteType = "GitHub"
UPDATER_URL = "https://api.github.com"
UPDATER_PROJECT_NAME = "SHIINASAMA/pyside_template"
UPDATER_APP_NAME = APP_NAME
UPDATER_TIMEOUT = 30