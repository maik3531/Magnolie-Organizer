"""Synthetic BlueZ/Pulse only. Never connect a real phone or change host audio."""
import copy
import json
import ast
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import magnolie_anruf_audio as audio
import magnolie_telefon as phone
import magnolie_hintergrund as background

ADDRESS = "AA:BB:CC:DD:EE:FF"
PEER = "11111111-1111-4111-8111-111111111111"
CALL = "22222222-2222-4222-8222-222222222222"
PATH = "/org/bluez/hci2/dev_AA_BB_CC_DD_EE_FF"


class BlueZ(audio.NativeBlueZAudio):
    def __init__(self):
        self.owner = ":1.81"
        self.calls = []
        self.change = lambda: None
        self.values = {
            "/org/bluez/hci2": {"org.bluez.Adapter1": {"Powered": True, "UUIDs": [audio.HF]}},
            PATH: {"org.bluez.Device1": {"Address": ADDRESS, "Alias": "Not an identity",
                "Adapter": "/org/bluez/hci2", "Paired": True, "Trusted": True,
                "Connected": True, "UUIDs": [audio.AG]}}}

    def objects(self): return copy.deepcopy(self.values)

    def connect_profile(self, path):
        already_connected = self.values[path]["org.bluez.Device1"]["Connected"]
        self.values[path]["org.bluez.Device1"]["Connected"] = True
        self.calls.append((path, "ConnectProfile", audio.AG))
        self.change()
        return not already_connected

    def disconnect_profile(self, path):
        self.calls.append((path, "DisconnectProfile", audio.AG))
        self.values[path]["org.bluez.Device1"]["Connected"] = False


class Pulse:
    def __init__(self):
        props = {"api.bluez5.address": ADDRESS, "api.bluez5.profile": "headset-audio-gateway"}
        self.card = {"index": 81, "name": "bound_card", "active_profile": "audio-gateway",
                     "properties": {"device.string": ADDRESS}, "profiles": {
                         "audio-gateway": {"available": "yes"}, "off": {"available": "yes"},
                         "headset-head-unit": {"available": "yes"}}}
        self.values = {
            "info": {"default_source_name": "pc_mic", "default_sink_name": "pc_speaker", "cookie": "epoch1"},
            "cards": [self.card],
            "sources": [dict(index=143, name="phone_downlink", card=81, properties=props,
                             state="RUNNING", mute=False, monitor_of_sink=None),
                        dict(index=51, name="pc_mic", card=7, properties={"device.api": "alsa"},
                             state="RUNNING", mute=False, monitor_of_sink=4294967295)],
            "sinks": [dict(index=197, name="phone_uplink", card=81, properties=props,
                           state="RUNNING", mute=False),
                      dict(index=24, name="pc_speaker", card=7, properties={"alsa.card": "3"},
                           state="RUNNING", mute=False)],
            "modules": [{"index": 9, "name": "module-loopback", "argument": "source=other sink=other"}],
            "sink-inputs": [], "source-outputs": []}
        self.commands = []
        self.next_id = 101
        self.observe = True
        self.fail_unload = False
        self.change = lambda args: None

    def run(self, args):
        args = args[1:]
        self.commands.append(args)
        if args[0] == "--format=json":
            return json.dumps(self.values[args[-1]])
        if args[0] == "set-card-profile":
            assert args[1] == "bound_card"
            self.card["active_profile"] = args[2]
        elif args[0] == "load-module":
            assert args[1] == "module-loopback"
            index = self.next_id
            self.next_id += 7
            self.values["modules"].append(dict(index=index, name=args[1], argument=" ".join(args[2:])))
            options = dict(arg.split("=", 1) for arg in args[2:])
            assert options["source_dont_move"] == options["sink_dont_move"] == "true"
            if self.observe:
                for endpoints, streams, field in (("sinks", "sink-inputs", "sink"), ("sources", "source-outputs", "source")):
                    endpoint = next(item for item in self.values[endpoints] if item["name"] == options[field])
                    self.values[streams].append(dict(owner_module=index, corked=False, mute=False,
                                                     **{field: endpoint["index"]}))
        elif args[0] == "unload-module":
            assert args[1] != "9", "foreign loopback must never be unloaded"
            if self.fail_unload:
                raise audio.AudioUnavailable("audio_server_unavailable")
            for kind, field in (("modules", "index"), ("sink-inputs", "owner_module"), ("source-outputs", "owner_module")):
                self.values[kind] = [item for item in self.values[kind] if str(item.get(field)) != args[1]]
        else:
            raise AssertionError("Forbidden global/stream command: " + repr(args))
        self.change(args)
        return "0\n"  # Intentionally NOT the actual module index; exit status is not evidence.


