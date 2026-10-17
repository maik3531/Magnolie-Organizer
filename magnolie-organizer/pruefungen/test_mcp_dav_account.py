"""Actual DAV settings/secret-adapter snapshots, with owned RAM credentials only."""
import importlib
import json
import threading
from test_nextcloud import multistatus, dav_response

from test_startup_read_failure import native, Host


class Vault:
    def __init__(self):
        self.values = {}
        self.fail = False
        self.entered = threading.Event()
        self.release = None
        self.drop_store = False
        self.drop_clear = False

    def store(self, account, password):
        if self.drop_store:
            return True
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
        if self.drop_clear:
            return True
        self.values.pop(account, None)
        return True


def test_correlated_connection_uses_real_discovery_and_rejects_changed_account(native, monkeypatch, tmp_path):
    store, vault = account_store(native, tmp_path)
    monkeypatch.setattr(native, "nextcloud_speicher", lambda: store)
    store.save(True, True, "https://owned.example.test", "owned-reader", "owned-discovery-secret")
    revision = store.read_snapshot()[2]
    calls = []
    mode = ["ok"]
    def transport(method, url, *_args):
        calls.append((method, url))
        if mode[0] == "change":
            mode[0] = "ok"
            store.save(True, True, "https://owned.example.test", "owned-reader", "owned-new-secret")
        if mode[0] == "fail":
            return 401, {}, b"owned-private-server-error"
        if ".well-known/" in url:
            calendar = "caldav" in url
            prefix, tag, ns = ("c", "calendar", "caldav") if calendar else ("a", "addressbook", "carddav")
            return 207, {}, multistatus(dav_response(url, [(prefix + ":" + tag + "-home-set", "<d:href>/" + tag + "/</d:href>")]),
                                       namespaces='xmlns:%s="urn:ietf:params:xml:ns:%s"' % (prefix, ns))
        calendar = "/calendar/" in url
        marker = '<c:calendar xmlns:c="urn:ietf:params:xml:ns:caldav"/>' if calendar else '<a:addressbook xmlns:a="urn:ietf:params:xml:ns:carddav"/>'
        return 207, {}, multistatus(dav_response(url + "owned/", [("d:resourcetype", marker)]))
    original_client = native.configured_client
    monkeypatch.setattr(native, "configured_client", lambda store, *args, **kwargs: original_client(store, transport=transport, **kwargs))
    host = Host(native); host._gesperrt = False
    host._nextcloud_dav_pruefen("owned-discovery-request", revision)
    callback, result = host.responses[-1]
    assert callback == "App.baumDavPruefung" and result["requestId"] == "owned-discovery-request"
    assert result["ok"] and result["reachable"] and result["revision"] == revision
    assert result["calendars"] == result["addressBooks"] == 1
    assert calls and all(method == "PROPFIND" for method, _ in calls)
    assert "owned-discovery-secret" not in json.dumps(result) and not host._mcp_dav_test_aktiv
    count = len(calls)
    host._nextcloud_dav_pruefen("owned-stale", "0" * 64)
    assert host.responses[-1][1]["code"] == "conflict" and len(calls) == count
    mode[0] = "fail"
    host._nextcloud_dav_pruefen("owned-401", revision)
    result = host.responses[-1][1]
    assert result["ok"] and not result["reachable"] and result["errorCode"] == "http_401"
    assert "owned-private" not in json.dumps(result)
    mode[0] = "change"
    host._nextcloud_dav_pruefen("owned-race", revision)
    assert host.responses[-1][1]["code"] == "conflict"
    host._gesperrt = True
    count = len(calls)
    host._nextcloud_dav_pruefen("owned-locked", store.read_snapshot()[2])
    assert host.responses[-1][1]["code"] == "profile_locked" and len(calls) == count
    host._gesperrt = False
    store.save(False, True, "https://owned.example.test", "owned-reader", "")
    host._nextcloud_dav_pruefen("owned-inactive", store.read_snapshot()[2])
    assert host.responses[-1][1]["code"] == "not_active" and len(calls) == count


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


def test_checked_save_verifies_config_and_credentials_not_just_backend_ack(native, monkeypatch, tmp_path):
    store, vault = account_store(native, tmp_path)
    first_revision = store.read_snapshot()[2]
    first = store.save_checked(first_revision, False, False, "https://owned.example.test/", " owned-reader ", "owned-secret-alpha")
    assert first[0]["server"] == "https://owned.example.test" and first[0]["benutzer"] == "owned-reader" and first[1]
    rewritten = store.save_checked(first[2], False, False, "https://owned.example.test", "owned-reader", "owned-secret-alpha")
    assert rewritten[2] != first[2], "A credential rewrite must create a fresh native version even for the same value"
    before = (tmp_path / "owned-dav.json").read_text(), dict(vault.values)
    try:
        store.save_checked(first[2], False, False, "https://owned.example.test", "owned-reader", "owned-secret-beta")
        raise AssertionError("Stale native revision accepted")
    except Exception as error:
        assert getattr(error, "code", None) == "conflict"
    assert ((tmp_path / "owned-dav.json").read_text(), vault.values) == before
    old_account = store.account("https://owned.example.test", "owned-reader")
    moved = store.save_checked(rewritten[2], False, False, "https://other-owned.example.test", "other-reader", "owned-secret-gamma", account_type="generic-dav")
    assert moved[0]["kontoArt"] == "generic-dav" and moved[1] and old_account not in vault.values
    cleared = store.save_checked(moved[2], False, False, "https://other-owned.example.test", "other-reader", delete_password=True, account_type="generic-dav")
    assert not cleared[1] and not vault.values
    vault.drop_store = True
    try:
        store.save_checked(cleared[2], False, False, "https://other-owned.example.test", "other-reader", "owned-false-store", account_type="generic-dav")
        raise AssertionError("Successful backend ack without stored credential was accepted")
    except Exception as error:
        assert getattr(error, "code", None) == "verification_failed"
    vault.drop_store = False
    restored = store.save_checked(store.read_snapshot()[2], False, False, "https://other-owned.example.test", "other-reader", "owned-secret-restored", account_type="generic-dav")
    vault.drop_clear = True
    try:
        store.save_checked(restored[2], False, False, "https://other-owned.example.test", "other-reader", delete_password=True, account_type="generic-dav")
        raise AssertionError("Successful backend ack without cleared credential was accepted")
    except Exception as error:
        assert getattr(error, "code", None) == "verification_failed"
    vault.drop_clear = False
    monkeypatch.setattr(native, "nextcloud_speicher", lambda: store)
    monkeypatch.setattr(native, "NextcloudDav", lambda *_: (_ for _ in ()).throw(AssertionError("Saving settings must not discover remote collections")))
    host = Host(native); host._gesperrt = False
    host._nextcloud_speichern(False, False, "https://other-owned.example.test", "other-reader", "", False,
        "App.baumBriefkastenGespeichert", "generic-dav", "owned-save", store.read_snapshot()[2])
    saved = host.responses[-1][1]
    assert saved["ok"] and saved["persisted"] and saved["verified"] and saved["requestId"] == "owned-save"
    assert saved["revision"] == store.read_snapshot()[2] and "owned-secret-restored" not in json.dumps(saved)
    host._nextcloud_speichern(False, False, "https://other-owned.example.test", "other-reader", "", False,
        "App.baumBriefkastenGespeichert", "generic-dav", "owned-stale-save", first_revision)
    assert host.responses[-1][1]["code"] == "conflict" and not host.responses[-1][1]["persisted"]
