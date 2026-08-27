# app/builtin/updater/extractor.py
import os
from pathlib import Path


def extract(archive_path: Path, dest_dir: Path) -> Path:
    """Extract a zip or tar.gz archive into dest_dir. Returns dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    if archive_path.name.endswith(".zip") or archive_path.suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    elif archive_path.name.endswith((".tar.gz", ".tgz")):
        import tarfile
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(dest_dir)
    else:
        raise RuntimeError(f"Unsupported archive format: {archive_path.name}")

    return dest_dir