@pytest.fixture
def route():
    bluez, pulse = BlueZ(), Pulse()
    router = audio.AnrufBluetooth(bluez, audio.NativePulseAudio(pulse.run, lambda _: "fake-pactl"))
    context = dict(device_id=PEER, identity="public-key", session=17, call_ref=CALL,
                   revision=2, address=ADDRESS, consent=(3, 5, 1))
    return router, bluez, pulse, context


def test_native_full_sequence_correct_roles_owned_duplex_and_cleanup(route):
    router, bluez, pulse, context = route
    assert router.probe(ADDRESS)["available"]
    pulse.card["active_profile"] = "off"
    remote = pulse.values["sources"].pop(0)
    bluez.change = lambda: pulse.values["sources"].insert(0, remote)
    assert not router.update(lambda: None)["active"]
    assert not [cmd for cmd in pulse.commands if cmd[0] == "load-module"]
    state = router.update(lambda: context.copy())
    assert state == dict(backend="linux_native_hfp", state="active", reason="duplex_route_observed",
        available=True, active=True, local_role="111e", remote_role="111f", device_id=PEER,
        call_ref=CALL, revision=2)
    loads = [cmd for cmd in pulse.commands if cmd[0] == "load-module"]
    assert [(cmd[2], cmd[3]) for cmd in loads] == [
        ("source=phone_downlink", "sink=pc_speaker"), ("source=pc_mic", "sink=phone_uplink")]
    assert set(router.modules) == {"101", "108"}
    assert router.update(lambda: context.copy())["active"]
    assert len([cmd for cmd in pulse.commands if cmd[0] == "load-module"]) == 2
    assert not router.update(lambda: None)["active"]
    assert pulse.card["active_profile"] == "off"
    assert bluez.calls == [(PATH, "ConnectProfile", audio.AG)]
    assert pulse.values["modules"] == [{"index": 9, "name": "module-loopback", "argument": "source=other sink=other"}]
    assert pulse.values["info"]["default_source_name"] == "pc_mic"
    assert pulse.values["info"]["default_sink_name"] == "pc_speaker"


@pytest.mark.parametrize("failure", ["rfcomm", "a2dp", "wrong_local_role", "untrusted", "unpaired", "off", "wrong_address", "ambiguous_address"])
def test_bluez_requires_actual_bound_connected_peer_and_hf_role(route, failure):
    router, bluez, pulse, context = route
    device = bluez.values[PATH]["org.bluez.Device1"]
    if failure == "rfcomm": device["UUIDs"] = [phone.BLUETOOTH_UUID]
    elif failure == "a2dp": device["UUIDs"] = ["0000110a-0000-1000-8000-00805f9b34fb"]
    elif failure == "wrong_local_role": bluez.values["/org/bluez/hci2"]["org.bluez.Adapter1"]["UUIDs"] = [audio.AG]
    elif failure == "off": bluez.values["/org/bluez/hci2"]["org.bluez.Adapter1"]["Powered"] = False
    elif failure == "untrusted": device["Trusted"] = False
    elif failure == "unpaired": device["Paired"] = False
    elif failure == "wrong_address": device["Address"] = "11:22:33:44:55:66"
    elif failure == "ambiguous_address": bluez.values[PATH + "_duplicate"] = copy.deepcopy(bluez.values[PATH])
    assert not router.probe(ADDRESS)["available"]
    assert not router.update(lambda: context.copy())["active"]
    assert not bluez.calls and not pulse.commands


