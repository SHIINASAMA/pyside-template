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
    cmd = ["xcrun", "notarytool", "submit", str(submit_path)]
    if os.getenv("APPLE_API_KEY"):
        cmd += ["--key", os.getenv("APPLE_API_KEY"), "--key-id", os.getenv("APPLE_API_KEY_ID", ""), "--issuer", os.getenv("APPLE_API_ISSUER")]
    else:
        cmd += ["--apple-id", os.getenv("APPLE_ID"), "--password", os.getenv("APPLE_APP_SPECIFIC_PASSWORD"), "--team-id", os.getenv("APPLE_TEAM_ID")]

    KEY_ARGS = []
    if os.getenv("APPLE_API_KEY"):
        KEY_ARGS = ["--key", os.getenv("APPLE_API_KEY"), "--key-id", os.getenv("APPLE_API_KEY_ID", ""), "--issuer", os.getenv("APPLE_API_ISSUER")]
    else:
        KEY_ARGS = ["--apple-id", os.getenv("APPLE_ID"), "--password", os.getenv("APPLE_APP_SPECIFIC_PASSWORD"), "--team-id", os.getenv("APPLE_TEAM_ID")]

    submission_id = ""
    try:
        # Run submit with --wait; capture output so we can extract the id/status.
        print("Submitting for notarization...")
        result = subprocess.run(cmd + ["--wait"], capture_output=True, text=True)
        out = result.stdout + result.stderr
        print(out)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, out)
        # Extract the submission id to fetch the notarization log for diagnostics.
        import re
        m = re.search(r"id: ([0-9a-fA-F-]{36})", out)
        if m:
            submission_id = m.group(1)
            print(f"Submission ID: {submission_id}")
    finally:
        if tmp_zip and tmp_zip.exists():
            tmp_zip.unlink(missing_ok=True)

    # If the submission id was captured and status is Invalid, fetch the
    # notarization log so the real reason is visible in CI.
    if submission_id:
        # notarytool log returns non-zero if there's no log yet; ignore failure.
        log_cmd = ["xcrun", "notarytool", "log", submission_id] + KEY_ARGS
        print(f"Fetching notarization log for {submission_id}...")
        lr = subprocess.run(log_cmd, capture_output=True, text=True)
        if lr.stdout:
            print("--- Notarization Log ---")
            print(lr.stdout)
        if lr.stderr:
            print(lr.stderr, file=sys.stderr)

    # Staple only if notarization succeeded. With --wait, notarytool exits 0 on
    # Invalid too, so check the output for Accepted before stapling.
    accepted = "status: Accepted" in out or "Accepted" in out or "Notarization successful" in out
    if not accepted:
        print("❌ Notarization was NOT accepted. Skipping staple (no ticket to attach).")
        sys.exit(1)

    staple_target = target
    print(f"Stapling {staple_target}...")
    _run(["xcrun", "stapler", "staple", str(staple_target)])
    _run(["xcrun", "stapler", "validate", str(staple_target)])
    print("✅ Notarization + stapling complete.")

if __name__ == "__main__":
    main()
