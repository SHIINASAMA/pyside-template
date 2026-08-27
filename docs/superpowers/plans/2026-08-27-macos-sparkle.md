# pyside-template macOS Sparkle Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate Sparkle (via PyObjC) as the self-update mechanism for macOS .app bundle builds, replacing the currently disabled `running_in_bundle() → is_enable = False` gate.

**Architecture:** On macOS, when `running_in_bundle()` returns `True`, the app creates an `SPUStandardUpdaterController` (via PyObjC bridge) instead of using the GitHub/GitLab HTTP-based updater. Sparkle handles appcast parsing, version comparison, download, extraction, and relaunch natively. The existing Linux/Windows two-process `--updater` model is unchanged.

**Tech Stack:** Python 3.13+, PySide6, PyObjC (`pyobjc-core`, `pyobjc-framework-Cocoa`), Sparkle.framework (embedded in .app/Contents/Frameworks/)

**Spec / design notes:**
- wifi-lens Sparkle pitfalls: `projects/pyside-template/自更新重构方案.md` in Obsidian vault
- wifi-lens reference impl: `wifi-lens/WiFiLens/Sources/WiFiLens/App/SparkleUpdater.swift`
- Selection doc: `技术/PySide与打包/Python桌面自更新方案选型.md` in Obsidian vault

## Global Constraints

- `requires-python = ">=3.13"` (pyproject.toml)
- macOS .app bundle builds only (PyInstaller); non-bundle environments (dev, Linux, Windows) must never load Sparkle
- Sparkle.framework is NOT a Python package — it must be downloaded and embedded at build time (CI or local build script)
- `pyobjc-core` and `pyobjc-framework-Cocoa` are the ONLY new runtime dependencies (macOS-only optional deps)
- Sparkle.framework must be downloaded from `sparkle-project/Sparkle` GitHub releases at a pinned version
- EdDSA signing key pair is required: private key for signing releases, public key embedded in .app for verification
- All Sparkle delegate callbacks must be implemented (error logging, update-found, no-update, cycle-complete) — per wifi-lens pitfalls
- `SUEnableAutomaticChecks` must be set to `false` BEFORE `SPUStandardUpdaterController` initialization — per wifi-lens pitfalls

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `app/builtin/updater/sparkle.py` | `SparkleUpdater` class wrapping SPUStandardUpdaterController via PyObjC |
| Create | `scripts/embed_sparkle.py` | Build script: downloads Sparkle.framework, embeds in .app bundle, patches Info.plist |
| Modify | `app/builtin/updater/__init__.py` | Export `SparkleUpdater`; add `get_updater()` macOS path that returns SparkleUpdater when in bundle |
| Modify | `app/builtin/updater/base.py` | Add `SparkleUpdater` as a concrete `Updater` subclass (or a parallel updater that replaces the ABC for macOS) |
| Modify | `app/__main__.py` | Wire SparkleUpdater on macOS .app bundle (instead of GitHub/GitLab HTTP updater) |
| Modify | `app/main_window.py` | Add macOS "Check for Updates" menu item; connect to `sparkle_updater.check_for_updates()` |
| Modify | `app/builtin/config.py` | Add `SPARKLE_APPCAST_URL`, `SPARKLE_EDDSA_PUBLIC_KEY` constants |
| Modify | `pyproject.toml` | Add `pyobjc-core` and `pyobjc-framework-Cocoa` as optional macOS deps (or platform-conditional) |
| Modify | `.github/workflows/release.yml` | Add Sparkle.framework download + embed step before DMG creation on macOS |
| Modify | `app/test/test_updater_sparkle.py` | Unit tests for SparkleUpdater (mocked SPUStandardUpdaterController) |

## Task Plan

### Task 1: Create `app/builtin/updater/sparkle.py`

**Files:** Create `app/builtin/updater/sparkle.py`

