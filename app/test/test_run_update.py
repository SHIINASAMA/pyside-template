# app/test/test_run_update.py
import os
import sys
from pathlib import Path
from unittest.mock import patch
from app.builtin.updater.run_update import (
    parse_update_args, wait_for_process_exit, replace_files, cleanup,
)


class TestParseUpdateArgs:
    def test_parse_all_flags(self):
        fake_argv = [
            "app", "--updater",
            "--updater-source", "/tmp/staging",
            "--updater-target", "/opt/app",
            "--updater-launch", "App",
            "--updater-old-pid", "12345",
            "--backup",
            "--updater-timeout", "60",
        ]
        with patch.object(sys, "argv", fake_argv):
            args = parse_update_args()
        assert args.source == Path("/tmp/staging")
        assert args.target == Path("/opt/app")
        assert args.launch == "App"
        assert args.old_pid == 12345
        assert args.backup is True
        assert args.timeout == 60

    def test_parse_defaults(self):
        fake_argv = ["app", "--updater"]
        with patch.object(sys, "argv", fake_argv):
            args = parse_update_args()
        assert args.old_pid == 0
        assert args.backup is False
        assert args.timeout == 30


class TestWaitForProcessExit:
    def test_nonexistent_pid_exits_immediately(self):
        # PID -1 does not exist, should return quickly
        wait_for_process_exit(-1, timeout=1)


class TestCleanup:
    def test_removes_directory(self, tmp_path):
        d = tmp_path / "staging"
        d.mkdir()
        (d / "file.txt").write_text("test")
        cleanup(d)
        assert not d.exists()
