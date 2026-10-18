import json
import os
import threading
import base64
import hashlib
from pathlib import Path
import socket

from test_baum_off_state import native, Host


class McpHost(Host):
    def __init__(self, module):
        super().__init__(module)
        self._baum_mcp_lokal = threading.local()
        self._baum_mcp_operation = threading.Lock()
        self._baum_mcp_revisionsschluessel = os.urandom(32)
        self.scripts = []

    def sende_js(self, source):
        self.scripts.append(source() if callable(source) else source)

    def _baum_stand_melden(self):
        self.antwort("App.baumStand", self._baum_bericht())

    def call(self, request):
        self._baum_mcp_operation.acquire()
        self._baum_mcp_arbeit({"requestId": "owned-tree-request", "request": request})
        script = self.scripts[-1]
        assert script.startswith("App.baumMcpErgebnis(JSON.parse(")
        encoded = script[len("App.baumMcpErgebnis(JSON.parse("):-3]
        return json.loads(json.loads(encoded))


def test_actual_tree_store_revision_and_scoped_gui_capture(native, monkeypatch):
    module, starts = native
    host = McpHost(module)
    initial = host.call({"action": "read"})
    assert initial["ok"] and len(initial["status"]["revision"]) == 64
    assert "eingang" not in initial["status"] and "privat" not in initial["status"]
    assert len(host.scripts) == 1
    monkeypatch.setattr(module, "baum_oeffentliche_adresse", lambda: "203.0.113.77")
    address = host.call({"action": "public_address", "expectedRevision": initial["status"]["revision"]})
    assert address["ok"] and address["publicAddress"] == "203.0.113.77" and address["status"]["revision"] == initial["status"]["revision"]
    stale = host.call({"action": "settings", "enabled": False, "name": "Owned MCP tree", "expectedRevision": "0" * 64})
    assert not stale["ok"] and stale["code"] == "conflict"
    updated = host.call({"action": "settings", "enabled": False, "name": "Owned MCP tree", "expectedRevision": initial["status"]["revision"]})
    assert updated["ok"] and updated["localVerified"]
    assert updated["status"]["name"] == module.baum_lesen()["name"] == "Owned MCP tree"
    assert updated["status"]["an"] is False and not starts
    assert updated["status"]["revision"] != initial["status"]["revision"]
    assert all(script.startswith("App.baumMcpErgebnis(") for script in host.scripts)
    created = host.call({"action": "pairing_create", "expectedRevision": updated["status"]["revision"], "address": "127.0.0.1", "port": 8737})
    assert created["ok"] and created["localVerified"] and isinstance(created["document"], dict)
    assert created["status"]["revision"] != updated["status"]["revision"]
    assert "privat" not in created["document"] and not starts
    host._baum_stand_melden()
    assert host.scripts[-1].startswith("App.baumStand(")


def test_actual_tree_write_failure_is_not_success(native, monkeypatch):
    module, starts = native
    host = McpHost(module)
    initial = host.call({"action": "read"})
    monkeypatch.setattr(module, "baum_schreiben", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("owned-private-write-error")))
    result = host.call({"action": "settings", "enabled": False, "name": "Failed change", "expectedRevision": initial["status"]["revision"]})
    assert not result["ok"] and result["code"] == "verification_failed"
    assert "owned-private" not in json.dumps(result) and not starts


def test_actual_peer_fingerprint_preferences_and_removal(native):
    module, starts = native
    host = McpHost(module)
    state = host._baum_zustand()
    other = module.baum_schluessel_erzeugen("Owned peer")
    peer = module.baum_partner_aufnehmen(state, other["name"], other["kennung"], other["oeffentlich"], "127.0.0.1", module.BAUM_PORT)
    peer["bestaetigt"] = True; peer["wartet"] = False
    host._baum_sichern(state)
    status = host.call({"action": "read"})["status"]
    base = {"peerId": peer["kennung"], "fingerprint": module.fingerabdruck(peer["oeffentlich"])}
    wrong = host.call({**base, "action": "remove", "fingerprint": "wrong", "expectedRevision": status["revision"]})
    assert not wrong["ok"] and wrong["code"] == "conflict"
    changed = host.call({**base, "action": "partner_settings", "expectedRevision": status["revision"], "trusted": False,
                         "contacts": True, "contactDeletions": False, "remoteAddress": "", "remotePort": module.BAUM_PORT})
    assert changed["ok"] and changed["localVerified"]
    stored = module.baum_partner(module.baum_lesen(), peer["kennung"])
    assert stored["kontakte"] and not stored["vertraut"]
    removed = host.call({**base, "action": "remove", "expectedRevision": changed["status"]["revision"]})
    assert removed["ok"] and removed["localVerified"] and not module.baum_lesen()["partner"] and not starts


