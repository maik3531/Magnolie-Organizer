"""Replay Android CallLifecycleTransportTest output through native owner/IPC/UI.

Usage: python3 -B call_transport_trace.py /tmp/.../trace
Only temporary synthetic stores, in-memory phone transport, and captured surfaces.
"""
import base64
import binascii
import json
import re
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

import test_call_audio as audio_fixtures
import test_callstate_alerts as alerts

phone, background = alerts.phone, alerts.background


def replay(directory, direction, supported):
    trace = json.loads((directory / (direction + ".json")).read_text())
    latencies = []
    with tempfile.TemporaryDirectory(prefix="magnolie-call-trace-", dir="/tmp/opencode") as temporary:
        service = audio_fixtures.service.__wrapped__(Path(temporary), audio_fixtures.route.__wrapped__())
        peer = service.store.peer(alerts.PEER)
        for grants in (peer["grants"]["grants"], peer["local_grants"]["grants"]):
            grants.update(answer_call=True, end_call=True, incoming_call_state=True)
        peer["capabilities"]["items"]["end_call"]["versions"] = [1, 2]
        sent, presented, delivered = [], [], []
        service.connections[alerts.PEER].send = sent.append
        glib, notices = alerts.DelayedGLib(), alerts.Notifications()
        clock = SimpleNamespace(time=lambda: trace[0]["occurred_ms"] / 1000, monotonic=background.time.monotonic)
        socket = str(Path(temporary) / "runtime/background.sock")
        server = background.IPCServer(SimpleNamespace(), socket, phone_backend=service,
            settings_getter=lambda: {"permissions": {"phone_call_notifications": True}})
        server._gui_subscribers["synthetic"] = (background.time.monotonic() + 30, False, True)
        events = background.PhoneDaemonEvents(lambda: service,
            {"permissions": {"phone_call_notifications": True}}, notices, glib,
            server.publish_event, server.gui_present, call_gui_ready=server.gui_notification_ready)
        server.phone_event_getter = events.take; server.phone_alert_handler = events.call_alert
        service.callback = events
        def popup(*args, **kwargs):
            presented.append(kwargs)
            if supported: assert kwargs["bei_anzeigen"]()
            return supported
        namespace = dict(re=re, base64=base64, binascii=binascii, time=clock, GLib=glib,
            _=lambda text: text, _REGIONAL={"homeCountry": "US", "language": "en"},
            telefon_schluessel=lambda *args: "", telefon_anreichern=lambda payload, *args: dict(payload, phone_display_hint=""),
            magnolie_meldung=popup, _ANRUF_LAUTSTAERKE=SimpleNamespace(restore=lambda *args: None))
        for method in ("_telefon_anruf_anzeigen", "_telefon_ereignis"):
            exec(alerts.extracted(method), namespace)
        owner = SimpleNamespace(_telefon=background.PhoneServiceProxy(path=socket), _gesperrt=False,
            _daten_sperre=threading.Lock(), _anruf_hinweis_sperre=threading.Lock(), _tray_zeigen=lambda: None,
            _aktuelle_daten={"einstellungen": {"adressen": {"kommunikation": {"anruf": {
                "art": "magnolie", "telefonId": alerts.PEER, "computerTelefonie": True}}}}},
            antwort=lambda function, body: delivered.append((function, body)))
        owner._telefon_anruf_anzeigen = MethodType(namespace["_telefon_anruf_anzeigen"], owner)
        server.start()
        recorded_clock = patch.object(phone, "now_ms", side_effect=lambda: int(clock.time() * 1000))
        recorded_clock.start()
        try:
            cursor = 0
            for value in trace:
                began = time.perf_counter()
                clock.time = lambda value=value: value["occurred_ms"] / 1000
                message = dict(type="message", v=1, message_id=str(uuid.uuid4()), kind="incoming_call_state.event",
                    created_ms=phone.now_ms(), expires_ms=phone.now_ms() + 60_000, body=value)
                service._payload(peer, service.connections[alerts.PEER], message)
                glib.drain()
                queued = server._poll_events(cursor, 0)
                for item in queued["events"]:
                    cursor = item["sequence"]
                    payload = owner._telefon._call("take_event", ticket=item["payload"]["ticket"])
                    with patch.object(background, "NativeNotifications", return_value=notices):
                        namespace["_telefon_ereignis"](owner, payload["event"], payload["payload"])
                        glib.drain()
                timing = {"state": value["state"], "event_to_frontend_ms": round((time.perf_counter()-began)*1000, 3)}
                if direction == "incoming" and value["state"] == "ringing":
                    assert len(presented) == 1
                    action = presented[0]["aktionen"][0][2] if supported else notices.items[0][2][0][2]
                    action_started = time.perf_counter()
                    action()
                    timing["action_to_transport_ms"] = round((time.perf_counter()-action_started)*1000, 3)
                    commands = [item for item in sent if item.get("kind") == "answer_call.command"]
                    assert len(commands) == 1 and commands[0]["body"]["call_ref"] == value["call_ref"]
                    phone.validate_answer_command(commands[0]["body"])
                elif direction == "outgoing":
                    assert not presented and not notices.items
                latencies.append(timing)
            assert [body["state"] for function, body in delivered if function == "App.telefonEingehenderAnruf"] == ["ringing", "offhook", "idle"]
            assert all(body["call_ref"] == trace[0]["call_ref"] for _, body in delivered)
            if direction == "incoming": assert not presented[0]["gueltig"]()
        finally:
            server.close()
            recorded_clock.stop()
    return {"direction": direction, "own_popup": supported, "states": 3, "answer_commands": int(direction == "incoming"),
        "fixture_only_latencies": latencies}


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    print(json.dumps([replay(directory, direction, supported)
        for direction in ("incoming", "outgoing") for supported in (True, False)], indent=2))
