"""Tests for the admin backup router."""
import time
from pathlib import Path
import pytest


class TestBackupSettings:
    def test_get_settings_returns_enabled_when_no_flag(self, tmp_path):
        from app.routers.backup import _backup_settings
        result = _backup_settings(backups_dir=str(tmp_path))
        assert result["enabled"] is True
        assert result["backup_count"] == 0
        assert result["last_backup_file"] is None

    def test_get_settings_returns_disabled_when_flag_exists(self, tmp_path):
        (tmp_path / ".backup_disabled").touch()
        from app.routers.backup import _backup_settings
        result = _backup_settings(backups_dir=str(tmp_path))
        assert result["enabled"] is False

    def test_get_settings_counts_sql_gz_files(self, tmp_path):
        (tmp_path / "wattwise-20260101.sql.gz").write_bytes(b"fake")
        (tmp_path / "wattwise-20260102.sql.gz").write_bytes(b"fake")
        from app.routers.backup import _backup_settings
        result = _backup_settings(backups_dir=str(tmp_path))
        assert result["backup_count"] == 2

    def test_get_settings_reports_last_backup(self, tmp_path):
        f1 = tmp_path / "wattwise-20260101.sql.gz"
        f1.write_bytes(b"a")
        time.sleep(0.05)
        f2 = tmp_path / "wattwise-20260102.sql.gz"
        f2.write_bytes(b"b")
        from app.routers.backup import _backup_settings
        result = _backup_settings(backups_dir=str(tmp_path))
        assert result["last_backup_file"] == "wattwise-20260102.sql.gz"


class TestBackupToggle:
    def test_enable_backup_removes_flag_file(self, tmp_path):
        flag = tmp_path / ".backup_disabled"
        flag.touch()
        from app.routers.backup import _set_backup_enabled
        _set_backup_enabled(enabled=True, backups_dir=str(tmp_path))
        assert not flag.exists()

    def test_disable_backup_creates_flag_file(self, tmp_path):
        from app.routers.backup import _set_backup_enabled
        _set_backup_enabled(enabled=False, backups_dir=str(tmp_path))
        assert (tmp_path / ".backup_disabled").exists()

    def test_enable_when_already_enabled_is_idempotent(self, tmp_path):
        from app.routers.backup import _set_backup_enabled
        _set_backup_enabled(enabled=True, backups_dir=str(tmp_path))
        _set_backup_enabled(enabled=True, backups_dir=str(tmp_path))
        assert not (tmp_path / ".backup_disabled").exists()


class TestBackupList:
    def test_list_returns_files_sorted_newest_first(self, tmp_path):
        f1 = tmp_path / "wattwise-20260101.sql.gz"
        f1.write_bytes(b"aaaa")
        time.sleep(0.05)
        f2 = tmp_path / "wattwise-20260102.sql.gz"
        f2.write_bytes(b"bb")
        from app.routers.backup import _list_backups
        result = _list_backups(backups_dir=str(tmp_path))
        assert result[0]["name"] == "wattwise-20260102.sql.gz"
        assert result[1]["name"] == "wattwise-20260101.sql.gz"
        assert result[0]["size_bytes"] == 2
        assert result[1]["size_bytes"] == 4