def test_disconnected_trusted_phone_connects_on_call_and_disconnects_on_end(route):
    router, bluez, pulse, context = route
    bluez.values[PATH]["org.bluez.Device1"]["Connected"] = False
    assert router.probe(ADDRESS)["reason"] == "connection_required"
    assert not bluez.calls
    assert router.update(lambda: context.copy())["active"]
    assert router.connection_hold
    assert router.update(lambda: None)["state"] == "inactive"
    assert bluez.calls == [(PATH, "ConnectProfile", audio.AG), (PATH, "DisconnectProfile", audio.AG)]
    assert not router.connection_hold


@pytest.mark.parametrize("already_connected", [False, True])
def test_pipewire_native_gateway_streams_are_not_duplicated(route, already_connected):
    router, bluez, pulse, context = route
    bluez.values[PATH]["org.bluez.Device1"]["Connected"] = already_connected
    pulse.values["cards"] = []
    pulse.values["sources"] = [pulse.values["sources"][1]]
    pulse.values["sinks"] = [pulse.values["sinks"][1]]
    common = {"api.bluez5.address": ADDRESS, "api.bluez5.profile": "headset-audio-gateway"}
    pulse.values["sink-inputs"] = [dict(sink=24, corked=False, mute=False, owner_module=None,
        properties=dict(common, **{"factory.name": "api.bluez5.sco.source"}))]
    pulse.values["source-outputs"] = [dict(source=51, corked=False, mute=False, owner_module=None,
        properties=dict(common, **{"factory.name": "api.bluez5.sco.sink"}))]
    assert router.update(lambda: context.copy())["reason"] == "native_duplex_route_observed"
    assert router.update(lambda: context.copy())["active"]
    assert not any(command[0] == "load-module" for command in pulse.commands)
    assert router.update(lambda: None)["state"] == "inactive"
    assert bluez.calls == ([] if already_connected else
        [(PATH, "ConnectProfile", audio.AG), (PATH, "DisconnectProfile", audio.AG)])


def test_call_ending_during_automatic_connection_releases_only_created_profile(route):
    router, bluez, pulse, context = route
    bluez.values[PATH]["org.bluez.Device1"]["Connected"] = False
    bluez.change = context.clear
    assert not router.update(lambda: context.copy() or None)["active"]
    assert bluez.calls == [(PATH, "ConnectProfile", audio.AG), (PATH, "DisconnectProfile", audio.AG)]
    assert not any(command[0] == "load-module" for command in pulse.commands)


def test_bluez_restart_does_not_disconnect_a_replacement_connection(route):
    router, bluez, pulse, context = route
    bluez.values[PATH]["org.bluez.Device1"]["Connected"] = False
    assert router.update(lambda: context.copy())["active"]
    bluez.owner = ":1.999"
    assert router.restore()
    assert bluez.calls == [(PATH, "ConnectProfile", audio.AG)]


@pytest.mark.parametrize("change", ["revision", "call_ref", "identity", "address", "session", "consent", "idle"])
def test_refresh_between_profile_and_microphone_blocks_stale_audio(route, change):
    router, bluez, pulse, context = route
    def changed(args):
        if args[0] == "load-module":
            if change == "idle": context.clear()
            elif change == "revision": context[change] += 1
            else: context[change] = "changed"
    pulse.change = changed
    assert not router.update(lambda: context.copy() or None)["active"]
    loads = [cmd for cmd in pulse.commands if cmd[0] == "load-module"]
    assert len(loads) == 1 and "source=pc_mic" not in loads[0]
    assert len(pulse.values["modules"]) == 1 and not bluez.calls


