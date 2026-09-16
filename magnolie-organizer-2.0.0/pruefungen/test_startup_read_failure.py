"""Actual Linux loader/startup/bridge/worker, with isolated storage and no GTK."""
import ast
import copy
import errno
import json
import os
from pathlib import Path
import queue
import sys
import threading
from types import SimpleNamespace
from unittest import mock

import pytest

from modul_laden import quellmodul_laden


SOURCE = Path(__file__).resolve().parents[1] / "bin/magnolie-organizer"


@pytest.fixture
def native(monkeypatch, tmp_path):
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        target = tmp_path / key
        target.mkdir()
        monkeypatch.setenv(key, str(target))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent-a1-bus")
    monkeypatch.setitem(sys.modules, "gi", None)
    m = quellmodul_laden("magnolie_startup_read_failure", SOURCE)
    profile = tmp_path / "profile"
    profile.mkdir()
    # Do not use GLib's cached home or the production helper's chmod repair.
    monkeypatch.setattr(m, "daten_datei", lambda: str(profile / "daten.json"))
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(profile))
    monkeypatch.setattr(m, "_kde_gui_bereitschaft", lambda *_: None)
    monkeypatch.setattr(m, "handbuch_installiert", lambda: False)
    monkeypatch.setattr(m, "handbuch_version", lambda: "")
    monkeypatch.setattr(m, "tray_system_verfuegbar", lambda: False)
    monkeypatch.setattr(m, "GLib", SimpleNamespace(idle_add=lambda *_: None))
    return m


def full_data():
    return {"version": 6, "notizen": [{"id": "note", "text": "keep", "html": "keep",
        "anhaenge": [{"id": "attachment", "daten": "data:text/plain;base64,a2VlcA=="}]}],
        "notizbuecher": [{"id": "book", "name": "keep"}],
        "termine": [{"id": "event", "titel": "keep", "datum": "2026-09-13"}],
        "aufgaben": [{"id": "task", "titel": "keep"}],
        "kontakte": [{"id": "contact", "foto": "data:image/png;base64,a2VlcA=="}],
        "jahrestage": [{"id": "anniversary"}], "feiertage": [], "tagmarken": [],
        "gesundheit": {"synthetic": [1, 2]},
        "smsPlanung": [{"id": "sms", "status": "planned"}],
        "smsVerlauf": [{"text": "keep"}], "personalSync": {"actor_id": "synthetic"},
        "customOrganizer": {"modules": [{"id": "module"}]},
        "einstellungen": {"allgemein": {}, "sync": {}}, "extension": {"keep": True}}


class Host:
    """No window constructor, but all storage and bridge methods are production."""
    def __init__(self, native):
        self.native = native
        self._gesperrt = True
        self._kennwort = ""
        self._aktuelle_daten = None
        self._daten_sperre = threading.RLock()
        self._baum_sperre = threading.RLock()
        self._speicher_auftraege = queue.Queue()
        self._operation_laeuft = self._sync_laeuft = False
        self._tray_einstellungen = {}
        self._regional = {"language": "en", "timeZone": "UTC"}
        self._setup_auswahl = None
        self.responses = []

    def __getattr__(self, name):
        return getattr(self.native.Fenster, name).__get__(self, type(self))

    def antwort(self, name, payload): self.responses.append((name, payload))
    def _organizer_vertraut(self): return True
    def _tray_telefone_aktualisieren(self): pass
    def _journal_planen(self): pass
    def _sms_antworten_ausliefern(self): pass
    def _cloud_sicherung_nach_speichern(self, *_): pass
    def _baum_dienst_pflegen(self): pass
    def _telefon_dienst_pflegen(self): pass

    def save(self, data, direct=False):
        self.responses.clear()
        text = json.dumps(data)
        if direct:
            self._speicher_auftraege.put((1, text))
        else:
            self.bei_nachricht(json.dumps({"cmd": "speichern", "id": 1, "text": text}))
        self._speicher_auftraege.put(None)
        self._speicher_lauf()
        return next(payload for name, payload in self.responses if name == "App.gespeichert")


def assert_blocked(host, path, original):
    assert host._gesperrt is True
    assert host._aktuelle_daten is None
    init = next(payload for name, payload in host.responses if name == "App.init")
    assert init["neu"] is False and init["gesperrt"] is True
    assert init.get("daten") is None
    assert init.get("ladeFehler")
    assert not host.save({"notizen": []})["ok"]
    assert not host.save({"notizen": []}, direct=True)["ok"]
    path.chmod(0o600)
    assert path.read_bytes() == original


