# macOS Notarization Blocked (Nuitka + Sparkle) — Findings

Status: INVESTIGATION CLOSED. The Sparkle self-update path for this Nuitka-built
PySide6 app does not pass Apple notarization. This branch is being abandoned for
the self-update feature.

## Root cause

Apple notarization rejected the distributable with:

```
status: Invalid
statusSummary: "Archive contains critical validation errors"
statusCode: 4000
issues:
  - path: "AppInstaller.dmg/App.app/Contents/MacOS/App"
    message: "The signature of the binary is invalid."
    architecture: "arm64"
```

Notably:

- The `Codesign` step passes: `codesign --verify --deep --strict` reports
  `valid on disk` / `satisfies its Designated Requirement`.
- The app binary is signed with `Developer ID Application: Shuai Zeng (ZMK8PL8T8J)`,
  hardened runtime (`--options runtime`), `--timestamp`, and a valid
  `entitlements.plist` (`allow-jit`, `allow-unsigned-executable-memory`,
  `disable-library-validation`).
- Local `codesign --verify --deep --strict` on an equivalent minimal Nuitka app
  also passes.

The failure comes from **Apple's notarization engine**, not from our codesign
steps. The decisive difference vs. wifi-lens (which notarizes fine):

- **wifi-lens** is a native Swift app built by Xcode. Its dynamic libraries live
  under `Contents/Frameworks` and its bundle layout is Apple-conformant.
- **This app is Nuitka standalone.** Nuitka places the dependencies
  (`QtCore`, `QtWidgets`, `libpython3.13.dylib`, PySide/Shiboken `.so`) directly
  under `Contents/MacOS/` and links them via `@executable_path`. Apple's
  notarization validation does not accept this layout, so it flags the main
  executable `App` as having an invalid signature.

## What was tried

- Inside-out signing of the embedded `Sparkle.framework` (XPCs -> Updater.app ->
  framework) using resolved real paths (not the top-level symlinks).
- Signing framework-internal binaries (`Sparkle`, `Autoupdate`) before the
  framework itself.
- Moving the `.sparkle-version` marker out of the framework root to avoid
  "unsealed contents".
- Notarizing the DMG (not a temp zip), matching wifi-lens.
- Exporting `SIGNING_IDENTITY` so the DMG is signed with the real Developer ID.
- Fetching `notarytool log` to surface the actual rejection reason.

None of these helps; the blocker is the Nuitka bundle layout.

## Recommendation

To ship a self-updating PySide6 desktop app on macOS with Sparkle + Apple
notarization, use a bundler that emits an Apple-conformant app layout
(dependencies under `Contents/Frameworks`):

- **py2app** or **PyInstaller** (macOS bundle mode), which place dynamic
  libraries under `Contents/Frameworks` and are known to work with notarization.
- The code modules (`app/builtin/updater/*`, `sparkle.py`, `embed_sparkle.py`,
  `codesign_macos.py`, `generate_appcast.sh`, `notarize_macos.py`) are
  bundler-agnostic and can be reused with a different packaging backend.

## Files touched on this branch

- `app/builtin/updater/*` (Sparkle/HTTP two-process updater)
- `scripts/embed_sparkle.py`, `scripts/codesign_macos.py`,
  `scripts/notarize_macos.py`, `scripts/generate_appcast.sh`, `scripts/entitlements.plist`
- `.github/workflows/release.yml`
- `docs/macos.md`, `docs/publish.md`

The self-update feature is not implemented end-to-end on macOS because Apple
notarization rejects the Nuitka bundle. The HTTP two-process updater for
Linux/Windows remains functional.