def test_actual_inbox_unicode_chunks_and_content_revision(native):
    module, starts = native
    host = McpHost(module)
    module.baum_eingang_schreiben([{"id": "owned-message", "von": "owned-peer", "inhalt": {"text": "Owned 🌸 é inbox"}}])
    chunk = host.call({"action": "inbox_read", "id": "owned-message", "limit": 7})
    assert chunk["ok"] and chunk["nextOffset"] == 7
    digest, raw = chunk["sha256"], base64.b64decode(chunk["dataBase64"])
    while chunk["nextOffset"] is not None:
        chunk = host.call({"action": "inbox_read", "id": "owned-message", "limit": 7, "offset": chunk["nextOffset"], "expectedSha256": digest})
        assert chunk["ok"]
        raw += base64.b64decode(chunk["dataBase64"])
    assert json.loads(raw.decode("utf-8"))["inhalt"]["text"] == "Owned 🌸 é inbox"
    stale = host.call({"action": "inbox_read", "id": "owned-message", "expectedSha256": "0" * 64})
    assert not stale["ok"] and stale["code"] == "conflict" and not starts
    revision = host.call({"action": "read"})["status"]["revision"]
    wrong = host.call({"action": "consume_inbox", "id": "owned-message", "expectedSha256": "0" * 64, "expectedRevision": revision})
    assert not wrong["ok"] and wrong["code"] == "conflict" and len(module.baum_eingang_lesen()) == 1
    consumed = host.call({"action": "consume_inbox", "id": "owned-message", "expectedSha256": digest, "expectedRevision": revision})
    assert consumed["ok"] and consumed["localVerified"] and module.baum_eingang_lesen() == []


def test_actual_outbox_commit_and_failed_readback(native, monkeypatch):
    module, starts = native
    host = McpHost(module)
    state = host._baum_zustand()
    other = module.baum_schluessel_erzeugen("Owned peer")
    peer = module.baum_partner_aufnehmen(state, other["name"], other["kennung"], other["oeffentlich"], "127.0.0.1", module.BAUM_PORT)
    peer["bestaetigt"] = True
    state["an"] = True
    host._baum_sichern(state)
    # Exercise the actual enqueue/store handler; delivery transport is an offline fixture.
    monkeypatch.setattr(module, "baum_post_zustellen", lambda *_args, **_kwargs: {"zugestellt": 0, "offen": 1})
    request = {"action": "send", "expectedRevision": host.call({"action": "read"})["status"]["revision"],
               "peerId": peer["kennung"], "fingerprint": module.fingerabdruck(peer["oeffentlich"]),
               "kind": "aufgabe", "content": {"id": "owned-task", "titel": "Owned 🌸 task"}}
    result = host.call(request)
    assert result["ok"] and result["queuedVerified"] and result["deliveryConfirmed"] is False
    stored = module.baum_post_lesen()
    assert len(stored) == 1 and stored[0]["inhalt"]["titel"] == "Owned 🌸 task"
    assert all(script.startswith("App.baumMcpErgebnis(") for script in host.scripts) and not starts
    monkeypatch.setattr(module, "baum_post_schreiben", lambda *_args, **_kwargs: True)
    result = host.call({**request, "expectedRevision": host.call({"action": "read"})["status"]["revision"]})
    assert not result["ok"] and not result.get("queuedVerified", False)


