"""Download Sparkle.framework and embed it into a macOS .app bundle.

This is a **build-time** script — run it after the .app bundle is assembled
but before signing / notarisation.  It is not imported by application code.

Usage example::

    python scripts/embed_sparkle.py \\
        --app-bundle-path dist/MyApp.app \\
        --sparkle-version 2.9.6 \\
        --appcast-url https://example.com/appcast.xml \\
        --eddsa-public-key BASE64KEY==

All arguments are required.  The script is idempotent: if the framework
already exists at the expected version it skips the download.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

_SPARKLE_VERSION_MARKER = "Sparkle.framework/.sparkle-version"

_DOWNLOAD_URL_TEMPLATE = (
    "https://github.com/sparkle-project/Sparkle/releases/download"
    "/{version}/Sparkle-{version}.tar.xz"
)


def _version_marker_path(app_bundle: Path) -> Path:
    """Return the path to the version marker inside the embedded framework."""
    # Store the version marker INSIDE the framework (Resources) so codesign
    # does not report "unsealed contents present in the root directory of an
    # embedded framework". A file at the framework root is treated as unsealed.
    return (
        app_bundle
        / "Contents"
        / "Frameworks"
        / "Sparkle.framework"
        / "Versions"
        / "B"
        / "Resources"
        / ".sparkle-version"
    )


def _already_embedded(app_bundle: Path, version: str) -> bool:
    """Return *True* if the requested version is already in place."""
    marker = _version_marker_path(app_bundle)
    if not marker.is_file():
        return False
    return marker.read_text().strip() == version


def _download_archive(version: str, dest: Path) -> None:
    """Download the Sparkle release archive to *dest*."""
    url = _DOWNLOAD_URL_TEMPLATE.format(version=version)
    print(f"Downloading Sparkle {version} ...")
    print(f"  URL: {url}")
    urllib.request.urlretrieve(url, dest)  # noqa: S310
    print(f"  Saved to {dest}")


def _extract_archive(archive: Path, dest_dir: Path) -> None:
    """Extract a ``.tar.xz`` archive into *dest_dir*."""
    import tarfile

    print("Extracting archive ...")
    with tarfile.open(archive) as tf:
        tf.extractall(dest_dir)  # noqa: S202
    print(f"  Extracted to {dest_dir}")


def _copy_framework(extracted_dir: Path, frameworks_dir: Path) -> None:
    """Copy ``Sparkle.framework`` into the bundle's Frameworks directory."""
    src = extracted_dir / "Sparkle.framework"
    if not src.is_dir():
        # Some releases nest under a top-level dir.
        candidates = list(extracted_dir.rglob("Sparkle.framework"))
        if not candidates:
            raise FileNotFoundError(
                "Could not locate Sparkle.framework in the extracted archive"
            )
        src = candidates[0]

    dst = frameworks_dir / "Sparkle.framework"
    if dst.exists():
        shutil.rmtree(dst)

    shutil.copytree(src, dst, symlinks=True)
    print(f"  Copied framework to {dst}")


def _write_version_marker(app_bundle: Path, version: str) -> None:
    """Write a small marker file so subsequent runs can skip re-download."""
    marker = _version_marker_path(app_bundle)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(version)


def _patch_info_plist(
    app_bundle: Path,
    *,
    appcast_url: str,
    eddsa_public_key: str,
) -> None:
    """Add / overwrite Sparkle keys in ``Info.plist``."""
    plist_path = app_bundle / "Contents" / "Info.plist"
    if not plist_path.is_file():
        raise FileNotFoundError(f"Info.plist not found at {plist_path}")

    with open(plist_path, "rb") as f:
        info = plistlib.load(f)

    info["SUFeedURL"] = appcast_url
    info["SUPublicEDKey"] = eddsa_public_key
    info["SUAllowsAutomaticUpdates"] = False
    # Sparkle requires CFBundleVersion to be present and non-empty.
    if "CFBundleVersion" not in info:
        info["CFBundleVersion"] = info.get("CFBundleShortVersionString", "1")

    with open(plist_path, "wb") as f:
        plistlib.dump(info, f, sort_keys=True)

    print(f"  Patched Info.plist at {plist_path}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed Sparkle.framework into a macOS .app bundle."
    )
    parser.add_argument(
        "--app-bundle-path",
        required=True,
        type=Path,
        help="Path to the .app bundle (e.g. dist/MyApp.app)",
    )
    parser.add_argument(
        "--sparkle-version",
        required=True,
        help="Sparkle release version to embed (e.g. 2.9.6)",
    )
    parser.add_argument(
        "--appcast-url",
        required=True,
        help="URL of the appcast XML feed",
    )
    parser.add_argument(
        "--eddsa-public-key",
        required=True,
        help="Base64-encoded EdDSA public key for Sparkle",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    app_bundle: Path = args.app_bundle_path
    version: str = args.sparkle_version

    if not (app_bundle / "Contents" / "Info.plist").is_file():
        sys.exit(f"Error: {app_bundle} does not look like a .app bundle")

    frameworks_dir = app_bundle / "Contents" / "Frameworks"
    frameworks_dir.mkdir(parents=True, exist_ok=True)

    # --- idempotent check ---
    if _already_embedded(app_bundle, version):
        print(f"Sparkle.framework {version} is already embedded - skipping download.")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / f"Sparkle-{version}.tar.xz"

            _download_archive(version, archive)
            _extract_archive(archive, tmp_path)
            _copy_framework(tmp_path, frameworks_dir)
            _write_version_marker(app_bundle, version)

    # --- patch Info.plist ---
    _patch_info_plist(
        app_bundle,
        appcast_url=args.appcast_url,
        eddsa_public_key=args.eddsa_public_key,
    )

    print("Done.")


if __name__ == "__main__":
    main()
