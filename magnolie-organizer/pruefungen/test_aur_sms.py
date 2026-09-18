"""AUR-02/04: captured transport only, no GUI, phone, profile or host services."""
import ast
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_kdeconnect as kde
import magnolie_phone_region as phone


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent-aur-sms")
    def forbidden(*args, **kwargs):
        raise AssertionError("host transport/profile forbidden")
    monkeypatch.setattr(kde.socket, "socket", forbidden)
    monkeypatch.setattr(kde, "create_backend", forbidden)
    monkeypatch.setattr(phone, "regional_context", lambda: ("GB", "en"))


def native(tmp_path, transport):
    tree = ast.parse((ROOT / "bin/magnolie-organizer").read_text())
    names = {"_telefon_schluessel", "kdeconnect_sms_senden"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    window = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Fenster")
    nodes.append(next(n for n in window.body if isinstance(n, ast.FunctionDef) and n.name == "_kde_sms_senden"))
    import re
    scope = {"os": os, "re": re, "DEVICE_ID": kde.DEVICE_ID, "SmsSubmissionJournal": kde.SmsSubmissionJournal,
        "daten_verzeichnis": lambda: str(tmp_path), "_": lambda s: s,
        "fehler_deutsch": lambda error, context: str(error),
        "_kdeconnect_backend": lambda: SimpleNamespace(send_sms=transport)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "SMS-only native source", "exec"), scope)
    return SimpleNamespace(**scope)


def test_pre_fix_dispatch_model_reproduces_restore_double_send(tmp_path):
    calls = []
    # Control model of the inspected pre-fix path: the ref accompanied only the
    # ACK, with no reservation consulted before the captured external effect.
    def before(number, text, country, client_ref):
        calls.append((phone.normalize(number, country), text))
        return {"ok": True, "state": "queued", "client_ref": client_ref}
    snapshot = json.dumps({"id": "saved-plan", "nummer": "07700900123", "text": "Synthetic only", "status": "planned"})
    for _ in range(2):
        sms = json.loads(snapshot)
        before(sms["nummer"], sms["text"], "GB", "plan:" + sms["id"])
    assert len(calls) == 2


@pytest.mark.parametrize("client_ref", ["plan:saved-plan", "immediate-stable-ref"])
def test_native_restart_restore_and_digest_only_reservation(tmp_path, client_ref):
    calls, replies = [], []
    path = tmp_path / "sms-submissions.sqlite3"
    def capture(number, text, device_id=None):
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT state FROM submissions").fetchall() == [("uncertain",)]
        calls.append((number, text, device_id))
        return {"ok": True, "state": "queued"}
    snapshot = {"nummer": "07700 900123", "text": "Synthetic secret SMS body", "land": "GB", "client_ref": client_ref}
    m = native(tmp_path, capture)
    m._kde_sms_senden(SimpleNamespace(antwort=lambda name, payload: replies.append(payload)),
        snapshot["nummer"], snapshot["text"], "GB", client_ref)
    assert replies[-1]["state"] == "submitted"
    # A new application/journal instance and an old full content snapshot.
    restored = json.loads(json.dumps(snapshot))
    again = native(tmp_path, capture).kdeconnect_sms_senden(**restored)
    assert again == {"ok": True, "state": "submitted"}
    assert calls == [("+447700900123", snapshot["text"], None)]
    assert path.stat().st_mode & 0o777 == 0o600
    raw = path.read_bytes()
    for secret in (client_ref, snapshot["text"], "447700900123"):
        assert secret.encode() not in raw
    assert sha256(client_ref.encode()).hexdigest().encode() in raw
    for field, value in (("nummer", "+12025550123"), ("text", "Changed"), ("land", "AT")):
        with pytest.raises(ValueError, match="mismatch"):
            native(tmp_path, capture).kdeconnect_sms_senden(**dict(restored, **{field: value}))
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["timeout", "crash", "failed-result"])
def test_uncertain_is_never_retried(tmp_path, failure):
    calls = []
    def capture(*args, **kwargs):
        calls.append(args)
        if failure == "crash":
            raise SystemExit("crash after reservation")
        if failure == "timeout":
            raise TimeoutError("could have sent")
        return {"ok": False, "state": "failed"}
    m = native(tmp_path, capture)
    args = ("+447700900123", "Synthetic", "GB")
    if failure == "crash":
        with pytest.raises(SystemExit):
            m.kdeconnect_sms_senden(*args, client_ref="plan:crash")
    else:
        assert m.kdeconnect_sms_senden(*args, client_ref="plan:crash")["state"] == "uncertain"
    for _ in range(3):
        assert native(tmp_path, capture).kdeconnect_sms_senden(*args, client_ref="plan:crash") == {"ok": False, "state": "uncertain"}
    assert len(calls) == 1