def test_pairing_file_and_actual_qr_output(native):
    module, starts = native
    host = McpHost(module)
    path = Path(module.daten_verzeichnis()) / "owned.magnolie-paarung"
    initial = host.call({"action": "read"})["status"]
    created = host.call({"action": "pairing_create", "expectedRevision": initial["revision"], "address": "127.0.0.1", "port": 8737, "path": str(path)})
    assert created["ok"] and created["localVerified"]
    actual = path.read_bytes()
    assert json.loads(actual) == created["document"] and created["file"] == {"path": str(path), "bytes": len(actual), "sha256": hashlib.sha256(actual).hexdigest()}
    inspected = host.call({"action": "pairing_read_file", "path": str(path), "expectedRevision": created["status"]["revision"]})
    assert inspected["ok"] and inspected["document"] == created["document"] and inspected["file"] == created["file"]
    assert inspected["status"]["revision"] == created["status"]["revision"]
    stale_import = host.call({"action": "pairing_import_file", "path": str(path), "expectedRevision": created["status"]["revision"], "expectedFileSha256": "0" * 64})
    assert not stale_import["ok"] and stale_import["code"] == "conflict"
    duplicate = host.call({"action": "pairing_create", "expectedRevision": created["status"]["revision"], "address": "127.0.0.1", "port": 8737, "path": str(path)})
    assert not duplicate["ok"] and path.read_bytes() == actual
    assert host.call({"action": "read"})["status"]["revision"] == created["status"]["revision"]
    __import__("pytest").importorskip("qrcode")
    svg_path = path.with_suffix(".svg")
    qr = host.call({"action": "pairing_create", "expectedRevision": created["status"]["revision"], "address": "127.0.0.1", "port": 8737, "format": "qr_svg", "path": str(svg_path)})
    assert qr["ok"] and qr["localVerified"] and qr["qrImage"].startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(qr["qrImage"].split(",", 1)[1])
    assert b"<svg" in svg and svg_path.read_bytes() == svg and qr["file"]["sha256"] == hashlib.sha256(svg).hexdigest() and not starts


def test_actual_private_loopback_mcp_send_receipt_and_peer_inbox(native, monkeypatch):
    module, starts = native
    host = McpHost(module)
    left = host._baum_zustand()
    right = module.baum_schluessel_erzeugen("Owned loopback peer")
    for own, remote in ((left, right), (right, left)):
        own["an"] = True
        peer = module.baum_partner_aufnehmen(own, remote["name"], remote["kennung"], remote["oeffentlich"], "127.0.0.1")
        peer["bestaetigt"] = True
    root = Path(module.daten_verzeichnis())
    remote_state, remote_inbox = root / "owned-remote-state.json", root / "owned-remote-inbox.json"
    monkeypatch.setattr(module, "BaumDienst", module._owned_real_baumdienst)
    backend = module.BaumDienst(lambda: right, lambda state: module.atomar_text_schreiben(str(remote_state), json.dumps(state)),
        bei_nachricht=lambda peer, body: module.baum_eingang_ablegen(peer, body, str(remote_inbox)), port=0)
    original_bind = socket.socket.bind
    def private_bind(sock, address):
        if sock.family == socket.AF_INET and address[1] == 0:
            return original_bind(sock, ("127.0.0.1", 0))
        raise OSError("Only owned ephemeral loopback listeners are allowed")
    monkeypatch.setattr(socket.socket, "bind", private_bind)
    monkeypatch.setattr(backend, "_rufdienst_starten", lambda: None)
    monkeypatch.setattr(module.BaumBluetoothDienst, "starten", lambda self: False)
    monkeypatch.setattr(module, "baum_mdns_veroeffentlichen", lambda *_args: None)
    try:
        assert backend.starten()
        left["partner"][0]["port"] = backend.port
        host._baum_sichern(left)
        status = host.call({"action": "read"})["status"]
        result = host.call({"action": "send", "expectedRevision": status["revision"], "peerId": right["kennung"],
            "fingerprint": module.fingerabdruck(right["oeffentlich"]), "kind": "aufgabe", "content": {"id": "owned-loopback-task", "titel": "Owned loopback 🌸 task"}})
        assert result["ok"] and result["queuedVerified"] and result["deliveryConfirmed"] is False
        received = module.baum_eingang_lesen(str(remote_inbox))
        assert len(received) == 1 and received[0]["inhalt"]["titel"] == "Owned loopback 🌸 task"
        assert remote_state.exists() and module.baum_post_lesen() == [] and not starts
        assert all(script.startswith("App.baumMcpErgebnis(") for script in host.scripts)
    finally:
        backend.anhalten()