@pytest.mark.parametrize("encrypted", [False, True])
def test_real_unreadable_startup_save_preserves_bytes(native, encrypted):
    if os.geteuid() == 0:
        pytest.skip("Read permissions must be exercised as non-root")
    path = Path(native.daten_datei())
    raw = json.dumps(full_data())
    if encrypted:
        raw = native.daten_huelle_anlegen(raw, "synthetic-only")[0]
    original = raw.encode()
    path.write_bytes(original)
    path.chmod(0)
    assert os.access(path.parent, os.W_OK)
    with pytest.raises(PermissionError):
        path.read_bytes()
    host = Host(native)
    host._oeffnen_oder_sperren()
    assert_blocked(host, path, original)
    assert not list(path.parent.glob("daten.json.defekt-*"))
    host.responses.clear()
    host._oeffnen_oder_sperren()
    if encrypted:
        assert host._gesperrt
        assert not host.save({})["ok"]
        host._entsperren("synthetic-only")
    assert not host._gesperrt
    assert host._aktuelle_daten == full_data()
    assert host.save(full_data())["ok"]
    saved = path.read_text()
    assert native.ist_verschluesselt(saved) is encrypted
    assert json.loads(native.entschluesseln(saved, "synthetic-only") if encrypted else saved) == full_data()


def test_ast_loader_read_and_copy_faults_raise(native):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    loader = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "lade_daten")
    namespace = dict(vars(native))
    namespace["uebernehme_alte_daten"] = lambda: False
    path = Path(native.daten_datei())
    path.write_text(json.dumps(full_data()))
    exec(compile(ast.Module(body=[loader], type_ignores=[]), str(SOURCE), "exec"), namespace)
    with mock.patch("builtins.open", side_effect=PermissionError("synthetic read")), \
            mock.patch.object(native.shutil, "copy2", side_effect=PermissionError("synthetic copy")), \
            pytest.raises(PermissionError):
        namespace["lade_daten"]()


@pytest.mark.parametrize("original", [b"{broken", b"", b"[]", b"null", b"true", b"42", b'"text"', b"\xff",
    b'{"magnolie":"magnolie-verschluesselt", "broken":'])
@pytest.mark.parametrize("copy_fails", [False, True])
def test_bad_document_is_not_new_even_after_preservation(native, monkeypatch, original, copy_fails):
    path = Path(native.daten_datei())
    path.write_bytes(original)
    if copy_fails:
        monkeypatch.setattr(native.shutil, "copy2", mock.Mock(side_effect=PermissionError("synthetic copy")))
    host = Host(native)
    host._oeffnen_oder_sperren()
    assert_blocked(host, path, original)
    copies = list(path.parent.glob("daten.json.defekt-*"))
    assert bool(copies) is not copy_fails
    assert all(item.read_bytes() == original for item in copies)


@pytest.mark.parametrize("error", [PermissionError(errno.EACCES, "synthetic"),
    OSError(errno.EIO, "synthetic"), NotADirectoryError(errno.ENOTDIR, "synthetic")])
def test_initial_read_io_failure_and_retry_load_actual_full_data(native, monkeypatch, error):
    path = Path(native.daten_datei())
    original = json.dumps(full_data()).encode()
    path.write_bytes(original)
    host = Host(native)
    with monkeypatch.context() as faults:
        faults.setattr(native, "open", mock.Mock(side_effect=error), raising=False)
        faults.setattr(native.shutil, "copy2", mock.Mock(side_effect=PermissionError("synthetic copy")))
        host._oeffnen_oder_sperren()
        assert_blocked(host, path, original)
    host.responses.clear()
    host._oeffnen_oder_sperren()
    assert host._aktuelle_daten == full_data()
    assert not host._gesperrt
    changed = copy.deepcopy(full_data())
    changed["notizen"][0]["text"] = "deliberate edit"
    assert host.save(changed)["ok"]
    assert json.loads(path.read_bytes()) == changed


@pytest.mark.parametrize("data", [None, {}, full_data()])
def test_absence_and_valid_empty_or_complete_profiles_save_normally(native, data):
    path = Path(native.daten_datei())
    if data is not None:
        path.write_text(json.dumps(data))
    host = Host(native)
    host._oeffnen_oder_sperren()
    init = next(payload for name, payload in host.responses if name == "App.init")
    assert init["neu"] is (data is None)
    assert init["echterErststart"] is (data is None)
    assert init["daten"] == data
    assert not host._gesperrt
    assert host.save(data if data is not None else full_data())["ok"]
    assert json.loads(path.read_bytes()) == (data if data is not None else full_data())


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("data", [{}, full_data()])
def test_actual_legacy_adoption_preserves_original_and_encryption(native, encrypted, data):
    path = Path(native.daten_datei())
    legacy = path.parent.parent / native.ALTER_NAME / "daten.json"
    legacy.parent.mkdir()
    raw = json.dumps(data)
    if encrypted:
        raw = native.daten_huelle_anlegen(raw, "synthetic-only")[0]
    legacy.write_text(raw)
    host = Host(native)
    host._oeffnen_oder_sperren()
    assert legacy.read_text() == path.read_text() == raw
    if encrypted:
        assert host._gesperrt
        assert not host.save({})["ok"]
        host._entsperren("synthetic-only")
    assert not host._gesperrt
    assert host._aktuelle_daten == data


def test_data_path_failure_cannot_escape_error_initialization(native, monkeypatch):
    path = Path(native.daten_datei())
    original = json.dumps(full_data()).encode()
    path.write_bytes(original)
    monkeypatch.setattr(native, "daten_datei", mock.Mock(side_effect=PermissionError("synthetic path")))
    host = Host(native)
    host._oeffnen_oder_sperren()
    assert_blocked(host, path, original)


