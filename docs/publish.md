# Release and Product Version Control

This template integrates **GitHub Action/GitLab Pipeline** for automated release. By pushing a Git tag, you can
automatically trigger
the build and release process.

> [!NOTE]
> If you want to release a wheel package, 
> you need to update the `project.version` field in pyproject.toml before creating a Git tag.

## Prerequisites

### GitLab Pipeline

1. **Runner Configuration**: Verify that the GitLab Runner for the target platform is properly installed and configured.

2. **Code Preparation**: Set `base_url`, `project_name` before call the `GitlabUpdater.fetch()` method.

### GitHub Action

1. **Code Preparation**: Set `project_name` before call the `GithubUpdater.fetch()` method.

### Selfed-Host Services

Manually set the `base_url` and `token`.

e.g.

```python
# before init QApplication
def init_updater():
    from app.builtin.gitlab_updater import GitlabUpdater
    updater = GitlabUpdater()
    updater.base_url = "https://gitlab.example.com"
    updater.project_name = "owner/project"


# check updates
async def check_updates():
    import sys
    from app.builtin.update_widget import UpdateWidget
    from app.builtin.gitlab_updater import GitlabUpdater
    updater = GitlabUpdater.instance()
    await updater.fetch()
    if updater.check_for_update(): 
        # If you have a parent, set it as a parameter.
        update_widget = UpdateWidget(parent=None, updater=updater)
        # Force update without user confirm
        # > await update_widget.on_update()
        # Ask user for update
        await update_widget.show()
        if update_widget.need_restart:
            # Apply update and restart if update is ready
            updater.apply_update()
            sys.exit(0)
```

## Release Workflow

When you push a tag to the remote repository, the CI/CD pipeline will be automatically triggered to build and publish
the release.

The **tag\_name** will serve as both the version number and the release channel.

## Tag Format Specification

The tag must follow one of the following formats:

- `x.y.z`

- `x.y.z-stable`

- `x.y.z-beta`

Regex pattern:

> ([0-9]+(\.[0-9]+){1,3})(\-(stable|alpha|beta|nightly|dev))?$

Where:

- **x.y.z** → Semantic Versioning, e.g., `1.2.3`

- **channel** → Release channel (optional). Currently supported values:

    - `stable` (stable release)
    - `alpha` (alpha release)
    - `beta` (beta release)
    - `nightly` (nightly release)
    - `dev` (dev release)

If additional release channels are required, the `Version` class constructor logic must be extended.


## Updater Configuration

Type your configuration in `updater.json`:

```json
{
  "version": "0.0.0",
  "proxy": "http://127.0.0.1:7890",
  "channel": "beta"
}
```

The `version` field will not be automatically updated; it is only used to manually set or override the current version.
This is typically used for testing purposes.

## macOS Sparkle Codesign Secrets

CI 正式签名需要以下 GitHub Secrets（未配置时自动 ad-hoc，仅本地 E2E）：

| Secret | 说明 |
|---|---|
| `APPLE_CERTIFICATE_P12_BASE64` | `base64` 后的 Developer ID Application 证书 p12 |
| `APPLE_CERTIFICATE_PASSWORD` | p12 密码 |
| `SPARKLE_APPCAST_URL` / `SPARKLE_EDDSA_PUBLIC_KEY` | appcast 地址与 EdDSA 公钥（`embed_sparkle.py` 用） |
| `APPLE_ID` + `APPLE_APP_SPECIFIC_PASSWORD` + `APPLE_TEAM_ID` 或 `APPLE_API_KEY` + `APPLE_API_ISSUER` | `notarytool` 公证（二选一） |

## References

- Version parsing and update logic: `app/builtin/updater/base.py`, `app/builtin/updater/*`
- macOS Sparkle: `app/builtin/updater/sparkle.py`, `scripts/embed_sparkle.py`, `scripts/codesign_macos.py`, `scripts/notarize_macos.py`, `scripts/entitlements.plist`
- CI/CD release scripts: 
  - `.gitlab-ci.yml`
  - `.github/workflow/release.yml`
  - and related scripts
    
