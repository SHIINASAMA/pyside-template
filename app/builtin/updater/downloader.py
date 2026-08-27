# app/builtin/updater/downloader.py
import hashlib
from pathlib import Path
from typing import Callable
from httpx import AsyncClient


async def fetch_checksum(url: str, client: AsyncClient) -> str | None:
    """Fetch sha256 checksum from a .sha256 file URL. Returns hash string or None."""
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
        text = r.text.strip()
        # Format: "<hash>  <filename>" or just "<hash>"
        return text.split()[0] if text else None
    except Exception:
        return None


async def download_with_checksum(
    url: str,
    dest: Path,
    expected_sha256: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """Download a file, optionally verify sha256. Returns dest path."""
    sha = hashlib.sha256()
    async with AsyncClient(follow_redirects=True) as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))
            downloaded = 0

            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes(8192):
                    f.write(chunk)
                    sha.update(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

    if expected_sha256 and sha.hexdigest() != expected_sha256:
        dest.unlink(missing_ok=True)
        raise ValueError(
            f"Checksum mismatch: expected {expected_sha256}, got {sha.hexdigest()}"
        )

    return dest
