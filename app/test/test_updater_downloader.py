# app/test/test_updater_downloader.py
import hashlib
import zipfile
from pathlib import Path
import pytest
from app.builtin.updater.extractor import extract


class TestExtractor:
    def test_extract_zip(self, tmp_path):
        archive = tmp_path / "test.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("hello.txt", "hello world")

        dest = tmp_path / "out"
        result = extract(archive, dest)
        assert (result / "hello.txt").read_text() == "hello world"

    def test_extract_unsupported(self, tmp_path):
        archive = tmp_path / "test.rar"
        archive.write_text("fake")
        dest = tmp_path / "out"
        with pytest.raises(RuntimeError, match="Unsupported"):
            extract(archive, dest)


class TestDownloaderChecksum:
    def test_sha256_calculation(self, tmp_path):
        """Test that we can compute sha256 of a file (unit test, no network)."""
        data = b"hello world"
        expected = hashlib.sha256(data).hexdigest()
        f = tmp_path / "test.bin"
        f.write_bytes(data)
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual == expected
