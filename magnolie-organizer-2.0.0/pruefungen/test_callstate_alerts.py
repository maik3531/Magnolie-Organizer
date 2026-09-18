"""Synthetic call control only: no phone, profile, contacts, or native dial effects."""
import ast
import copy
import json
import re
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import magnolie_telefon as phone
import magnolie_hintergrund as background

PEER = "11111111-1111-4111-8111-111111111111"
CALL = "22222222-2222-4222-8222-222222222222"
NEXT = "33333333-3333-4333-8333-333333333333"


def call(direction="incoming", state="ringing", revision=1):
    return dict(call_ref=CALL, direction=direction, state=state, revision=revision,
        number="", number_status="not_shared", occurred_ms=1000, started_ms=1000,
        offhook_ms=1000 if state == "offhook" else 0, ended_ms=1000 if state == "idle" else 0,
        control_origin="unknown", spam_status="unknown", battery_percent=-1, battery_captured_ms=0)


class Store:
    def __init__(self):
        self.commands = {}
        grants = {name: True for name in ("answer_call", "end_call", "incoming_call_state")}
        self.value = dict(device_id=PEER, state="paired", static_public="synthetic-public-identity",
            local_grants={"grants": dict(grants)}, grants={"grants": dict(grants)}, capabilities={"items": {
                "incoming_call_state": {"available": True, "versions": [2]},
                "answer_call": {"available": True, "versions": [1]}, "end_call": {"available": True, "versions": [1, 2]}}})
    def peer(self, peer_id): return self.value if peer_id == PEER else None
    def command_state(self, ref): return self.commands.get(ref)
    def remember_command(self, peer_id, ref, state): self.commands[ref] = state
    def queue(self, peer_id, kind, body, ttl):
        return dict(message_id=NEXT, kind=kind, body=body, ttl=ttl)
    def outbox_policy(self, *args): return "any"
    def mark_attempt(self, *args): pass


class Notifications:
    def __init__(self): self.items, self.launches, self.withdrawn = [], [], []
    def show(self, title, body, actions=(), **kwargs):
        self.items.append((title, body, actions)); return True
    def withdraw(self, key): self.withdrawn.append(key)
    def open_call_action(self, token): self.launches.append(token)
    def open_organizer(self): raise AssertionError("call alert opened full book")


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(phone, "now_ms", lambda: 1000)
    value = phone.PhoneService.__new__(phone.PhoneService)
    value.lock = threading.RLock()
    value.store = Store()
    value.incoming_calls = {PEER: call()}
    value.call_action_tickets = {}
    value.sent = []
    value.connections = {PEER: SimpleNamespace(send=value.sent.append)}
    value.incoming_call_channels = dict(value.connections)
    value.connection_transports = {PEER: "wifi"}
    return value


def daemon(service, visible=False, consent=True):
    notifications = Notifications()
    forwarded = []
    glib = SimpleNamespace(idle_add=lambda method, *args: method(*args), timeout_add=lambda *args: 1)
    events = background.PhoneDaemonEvents(lambda: service,
        {"permissions": {"phone_call_notifications": consent}}, notifications, glib,
        lambda *args: forwarded.append(args) or True, lambda: visible)
    return events, notifications, forwarded


@pytest.mark.parametrize("direction", ["outgoing", "unknown"])
@pytest.mark.parametrize("gui", [True, False])
def test_outgoing_and_unobserved_offhook_never_notify(service, direction, gui):
    events, notices, _ = daemon(service, gui)
    for state in ("ringing", "offhook", "idle"):
        service.incoming_calls[PEER] = call(direction, state)
        events("incoming_call", dict(call(direction, state), device_id=PEER))
    assert not notices.items and not service.sent


def test_outgoing_control_failure_is_not_labeled_incoming(service):
    events, notices, _ = daemon(service)
    events("end_status", {"call_ref": CALL, "state": "failed", "error": "os_restricted"})
    assert notices.items[0][0] == "Phone"
    assert "Incoming call" not in repr(notices.items)