def test_directory_or_dangling_symlink_is_not_absence(native):
    path = Path(native.daten_datei())
    path.mkdir()
    with pytest.raises(IsADirectoryError):
        native.lade_daten()
    path.rmdir()
    path.symlink_to(path.parent / "missing-target")
    with pytest.raises(FileNotFoundError):
        native.lade_daten()
    assert path.is_symlink()


def test_unreadable_legacy_is_not_new(native, monkeypatch):
    path = Path(native.daten_datei())
    legacy = path.parent.parent / native.ALTER_NAME / "daten.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps(full_data()))
    monkeypatch.setattr(native.shutil, "copy2", mock.Mock(side_effect=PermissionError("synthetic legacy")))
    with pytest.raises(PermissionError):
        native.lade_daten()
    assert not path.exists()


@pytest.mark.parametrize("raw", ["[]", "null", "{broken"])
@pytest.mark.parametrize("version", [1, 2])
def test_encrypted_bad_plaintext_never_unlocks_or_migrates(native, raw, version):
    path = Path(native.daten_datei())
    encrypted = (native.verschluesseln(raw, "synthetic-only") if version == 1 else
                 native.daten_huelle_anlegen(raw, "synthetic-only")[0])
    path.write_text(encrypted)
    host = Host(native)
    host._oeffnen_oder_sperren()
    assert host._gesperrt
    host._entsperren("synthetic-only")
    assert host._gesperrt and host._aktuelle_daten is None
    assert any(name == "App.entsperrtFehler" for name, _ in host.responses)
    assert not host.save({})["ok"]
    assert not host.save({}, direct=True)["ok"]
    assert path.read_text() == encrypted


@pytest.mark.parametrize("padding", ["", " " * 500])
def test_readable_malformed_envelope_is_never_a_plain_book(native, padding):
    path = Path(native.daten_datei())
    original = (padding + json.dumps({"magnolie": native.KENNWORT_KENNUNG, "fassung": 2})).encode()
    path.write_bytes(original)
    host = Host(native)
    host._oeffnen_oder_sperren()
    assert host._gesperrt and host._aktuelle_daten is None
    host._entsperren("synthetic-only")
    assert host._gesperrt
    assert not host.save({})["ok"]
    assert not host.save({}, direct=True)["ok"]
    assert path.read_bytes() == original


def test_native_storage_helper_cannot_repair_file_permissions(native, monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("Read permissions must be exercised as non-root")
    # Exercise the real storage helpers too. Denied chmod models a file that
    # the process cannot repair, while the read/copy failures are real mode checks.
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name in ("daten_datei", "daten_verzeichnis")]
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(SOURCE), "exec"), vars(native))
    path = Path(native.daten_datei())
    original = json.dumps(full_data()).encode()
    path.write_bytes(original)
    path.chmod(0)
    chmod = os.chmod

    def deny_file_repair(target, mode, *args, **kwargs):
        if str(target) == str(path):
            raise PermissionError("synthetic denied permission repair")
        return chmod(target, mode, *args, **kwargs)

    with monkeypatch.context() as faults:
        faults.setattr(native.os, "chmod", deny_file_repair)
        host = Host(native)
        host._oeffnen_oder_sperren()
        assert host._gesperrt
        assert not host.save({})["ok"]
    path.chmod(0o600)
    assert path.read_bytes() == original


@pytest.mark.parametrize("error", [PermissionError("synthetic transaction"),
    OSError(errno.EIO, "synthetic transaction"), RuntimeError("synthetic transaction")])
def test_password_transaction_read_failure_stays_closed(native, monkeypatch, error):
    path = Path(native.daten_datei())
    original = json.dumps(full_data()).encode()
    path.write_bytes(original)
    monkeypatch.setattr(native, "kennwort_transaktion_reparieren", mock.Mock(side_effect=error))
    host = Host(native)
    host._oeffnen_oder_sperren()
    assert_blocked(host, path, original)


def test_read_guard_only_accepts_absence_not_permission_errors(native, monkeypatch):
    host = Host(native)
    host._gesperrt = False
    assert host._darf_schreiben()
    with monkeypatch.context() as faults:
        faults.setattr(native, "open", mock.Mock(side_effect=PermissionError("synthetic")), raising=False)
        assert not host._darf_schreiben()
    path = Path(native.daten_datei())
    path.symlink_to(path.parent / "missing")
    assert not host._darf_schreiben()


def test_error_and_retry_labels_already_translated_in_all_20_catalogs():
    from test_locale_completeness import _catalog
    catalogs = sorted((SOURCE.parent.parent / "po").glob("*.po"))
    assert len(catalogs) == 19  # Plus the English source messages.
    for path in catalogs:
        entries = _catalog(path)
        for text in ("The file could not be read.", "Refresh", "Close"):
            entry = entries[(None, text)]
            assert "fuzzy" not in entry["flags"], (path, text)
            assert entry["values"] and all(entry["values"]), (path, text)
