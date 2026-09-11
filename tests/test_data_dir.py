"""Where the administration ends up.

The default location is not a detail: it decides whether someone's books quietly get
synced to a cloud drive, whether they can find them to make a back-up, and whether an
update leaves them looking at an empty administration.
"""

from __future__ import annotations

from app import db


class TestDefaultLocation:
    def test_a_fresh_install_gets_a_visible_folder_in_the_home_directory(self, tmp_path):
        assert db.standaard_data_dir(tmp_path) == tmp_path / "Boekhouding"

    def test_it_avoids_the_folders_that_sync_or_hide(self, tmp_path):
        delen = db.standaard_data_dir(tmp_path).relative_to(tmp_path).parts
        assert "Documents" not in delen, "OneDrive backs this one up; SQLite hates that"
        assert "OneDrive" not in delen
        assert "AppData" not in delen, "invoices and receipts are not program state"


class TestAnExistingAdministration:
    def test_one_in_the_old_place_keeps_being_used(self, tmp_path):
        oud = tmp_path / db.OUDE_DATA_DIR
        oud.mkdir(parents=True)
        (oud / "boekhouding.sqlite3").write_bytes(b"SQLite format 3\x00")
        assert db.standaard_data_dir(tmp_path) == oud

    def test_an_old_folder_without_a_database_is_ignored(self, tmp_path):
        (tmp_path / db.OUDE_DATA_DIR).mkdir(parents=True)
        assert db.standaard_data_dir(tmp_path) == tmp_path / "Boekhouding"

    def test_the_new_place_wins_once_it_exists(self, tmp_path):
        """After moving the folder, both exist for a while. The new one counts."""
        oud = tmp_path / db.OUDE_DATA_DIR
        oud.mkdir(parents=True)
        (oud / "boekhouding.sqlite3").write_bytes(b"SQLite format 3\x00")
        (tmp_path / "Boekhouding").mkdir()
        assert db.standaard_data_dir(tmp_path) == tmp_path / "Boekhouding"
