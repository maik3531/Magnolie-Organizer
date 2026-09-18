"""Native HFP routing, shared by the foreground and background phone owner.

This is not the Magnolie RFCOMM transport. The installed audio server must
already support the local HF role; we never install roles or change defaults.
"""
import json
import os
import re
import selectors
import shlex
import shutil
import subprocess
import threading
import time
import uuid


AG = "0000111f-0000-1000-8000-00805f9b34fb"
HF = "0000111e-0000-1000-8000-00805f9b34fb"
ADDRESS = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")
# These names describe the REMOTE role. headset-head-unit is the wrong way round.
AG_PROFILES = {"audio-gateway", "headset-audio-gateway", "headset_audio_gateway"}
AG_NODE_PROFILES = {"headset-audio-gateway", "headset_audio_gateway", "hfp_ag"}


class AudioUnavailable(Exception):
    pass


def bounded_command(arguments):
    """Bound time and bytes while reading, not just after communicate()."""
    with subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, env=dict(os.environ, LC_ALL="C.UTF-8")) as process:
        try:
            data = bytearray()
            until = time.monotonic() + 3
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = until - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise AudioUnavailable("audio_timeout")
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise AudioUnavailable("audio_response_too_large")
            if process.wait(timeout=max(.01, until - time.monotonic())):
                raise AudioUnavailable("audio_server_unavailable")
            return data.decode("utf-8", errors="strict")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


class NativeBlueZAudio:
    guard = None

    def objects(self):
        from gi.repository import Gio, GLib
        if self.guard:
            self.guard()
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.owner = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "GetNameOwner", GLib.Variant("(s)", ("org.bluez",)),
            None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        if self.guard:
            self.guard()
        return self.bus.call_sync(self.owner, "/", "org.freedesktop.DBus.ObjectManager",
            "GetManagedObjects", None, None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]

    def device(self, address, require_connected=True):
        objects = self.objects()
        matches = [(path, interfaces["org.bluez.Device1"]) for path, interfaces in objects.items()
                   if str(interfaces.get("org.bluez.Device1", {}).get("Address", "")).upper() == address]
        if len(matches) != 1:
            raise AudioUnavailable("bound_device_unavailable")
        path, device = matches[0]
        adapter = objects.get(device.get("Adapter"), {}).get("org.bluez.Adapter1", {})
        if (not device.get("Paired") or not device.get("Trusted") or device.get("Blocked")
                or require_connected and not device.get("Connected") or not adapter.get("Powered")):
            raise AudioUnavailable("existing_connected_trusted_bond_required")
        if AG not in [str(value).lower() for value in device.get("UUIDs", [])]:
            raise AudioUnavailable("remote_hfp_ag_unavailable")
        if HF not in [str(value).lower() for value in adapter.get("UUIDs", [])]:
            raise AudioUnavailable("local_hfp_hf_unavailable")
        self.last_connected = bool(device.get("Connected"))
        return path

    def connect_profile(self, path):
        from gi.repository import Gio, GLib
        if self.guard:
            self.guard()
        try:
            self.bus.call_sync(self.owner, path, "org.bluez.Device1",
                "ConnectProfile", GLib.Variant("(s)", (AG,)),
                None, Gio.DBusCallFlags.NONE, 3000, None)
            return True
        except GLib.Error as error:
            if Gio.DBusError.get_remote_error(error) == "org.bluez.Error.AlreadyConnected":
                return False
            raise

    def disconnect_profile(self, path):
        from gi.repository import Gio, GLib
        try:
            self.bus.call_sync(self.owner, path, "org.bluez.Device1",
                "DisconnectProfile", GLib.Variant("(s)", (AG,)),
                None, Gio.DBusCallFlags.NONE, 3000, None)
        except GLib.Error as error:
            if Gio.DBusError.get_remote_error(error) not in (
                    "org.bluez.Error.NotConnected", "org.freedesktop.DBus.Error.UnknownObject"):
                raise

    def release_profile(self, address, path, owner):
        objects = self.objects()
        device = objects.get(path, {}).get("org.bluez.Device1", {})
        if self.owner == owner and str(device.get("Address", "")).upper() == address and device.get("Connected"):
            self.disconnect_profile(path)


