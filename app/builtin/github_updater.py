from glom import glom
from httpx import AsyncClient

from singleton_decorator import singleton


from app.builtin.update import Updater, Version, get_arch, get_sysname
from app.builtin.paths import AppPaths


@singleton
class GithubUpdater(Updater):
    base_url: str = "https://api.github.com"
    project_name: str = ""
    app_name: str = "App"
    timeout = 5
    token = None

    _headers = None

    def create_async_client(self) -> AsyncClient:
        if not self._headers:
            headers = {"Accept": "application/vnd.github+json"}
            if self.token:
                headers["Authorization"] = f"token {self.token}"
            self._headers = headers
        return AsyncClient(
            proxy=self.proxy, headers=self._headers, timeout=self.timeout
        )

    async def fetch(self):
        async with self.create_async_client() as client:
            r = await client.get(
                url=f"{self.base_url}/repos/{self.project_name}/releases",
                params={"per_page": "100", "page": "1"},
                follow_redirects=True
            )
            r.raise_for_status()
            releases = []
            for release in r.json():
                version = Version(release["tag_name"])
                if version.release_type == self.release_type:
                    releases.append(release)
            latest_release = max(
                releases, key=lambda x: Version(x["tag_name"]), default=None
            )
            if latest_release is None:
                # Does have any release for this channel
                self.remote_version = Version("0.0.0.0")
                return
            self.remote_version = Version(latest_release["tag_name"])
            self.description = latest_release["body"]

            arch = get_arch()
            sysname = get_sysname()
            package_name = f"{self.app_name}-{sysname}-{arch}"

            self.download_url = None
            for assets in glom(latest_release, "assets", default={}):
                if package_name in assets["name"]:
                    package_name = assets["name"]
                    self.download_url = assets["browser_download_url"]
                    break

            if self.download_url is None:
                raise FileNotFoundError(
                    f"Package {package_name} not found in release assets."
                )

            r = await client.head(url=self.download_url, follow_redirects=True)
            r.raise_for_status()

            paths = AppPaths()
            self.filename = f"{paths.update_dir}/{package_name}"
