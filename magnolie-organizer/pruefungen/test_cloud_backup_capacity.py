"""Reject a full backup directory before producing another archive (#818)."""
import importlib
from pathlib import Path

import pytest

from modul_laden import quellmodul_laden


ROOT = Path(__file__).resolve().parents[1]
native = quellmodul_laden("magnolie_cloud_capacity", ROOT / "bin/magnolie-organizer")
policy = importlib.import_module("magnolie_cloud_backup")
DATA = {"version": 6, "termine": [], "einstellungen": {}}
PASSWORD = "synthetic-capacity-test"


def fill(directory, count):
    for index in range(count):
        (directory / ("unrelated-%04d" % index)).write_bytes(b"preserve")


def create(directory):
    return native.automatische_sicherung_anlegen(DATA, str(directory), PASSWORD, 2)


def test_repeated_failure_in_full_directory_does_not_create_archives(tmp_path):
    fill(tmp_path, 1000)
    for _ in range(3):
        with pytest.raises(OSError, match="too many entries"):
            create(tmp_path)
        assert not list(tmp_path.glob("*.magnolie"))
        assert len(list(tmp_path.iterdir())) == 1000
    assert all(path.read_bytes() == b"preserve" for path in tmp_path.iterdir())


def test_capacity_is_checked_before_archive_encryption(tmp_path, monkeypatch):
    fill(tmp_path, 1000)
    def must_not_encode(*args, **kwargs):
        raise AssertionError("A rejected backup folder reached archive encryption")
    monkeypatch.setattr(native, "gesamtarchiv_erzeugen", must_not_encode)
    with pytest.raises(OSError, match="too many entries"):
        create(tmp_path)


def test_last_available_slot_succeeds_and_subsequent_attempt_is_read_only(tmp_path):
    fill(tmp_path, 999)
    archive = Path(create(tmp_path))
    original = archive.read_bytes()
    result = native.gesamtarchiv_lesen(str(archive), PASSWORD)
    assert result["daten"]["termine"] == []
    assert len(list(tmp_path.iterdir())) == 1000
    with pytest.raises(OSError, match="too many entries"):
        create(tmp_path)
    assert list(tmp_path.glob("*.magnolie")) == [archive]
    assert archive.read_bytes() == original


def test_bounded_directory_still_verifies_then_prunes_only_owned_archives(tmp_path):
    fill(tmp_path, 997)
    first = Path(create(tmp_path))
    second = Path(create(tmp_path))
    third = Path(create(tmp_path))
    assert not first.exists()
    assert second.exists() and third.exists()
    assert len(list(tmp_path.glob("unrelated-*"))) == 997
    assert native.gesamtarchiv_lesen(str(third), PASSWORD)["daten"]["termine"] == []


def test_external_change_after_verification_preserves_archive_and_blocks_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "LIST_LIMIT", 2)
    fill(tmp_path, 1)
    original_read = native.gesamtarchiv_lesen

    def read_then_add_foreign_file(*args, **kwargs):
        result = original_read(*args, **kwargs)
        (tmp_path / "foreign-after-verification").write_bytes(b"preserve")
        return result

    monkeypatch.setattr(native, "gesamtarchiv_lesen", read_then_add_foreign_file)
    with pytest.raises(OSError, match="too many entries"):
        create(tmp_path)
    archive, = tmp_path.glob("*.magnolie")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert original_read(str(archive), PASSWORD)["daten"]["termine"] == []
    with pytest.raises(OSError, match="too many entries"):
        create(tmp_path)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
