"""Codesign a Nuitka-built .app bundle + embedded Sparkle.framework.

Resolves the `bundle format is ambiguous` / `--no-strict` deadlock
documented in `技术/PySide与打包/pyside-template-Sparkle踩坑.md`:

* Sparkle.framework contains nested bundles (Updater.app, XPCServices/*.xpc)
  which require inside-out signing — inner bundles first, outer framework
  and finally the host .app.
* Using ``codesign --deep`` hides the problem but fails
  ``codesign --verify --strict`` and is rejected by Sparkle's installer.
* ``codesign --no-strict`` silences the ambiguous error but produces a
  signature that Sparkle considers corrupted.

The correct fix is explicit, non-deep, inside-out signing with
``--options runtime`` (hardened runtime) and ``--timestamp``.
Ad-hoc signing (``-``) is used when no Developer ID is available so
local E2E can still exercise Sparkle's code paths.

Usage::

    python scripts/codesign_macos.py --app-bundle build/App.app --identity "Developer ID Application: ..."

    # ad-hoc (local dev, no notarization)
    python scripts/codesign_macos.py --app-bundle build/App.app

    # with custom entitlements
    python scripts/codesign_macos.py --app-bundle build/App.app --identity "Apple Dev" --entitlements scripts/entitlements.plist

Requires macOS with ``codesign`` / ``codesign --verify``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

def _run(cmd: list[str], *, verbose: bool = True) -> None:
    if verbose:
        print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    if result.stdout.strip() and verbose:
        print(result.stdout.strip())
    if result.stderr.strip() and verbose:
        # codesign prints to stderr on success
        print(result.stderr.strip())

def _is_macho(path: Path) -> bool:
    try:
        out = subprocess.run(["file", "-b", str(path)], capture_output=True, text=True, check=True).stdout
        return "Mach-O" in out
    except Exception:
        return False

def _find_nested_bundles(app_bundle: Path) -> list[Path]:
    """Return nested bundles in inside-out signing order."""
    bundles: list[Path] = []

    # 1. XPC Services inside Sparkle.framework (deepest)
    for xpc in sorted(app_bundle.rglob("*.xpc")):
        # Only consider bundles that are inside Sparkle.framework or the app itself
        if xpc.is_dir():
            bundles.append(xpc)

    # 2. Updater.app inside Sparkle.framework
    for updater_app in sorted(app_bundle.rglob("Updater.app")):
        if updater_app.is_dir():
            bundles.append(updater_app)

    # 3. Sparkle.framework itself (and any other .framework) — only top-level,
    # not Versions/B substructure
    for fw in sorted(app_bundle.rglob("*.framework")):
        if fw.is_dir() and fw.suffix == ".framework":
            # Skip Versions subdirectories — they are part of the framework internals
            if "Versions" in fw.parts:
                continue
            if fw not in bundles:
                bundles.append(fw)

    # De-duplicate and resolve symlinks to REAL paths.
    # codesign cannot sign through Sparkle's top-level symlinks (XPCServices,
    # Updater.app, Sparkle, Autoupdate -> Versions/Current/...); it reports
    # "bundle format unrecognized, invalid, or unsuitable". Always sign the
    # resolved real path (e.g. .../Versions/B/XPCServices/Downloader.xpc).
    seen: set[str] = set()
    ordered: list[Path] = []
    for b in bundles:
        try:
            real = str(b.resolve())
        except Exception:
            real = str(b)
        if real not in seen:
            seen.add(real)
            ordered.append(b.resolve() if b.is_symlink() else b)

    # Sort by depth descending (deeper first) so inner bundles are signed first.
    ordered.sort(key=lambda p: len(p.parts), reverse=True)
    return ordered

def _find_macho_binaries(app_bundle: Path) -> list[Path]:
    """Find Mach-O binaries that need individual signing before their bundle."""
    candidates: list[Path] = []
    # Common locations: Contents/MacOS/*, Frameworks/**/*.dylib, Frameworks/**/Versions/*/...
    for pattern in ["Contents/MacOS/*", "Contents/Frameworks/**/*", "Contents/Frameworks/*"]:
        for p in app_bundle.glob(pattern):
            if p.is_file() and _is_macho(p):
                candidates.append(p)
    # Also direct dylibs/so inside Contents/MacOS (Nuitka may place .so there)
    for p in (app_bundle / "Contents" / "MacOS").rglob("*"):
        if p.is_file() and _is_macho(p) and p not in candidates:
            candidates.append(p)
    # Also Sparkle binaries that are not inside a bundle's MacOS (e.g. Versions/B/Sparkle, Autoupdate)
    for p in app_bundle.rglob("Sparkle"):
        if p.is_file() and _is_macho(p) and p not in candidates:
            candidates.append(p)
    for p in app_bundle.rglob("Autoupdate"):
        if p.is_file() and _is_macho(p) and p not in candidates:
            candidates.append(p)
    return sorted(set(candidates))

def _codesign_path(path: Path, identity: str, entitlements: Path | None, *, verbose: bool) -> None:
    cmd = ["codesign", "--force", "--sign", identity, "--options", "runtime", "--timestamp"]
    # Entitlements only for the outermost App.app and its main executable
    is_main_app = path.suffix == ".app" and "Contents/Frameworks" not in str(path) and "XPCServices" not in str(path) and "Updater.app" not in str(path)
    is_main_exe = path.name == "App" and "Contents/MacOS" in str(path) and "Frameworks" not in str(path)
    if entitlements and entitlements.is_file() and (is_main_app or is_main_exe):
        cmd += ["--entitlements", str(entitlements)]
    # Do NOT use --deep, do NOT use --no-strict
    cmd.append(str(path))
    _run(cmd, verbose=verbose)

def _verify(app_bundle: Path, identity: str = "-", verbose: bool = True) -> None:
    print("\nVerifying signatures...")
    _run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_bundle)], verbose=verbose)
    # spctl (Gatekeeper) only passes AFTER notarization and for a fully-formed
    # distributable .app. At codesign time the bundle isn't notarized yet, so
    # spctl is expected to fail. Treat it as a warning, not a hard error —
    # the meaningful check is `codesign --verify --strict` above.
    if identity != "-":
        try:
            _run(["spctl", "--assess", "--type", "execute", "--verbose", str(app_bundle)], verbose=verbose)
        except subprocess.CalledProcessError as e:
            print("⚠️  spctl did not pass yet — expected before notarization "
                  f"(Gatekeeper needs a notarized, properly-formed bundle). stderr: {e.stderr}")
    else:
        print("(skipping spctl for ad-hoc signing — Gatekeeper will reject ad-hoc, expected)")
    print("✅ Verification passed (strict)")

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Codesign a Nuitka .app + Sparkle.framework (inside-out, no --deep).")
    parser.add_argument("--app-bundle", required=True, type=Path, help="Path to .app bundle (e.g. build/App.app)")
    parser.add_argument("--identity", default="-", help="Signing identity (default: '-' for ad-hoc). Use 'Developer ID Application: ...' for distribution.")
    parser.add_argument("--entitlements", type=Path, default=Path("scripts/entitlements.plist"), help="Entitlements plist for the main app (optional)")
    parser.add_argument("--skip-verify", action="store_true", help="Skip verification step")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args(argv)

    app_bundle: Path = args.app_bundle
    identity: str = args.identity
    entitlements: Path | None = args.entitlements if args.entitlements and args.entitlements.is_file() else None

    if not app_bundle.is_dir():
        sys.exit(f"Error: {app_bundle} is not a directory / .app bundle not found")
    if not (app_bundle / "Contents" / "Info.plist").is_file():
        sys.exit(f"Error: {app_bundle}/Contents/Info.plist missing — not a valid .app bundle")

    if sys.platform != "darwin":
        print("Warning: codesign is only available on macOS — skipping")
        return

    # Check codesign exists
    try:
        subprocess.run(["which", "codesign"], capture_output=True, check=True)
    except FileNotFoundError:
        sys.exit("Error: codesign not found (are you on macOS?)")

    print(f"Signing bundle: {app_bundle}")
    print(f"Identity: {identity}")
    if entitlements:
        print(f"Entitlements: {entitlements}")
    else:
        print("Entitlements: (none, using hardened runtime without custom entitlements)")

    # 1. Strip existing signatures that are ad-hoc from previous runs? No — --force overwrites.

    # 2. Sign nested bundles inside-out (XPC -> Updater.app -> Frameworks)
    nested = _find_nested_bundles(app_bundle)
    if nested:
        print(f"\nFound {len(nested)} nested bundle(s) to sign inside-out:")
        for b in nested:
            print(f"  - {os.path.relpath(b, app_bundle)}")

        for bundle in nested:
            # For frameworks/XPCs, sign without custom entitlements
            # For the main Sparkle binaries, sign the Mach-O inside first if needed
            print(f"\nSigning bundle: {os.path.relpath(bundle, app_bundle)}")
            cmd = ["codesign", "--force", "--sign", identity, "--options", "runtime", "--timestamp", str(bundle)]
            _run(cmd, verbose=args.verbose)
    else:
        print("No nested Sparkle bundles found — signing main app only")

    # 3. Also sign any loose Mach-O binaries that are not inside a signed bundle yet
    # (e.g. Contents/MacOS/App, Qt dylibs). We sign them before the outer app.
    machos = _find_macho_binaries(app_bundle)
    # Filter to those not already covered by bundle signing — but signing them again is harmless
    # We sign top-level Mach-Os that live outside Frameworks bundles
    loose = [m for m in machos if "Contents/MacOS" in str(m) and "Frameworks" not in str(m) and "XPCServices" not in str(m)]
    if loose:
        print(f"\nSigning {len(loose)} Mach-O binary(ies) in Contents/MacOS:")
        for m in loose:
            print(f"  - {os.path.relpath(m, app_bundle)}")
            # Main executable gets entitlements + hardened runtime
            cmd = ["codesign", "--force", "--sign", identity, "--options", "runtime", "--timestamp"]
            if entitlements and m.name == "App":
                cmd += ["--entitlements", str(entitlements)]
            cmd.append(str(m))
            _run(cmd, verbose=args.verbose)

    # 4. Finally sign the outer .app bundle (with entitlements if provided)
    print(f"\nSigning outer bundle: {app_bundle}")
    cmd = ["codesign", "--force", "--sign", identity, "--options", "runtime", "--timestamp"]
    if entitlements:
        cmd += ["--entitlements", str(entitlements)]
    cmd.append(str(app_bundle))
    _run(cmd, verbose=args.verbose)

    if not args.skip_verify:
        try:
            _verify(app_bundle, identity=identity, verbose=args.verbose)
        except subprocess.CalledProcessError as e:
            print("\n⚠️  Strict verification failed — this bundle will be rejected by Sparkle/Gatekeeper.", file=sys.stderr)
            print("   If you used ad-hoc signing ('-'), this is expected for local dev.", file=sys.stderr)
            print("   For distribution, sign with a valid Developer ID and notarize.", file=sys.stderr)
            raise

    print("\n✅ Codesign complete.")

if __name__ == "__main__":
    main()