@pytest.mark.parametrize("action,kind", [("answer", "answer_call.command"), ("reject", "end_call.command")])
def test_cold_notification_actions_capture_transport_and_are_one_shot(service, action, kind):
    events, notices, _ = daemon(service)
    events("incoming_call", dict(call(), device_id=PEER))
    assert len(notices.items) == 1 and not notices.launches
    actions = {item[0]: item[2] for item in notices.items[0][2]}
    assert set(actions) == {"answer", "reject"}
    actions[action]()
    assert not service.sent  # Only the launched app may consume the daemon ticket.
    token = notices.launches[0]
    assert re.fullmatch("[0-9a-f]{64}", token)
    server = background.IPCServer.__new__(background.IPCServer)
    server.gui_notification_ready = lambda: False
    server.settings_getter = lambda: {"permissions": {"phone_call_notifications": True}}
    server.phone_backend = service
    assert server._phone_operation("phone_call_action", {"token": token})
    assert service.sent[0]["kind"] == kind
    assert service.sent[0]["body"]["call_ref"] == CALL
    assert service.sent[0]["body"]["expected_state"] == "ringing"
    assert service.sent[0]["ttl"] == 10_000
    assert not service.call_action(token)
    sibling = "answer" if action == "reject" else "reject"
    actions[sibling]()
    assert not service.call_action(notices.launches[-1])
    assert len(service.sent) == 1


@pytest.mark.parametrize("change", ["call", "revision", "offhook", "idle", "outgoing", "identity", "connection", "unpaired", "local", "remote", "state_consent", "state_capability", "state_version", "old_observation", "future_observation", "capability"])
def test_stale_or_revoked_actions_cannot_touch_later_call(service, change):
    token = service.call_action_tokens(PEER, CALL, 1)["answer"]
    current, peer = service.incoming_calls[PEER], service.store.value
    if change == "call": current["call_ref"] = NEXT
    elif change == "revision": current["revision"] = 2
    elif change in ("offhook", "idle"): current["state"] = change
    elif change == "outgoing": current["direction"] = "outgoing"
    elif change == "identity": peer["static_public"] = "different-public-identity"
    elif change == "connection": service.connections[PEER] = object()
    elif change == "unpaired": peer["state"] = "unpaired"
    elif change == "local": peer["local_grants"]["grants"]["answer_call"] = False
    elif change == "remote": peer["grants"]["grants"]["answer_call"] = False
    elif change == "state_consent": peer["local_grants"]["grants"]["incoming_call_state"] = False
    elif change == "state_capability": peer["capabilities"]["items"]["incoming_call_state"]["available"] = False
    elif change == "state_version": peer["capabilities"]["items"]["incoming_call_state"]["versions"] = [1]
    elif change == "old_observation": current["occurred_ms"] = -60000
    elif change == "future_observation": current["occurred_ms"] = 1001
    elif change == "capability": peer["capabilities"]["items"]["answer_call"]["available"] = False
    assert not service.call_action(token)
    assert not service.sent


def test_expiry_restart_privacy_and_legacy_capability(service):
    with patch.object(phone.time, "monotonic", return_value=100):
        tokens = service.call_action_tokens(PEER, CALL, 1)
    assert not service.store.commands
    assert "number" not in repr(service.call_action_tickets) and "not_shared" not in repr(service.call_action_tickets)
    with patch.object(phone.time, "monotonic", return_value=160):
        assert not service.call_action(tokens["answer"])
    service.call_action_tickets = {}  # Restart has no durable action tickets.
    assert not service.call_action(tokens["reject"])
    service.store.value["capabilities"]["items"]["end_call"]["versions"] = [1]
    assert set(service.call_action_tokens(PEER, CALL, 1)) == {"answer"}


