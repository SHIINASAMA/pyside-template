"""Notarize a macOS .app / .dmg via notarytool and staple.

Requires env:
  APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID
  or APPLE_API_KEY / APPLE_API_ISSUER

Usage:
  python scripts/notarize_macos.py --bundle build/App.app
  python scripts/notarize_macos.py --dmg release/AppInstaller.dmg

If env is missing, the script exits 0 with a warning (safe for forks / local dev).
"""

from __future__ import annotations
import argparse
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

def _run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)

def _have_notary_creds() -> bool:
    if os.getenv("APPLE_API_KEY") and os.getenv("APPLE_API_ISSUER"):
        return True
    return bool(os.getenv("APPLE_ID") and os.getenv("APPLE_APP_SPECIFIC_PASSWORD") and os.getenv("APPLE_TEAM_ID"))

def main(argv=None):
    p = argparse.ArgumentParser(description="Notarize .app or .dmg via notarytool")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--bundle", type=Path, help="Path to .app bundle")
    g.add_argument("--dmg", type=Path, help="Path to .dmg")
    p.add_argument("--wait", action="store_true", help="Wait for notarization to complete")
    args = p.parse_args(argv)

    if not _have_notary_creds():
        print("⚠️  Notarization credentials not set (APPLE_ID / APPLE_API_KEY) — skipping notarization.")
        print("   Set APPLE_ID + APPLE_APP_SPECIFIC_PASSWORD + APPLE_TEAM_ID or APPLE_API_KEY + APPLE_API_ISSUER to enable.")
        return

    target = args.bundle or args.dmg
    if not target.exists():
        sys.exit(f"Target not found: {target}")

    # notarytool requires a zip for .app, or can take .dmg directly
    submit_path: Path
    tmp_zip = None
    if args.bundle:
        tmp_zip = Path(tempfile.mktemp(suffix=".zip"))
        print(f"Zipping {target} -> {tmp_zip} for submission...")
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for f in target.rglob("*"):
                z.write(f, f.relative_to(target.parent))
        submit_path = tmp_zip
    else:
        submit_path = target

    # Build notarytool submit command
    cmd = ["xcrun", "notarytool", "submit", str(submit_path), "--wait" if args.wait else "--wait"]
    if os.getenv("APPLE_API_KEY"):
        cmd += ["--key", os.getenv("APPLE_API_KEY"), "--key-id", os.getenv("APPLE_API_KEY_ID", ""), "--issuer", os.getenv("APPLE_API_ISSUER")]
    else:
        cmd += ["--apple-id", os.getenv("APPLE_ID"), "--password", os.getenv("APPLE_APP_SPECIFIC_PASSWORD"), "--team-id", os.getenv("APPLE_TEAM_ID")]

    try:
        _run(cmd)
    finally:
        if tmp_zip and tmp_zip.exists():
            tmp_zip.unlink(missing_ok=True)

    # Staple if .app or .dmg
    staple_target = target
    print(f"Stapling {staple_target}...")
    _run(["xcrun", "stapler", "staple", str(staple_target)])
    _run(["xcrun", "stapler", "validate", str(staple_target)])
    print("✅ Notarization + stapling complete.")

if __name__ == "__main__":
    main()
