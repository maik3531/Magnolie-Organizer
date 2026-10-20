#!/usr/bin/env python3
"""Synthetic pinned TCP session; actual native timer control request/report handlers."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import sys
import tempfile
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone
import magnolie_time_control as control

PHONE = sys.argv[1]


def main():
    capabilities = phone.desktop_capabilities
    assert 13 in capabilities()["items"]["personal_tasks_sync"]["versions"]
    with tempfile.TemporaryDirectory(prefix="native-time-control-") as directory:
        events = []
        service = phone.PhoneService(str(Path(directory) / "phone"), "Synthetic desktop", callback=lambda kind, value: events.append((kind, value)))
        service.enabled = True
        peer = dict(device_id=PHONE, display_name="Owned phone", static_public=phone.b64(b"p" * 32), state="paired",
            capabilities=capabilities(), grants=phone.desktop_grants(), local_grants=phone.desktop_grants(), last_contact_ms=0,
            bluetooth=dict(enabled=False, address=""), personal_sync=dict(own_device=True, remote_own_device=False, auto_wifi=False, last_report={}))
        service.store.peers.append(peer); service.store.save_peers(); service.set_time_sync(PHONE, True)
        service.store.initialize_shared_settings(PHONE, peer["static_public"],
            dict(phone.shared_sync_contract.DEFAULTS, auto_mode="manual", time_enabled=True, time_mode="two_way"))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1); listener.settimeout(25)
            print(json.dumps({"port": listener.getsockname()[1], "device_id": service.store.identity["device_id"]}), flush=True)
            connection, _ = listener.accept()
            with connection, ThreadPoolExecutor(max_workers=1) as pool:
                connection.settimeout(0.2)
                channel = phone.SecureChannel(connection, bytes([7]) * 32, bytes([13]) * 32, bytes([14]) * 4, bytes([11]) * 32, bytes([12]) * 4)
                native_send = channel.send
                def send(wire):
                    if wire.get("kind") == control.REQUEST:
                        assert not service.lock._is_owned(), "Timer transport held its source guard during send"
                    native_send(wire)
                channel.send = send
                service.connections[PHONE] = channel; service.connection_transports[PHONE] = "wifi"
                service._ensure_desktop_updates(PHONE)
                result = None
                def run_controls():
                    fingerprint = phone.fingerprint(phone.unb64(peer["static_public"], 32))
                    def call(body):
                        value = service.request_time_control(PHONE, fingerprint, body)
                        assert value["report"]["status"] in ("ok", "duplicate"), value
                        return value["report"]
                    before = call(control.request(str(uuid4())))
                    operation = str(uuid4())
                    start = control.request(str(uuid4()), "start", operation_id=operation, expected_revision=before["revision"],
                        restore_epoch=before["restore_epoch"], activity="Native timer TCP fixture")
                    started = call(start); assert started["persisted"] and started["entries"][0]["id"] == operation
                    pause = call(control.request(str(uuid4()), "pause", operation_id=str(uuid4()), expected_revision=started["revision"],
                        restore_epoch=started["restore_epoch"], entry_id=operation)); assert pause["paused"]
                    duplicate = copy.deepcopy(start); duplicate["request_id"] = str(uuid4())
                    replay = call(duplicate); assert replay["status"] == "duplicate" and replay["entries"][0]["pauseMinute"] is not None
                    fresh = call(control.request(str(uuid4())))
                    resumed = call(control.request(str(uuid4()), "resume", operation_id=str(uuid4()), expected_revision=fresh["revision"],
                        restore_epoch=fresh["restore_epoch"], entry_id=operation)); assert not resumed["paused"]
                    finished = call(control.request(str(uuid4()), "finish", operation_id=str(uuid4()), expected_revision=resumed["revision"],
                        restore_epoch=resumed["restore_epoch"], entry_id=operation)); assert finished["persisted"] and finished["entries"] == []
                    return {"native_timer_control": True, "operation_id": operation, "command_count": 4,
                        "duplicate_verified": True, "timer_reports_not_cached": not any(kind == "time_control_report" for kind, _ in events)}
                deadline = time.monotonic() + 55
                while time.monotonic() < deadline:
                    for queued in service.store.pending(PHONE): service._send_message(channel, PHONE, queued)
                    try:
                        received = channel.receive()
                        service._payload(peer, channel, received)
                    except socket.timeout: pass
                    if result is None and service.time_status(PHONE).get("ready") and service.shared_settings_ready(PHONE):
                        result = pool.submit(run_controls)
                        def completed(future):
                            if future.exception() is not None:
                                import traceback
                                traceback.print_exception(future.exception(), file=sys.stderr)
                        result.add_done_callback(completed)
                    if result is not None and result.done():
                        value = result.result(); channel.send(dict(type="close", reason="normal"))
                        print(json.dumps(value), flush=True); return
                raise TimeoutError("Native timer control fixture did not finish")


if __name__ == "__main__": main()