def test_atomic_concurrent_reservation(tmp_path):
    calls = []
    def send():
        calls.append(True)
        return {"ok": True}
    def attempt(_):
        return kde.SmsSubmissionJournal(str(tmp_path / "journal.sqlite3")).submit(
            "shared", "+447700900123", "Synthetic", "GB", None, send)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    assert len(calls) == 1
    assert all(r["state"] in ("uncertain", "submitted") for r in results)


@pytest.mark.parametrize("failure", ["corrupt", "full", "disk", "fsync", "missing-ref"])
def test_reservation_failure_prevents_side_effect(tmp_path, monkeypatch, failure):
    path = tmp_path / "sms-submissions.sqlite3"
    calls = []
    if failure == "corrupt":
        path.write_bytes(b"not a sqlite database")
    if failure == "full":
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE submissions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL)")
            db.executemany("INSERT INTO submissions VALUES (?, '', 'submitted')", ((str(i),) for i in range(10000)))
    if failure == "disk":
        def broken(*args, **kwargs):
            raise OSError("disk unavailable")
        monkeypatch.setattr(kde.sqlite3, "connect", broken)
    if failure == "fsync":
        def broken(*args, **kwargs):
            raise OSError("durability unavailable")
        monkeypatch.setattr(kde.os, "fsync", broken)
    with pytest.raises((ValueError, OSError, sqlite3.DatabaseError)):
        native(tmp_path, lambda *args: calls.append(args)).kdeconnect_sms_senden(
            "+447700900123", "Synthetic", "GB", client_ref=None if failure == "missing-ref" else "ref")
    assert not calls


@pytest.mark.parametrize("country,number,expected", [
    ("GB", "07700 900123", "+447700900123"), ("DE", "0170 1234567", "+491701234567"),
    ("AT", "0664 1234567", "+436641234567"), ("CH", "079 1234567", "+41791234567"),
    ("FR", "06 12 34 56 78", "+33612345678"), ("IT", "02 12345678", "+390212345678"),
    ("US", "202 555 0123", "+12025550123"), ("AU", "0412 345 678", "+61412345678")])
def test_native_phone_region_to_captured_transport(tmp_path, country, number, expected):
    calls = []
    def capture(number, text):
        calls.append(number)
        return {"ok": True}
    m = native(tmp_path, capture)
    assert m._telefon_schluessel(number, country) == expected
    assert m._telefon_schluessel(expected, "ZZ") == expected
    assert m.kdeconnect_sms_senden(number, "Synthetic", country, client_ref="region")["ok"]
    assert calls == [expected]


def test_unknown_region_missing_library_and_explicit_e164(tmp_path, monkeypatch):
    m = native(tmp_path, lambda *args: pytest.fail("invalid recipient dispatched"))
    for country in ("ZZ", "", None):
        with pytest.raises(ValueError):
            m.kdeconnect_sms_senden("07700900123", "Synthetic", country, client_ref="unknown")
    monkeypatch.setattr(phone, "phonenumbers", None)
    assert phone.normalize("07700900123", "GB") == "07700900123"
    assert phone.normalize("+490123456789", "GB") == "+490123456789"


def test_short_communication_number_does_not_launch_a_dialer(tmp_path):
    tree = ast.parse((ROOT / "bin/magnolie-organizer").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "sozial_oeffnen")
    scope = {"_": lambda text: text, "kanonischer_text": lambda text: str(text).casefold(),
             "_telefon_schluessel": phone.normalize}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / "bin/magnolie-organizer"), "exec"), scope)
    calls = []
    for number in ("123", "+49123"):
        result = scope["sozial_oeffnen"]("phone", number, starter=calls.append, welcher=lambda name: "/synthetic/" + name, land="DE")
        assert result == {"ok": False, "fehler": "Enter a complete phone number."}
    assert calls == []


def test_all_regions_browser_and_native_library_parity():
    p = phone.phonenumbers
    vectors = []
    for country in sorted(p.SUPPORTED_REGIONS):
        for kind in range(10):
            example = p.example_number_for_type(country, kind)
            if example is None:
                continue
            expected = p.format_number(example, p.PhoneNumberFormat.E164)
            for number in (p.format_number(example, p.PhoneNumberFormat.NATIONAL), expected):
                assert phone.normalize(number, country) == expected, (country, number)
                vectors.append({"country": country, "number": number, "expected": expected})
    result = subprocess.run(["bun", str(ROOT.parent / "magnolie-organizer-windows/tests/aur-phone-vectors.js")],
        input=json.dumps(vectors), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)