def test_exit_zero_is_not_routing_evidence_and_cleanup_retries(route, monkeypatch):
    router, bluez, pulse, context = route
    clock = iter(range(1000))
    monkeypatch.setattr(audio.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(audio.time, "sleep", lambda _: None)
    pulse.observe = False
    pulse.fail_unload = True
    assert not router.update(lambda: context.copy())["active"]
    assert router.modules_pending
    pulse.fail_unload = False
    assert router.restore() and not router.modules_pending
    assert len(pulse.values["modules"]) == 1


@pytest.mark.parametrize("failure", ["wrong_card", "wrong_role", "monitor", "wrong_default", "muted", "foreign_stream", "missing_tools", "bad_json", "large_json"])
def test_pulse_actual_properties_fail_closed(route, failure, monkeypatch):
    router, bluez, pulse, context = route
    clock = iter(range(10000))
    monkeypatch.setattr(audio.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(audio.time, "sleep", lambda _: None)
    if failure == "wrong_card": pulse.card["properties"]["device.string"] = "11:22:33:44:55:66"
    elif failure == "wrong_role":
        pulse.card["profiles"] = {"headset-head-unit": {"available": "yes"}}
        pulse.card["active_profile"] = "headset-head-unit"
    elif failure == "monitor": pulse.values["sources"][1]["monitor_of_sink"] = 24
    elif failure == "wrong_default": pulse.values["info"]["default_source_name"] = "not_our_mic"
    elif failure == "muted": pulse.values["sources"][1]["mute"] = True
    elif failure == "foreign_stream": pulse.values["sink-inputs"] = [{"sink": 197, "owner_module": 9}]
    elif failure == "missing_tools": router.pulse.finder = lambda _: None
    elif failure == "bad_json": router.pulse.runner = lambda _: "not JSON"
    elif failure == "large_json": router.pulse.runner = lambda _: " " * (1024 * 1024 + 1)
    assert not router.update(lambda: context.copy())["active"]
    assert not [cmd for cmd in pulse.commands if cmd[0] == "load-module"]
    if failure in ("wrong_card", "wrong_role"):
        assert bluez.calls == [(PATH, "ConnectProfile", audio.AG)]
    if failure in ("missing_tools", "bad_json", "large_json", "monitor", "wrong_default", "muted"):
        assert not bluez.calls


def test_native_audio_adopted_by_another_application_is_not_disconnected(route):
    router, bluez, pulse, context = route
    pulse.card["active_profile"] = "off"
    assert router.update(lambda: context.copy())["active"]
    pulse.values["sink-inputs"].append({"sink": 197, "owner_module": 9})
    assert router.restore()
    assert pulse.card["active_profile"] == "audio-gateway"
    assert not bluez.calls


@pytest.fixture
def service(tmp_path, route):
    router, _, _, _ = route
    backend = SimpleNamespace(availability=lambda: (True, "available"), paired_devices=lambda: [])
    service = phone.PhoneService(str(tmp_path / "phone"), "Synthetic PC", bluetooth_backend=backend, call_audio=router)
    service.enabled, service.server = True, object()
    peer = dict(device_id=PEER, display_name="Synthetic phone", static_public=phone.b64(b"k" * 32), state="paired",
        capabilities=phone.desktop_capabilities(), grants=phone.desktop_grants(), local_grants=phone.desktop_grants(),
        last_contact_ms=0, bluetooth={"enabled": True, "address": ADDRESS}, call_audio={"prefer_pc": True},
        personal_sync={"own_device": True, "remote_own_device": True, "auto_wifi": False, "last_report": {}})
    for key in ("grants", "local_grants"):
        peer[key]["grants"]["incoming_call_state"] = True
    service.store.peers = [peer]
    service.store.save_peers()
    service.connections[PEER] = SimpleNamespace(send=lambda _: None)
    service.connection_transports[PEER] = "bluetooth"
    return service


def event(service, state="offhook", revision=2, ref=CALL, occurred=None):
    now = phone.now_ms() if occurred is None else occurred
    value = dict(call_ref=ref, revision=revision, direction="incoming", state=state,
        number="", number_status="not_shared", occurred_ms=now, started_ms=now,
        offhook_ms=now if state == "offhook" else 0, ended_ms=now if state == "idle" else 0,
        control_origin="phone", spam_status="unknown", battery_percent=-1, battery_captured_ms=0)
    # One clock sample: separate samples can accidentally create a 60001-ms
    # envelope, which the real protocol correctly rejects as over its TTL limit.
    sent_at = phone.now_ms()
    message = dict(type="message", v=1, message_id=str(uuid.uuid4()), kind="incoming_call_state.event",
                   created_ms=sent_at, expires_ms=sent_at + 60000, body=value)
    service._payload(service.store.peer(PEER), service.connections[PEER], message)
    return value


def test_owner_offhook_only_no_implicit_grants_and_snapshot_contract(service):
    before = copy.deepcopy(service.store.peer(PEER)["local_grants"])
    event(service, "ringing", 1)
    assert service._call_audio_context() is None
    assert not service.call_audio.update(service._call_audio_context)["active"]
    event(service)
    assert service._call_audio_context()
    assert service.call_audio.update(service._call_audio_context)["active"]
    report = service.report()
    assert report["bluetooth"]["available"] and report["call_audio"]["route"]["active"]
    assert len(json.dumps(report)) < background.MAX_PHONE_MESSAGE
    assert "identity" not in report["call_audio"]["route"]
    event(service, "idle", 3)
    assert not service.report()["call_audio"]["route"]["active"]
    service.call_audio.update(service._call_audio_context)
    assert not service.call_audio.modules_pending
    assert service.store.peer(PEER)["local_grants"] == before
    assert before["grants"]["answer_call"] is False


def test_event_fixture_keeps_exact_ttl_when_clock_advances(service, monkeypatch):
    import itertools
    clock = itertools.count(phone.now_ms())
    monkeypatch.setattr(phone, "now_ms", lambda: next(clock))
    event(service)
    assert service._call_audio_context(), "Fixture envelope must stay valid across a millisecond boundary"


@pytest.mark.parametrize("change", ["own", "preference", "local", "remote", "connection", "off", "peer", "revision"])
def test_current_owner_consent_and_binding_rechecked(service, change):
    event(service)
    assert service._call_audio_context()
    peer = service.store.peer(PEER)
    if change == "own": peer["personal_sync"]["own_device"] = False
    elif change == "preference": service.set_call_audio(PEER, False)
    elif change == "local": peer["local_grants"]["grants"]["incoming_call_state"] = False
    elif change == "remote": peer["grants"]["grants"]["incoming_call_state"] = False
    elif change == "connection": service.connections[PEER] = object()
    elif change == "off": service.stop_event.set()
    elif change == "peer": service.store.peers = []
    elif change == "revision": peer["local_grants"]["revision"] += 1
    assert service._call_audio_context() is None
    assert not service.call_audio.update(service._call_audio_context)["active"]


def test_old_call_and_old_session_replay_never_open_microphone(service):
    now = phone.now_ms()
    event(service, occurred=now - 20000)
    assert service._call_audio_context() is None
    event(service, revision=3, occurred=now)
    assert service._call_audio_context()
    later = str(uuid.uuid4())
    event(service, revision=1, ref=later, occurred=now)
    assert service._call_audio_context()["call_ref"] == later
    event(service, revision=4, occurred=now)
    assert service._call_audio_context() is None


def test_own_confirmation_default_and_explicit_false_survive_reload(service):
    peer = service.store.peer(PEER)
    peer.pop("call_audio")
    peer["personal_sync"]["own_device"] = False
    grants = copy.deepcopy(peer["local_grants"])
    service.set_personal_sync(PEER, True)
    assert peer["call_audio"] == {"prefer_pc": True}
    service.set_call_audio(PEER, False)
    service.set_personal_sync(PEER, False)
    service.set_personal_sync(PEER, True)
    assert peer["call_audio"] == {"prefer_pc": False}
    assert service.store._load_peers()[0]["call_audio"] == {"prefer_pc": False}
    assert peer["local_grants"] == grants


def test_background_owner_preference_uses_same_user_ipc(service, tmp_path):
    path = str(tmp_path / "ipc/background.sock")
    server = background.IPCServer(SimpleNamespace(), path, phone_backend=service).start()
    try:
        background.ipc_request("phone_set_call_audio", {"peer_id": PEER, "prefer_pc": False}, path=path)
        assert service.store.peer(PEER)["call_audio"]["prefer_pc"] is False
        report = background.ipc_request("phone_report", {}, path=path)
        assert report["call_audio"]["backend"] == "linux_native_hfp"
    finally:
        server.close()


def test_phone_owner_shutdown_joins_audio_and_closes_only_owned_resources(service):
    event(service)
    sock = SimpleNamespace(shutdown=lambda _: None, close=lambda: None)
    service.server = service.connections[PEER].sock = sock
    service._unpublish = lambda: None
    def forbidden_probe(_): raise AssertionError("capability probe must not delay active-route cancellation")
    service.call_audio.probe = forbidden_probe
    service.audio_thread = threading.Thread(target=service._call_audio_loop)
    service.audio_thread.start()
    try:
        until = time.monotonic() + 3
        while not service.call_audio.state["active"] and time.monotonic() < until:
            time.sleep(.01)
        assert service.call_audio.state["active"]
    finally:
        assert service.stop()
    assert not service.audio_thread.is_alive()
    assert not service.call_audio.modules_pending and not service.call_audio.state["active"]


def test_pulse_restart_or_user_profile_change_is_not_undone(route):
    router, _, pulse, context = route
    pulse.card["active_profile"] = "off"
    assert router.update(lambda: context.copy())["active"]
    pulse.values["info"]["cookie"] = "different-server"
    assert router.restore()
    assert pulse.card["active_profile"] == "audio-gateway"


def test_bounded_native_command_parser_without_any_audio_tools():
    assert audio.bounded_command([sys.executable, "-c", "print('[]')"]).strip() == "[]"
    with pytest.raises(audio.AudioUnavailable, match="too_large"):
        audio.bounded_command([sys.executable, "-c", "import sys; sys.stdout.write('x' * 2000000)"])
    with pytest.raises(audio.AudioUnavailable, match="unavailable"):
        audio.bounded_command([sys.executable, "-c", "raise SystemExit(1)"])
    with pytest.raises(audio.AudioUnavailable, match="timeout"):
        audio.bounded_command([sys.executable, "-c", "import time; time.sleep(5)"])


def test_delayed_daemon_snapshot_revalidates_call_and_bound_peer(service):
    event(service)
    assert service.call_audio.update(service._call_audio_context)["active"]
    tickets = []
    events = background.PhoneDaemonEvents(lambda: service, {}, SimpleNamespace(), SimpleNamespace(),
        lambda _, payload: tickets.append(payload["ticket"]) or True, lambda: True)
    events._forward("call_audio", service.call_audio_status())
    service.store.peer(PEER)["bluetooth"]["address"] = "11:22:33:44:55:66"
    assert not events.take(tickets[0])["payload"]["route"]["active"]
    assert not service.call_audio_status()["available"]
    service.call_audio.restore()


def test_native_source_and_packaging_boundaries():
    root = BIN.parent
    sys.path.insert(0, str(root / "werkzeuge"))
    from runtime_pruefen import package_modules
    inventory = {path.name for path in BIN.glob("*.py")}
    assert all(files == inventory for files in package_modules(root).values())
    for file in ("magnolie-organizer", "magnolie_telefon.py", "magnolie_hintergrund.py", "magnolie_anruf_audio.py"):
        ast.parse((BIN / file).read_text(encoding="utf-8"))
    for file in ("debian/install", "rpm/magnolie-organizer.spec", "werkzeuge/appimage_bauen.sh",
                 "flatpak/io.gitlab.maik3531.MagnolieOrganizer.json"):
        assert "magnolie_anruf_audio.py" in (root / file).read_text()
    manifest = json.loads((root / "flatpak/io.gitlab.maik3531.MagnolieOrganizer.json").read_text())
    assert "--socket=pulseaudio" in manifest["finish-args"]
    assert "--system-talk-name=org.bluez" in manifest["finish-args"]
    assert "--socket=system-bus" not in manifest["finish-args"]
    native = (BIN / "magnolie_anruf_audio.py").read_text()
    assert "bluetoothctl" not in native and "set-default-" not in native and '"move-' not in native
    assert '"Disconnect"' not in native
    assert '"DisconnectProfile", GLib.Variant("(s)", (AG,))' in native
    assert '"Pair"' not in native and '"Set"' not in native


def test_new_manual_texts_and_reused_label_in_all_desktop_catalogs():
    sys.path.insert(0, str(BIN.parents[1] / "tools"))
    import call_audio_locales as locales
    from test_locale_completeness import _catalog
    assert len(locales.TRANSLATIONS) == 20
    root = BIN.parents[1]
    native = json.loads((root / "Magnolie-Organizer-Windows-2.0.0/app/native-i18n.json").read_text())
    for locale, values in locales.TRANSLATIONS.items():
        assert len(values) == 3 and all(values)
        if locale == "en":
            continue
        for application in (root / "magnolie-organizer-2.0.0", root / "Magnolie-Organizer-Windows-2.0.0/app"):
            po = application / "po" / (locale + ".po")
            entries = _catalog(po)
            js = (application / "web/i18n" / (locale + ".js")).read_text()
            catalog = json.loads(re.fullmatch(r'window\.MagnolieI18n\.registerCatalog\("[^"\n]+", (.*)\);\s*', js)[1])
            for key, value in zip(locales.KEYS, values):
                assert entries[(None, key)]["values"] == [value]
                assert catalog["messages"][key] == native["locales"][locale][key] == value
            assert catalog["messages"]["Bluetooth device for call audio"]
            subprocess.run(["msgfmt", "--check", "--check-format", "-o", "/dev/null", str(po)],
                           check=True, capture_output=True)


def test_native_bluez_profile_method_uses_remote_ag_and_no_registration(monkeypatch):
    calls = []
    class Error(Exception): pass
    glib = SimpleNamespace(Error=Error, Variant=lambda signature, values: (signature, values))
    gio = SimpleNamespace(DBusCallFlags=SimpleNamespace(NONE=0),
        DBusError=SimpleNamespace(get_remote_error=lambda _: "org.bluez.Error.AlreadyConnected"))
    monkeypatch.setitem(sys.modules, "gi.repository", SimpleNamespace(Gio=gio, GLib=glib))
    backend = audio.NativeBlueZAudio()
    backend.owner = ":1.81"
    backend.bus = SimpleNamespace(call_sync=lambda *args: calls.append(args))
    backend.connect_profile(PATH)
    assert [(args[0], args[1], args[2], args[3], args[4]) for args in calls] == [
        (":1.81", PATH, "org.bluez.Device1", "ConnectProfile", ("(s)", (audio.AG,)))]
    def already_connected(*_): raise Error()
    backend.bus.call_sync = already_connected
    backend.connect_profile(PATH)  # Existing OS-owned connection needs no mutation.


def test_pulseaudio_json_profile_list_and_device_path_properties(route):
    router, _, pulse, context = route
    pulse.card["profiles"] = [dict(name=name, **values) for name, values in pulse.card["profiles"].items()]
    pulse.card["active_profile"] = {"name": "headset_audio_gateway"}
    pulse.card["profiles"].append({"name": "headset_audio_gateway", "available": "yes"})
    for kind in ("sources", "sinks"):
        pulse.values[kind][0]["properties"] = {"bluez.path": PATH, "bluetooth.protocol": "headset_audio_gateway"}
    assert router.update(lambda: context.copy())["active"]
    assert router.restore()


def test_consent_revoked_during_native_query_prevents_next_mutation(route):
    router, bluez, pulse, context = route
    original = pulse.run
    def revoke(args):
        value = original(args)
        if args[-1] == "info":
            context.clear()
        return value
    router.pulse.runner = revoke
    assert not router.update(lambda: context.copy() or None)["active"]
    assert not bluez.calls and not [cmd for cmd in pulse.commands if cmd[0] != "--format=json"]


def test_recreated_card_profile_is_not_owned(route):
    router, _, pulse, context = route
    pulse.card["active_profile"] = "off"
    assert router.update(lambda: context.copy())["active"]
    pulse.card["index"] = 82
    assert router.restore()
    assert pulse.card["active_profile"] == "audio-gateway"


def test_failed_cleanup_never_claims_verified_release(route):
    router, _, pulse, context = route
    assert router.update(lambda: context.copy())["active"]
    pulse.fail_unload = True
    assert not router.restore()
    assert router.state["state"] == "unavailable" and router.state["reason"] == "cleanup_pending"
    assert not router.state["active"] and router.modules_pending
    pulse.fail_unload = False
    assert router.restore() and router.state["reason"] == "released"