class NativePulseAudio:
    def __init__(self, runner=None, finder=None):
        self.runner = runner or bounded_command
        self.finder = finder or shutil.which
        self.guard = None

    def command(self, *arguments):
        if self.guard:
            self.guard()
        tool = self.finder("pactl")
        if not tool:
            raise AudioUnavailable("pactl_missing")
        result = self.runner([tool, *arguments])
        if self.guard:
            self.guard()
        return result

    def data(self, kind):
        raw = self.command("--format=json", *(["info"] if kind == "info" else ["list", kind]))
        if len(raw.encode("utf-8")) > 1024 * 1024:
            raise AudioUnavailable("audio_response_too_large")
        value = json.loads(raw)
        if kind == "info":
            if not isinstance(value, dict):
                raise AudioUnavailable("audio_json_unavailable")
        elif (not isinstance(value, list) or len(value) > 4096
              or any(not isinstance(item, dict) for item in value)):
            raise AudioUnavailable("audio_json_unavailable")
        return value

    @staticmethod
    def address(item):
        props = item.get("properties", {})
        addresses = set()
        for key in ("api.bluez5.address", "bluez5.address", "device.string"):
            value = str(props.get(key, "")).upper()
            if ADDRESS.fullmatch(value):
                addresses.add(value)
        for key in ("api.bluez5.path", "bluez.path"):
            match = re.fullmatch(r"/org/bluez/hci[0-9]+/dev_([0-9A-Fa-f_]{17})", str(props.get(key, "")))
            if match:
                addresses.add(match[1].replace("_", ":").upper())
        return next(iter(addresses)) if len(addresses) == 1 else ""

    @staticmethod
    def name(item):
        name = item.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", name):
            raise AudioUnavailable("audio_endpoint_unavailable")
        return name

    @staticmethod
    def profile_name(card):
        value = card.get("active_profile", "")
        return value.get("name", "") if isinstance(value, dict) else value

    def card(self, address):
        cards = [item for item in self.data("cards") if self.address(item) == address]
        if len(cards) != 1:
            raise AudioUnavailable("phone_audio_card_unavailable")
        card = cards[0]
        self.name(card)
        if type(card.get("index")) is not int:
            raise AudioUnavailable("phone_audio_card_unavailable")
        profiles = card.get("profiles", {})
        if isinstance(profiles, list):
            profiles = {item.get("name"): item for item in profiles if isinstance(item, dict)}
        if not isinstance(profiles, dict):
            raise AudioUnavailable("local_hfp_hf_unavailable")
        available = [name for name, props in profiles.items() if name in AG_PROFILES
                     and isinstance(props, dict) and props.get("available") not in ("no", False)]
        if not available:
            raise AudioUnavailable("local_hfp_hf_unavailable")
        active = self.profile_name(card)
        return card, active if active in available else sorted(available)[0]

    def local_endpoints(self):
        info = self.data("info")
        result = []
        for kind, default in (("sources", "default_source_name"), ("sinks", "default_sink_name")):
            local = [item for item in self.data(kind) if item.get("name") == info.get(default)
                     and not self.address(item) and not self.is_monitor(item)
                     and (item.get("properties", {}).get("device.api") == "alsa"
                          or "alsa.card" in item.get("properties", {}))]
            if len(local) != 1 or type(local[0].get("index")) is not int or local[0].get("mute") is not False:
                raise AudioUnavailable("pc_endpoints_unavailable")
            self.name(local[0])
            result.append(local[0])
        return result

    def endpoints(self, address, card):
        local = self.local_endpoints()
        remote = []
        for kind in ("sources", "sinks"):
            matches = [item for item in self.data(kind) if self.address(item) == address
                      and str(item.get("card")) == str(card.get("index"))
                      and item.get("properties", {}).get("api.bluez5.profile",
                          item.get("properties", {}).get("bluetooth.protocol")) in AG_NODE_PROFILES
                      and not self.is_monitor(item)]
            if len(matches) != 1:
                raise AudioUnavailable("duplex_endpoints_unavailable")
            item = matches[0]
            self.name(item)
            if type(item.get("index")) is not int or item.get("mute") is not False:
                raise AudioUnavailable("audio_endpoint_unavailable")
            remote.append(item)
        # Phone downlink -> PC sink; PC microphone -> phone uplink.
        return ((remote[0], local[1]), (local[0], remote[1]))

    @staticmethod
    def is_monitor(item):
        return item.get("monitor_of_sink") not in (None, 4294967295, "4294967295") or bool(item.get("monitor_of_sink_name"))

    def foreign_streams(self, address, owned):
        for endpoints, streams, field in (("sinks", "sink-inputs", "sink"),
                                          ("sources", "source-outputs", "source")):
            indices = {str(item.get("index")) for item in self.data(endpoints) if self.address(item) == address}
            if any(str(item.get(field)) in indices and str(item.get("owner_module")) not in owned
                   for item in self.data(streams)):
                return True
        return False

    def native_gateway(self, address):
        """Observe PipeWire's native AG streams without creating duplicate loops."""
        local_source, local_sink = self.local_endpoints()
        for kind, field, endpoint, factory in (
                ("sink-inputs", "sink", local_sink, "api.bluez5.sco.source"),
                ("source-outputs", "source", local_source, "api.bluez5.sco.sink")):
            matches = [item for item in self.data(kind) if self.address(item) == address
                       and item.get("properties", {}).get("api.bluez5.profile") in AG_NODE_PROFILES
                       and item.get("properties", {}).get("factory.name") == factory]
            if (len(matches) != 1 or matches[0].get("corked") is not False
                    or matches[0].get("mute") is not False
                    or str(matches[0].get(field)) != str(endpoint["index"])
                    or endpoint.get("state") != "RUNNING"):
                return False
        return True