def test_post_send_journal_write_failure_keeps_uncertain(tmp_path, monkeypatch):
    connect, calls = kde.sqlite3.connect, []
    class Connection:
        def __init__(self, *args, **kwargs):
            self.db = connect(*args, **kwargs)
            self.commits = 0
        def execute(self, *args):
            return self.db.execute(*args)
        def close(self):
            self.db.close()
        def commit(self):
            self.commits += 1
            if self.commits == 2:
                raise OSError("disk failed after handoff")
            self.db.commit()
    monkeypatch.setattr(kde.sqlite3, "connect", Connection)
    def capture(*args):
        calls.append(args)
        return {"ok": True}
    m = native(tmp_path, capture)
    assert m.kdeconnect_sms_senden("+447700900123", "Synthetic", "GB", client_ref="post-write")["state"] == "uncertain"
    assert m.kdeconnect_sms_senden("+447700900123", "Synthetic", "GB", client_ref="post-write")["state"] == "uncertain"
    assert len(calls) == 1


def test_actual_native_sms_adapter_with_capture_dbus(tmp_path):
    backend = kde.KDEConnectNativeBackend(None, None, SimpleNamespace(Variant=lambda signature, value: (signature, value)))
    backend._owner = lambda: ":synthetic.1"
    backend._devices = lambda owner: [{"sms_send": True, "device_id": "a" * 32}]
    calls = []
    def capture(*args):
        with sqlite3.connect(tmp_path / "sms-submissions.sqlite3") as db:
            assert db.execute("SELECT state FROM submissions").fetchall() == [("uncertain",)]
        calls.append(args)
    backend._call = capture
    m = native(tmp_path, backend.send_sms)
    for _ in range(2):
        assert m.kdeconnect_sms_senden("07700900123", "Synthetic", "GB", client_ref="plan:native")["state"] == "submitted"
    assert len(calls) == 1
    assert calls[0][2:5] == ("org.kde.kdeconnect.device.sms", "sendSms", "(avsavx)")
    assert calls[0][5][0] == [("(s)", ("+447700900123",))]


def test_actual_sms_dispatcher_never_replaces_unknown_country():
    tree = ast.parse((ROOT / "bin/magnolie-organizer").read_text())
    branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and
        isinstance(n.test, ast.Compare) and any(isinstance(c, ast.Constant) and c.value == "kde_sms_senden" for c in n.test.comparators))
    branch = ast.fix_missing_locations(ast.If(test=branch.test, body=branch.body, orelse=[]))
    code = compile(ast.Module(body=[branch], type_ignores=[]), "SMS dispatcher only", "exec")
    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            self.target()
    for country in ("GB", "AT", "CH", "ZZ", ""):
        calls = []
        exec(code, {"befehl": "kde_sms_senden", "nachricht": {"land": country, "clientRef": "plan:exact"},
            "threading": SimpleNamespace(Thread=ImmediateThread),
            "self": SimpleNamespace(_kde_sms_senden=lambda *args: calls.append(args))})
        assert calls[0][2:4] == (country, "plan:exact")


def test_actual_full_archive_keeps_all_sms_content():
    import hashlib
    from datetime import datetime, timezone
    tree = ast.parse((ROOT / "bin/magnolie-organizer").read_text())
    names = {"gesamtarchiv_erzeugen", "_gesamtarchiv_kanonisch", "_gesamtarchiv_tokens_pruefen",
        "_gesamtarchiv_wiederholungen_normalisieren", "_aufgaben_graph_normalisieren", "_stabile_aufgaben_uid"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names or
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id.startswith("GESAMTARCHIV_") for t in n.targets)]
    scope = {"json": json, "hashlib": hashlib, "datetime": datetime, "timezone": timezone}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "Archive-only source", "exec"), scope)
    data = {"einstellungen": {"adressen": {"smsSchedulingEnabled": True}},
        "smsPlanung": [{"id": "planned", "status": "planned", "text": "?????? - ??", "originalText": "Привет — 你好", "land": "GB", "nummer": "+447700900123"}],
        "smsVerlauf": [{"id": "sent", "status": "submitted", "text": "Synthetic history", "nummer": "+447700900123"}]}
    archive = json.loads(scope["gesamtarchiv_erzeugen"](data, appversion="synthetic"))
    assert archive["daten"]["smsPlanung"] == data["smsPlanung"]
    assert archive["daten"]["smsVerlauf"] == data["smsVerlauf"]
    assert archive["daten"]["einstellungen"] == data["einstellungen"]
