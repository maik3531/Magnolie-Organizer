"""Origin is local command metadata, shared with the existing call engine."""
import sqlite3
from uuid import uuid4

import pytest
from test_mcp_call_context import fixture, event
from test_time_sync_runtime import message
import magnolie_telefon as phone
import magnolie_hintergrund as background


@pytest.mark.parametrize("action", ["dial", "answer", "end"])
@pytest.mark.parametrize("origin", ["gui", "mcp"])
def test_native_call_handlers_preserve_origin_and_route_signed_results(tmp_path, monkeypatch, action, origin):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    reference = str(uuid4()); call = event()
    if action == "end": call.update(state="offhook", offhook_ms=call["started_ms"])
    if action != "dial": service._payload(peer, channel, message("incoming_call_state.event", call))
    events.clear(); channel.sent.clear()
    observed = []; service.private_call_result_observer = lambda *args: observed.append(args)
    if action == "dial": service.request_dial(peer["device_id"], "+49301234567", reference, origin=origin)
    elif action == "answer": service.request_answer(peer["device_id"], call["call_ref"], reference, origin=origin)
    else: service.request_end_call(peer["device_id"], call["call_ref"], call["revision"], reference, origin=origin)
    assert service.store.command_origin(peer["device_id"], reference) == origin
    assert not any("origin" in wire.get("body", {}) for wire in channel.sent), "Local origin must never enter the phone protocol"
    if origin == "mcp": assert not any(kind in ("dial_status", "answer_status", "end_status") for kind, _ in events)
    events.clear()
    kind = {"dial": "dial_request.result", "answer": "answer_call.result", "end": "end_call.result"}[action]
    body = dict(state="submitted", error="none", occurred_ms=phone.now_ms())
    if action == "dial": body["client_ref"] = reference
    else: body.update(command_ref=reference, call_ref=call["call_ref"])
    service._payload(peer, channel, message(kind, body))
    assert channel.sent[-1]["status"] == "accepted" and service.store.command_state(reference) == "submitted"
    gui_results = [value for name, value in events if name in ("dial_status", "answer_status", "end_status")]
    if origin == "mcp":
        assert not gui_results and len(observed) == 1
        assert observed[0] == (peer["device_id"], peer["static_public"], channel, kind, body)
    else:
        assert len(gui_results) == 1 and not observed


def test_private_origin_survives_reopen_and_late_reply_without_owner_stays_out_of_gui(tmp_path, monkeypatch):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    reference = str(uuid4())
    service.request_dial(peer["device_id"], "+49301234567", reference, origin="mcp")
    service.store = phone.PhoneStore(service.store.root, "Reopened command store")
    assert service.store.command_origin(peer["device_id"], reference) == "mcp"
    assert service.store.update_command_origin(str(uuid4()), reference, "failed") is None
    assert service.store.command_state(reference) == "queued"
    service.private_call_result_observer = None; events.clear()
    service._payload(peer, channel, message("dial_request.result", dict(client_ref=reference, state="submitted", error="none", occurred_ms=phone.now_ms())))
    assert channel.sent[-1]["status"] == "accepted" and service.store.command_state(reference) == "submitted"
    assert not any(kind == "dial_status" for kind, _ in events)


def test_legacy_command_migration_preserves_gui_origin_and_state(tmp_path, monkeypatch):
    service, peer, _, _ = fixture(tmp_path, monkeypatch)
    reference = str(uuid4()); service.store.remember_command(peer["device_id"], reference, "submitted")
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("ALTER TABLE command_effect RENAME TO previous_command_effect")
        db.execute("CREATE TABLE command_effect(client_ref TEXT PRIMARY KEY,state TEXT NOT NULL,first_seen_ms INTEGER NOT NULL,peer_id TEXT NOT NULL DEFAULT '')")
        db.execute("INSERT INTO command_effect SELECT client_ref,state,first_seen_ms,peer_id FROM previous_command_effect")
        db.execute("DROP TABLE previous_command_effect")
    reopened = phone.PhoneStore(service.store.root, "Migrated command store")
    assert reopened.command_origin(peer["device_id"], reference) == "gui" and reopened.command_state(reference) == "submitted"
    assert reopened.update_command_origin(peer["device_id"], reference, "failed") == "gui"


def test_ordinary_daemon_dial_request_cannot_choose_private_origin():
    with pytest.raises(background.IPCError):
        background._request_shape("phone_request_dial", dict(peer_id=str(uuid4()), destination="+49301234567", client_ref=str(uuid4()), origin="mcp"))
