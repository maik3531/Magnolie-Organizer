import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modul_laden import quellmodul_laden


ROOT = Path(__file__).resolve().parents[1]
policy = quellmodul_laden("magnolie_cloud_policy", ROOT / "bin" / "magnolie_cloud_backup.py")
organizer = quellmodul_laden("magnolie_cloud_organizer", ROOT / "bin" / "magnolie-organizer")


def test_native_secret_calls_receive_a_live_bounded_cancellable(monkeypatch):
    pytest.importorskip("gi.repository.Gio")
    monkeypatch.setattr(policy, "SECRET_OPERATION_TIMEOUT", 0.02)
    seen = []
    class Secret:
        COLLECTION_DEFAULT = "owned-collection"
        @staticmethod
        def blocked(*args):
            cancellation = args[-1]
            assert cancellation is not None and not cancellation.is_cancelled()
            event = threading.Event()
            cancellation.connect(lambda *_args: event.set())
            assert event.wait(1), "Native call did not receive cancellation"
            seen.append(cancellation.is_cancelled())
            raise RuntimeError("owned_cancelled_native_call")
        password_lookup_sync = blocked
        password_store_sync = blocked
    store = policy.ArchiveSecretStore()
    monkeypatch.setattr(store, "_secret", lambda: (Secret, "owned-schema"))
    started = time.monotonic()
    assert store.available() is False
    with pytest.raises(RuntimeError):
        store.store("owned-fixture-password")
    assert seen == [True, True] and time.monotonic() - started < 1


def test_due_policy_and_retention_bounds():
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    assert not policy.due(False, "daily", "", now)
    assert policy.due(True, "daily", "", now)
    assert not policy.due(True, "daily", "2026-08-30T12:00:01Z", now)
    assert policy.due(True, "daily", "2026-08-30T12:00:00Z", now)
    assert not policy.due(True, "weekly", "2026-08-25T12:00:00Z", now)
    assert policy.due(True, "weekly", "2026-08-24T12:00:00Z", now)
    assert policy.retention_count(1) == 2
    assert policy.retention_count(99) == 30


def test_retention_only_deletes_owned_regular_files_after_verified_success(tmp_path):
    files = []
    for index in range(4):
        path = tmp_path / ("magnolie-auto-2026083%d-120000-000000-%s.magnolie" %
                           (index, chr(ord("a") + index) * 32))
        path.write_text("archive", encoding="utf-8")
        files.append(path)
    unrelated = tmp_path / "magnolie-auto-keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    symlink = tmp_path / ("magnolie-auto-20260830-130000-000000-%s.magnolie" % ("f" * 32))
    symlink.symlink_to(unrelated)
    deleted = policy.apply_retention(str(tmp_path), 2, str(files[-1]))
    assert len(deleted) == 2
    assert files[-1].exists()
    assert unrelated.exists() and symlink.is_symlink()


def test_archive_is_read_back_before_retention_and_failed_readback_is_removed(tmp_path, monkeypatch):
    data = {"version": 6, "termine": [], "einstellungen": {}}
    events = []
    original_read = organizer.gesamtarchiv_lesen
    monkeypatch.setattr(organizer, "gesamtarchiv_lesen",
                        lambda path, password: (events.append("read"), original_read(path, password))[1])
    monkeypatch.setattr(organizer, "cloud_backup_retention",
                        lambda *args: events.append("retention"))
    path = organizer.automatische_sicherung_anlegen(data, str(tmp_path), "Rosenholz1896", 7)
    assert events == ["read", "retention"] and os.path.isfile(path)

    monkeypatch.setattr(organizer, "gesamtarchiv_lesen",
                        lambda *_args: (_ for _ in ()).throw(RuntimeError("tampered")))
    with pytest.raises(RuntimeError):
        organizer.automatische_sicherung_anlegen(data, str(tmp_path), "Rosenholz1896", 7)
    assert len(list(tmp_path.glob("*.magnolie"))) == 1


def test_secret_service_is_dedicated_and_fails_closed():
    class Broken:
        def lookup(self, _account):
            raise RuntimeError("unavailable")

    store = policy.ArchiveSecretStore(Broken())
    assert store.SCHEMA_NAME.endswith("AutomaticBackup")
    assert "Nextcloud" not in store.SCHEMA_NAME
    assert not store.available()
    source = (ROOT / "bin" / "magnolie_cloud_backup.py").read_text(encoding="utf-8")
    assert "plaintext" not in source.lower()
    assert "Secret.password_store_sync" in source


def test_linux_save_routing_never_uses_background_daemon_for_cloud_backup():
    source = (ROOT / "bin" / "magnolie-organizer").read_text(encoding="utf-8")
    worker = source[source.index("    def _speicher_lauf(self):"):source.index("    def _darf_schreiben(self):")]
    assert "_cloud_sicherung_nach_speichern(daten)" in worker
    assert "background" not in worker and "daemon" not in worker
    assert "_daten_sperre" in worker


def cross_windows_dpapi_save_routing_and_readback_sources():
    windows = ROOT.parent / "magnolie-organizer-windows"
    service = (windows / "CloudBackupService.cs").read_text(encoding="utf-8")
    dispatcher = (windows / "BridgeDispatcher.cs").read_text(encoding="utf-8")
    paths = (windows / "WindowsPaths.cs").read_text(encoding="utf-8")
    assert "DataProtectionScope.CurrentUser" in service
    assert "AutomaticBackup/v1" in service and "CloudBackupPassword" in paths
    assert "RunCloudBackupAfterSaveAsync(document.RootElement.GetRawText(), force: false)" in dispatcher
    assert "cloud_sicherung_test" in dispatcher and "MutationGate.Global.WaitAsync()" in dispatcher
    assert service.index("GesamtarchivService.Read") < service.index(
        "ApplyRetention(settings.Folder")
    assert "FileAttributes.ReparsePoint" in service and "ListingLimit = 1000" in service