class AnrufBluetooth:
    """One cancellable, resource-owned route; only the phone service may drive it."""
    def __init__(self, bluez=None, pulse=None):
        self.bluez = bluez or NativeBlueZAudio()
        self.pulse = pulse or NativePulseAudio()
        self.lock = threading.RLock()
        self.token = uuid.uuid4().hex
        self.modules = {}
        self.modules_pending = False
        self.profile_hold = None
        self.connection_hold = None
        self.native_gateway_active = False
        self.key = None
        self.active_context = None
        self.retry_key, self.retry_at = None, 0
        self.state = self.snapshot("unavailable", "not_probed")

    @staticmethod
    def snapshot(state, reason, **values):
        return dict(backend="linux_native_hfp", state=state, reason=reason,
                    available=state in ("available", "active"), active=state == "active",
                    local_role="111e", remote_role="111f", **values)

    def probe(self, address):
        try:
            if not ADDRESS.fullmatch(address):
                raise AudioUnavailable("bound_device_unavailable")
            self.bluez.device(address, require_connected=False)
            self.pulse.local_endpoints()
            if not self.bluez.last_connected:
                return self.snapshot("available", "connection_required")
            if not self.pulse.native_gateway(address):
                self.pulse.card(address)
            return self.snapshot("available", "ready")
        except Exception as error:
            return self.snapshot("unavailable", str(error) if isinstance(error, AudioUnavailable) else "native_access_unavailable")

    def _check(self, context, refresh):
        if not context or refresh() != context:
            raise AudioUnavailable("call_changed")
        self.bluez.device(context["address"], require_connected=False)
        if refresh() != context:
            raise AudioUnavailable("call_changed")

    def _wait(self, action, context, refresh, timeout=2):
        until = time.monotonic() + timeout
        while True:
            self._check(context, refresh)
            try:
                result = action()
                if result:
                    return result
            except AudioUnavailable:
                pass
            if time.monotonic() >= until:
                raise AudioUnavailable("route_not_observed")
            time.sleep(.1)

    def update(self, refresh):
        with self.lock:
            context = refresh()
            if not context:
                self.retry_key = None
                released = self.restore()
                self.state = self.snapshot("inactive" if released else "unavailable",
                                           "no_authorized_call" if released else "cleanup_pending")
                return dict(self.state)
            key = (context["device_id"], context["identity"], context["session"],
                   context["call_ref"], context["revision"], context["address"], context["consent"])
            if self.retry_key == key and time.monotonic() < self.retry_at:
                failure = dict(self.state)
                self.restore()
                self.state = failure
                return dict(self.state)
            if self.key != key:
                self.restore()
            self.key = key
            def current():
                if refresh() != context:
                    raise AudioUnavailable("call_changed")
            self.bluez.guard = self.pulse.guard = current
            try:
                if self.modules_pending or self.profile_hold or self.connection_hold or self.native_gateway_active:
                    if self.state["active"] and self._observed(context, refresh):
                        return dict(self.state)
                    self.restore()
                    if self.modules_pending or self.profile_hold or self.connection_hold:
                        raise AudioUnavailable("cleanup_pending")
                    self.key = key
                self._check(context, refresh)
                path = self.bluez.device(context["address"], require_connected=False)
                was_connected = self.bluez.last_connected
                self.pulse.local_endpoints()
                if self.pulse.foreign_streams(context["address"], set()):
                    raise AudioUnavailable("phone_audio_in_use")
                # Own only the profile requested for this authorized conversation.
                # Keep enough identity to release it even after a lost RPC reply.
                def connect():
                    previous = self.connection_hold
                    hold = (context["address"], path, self.bluez.owner)
                    if not was_connected:
                        self.connection_hold = hold
                    created = self.bluez.connect_profile(path)
                    if created is True:
                        self.connection_hold = hold
                    elif created is False:
                        self.connection_hold = previous
                def ready_route():
                    self.bluez.device(context["address"])
                    if self.pulse.native_gateway(context["address"]):
                        return ("native", None)
                    legacy = self.pulse.card(context["address"])
                    self.pulse.endpoints(context["address"], legacy[0])
                    return ("legacy", legacy)
                try:
                    mode, legacy = ready_route()
                except AudioUnavailable:
                    connect()
                    mode, legacy = self._wait(ready_route, context, refresh, timeout=6)
                if mode == "native":
                    self.native_gateway_active = True
                    self._check(context, refresh)
                    self.active_context = context
                    self.state = self.snapshot("active", "native_duplex_route_observed", device_id=context["device_id"],
                        call_ref=context["call_ref"], revision=context["revision"])
                    return dict(self.state)
                card, profile = legacy
                try:
                    self.pulse.endpoints(context["address"], card)
                except AudioUnavailable:
                    self._check(context, refresh)
                    connect()
                self._check(context, refresh)
                card, profile = self.pulse.card(context["address"])
                old = self.pulse.profile_name(card)
                if old != profile:
                    if self.pulse.foreign_streams(context["address"], set()):
                        raise AudioUnavailable("phone_audio_in_use")
                    self._check(context, refresh)
                    cookie = self.pulse.data("info").get("cookie")
                    if cookie is None or not old:
                        raise AudioUnavailable("profile_ownership_unavailable")
                    self.profile_hold = (context["address"], self.pulse.name(card), old, profile, cookie, card["index"])
                    self.pulse.command("set-card-profile", self.pulse.name(card), profile)
                self._check(context, refresh)
                card, _ = self.pulse.card(context["address"])
                if self.pulse.profile_name(card) != profile:
                    raise AudioUnavailable("profile_not_observed")
                routes = self._wait(lambda: self.pulse.endpoints(context["address"], card), context, refresh)
                for source, sink in routes:
                    self._check(context, refresh)  # In particular immediately before opening the mic.
                    args = ["source=" + self.pulse.name(source), "sink=" + self.pulse.name(sink),
                            "source_dont_move=true", "sink_dont_move=true",
                            "source_output_properties=magnolie.call.owner=" + self.token,
                            "sink_input_properties=magnolie.call.owner=" + self.token]
                    # Discover by the unguessable ownership tag even if pactl loses its reply.
                    self.modules_pending = True
                    try:
                        self.pulse.command("load-module", "module-loopback", *args)
                    finally:
                        self._owned_modules()
                self._wait(lambda: self._observed(context, refresh), context, refresh)
                self.active_context = context
                self.state = self.snapshot("active", "duplex_route_observed", device_id=context["device_id"],
                    call_ref=context["call_ref"], revision=context["revision"])
            except Exception as error:
                self.restore()
                self.state = self.snapshot("unavailable", str(error) if isinstance(error, AudioUnavailable) else "native_access_unavailable")
                self.retry_key, self.retry_at = key, time.monotonic() + 10
            finally:
                self.bluez.guard = self.pulse.guard = None
            return dict(self.state)

    def _owned_modules(self):
        found = {}
        for item in self.pulse.data("modules"):
            if item.get("name") != "module-loopback" or not isinstance(item.get("index"), int):
                continue
            args = shlex.split(item.get("argument", ""))
            if all(key + "=magnolie.call.owner=" + self.token in args for key in
                   ("source_output_properties", "sink_input_properties")):
                found[str(item["index"])] = args
        self.modules = found
        return found

    def _observed(self, context, refresh):
        self._check(context, refresh)
        self.bluez.device(context["address"])
        if self.native_gateway_active:
            return self.pulse.native_gateway(context["address"])
        card, _ = self.pulse.card(context["address"])
        if self.pulse.profile_name(card) not in AG_PROFILES:
            return False
        routes = self.pulse.endpoints(context["address"], card)
        modules = self._owned_modules()
        if len(modules) != 2 or self.pulse.foreign_streams(context["address"], set(modules)):
            return False
        inputs, outputs = self.pulse.data("sink-inputs"), self.pulse.data("source-outputs")
        for source, sink in routes:
            matches = [index for index, args in modules.items()
                       if "source=" + source["name"] in args and "sink=" + sink["name"] in args]
            if len(matches) != 1 or any(item.get("state") != "RUNNING" for item in (source, sink)):
                return False
            for streams, field, endpoint in ((inputs, "sink", sink), (outputs, "source", source)):
                actual = [item for item in streams if str(item.get("owner_module")) == matches[0]]
                if (len(actual) != 1 or str(actual[0].get(field)) != str(endpoint["index"])
                        or actual[0].get("corked") is not False or actual[0].get("mute") is not False):
                    return False
        self._check(context, refresh)
        return True

    def restore(self):
        with self.lock:
            pending = bool(self.modules_pending or self.profile_hold or self.connection_hold)
            self.state = self.snapshot("unavailable" if pending else "inactive",
                                       "cleanup_pending" if pending else "released")
            self.active_context = None
            self.native_gateway_active = False
            self.key = None
            bluez_guard, pulse_guard = self.bluez.guard, self.pulse.guard
            self.bluez.guard = self.pulse.guard = None
            try:
                if self.modules_pending:
                    for index in list(self._owned_modules()):
                        self.pulse.command("unload-module", index)
                    if self._owned_modules():
                        return False
                    self.modules_pending = False
                if self.profile_hold:
                    address, name, old, selected, cookie, index = self.profile_hold
                    cards = [item for item in self.pulse.data("cards") if self.pulse.address(item) == address
                             and item.get("name") == name]
                    if (len(cards) == 1 and cards[0].get("index") == index and self.pulse.profile_name(cards[0]) == selected
                            and self.pulse.data("info").get("cookie") == cookie):
                        if self.pulse.foreign_streams(address, set()):
                            # Someone else adopted the profile. It no longer belongs to us.
                            self.profile_hold = None
                            self.connection_hold = None
                            self.state = self.snapshot("inactive", "released")
                            return True
                        if old:
                            self.pulse.command("set-card-profile", name, old)
                            cards = self.pulse.data("cards")
                            if any(item.get("name") == name and self.pulse.profile_name(item) == selected for item in cards):
                                return False
                    self.profile_hold = None
                if self.connection_hold:
                    address, path, owner = self.connection_hold
                    if not self.pulse.foreign_streams(address, set()):
                        self.bluez.release_profile(address, path, owner)
                    self.connection_hold = None
                self.state = self.snapshot("inactive", "released")
                return True
            except Exception:
                # Keep ownership for a later cleanup attempt, never disconnect all profiles.
                return False
            finally:
                self.bluez.guard, self.pulse.guard = bluez_guard, pulse_guard