def test_reconnected_transport_cannot_reissue_actions_from_previous_ring(service):
    token = service.call_action_tokens(PEER, CALL, 1)["answer"]
    service.stop_event = threading.Event()
    service._purge_identifiers = lambda peer: None
    service.connections[PEER].sock = SimpleNamespace(close=lambda: None)
    replacement = SimpleNamespace(send=lambda message: None)
    service._activate_connection(PEER, replacement, "wifi")
    assert not service.call_action(token)
    assert not service.call_action_tokens(PEER, CALL, 1)
    assert not service.call_is_current(PEER, CALL, 1)
    service.incoming_calls[PEER] = call()
    service.incoming_call_channels[PEER] = replacement
    assert set(service.call_action_tokens(PEER, CALL, 1)) == {"answer", "reject"}


def test_call_received_during_authenticated_handshake_is_presented_after_activation(service):
    channel = service.connections.pop(PEER)
    service.stop_event = threading.Event()
    service._purge_identifiers = lambda peer: None
    observed = []
    service.callback = lambda event, payload: observed.append((event, payload))
    assert not service.call_is_current(PEER, CALL, 1)
    service._activate_connection(PEER, channel, "wifi")
    assert service.call_is_current(PEER, CALL, 1)
    assert len(observed) == 1 and observed[0][1]["call_ref"] == CALL


def test_temporary_outgoing_end_grant_does_not_authorize_incoming_rejection(service):
    service.store.value["local_grants"]["grants"]["answer_call"] = False
    assert not service.call_action_tokens(PEER, CALL, 1)
    with pytest.raises(RuntimeError): service.request_end_call(PEER, CALL, 1, NEXT)
    assert not service.sent


@pytest.mark.parametrize("gui", [True, False])
def test_notification_consent_and_gui_tray_ownership(service, gui):
    events, notices, forwarded = daemon(service, gui, False)
    events("incoming_call", dict(call(), device_id=PEER))
    assert not notices.items
    events.settings["permissions"]["phone_call_notifications"] = True
    events("incoming_call", dict(call(), device_id=PEER))
    assert len(notices.items) == (0 if gui else 1)
    if gui:
        assert len(forwarded) == 2
        assert events.take(forwarded[-1][1]["ticket"])["payload"]["notify"] is True


def test_daemon_consent_is_revalidated_after_notification_click(service):
    token = service.call_action_tokens(PEER, CALL, 1)["answer"]
    server = background.IPCServer.__new__(background.IPCServer)
    server.gui_notification_ready = lambda: False
    server.settings_getter = lambda: {}
    server.phone_backend = service
    with pytest.raises(background.IPCError): server._phone_operation("phone_call_action", {"token": token})
    assert not service.sent


def test_delayed_old_callback_cannot_invalidate_new_daemon_delivery(service):
    events, notices, _ = daemon(service, visible=True)
    newer = dict(call(), call_ref=NEXT)
    service.incoming_calls[PEER] = newer
    events("incoming_call", dict(newer, device_id=PEER))
    token = events._call_alert["token"]
    events("incoming_call", dict(call(state="idle", revision=2), device_id=PEER))
    assert events.call_alert(token, "claim")
    assert not notices.items


def test_native_generation_gate_rechecks_old_callback_after_new_state(service):
    from types import MethodType
    namespace = dict(_REGIONAL={"homeCountry": "US", "language": "en"},
        telefon_anreichern=lambda payload, *args: payload)
    exec(extracted("_telefon_ereignis"), namespace)
    newer = dict(call(), call_ref=NEXT, device_id=PEER)
    owner = SimpleNamespace(_telefon=service, _anruf_hinweis_sperre=threading.Lock(),
        _aktueller_anruf_hinweis=newer, _gesperrt=True, antwort=lambda *args: None)
    owner.event = MethodType(namespace["_telefon_ereignis"], owner)
    entered = threading.Event()
    worker = threading.Thread(target=lambda: (entered.set(), owner.event("incoming_call", dict(call(), device_id=PEER))))
    with owner._anruf_hinweis_sperre:
        worker.start(); assert entered.wait(2)
        service.incoming_calls[PEER] = newer
    worker.join(2)
    assert not worker.is_alive()
    assert owner._aktueller_anruf_hinweis == newer


