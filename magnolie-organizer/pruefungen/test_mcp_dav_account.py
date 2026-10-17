"""Actual DAV settings/secret-adapter snapshots, with owned RAM credentials only."""
import importlib
import json
import threading

from test_startup_read_failure import native, Host


class Vault:
    def __init__(self):
        self.values = {}
        self.fail = False
        self.entered = threading.Event()
        self.release = None

    def store(self, account, password):
        self.values[account] = password
        if self.release is not None:
            self.entered.set()
            assert self.release.wait(3)
        return True

    def lookup(self, account):
        if self.fail:
            raise RuntimeError("owned-private-vault-error")
        return self.values.get(account)

    def clear(self, account):
        self.values.pop(account, None)
        return True


def account_store(native, tmp_path):
    sdk = importlib.import_module(native.NextcloudSettingsStore.__module__)
    vault = Vault()
    return native.NextcloudSettingsStore(str(tmp_path / "owned-dav.json"), sdk.SecretServiceStore(vault)), vault


def test_actual_account_snapshot_revision_and_correlated_redacted_status(native, monkeypatch, tmp_path):
    store, vault = account_store(native, tmp_path)
    monkeypatch.setattr(native, "nextcloud_speicher", lambda: store)
    monkeypatch.setattr(native, "NextcloudDav", lambda *_: (_ for _ in ()).throw(AssertionError("A metadata read must not discover remote collections")))
    empty = store.read_snapshot()
    assert empty[0] is None and not empty[1] and len(empty[2]) == 64 and empty[3] is None
    assert store.read_snapshot()[2] == empty[2]
    store.save(True, True, "https://owned.example.test", "owned-reader", "owned-secret-alpha")
    first = store.read_snapshot()
    assert first[1] and first[2] != empty[2] and first[3] is None
    host = Host(native); host._gesperrt = False
    host._nextcloud_status_melden("App.baumBriefkastenStatus", "owned-request")
    callback, result = host.responses[-1]
    assert callback == "App.baumBriefkastenStatus" and result["requestId"] == "owned-request" and result["revision"] == first[2]
    assert result["url"] == "https://owned.example.test" and result["benutzer"] == "owned-reader" and result["kennwortVorhanden"]
    assert not result["kalender"] and not result["adressbuecher"] and result["fehler"] == ""
    assert "owned-secret-alpha" not in json.dumps(result) and "owned-secret-alpha" not in (tmp_path / "owned-dav.json").read_text()
    public_config = (tmp_path / "owned-dav.json").read_text()
    store.save(True, True, "https://owned.example.test", "owned-reader", "owned-secret-beta")
    second = store.read_snapshot()
    assert second[2] != first[2] and (tmp_path / "owned-dav.json").read_text() == public_config
    same_store = native.NextcloudSettingsStore(store.path, store.secrets)
    assert same_store.read_snapshot()[2] == second[2]
    vault.fail = True
    host._nextcloud_status_melden("App.baumBriefkastenStatus", "owned-unavailable")
    unavailable = host.responses[-1][1]
    assert unavailable["revision"] is None and unavailable["fehlerCode"] == "secret_service_unavailable"
    assert unavailable["url"] == "https://owned.example.test" and unavailable["benutzer"] == "owned-reader"
    assert "owned-private-vault-error" not in json.dumps(unavailable)
    vault.fail = False
    (tmp_path / "owned-dav.json").write_text("{damaged", encoding="utf-8")
    host._nextcloud_status_melden("App.baumBriefkastenStatus", "owned-invalid")
    assert host.responses[-1][1]["revision"] is None and host.responses[-1][1]["fehlerCode"] == "invalid_config"
    host._gesperrt = True
    host._nextcloud_status_melden("App.baumBriefkastenStatus", "owned-locked")
    assert host.responses[-1][1] == {"requestId": "owned-locked", "ok": False, "code": "profile_locked"}
    assert not host._mcp_dav_status_aktiv
    host.bei_nachricht(json.dumps({"cmd": "baum_briefkasten_status", "requestId": "owned-locked-dispatch"}))
    assert host.responses[-1][1] == {"requestId": "owned-locked-dispatch", "ok": False, "code": "profile_locked"}
    host._gesperrt = False
    host._mcp_dav_status_aktiv = True
    host.bei_nachricht(json.dumps({"cmd": "baum_briefkasten_status", "requestId": "owned-busy"}))
    assert host.responses[-1][1]["code"] == "native_busy"


def test_snapshot_waits_for_the_same_real_save_transaction(native, tmp_path):
    store, vault = account_store(native, tmp_path)
    store.save(False, False, "https://owned.example.test", "owned-reader", "owned-secret-alpha")
    vault.release = threading.Event()
    errors, snapshots = [], []
    def save():
        try:
            store.save(True, False, "https://owned.example.test", "owned-reader", "owned-secret-beta")
        except BaseException as error:
            errors.append(error)
    def read():
        try:
            snapshots.append(store.read_snapshot())
        except BaseException as error:
            errors.append(error)
    writer = threading.Thread(target=save)
    reader = threading.Thread(target=read)
    try:
        writer.start(); assert vault.entered.wait(2)
        reader.start(); reader.join(0.05)
        assert reader.is_alive() and not snapshots
    finally:
        vault.release.set(); writer.join(3)
        if reader.ident is not None:
            reader.join(3)
    assert not writer.is_alive() and not reader.is_alive() and not errors
    assert snapshots[0][0]["davAktiv"] and snapshots[0][1] and snapshots[0][3] is None
    assert snapshots[0][2] == store.read_snapshot()[2]
