"""Synthetic-only NDJSON adapter using the current launcher and receiving callback."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import types

sys.dont_write_bytecode = True
repo = Path(__file__).resolve().parents[2]
root = Path(os.environ["CONTACT_INTEROP_HOME"])
assert str(root.resolve()).startswith("/tmp/opencode/")
loader = importlib.machinery.SourceFileLoader("contact_interop", str(repo / "magnolie-organizer/bin/magnolie-organizer"))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = m
loader.exec_module(m)
owner_class = next(c for c in vars(m).values() if isinstance(c, type) and "_baum_empfangen" in vars(c))
owner = types.SimpleNamespace(_gesperrt=False, _kennwort="", _baum_sperre=threading.RLock())
state = m.baum_lesen()
state["an"] = True
owner._baum_zustand = lambda: state
owner._baum_sichern = lambda value: m.baum_schreiben(value)
owner._baum_stand_melden = lambda: None
owner._baum_kontakt_faehigkeiten_anmelden = types.MethodType(owner_class._baum_kontakt_faehigkeiten_anmelden, owner)
owner._baum_empfangen = types.MethodType(owner_class._baum_empfangen, owner)
dienst = m.BaumDienst(owner._baum_zustand, owner._baum_sichern, bei_nachricht=owner._baum_empfangen, sperre=owner._baum_sperre)
m.benachrichtigen = lambda *a, **kw: None
start = private = session = envelope = None

def run(r):
    global state, start, private, session, envelope
    op, data, text = r["op"], r.get("data"), r.get("text", "")
    if op == "init":
        state["partner"] = []
        m.baum_post_schreiben([])
        m.baum_eingang_schreiben([])
        m.baum_schreiben(state)
        return {k: state[k] for k in ("kennung", "name", "oeffentlich", "port")}
    if op == "pair":
        p = m.baum_partner_aufnehmen(state, data["name"], data["kennung"], data["oeffentlich"], "127.0.0.1", data["port"])
        p["bestaetigt"] = True
        m.baum_schreiben(state)
        return p
    if op == "start":
        start, private = m.fs_start_bauen(state, state["partner"][0])
        return start
    if op == "message":
        session = m.fs_antwort_oeffnen(state, state["partner"][0], start, data, private)
        envelope = m.umschlag_bauen_fs(session, state["kennung"], state["partner"][0]["kennung"], r["content"], m._fs_b64(os.urandom(16)))
        return envelope
    if op == "ack": return m.fs_ack_pruefen(session, envelope, data)
    if op == "request":
        status, body = dienst.behandeln(text, data, "127.0.0.1", bereits_begrenzt=True)
        return {"Status": status, "Body": body}
    if op == "status": return {"partner": state["partner"], "eingang": m.baum_eingang_lesen()}
    if op == "outbox": return m.baum_post_lesen()
    if op == "restart":
        state = m.baum_lesen()
        return state["partner"][0]
    if op == "capabilities": return m.baum_kontakt_faehigkeiten()
    if op == "validate":
        m.baum_kontakt_nutzlast_pruefen(data["art"], data)
        return True
    if op == "for-peer": return m.baum_kontakt_fuer_partner(r["peer"], data)
    if op == "queue-compat":
        remote = m.baum_schluessel_erzeugen()
        state["partner"] = []
        p = m.baum_partner_aufnehmen(state, remote["name"], remote["kennung"], remote["oeffentlich"], "127.0.0.1")
        p["bestaetigt"] = True
        back = m.baum_partner_aufnehmen(remote, state["name"], state["kennung"], state["oeffentlich"], "127.0.0.1")
        observed, reports = [], []
        def sender(_url, encrypted):
            opened, _ = m.umschlag_oeffnen(remote["geheim"], back, remote["kennung"], encrypted, 0)
            observed.append(opened["art"])
            return opened["art"] == ("kontakt_faehigkeiten" if text == "reject-contact" else "kontakt_sync")
        original = m.baum_post_zustellen
        m.baum_post_zustellen = lambda s, post: original(s, post, sender=sender)
        owner.antwort = lambda name, value: reports.append(value) if name == "App.baumGesendet" else None
        m.baum_post_schreiben([])
        try: owner_class._baum_sendung(owner, p["kennung"], "kontakt_sync", data)
        finally: m.baum_post_zustellen = original
        return {"report": reports[-1], "observed": observed, "outbox": m.baum_post_lesen()}
    if op == "vcf": return dict(m.vcf_lesen(text), art="vcf", abgebrochen=False)
    if op == "ldif": return dict(m.ldif_lesen(text), art="claws", abgebrochen=False)
    if op == "write-vcf": return m.vcf_schreiben(data)
    if op == "write-ldif": return m.ldif_schreiben(data)
    raise ValueError(op)

for line in sys.stdin:
    try: result = {"value": run(json.loads(line))}
    except Exception as error: result = {"error": repr(error)}
    print(json.dumps(result), flush=True)