def test_hidden_ready_gui_owns_compact_alert_without_background_opt_in(service):
    events, notices, forwarded = daemon(service, visible=False, consent=False)
    events.call_gui_ready = lambda: True
    events("incoming_call", dict(call(), device_id=PEER))
    assert not notices.items and len(forwarded) == 1
    assert events.take(forwarded[0][1]["ticket"])["payload"]["notify"] is True
    server = background.IPCServer.__new__(background.IPCServer)
    server.gui_notification_ready = lambda: True
    server.settings_getter = lambda: {}
    server.phone_backend = service
    tokens = server._phone_operation("phone_call_action_tokens", {"peer_id": PEER, "call_ref": CALL, "revision": 1})
    assert set(tokens) == {"answer", "reject"}
    server.gui_notification_ready = lambda: False
    with pytest.raises(background.IPCError): server._phone_operation("phone_call_action", {"token": tokens["answer"]})
    assert not service.sent


def test_cold_action_traverses_same_user_unix_ipc_and_captured_phone_transport(service):
    token = service.call_action_tokens(PEER, CALL, 1)["reject"]
    with tempfile.TemporaryDirectory(prefix="magnolie-call-ipc-") as directory:
        path = str(Path(directory) / "runtime/background.sock")
        server = background.IPCServer(SimpleNamespace(), path, phone_backend=service,
            settings_getter=lambda: {"permissions": {"phone_call_notifications": True}}).start()
        try:
            assert background.ipc_request("phone_call_action", {"token": token}, path=path)
            assert not background.ipc_request("phone_call_action", {"token": token}, path=path)
        finally:
            server.close()
    assert len(service.sent) == 1 and service.sent[0]["body"]["call_ref"] == CALL
    assert service.sent[0]["body"]["expected_state"] == "ringing"


def test_system_action_launch_arguments_contain_only_opaque_token():
    notifications = background.NativeNotifications.__new__(background.NativeNotifications)
    notifications.executable = "/synthetic/Magnolie Organizer"
    with patch.object(background.subprocess, "Popen") as launch, patch.object(background, "notification_launch_environment", return_value={}):
        notifications.open_call_action("1" * 64)
        assert launch.call_args.args[0] == [notifications.executable, "--call-action", "1" * 64]
        assert launch.call_args.kwargs["start_new_session"] is True
        notifications.open_call_action("+12025550123")
        notifications.open_call_action("1" * 64 + " --other-command")
        assert launch.call_count == 1


def extracted(name):
    tree = ast.parse((BIN / "magnolie-organizer").read_text(encoding="utf-8"))
    node = next(item for item in ast.walk(tree) if isinstance(item, ast.FunctionDef) and item.name == name)
    return compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "call-extracted", "exec")


def test_cold_launcher_only_consumes_ticket_without_loading_profile(service):
    token = service.call_action_tokens(PEER, CALL, 1)["reject"]
    with patch.object(background, "ipc_request", side_effect=lambda operation, arguments: service.call_action(arguments["token"])), patch.object(background.os, "geteuid", return_value=1000), patch.object(background.subprocess, "Popen") as launch, patch.object(background, "service_executable", return_value="/synthetic/organizer"), patch.object(background, "notification_launch_environment", return_value={}):
        assert background.call_action_main(["--call-action", token]) == 0
        assert launch.call_args.args[0] == ["/synthetic/organizer"]
        assert background.call_action_main(["--call-action", token]) == 1
        assert background.call_action_main(["--call-action", token, "--other-command"]) == 2
        assert launch.call_count == 1
    assert service.sent[0]["kind"] == "end_call.command"
    source = (BIN / "magnolie-organizer").read_text()
    assert source.index("sys.exit(call_action_main") < source.index("_crash_reporting_install") < source.index("gi.require_version(\"Gtk\"")


