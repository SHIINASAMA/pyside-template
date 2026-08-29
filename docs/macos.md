# macOS Build Guide

## Python Must Use a Framework Build

When running Qt-based GUI applications (such as Qt Designer) on macOS, you **must** use a **Framework build** of Python.

### Installation

It is recommended to install Python via Homebrew:

```bash
brew install python@3.13
```

Alternatively, download the official macOS installer from the Python website (the official installer provides a Framework build by default).

> [!NOTE]
> Adjust the Python version according to the actual version required by the project.


### Possible Error

If a non-Framework build of Python is used, running GUI applications may result in the following error:

> Unable to find Python library directory. Use a framework build of Python.

This is caused by macOS GUI runtime requirements and is unrelated to the project code.


### Virtual Environment Initialization

When creating a virtual environment, you must explicitly specify the Framework build interpreter.

> [!NOTE]
> `python3.13` is only an example version and is **not hardcoded**.  
You must select the Python version required by the project.

The required version can usually be found in the `.python-version` file located in the project root directory.

Example:

```bash
uv venv --python /opt/homebrew/bin/python3.13
```

Replace `3.13` with the version required by the project.

Do not use:

-   The system default Python
    
-   A non-Framework build of Python
    
-   Any minimal or embedded Python build
    

## Nuitka Limitations on macOS

On macOS:

-   Only `.app bundle` builds are supported
    
-   `onefile` is not supported
    
-   `onedir` is not supported
    

Therefore:

-   `pyside-cli build` uses bundle mode by default
    
-   No additional parameters are required
    

If you require:

-   Single-file distribution (`onefile`)
    
-   Directory-based distribution (`onedir`)
    

You must use **PyInstaller** as the build backend.

## Self-Update (macOS)

### Sparkle via PyObjC

macOS 更新走 **Sparkle 2.x**（通过 PyObjC 桥接 `SPUStandardUpdaterController`）：

- 构建后需嵌入 `Sparkle.framework`：`python scripts/embed_sparkle.py --app-bundle-path build/App.app --sparkle-version 2.9.6 --appcast-url <URL> --eddsa-public-key <KEY>`
- 应用启动时自动尝试 `SparkleUpdater`，失败回退到 HTTP 两进程更新器
- 菜单栏 `Check for Updates...` 触发 `checkForUpdates_`

### Codesign / Notarization

Nuitka 打出的 `.app` + `Sparkle.framework` 存在嵌套 bundle，**不能**用 `codesign --deep` 或 `--no-strict`：

| 错误做法 | 后果 |
|---|---|
| `codesign --deep` | 隐藏问题但 `codesign --verify --strict` 失败，Sparkle installer 拒绝 |
| `codesign --no-strict` | 绕过 `bundle format is ambiguous` 但签名被 Sparkle 判为 corrupted |

**正确做法：inside-out 显式签名（已封装为脚本）**

```bash
# 本地 ad-hoc（可跑通 Sparkle E2E 的下载/版本比较，但 Gatekeeper 仍会拦截）
python scripts/codesign_macos.py --app-bundle build/App.app --verbose

# 发版签名（需 Developer ID）
python scripts/codesign_macos.py --app-bundle build/App.app --identity "Developer ID Application: Your Team (TEAMID)" --entitlements scripts/entitlements.plist
python scripts/notarize_macos.py --bundle build/App.app --wait  # 需 APPLE_ID / APPLE_API_KEY
```

签名顺序（脚本已自动处理）：`XPCServices/*.xpc` → `Updater.app` → `Autoupdate` / `Sparkle` 二进制 → `Sparkle.framework` →  loose Mach-O (`Contents/MacOS/*`) → 外层 `App.app`（带 `scripts/entitlements.plist` + `--options runtime --timestamp`）

CI 已集成：`.github/workflows/release.yml` 的 `Codesign (macOS)` + `Notarize (macOS)` 两步。未配置证书时自动降级为 ad-hoc；配置 `APPLE_CERTIFICATE_P12_BASE64` 等 secrets 后自动走正式签名 + 公证。详见 `scripts/codesign_macos.py` 注释。

常见问题详见 Obsidian `技术/PySide与打包/pyside-template-Sparkle踩坑.md`。