**Design:** Create a `SparkleUpdater` class that wraps `SPUStandardUpdaterController` via PyObjC. This is NOT a subclass of `Updater` ABC (Sparkle doesn't use the GitHub/GitLab fetch model). Instead, it's a parallel updater that the app selects on macOS .app bundles.

The class must:
- Lazily import PyObjC modules (`objc`, `Foundation`, `AppKit`) to avoid ImportError on non-macOS
- Load Sparkle.framework from the app bundle's `Contents/Frameworks/` via `NSBundle`
- Create `SPUStandardUpdaterController` with a delegate that implements all callbacks
- Set `SUEnableAutomaticChecks = False` BEFORE controller init (wifi-lens pitfall #1)
- Expose `check_for_updates()` → `controller.checkForUpdates_(None)`
- Expose `automatically_checks` property → reads/writes `UserDefaults["SUEnableAutomaticChecks"]`
- Expose `current_version` (from `NSBundle.mainBundle().infoDictionary["CFBundleShortVersionString"]`)
- Log all delegate callbacks (didAbortWithError, failedToDownloadUpdate, didFindValidUpdate, updaterDidNotFindUpdate, didFinishUpdateCycleFor) — per wifi-lens pitfall #2

**Fallback:** If PyObjC or Sparkle.framework is unavailable (dev environment, non-macOS), `SparkleUpdater` should raise `ImportError` or `RuntimeError` so the app can fall back to the HTTP updater.

**Tests:** Create `app/test/test_updater_sparkle.py` with mocked PyObjC (mock `SPUStandardUpdaterController`, `NSBundle`, `UserDefaults`). Test init, check_for_updates, automatically_checks toggle, delegate callback logging. Tests must pass WITHOUT Sparkle.framework installed (all mocked).

**Commit:** `feat: add Sparkle updater wrapper for macOS via PyObjC`

### Task 2: Create `scripts/embed_sparkle.py`

**Files:** Create `scripts/embed_sparkle.py`

**Design:** A build-time script (run in CI or locally) that:
1. Downloads `Sparkle.framework` from `sparkle-project/Sparkle` GitHub releases (pinned version, e.g. 2.x)
2. Extracts it
3. Copies it to `<app_bundle>/Contents/Frameworks/Sparkle.framework`
4. Patches `<app_bundle>/Contents/Info.plist` to add:
   - `SUFeedURL` = the GitHub releases atom feed URL (from config)
   - `SUPublicEDKey` = the EdDSA public key (from config or env var)
   - `SUAllowsAutomaticUpdates` = `false` (we control this ourselves)

The script should:
- Accept `--app-bundle-path`, `--sparkle-version`, `--appcast-url`, `--eddsa-public-key` as arguments
- Be idempotent (skip download if framework already exists at the right version)
- Verify the downloaded archive's sha256 (optional but recommended)
- Use only stdlib + `urllib.request` (no new deps for the build script)

**Tests:** Manual verification in CI (the script is a build tool, not runtime code).

**Commit:** `build: add Sparkle.framework embed script for macOS`

### Task 3: Wire SparkleUpdater into `__main__.py`

**Files:** Modify `app/__main__.py`, `app/builtin/config.py`

**Design:**
- Add to `config.py`: `SPARKLE_APPCAST_URL = ""` (empty default; user sets it), `SPARKLE_EDDSA_PUBLIC_KEY = ""`
- In `__main__.py`, after `get_updater()`:
  - If `running_in_bundle()` is True (macOS .app):
    - Try to create `SparkleUpdater` (import from `app.builtin.updater.sparkle`)
    - If successful, use it instead of the HTTP updater
    - If import fails (PyObjC not installed, Sparkle.framework missing), log warning and fall back to HTTP updater (graceful degradation)
  - If not in bundle: use HTTP updater as before (no change)

**Key ruling:** The `SparkleUpdater` replaces the `Updater` ABC on macOS — it has a different interface (`check_for_updates()` instead of `fetch()` + `check_for_update()`). The app's `check_update` flow in `main_window.py` must branch on updater type.

**Commit:** `refactor: wire SparkleUpdater into macOS app startup`

### Task 4: Add "Check for Updates" menu on macOS

**Files:** Modify `app/main_window.py`

**Design:**
- In `MainWindow.__init__`, if the updater is a `SparkleUpdater`:
  - Add a "Check for Updates..." action to the macOS app menu (via `QMenuBar`)
  - Connect it to `sparkle_updater.check_for_updates()`
- In `check_update`, if the updater is a `SparkleUpdater`:
  - Skip the HTTP-based `fetch()` + `check_for_update()` flow entirely
  - Sparkle handles everything natively (appcast, version check, download, install)
  - Optionally: listen for Sparkle notifications to show update status in the UI

**Commit:** `feat: add macOS Check for Updates menu item via Sparkle`

### Task 5: Add PyObjC deps to `pyproject.toml`

**Files:** Modify `pyproject.toml`

**Design:** Add optional macOS dependencies:
```
[project.optional-dependencies]
macos-sparkle = [
    "pyobjc-core>=10.0",
    "pyobjc-framework-Cocoa>=10.0",
]
```
These are installed only on macOS (CI and local builds). Non-macOS environments don't install them.

**Commit:** `deps: add pyobjc optional dependencies for macOS Sparkle`

### Task 6: Update CI to embed Sparkle.framework

**Files:** Modify `.github/workflows/release.yml`

**Design:** In the macOS packaging step, BEFORE DMG creation:
1. Install pyobjc deps: `pip install pyobjc-core pyobjc-framework-Cocoa`
2. Run `python scripts/embed_sparkle.py --app-bundle-path build/${APP_NAME}.app --sparkle-version 2.x --appcast-url $SPARKLE_APPCAST_URL --eddsa-public-key $SPARKLE_EDDSA_PUBLIC_KEY`
3. The env vars `SPARKLE_APPCAST_URL` and `SPARKLE_EDDSA_PUBLIC_KEY` come from GitHub Actions secrets

**Commit:** `ci: embed Sparkle.framework in macOS builds`

### Task 7: Final verification

**Files:** Run all checks

**Checks:**
1. `uv run pytest app/test/ -v` — ALL must pass
2. `grep -rn "from app.builtin.update import\|from app.builtin.github_updater\|from app.builtin.gitlab_updater" app/ --include="*.py"` — no stale imports
3. `grep "glom" pyproject.toml` — no glom
4. Verify `sparkle.py` gracefully degrades when PyObjC is unavailable (test with mocked imports)
5. Verify `embed_sparkle.py` is idempotent and handles missing framework gracefully

**Commit (if needed):** `fix: final cleanup for macOS Sparkle integration`

## Compatibility Notes

### 1. PyObjC is macOS-only
`pyobjc-core` and `pyobjc-framework-Cocoa` only install on macOS. On Linux/Windows, the optional deps section is skipped. The `sparkle.py` module uses lazy imports so it never breaks on non-macOS.

### 2. Sparkle.framework version pinning
Pin to a specific Sparkle release (e.g. 2.6.x). The embed script downloads from GitHub releases. For airgapped environments, the framework can be vendored in the repo.

### 3. EdDSA key management
The private key is used only for signing releases (in CI or locally). The public key is embedded in the .app. Key generation: `generate_keys` tool from Sparkle. Store private key in GitHub Actions secrets; public key in `config.py` or CI env.

### 4. Existing Linux/Windows updater unchanged
The `--updater` two-process model for Linux/Windows is completely unaffected. Sparkle is macOS-only and loaded conditionally.

### 5. Graceful degradation
If Sparkle.framework is missing at runtime (e.g. dev environment, broken build), the app falls back to the HTTP updater with a warning log. The app never crashes due to missing Sparkle.

### 6. Appcast URL
The appcast URL points to the GitHub releases atom feed: `https://github.com/{owner}/{repo}/releases.atom`. This is the same feed Sparkle parses natively. No custom appcast server needed.

## Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| PyObjC cannot load Sparkle.framework | High | Verify early (Task 1 spike); fallback to HTTP updater |
| Sparkle.framework not embedded in CI | High | Idempotent embed script with CI verification step |
| EdDSA key pair not generated | Medium | Document key generation; CI fails gracefully if key missing |
| Sparkle init side effects (SUEnableAutomaticChecks) | Medium | Set UserDefaults before init (wifi-lens pitfall #1) |
| PyInstaller bundle structure mismatch | Medium | Test with actual PyInstaller output; adjust framework path |
| macOS version compatibility | Low | Sparkle supports 10.13+; pyside-template requires macOS 13+ |