def test_android_direction_and_native_control_source_boundaries():
    root = BIN.parents[1]
    android = root / "magnolie-notes-1.0.13/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon"
    calls = (android / "EingehendeAnrufe.kt").read_text()
    assert '"outgoing", number, clientRef' in calls
    assert 'if (value == TelephonyManager.CALL_STATE_RINGING) "incoming" else "unknown"' in calls
    assert 'expectedCallRef != call?.callRef' in calls and 'call.callRef != callRef || call.revision != revision' in calls
    assert 'liveStateMatches(TelephonyManager.CALL_STATE_RINGING)' in calls
    assert 'expectedState == "ringing" && call.direction != "incoming"' in calls
    assert 'acceptRingingCall(VideoProfile.STATE_AUDIO_ONLY)' in calls and '?.endCall()' in calls
    assert "requestRole" not in calls and "ROLE_DIALER" not in calls
    assert 'listOf(1, 2)' in (android / "TelefonModelle.kt").read_text()


@pytest.mark.parametrize("supported", [True, False])
@pytest.mark.parametrize("controls", [True, False])
@pytest.mark.parametrize("local_photo", [True, False])
def test_native_alert_uses_only_local_bound_contact_and_real_action_tokens(service, supported, controls, local_photo):
    import base64
    import binascii
    current = dict(call(), device_id=PEER, number="+12025550123", number_status="available")
    service.incoming_calls[PEER] = current
    service.store.value["local_grants"]["grants"]["answer_call"] = controls
    panels = []
    notices = Notifications()
    photo = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nsynthetic").decode()
    contact = dict(vorname="Local", nachname="Synthetic", foto=photo if local_photo else "https://invalid/local-photo",
                   telefone=[{"wert": "+12025550123"}])
    owner = SimpleNamespace(_aktueller_anruf_hinweis=current, _telefon=service,
        _daten_sperre=threading.Lock(), _aktuelle_daten={"kontakte": [contact]}, _tray_zeigen=lambda: None)
    namespace = dict(re=re, base64=base64, binascii=binascii, threading=threading,
        ton_abspielen=lambda **kwargs: None, time=SimpleNamespace(time=lambda: 1, monotonic=lambda: 1),
        _=lambda text: text, _REGIONAL={"homeCountry": "US", "language": "en"},
        telefon_schluessel=lambda value, country: value, _telefon_liste=lambda value: value["telefone"],
        telefon_anreichern=lambda *args: {"phone_display_hint": ""},
        GLib=SimpleNamespace(idle_add=lambda method: method(), timeout_add=lambda *args: 1),
        magnolie_meldung=lambda *args, **kwargs: panels.append((args, kwargs)) or supported)
    exec(extracted("_telefon_anruf_anzeigen"), namespace)
    # Untrusted frontend metadata must not replace the locally bound contact.
    with patch.object(background, "NativeNotifications", return_value=notices):
        namespace["_telefon_anruf_anzeigen"](owner, dict(state="ringing", callRef=CALL, kennung=PEER,
            revision=1, name="Untrusted name", nummer="+12025550999", foto="https://invalid/photo", stil="system", annehmen=True))
    assert panels[0][0][1].splitlines()[:2] == ["Local Synthetic", "+12025550123"]
    assert panels[0][1]["foto"] == (b"\x89PNG\r\n\x1a\nsynthetic" if local_photo else b"")
    assert "Untrusted" not in repr(panels)
    actions = panels[0][1]["aktionen"]
    assert [item[1] for item in actions] == ["Answer", "Reject", "Silence this alert"]
    actions[-1][2]()
    assert not service.sent  # Mute is local dismissal, never fake microphone control.
    if not controls:
        assert actions[0][2] is None and actions[1][2] is None
        assert "Call controls unavailable" in panels[0][0][1]
        return
    if supported:
        actions[1][2]()
    else:
        notices.items[0][2][1][2]()
    assert service.sent[0]["kind"] == "end_call.command"
    assert "Local Synthetic" not in json.dumps(service.sent) and "+12025550123" not in json.dumps(service.sent)
    current["state"] = "offhook"
    assert not panels[0][1]["gueltig"]()


def test_manual_localizations_have_all_twenty_languages_and_unique_keys():
    import importlib.util
    import subprocess
    spec = importlib.util.spec_from_file_location("call_locales", BIN.parents[1] / "tools/callstate_locales.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    spec = importlib.util.spec_from_file_location("call_catalog", BIN.parent / "werkzeuge/desktop_pot_merge.py")
    parser = importlib.util.module_from_spec(spec); spec.loader.exec_module(parser)
    assert len(module.TRANSLATIONS) == 20 and len(set(module.KEYS)) == 3
    native = json.loads((BIN.parents[1] / "Magnolie-Organizer-Windows-2.0.0/app/native-i18n.json").read_text())
    for locale, values in module.TRANSLATIONS.items():
        assert all(values)
        if locale != "en":
            assert all(native["locales"][locale][key] == value for key, value in zip(module.KEYS, values))
            for directory in (BIN.parent / "po", BIN.parents[1] / "Magnolie-Organizer-Windows-2.0.0/app/po"):
                path = directory / (locale + ".po")
                entries = [entry for entry in parser.catalog(path) if not entry["obsolete"]]
                for key, value in zip(module.KEYS, values):
                    matches = [entry for entry in entries if entry["msgid"] == key]
                    assert len(matches) == 1 and matches[0]["msgstr"] == value
                    assert "fuzzy" not in matches[0]["flags"]
                subprocess.run(["msgfmt", "--check", "--check-format", "-o", "/dev/null", str(path)],
                    check=True, capture_output=True)


class DelayedGLib:
    def __init__(self): self.idles, self.timers = [], []
    def idle_add(self, method, *args): self.idles.append(lambda: method(*args)); return len(self.idles)
    def timeout_add(self, delay, method): self.timers.append((delay, method)); return len(self.timers)
    def drain(self):
        while self.idles: self.idles.pop(0)()
    def fire(self, delay):
        for item in list(self.timers):
            if item[0] == delay:
                self.timers.remove(item)
                if item[1](): self.timers.append(item)


@pytest.mark.parametrize("outcome", ["missing", "failed", "shown", "lost-after-claim", "idle", "revoked", "no-consent", "publish-failed"])
def test_handoff_ack_or_fallback_never_trusts_event_queue(service, outcome):
    glib, notices, published = DelayedGLib(), Notifications(), []
    events = background.PhoneDaemonEvents(lambda: service,
        {"permissions": {"phone_call_notifications": outcome != "no-consent"}}, notices, glib,
        lambda *args: published.append(args) or outcome != "publish-failed", lambda: True)
    events("incoming_call", dict(call(), device_id=PEER)); glib.drain()
    token = events._call_alert["token"]
    if outcome in ("failed", "shown", "lost-after-claim"):
        assert events.call_alert(token, "claim")
        assert not events.call_alert(token, "claim")
        if outcome != "lost-after-claim": assert events.call_alert(token, outcome)
    if outcome == "idle": service.incoming_calls[PEER]["state"] = "idle"
    if outcome == "revoked": service.store.value["local_grants"]["grants"]["incoming_call_state"] = False
    glib.fire(2000)
    assert len(notices.items) == (1 if outcome in ("missing", "failed", "lost-after-claim", "publish-failed") else 0)
    assert events.call_alert(token, "claim") == (outcome == "no-consent")
    assert not service.sent


@pytest.mark.parametrize("change", ["idle", "connection", "grant", "new-call", "expiry"])
def test_daemon_coalesces_and_withdraws_against_actual_phone(service, change):
    glib, notices = DelayedGLib(), Notifications()
    events = background.PhoneDaemonEvents(lambda: service,
        {"permissions": {"phone_call_notifications": True}}, notices, glib, lambda *args: True, lambda: False)
    events("incoming_call", dict(call(), device_id=PEER))
    if change == "idle":
        service.incoming_calls[PEER] = call(state="idle", revision=2)
        events("incoming_call", dict(service.incoming_calls[PEER], device_id=PEER))
        glib.drain(); assert not notices.items; return
    glib.drain(); assert len(notices.items) == 1
    if change == "connection": service.connections.clear()
    if change == "grant": service.store.value["grants"]["grants"]["incoming_call_state"] = False
    if change == "new-call": service.incoming_calls[PEER]["call_ref"] = NEXT
    with patch.object(background.time, "monotonic", return_value=background.time.monotonic() + (61 if change == "expiry" else 0)):
        glib.fire(300)
    assert notices.withdrawn[-1] == "phone-call"


@pytest.mark.parametrize("supported", [True, False])
def test_native_gui_before_app_init_claims_actual_ipc_delivery(service, supported):
    import base64
    import binascii
    from types import MethodType
    glib, notices, daemon_notices = DelayedGLib(), Notifications(), Notifications()
    panels = []
    def popup(*args, **kwargs):
        panels.append(kwargs)
        if supported: assert kwargs["bei_anzeigen"]()
        return supported
    namespace = dict(re=re, base64=base64, binascii=binascii, threading=threading,
        ton_abspielen=lambda **kwargs: None, time=SimpleNamespace(time=lambda: 1, monotonic=lambda: 1),
        _=lambda text: text, _REGIONAL={"homeCountry": "US", "language": "en"},
        telefon_schluessel=lambda *args: "", telefon_anreichern=lambda payload, *args: dict(payload, phone_display_hint=""),
        GLib=glib, magnolie_meldung=popup)
    exec(extracted("_telefon_anruf_anzeigen"), namespace)
    exec(extracted("_telefon_ereignis"), namespace)
    with tempfile.TemporaryDirectory(prefix="magnolie-call-handoff-") as directory:
        path = str(Path(directory) / "runtime/background.sock")
        server = background.IPCServer(SimpleNamespace(), path, phone_backend=service,
            settings_getter=lambda: {"permissions": {"phone_call_notifications": True}})
        server._gui_subscribers["synthetic"] = (background.time.monotonic() + 30, False, True)
        events = background.PhoneDaemonEvents(lambda: service,
            {"permissions": {"phone_call_notifications": True}}, daemon_notices, glib,
            server.publish_event, server.gui_present, call_gui_ready=server.gui_notification_ready)
        server.phone_event_getter = events.take; server.phone_alert_handler = events.call_alert; server.start()
        try:
            proxy = background.PhoneServiceProxy(path=path)
            replies = []
            owner = SimpleNamespace(_telefon=proxy, _gesperrt=False, _daten_sperre=threading.Lock(),
                _anruf_hinweis_sperre=threading.Lock(),
                _tray_zeigen=lambda: None,
                _aktuelle_daten={"einstellungen": {"adressen": {"kommunikation": {"anruf": {
                    "art": "magnolie", "telefonId": PEER, "eingehendBenachrichtigen": True, "computerTelefonie": True}}}}},
                antwort=lambda *args: replies.append(args))
            owner._telefon_anruf_anzeigen = MethodType(namespace["_telefon_anruf_anzeigen"], owner)
            events("incoming_call", dict(call(), device_id=PEER)); glib.drain()
            queued = server._poll_events(0, 0)["events"][0]
            delivered = proxy._call("take_event", ticket=queued["payload"]["ticket"])
            with patch.object(background, "NativeNotifications", return_value=notices):
                namespace["_telefon_ereignis"](owner, delivered["event"], delivered["payload"])
                glib.drain(); glib.fire(2000)
            assert len(panels) == 1 and len(notices.items) == (0 if supported else 1) and not daemon_notices.items
            assert events._call_alert["state"] == "shown"
            assert [reply[0] for reply in replies] == ["App.telefonEingehenderAnruf"]  # JS never ran.
            (panels[0]["aktionen"][1][2] if supported else notices.items[0][2][1][2])()
            assert service.sent[0]["kind"] == "end_call.command"
            assert service.sent[0]["body"]["call_ref"] == CALL
        finally:
            server.close()
