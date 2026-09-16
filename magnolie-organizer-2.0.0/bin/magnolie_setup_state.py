#!/usr/bin/env python3
"""First-run state and lazy, selection-triggered setup adapters."""

import json
import os
import tempfile
from datetime import datetime, timezone


PROGRAM_NAME = "magnolie-organizer"
MARKER_NAME = "setup-state.json"
SCHEMA_VERSION = 1
READY_STATES = frozenset(("complete", "adopted", "skipped"))


def config_directory():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, PROGRAM_NAME)


def marker_path():
    return os.path.join(config_directory(), MARKER_NAME)


def evidence_paths():
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return (
        os.path.join(data, PROGRAM_NAME),
        config_directory(),
    )


def _has_evidence(path, marker):
    if os.path.isfile(path) or os.path.islink(path):
        return os.path.abspath(path) != os.path.abspath(marker)
    if not os.path.lexists(path):
        return False
    try:
        entries = os.listdir(path)
    except OSError:
        return True
    return any(os.path.abspath(os.path.join(path, name)) != os.path.abspath(marker)
               for name in entries)


def _read_marker(path):
    try:
        if os.path.getsize(path) > 256 * 1024:
            return None
        with open(path, "r", encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != SCHEMA_VERSION:
        return None
    if value.get("status") not in READY_STATES | {"pending"}:
        return None
    return value


def classify(path=None, evidence=None):
    """Return fresh, pending, ready, or damaged without modifying storage."""
    path = path or marker_path()
    if os.path.lexists(path):
        marker = _read_marker(path)
        if marker is None:
            return "damaged"
        return "ready" if marker["status"] in READY_STATES else "pending"
    candidates = tuple(evidence if evidence is not None else evidence_paths())
    return "existing" if any(_has_evidence(item, path) for item in candidates) else "fresh"


def _atomic_json(path, value):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".setup-", dir=directory)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            descriptor = -1
            json.dump(value, target, ensure_ascii=False, sort_keys=True, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_state(status, selections=None, path=None):
    if status not in READY_STATES | {"pending"}:
        raise ValueError("invalid setup status")
    value = {
        "schema": SCHEMA_VERSION,
        "status": status,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if selections is not None:
        # Imported personal data is handed to the web merge in memory, not persisted here.
        selections = {key: value for key, value in selections.items() if key != "stagedImports"}
        encoded = json.dumps(selections, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 128 * 1024:
            raise ValueError("setup selections are too large")
        value["selections"] = json.loads(encoded)
    _atomic_json(path or marker_path(), value)
    return value


def classify_and_adopt(path=None, evidence=None):
    state = classify(path, evidence)
    if state == "existing":
        try:
            write_state("adopted", {"reason": "pre-existing-local-state"}, path)
        except OSError:
            return "damaged"
        return "ready"
    return state


def services_allowed(state=None):
    return (state if state is not None else classify()) in {"ready", "existing"}


def assistant_required(state):
    """Return whether a normal foreground start must run setup."""
    return state in {"fresh", "pending", "damaged"}


class SetupServices:
    """Read-only importer adapters; credentials remain in memory until Finish."""

    def __init__(self, parse, scan, connection_store, translate=lambda text: text, thunderbird_profiles=None):
        self.parse = parse
        self.scan = scan
        self.connection_store = connection_store
        self.translate = translate
        self.thunderbird_profiles = thunderbird_profiles
        self.connections = {}

    def prepare_import(self, source, path=None):
        if path is None:
            if source not in ("thunderbird", "evolution"):
                return None
            result = self.scan(source)
            if source == "thunderbird" and self.thunderbird_profiles:
                for profile in self.thunderbird_profiles():
                    try:
                        with open(os.path.join(profile, "compatibility.ini"), encoding="utf-8") as stream:
                            text = stream.read(64 * 1024 + 1)
                        if len(text) > 64 * 1024:
                            continue
                        version = next((line[12:] for line in text.splitlines() if line.startswith("LastVersion=")), "")
                        if version:
                            result["sourceVersion"] = "".join(c for c in version if c.isascii() and (c.isalnum() or c in "._-"))[:80]
                            break
                    except (OSError, UnicodeError):
                        pass
            return result if any(result.get(key) for key in (
                "kontakte", "termine", "aufgaben", "jahrestage", "geburtstage", "notizen")) else None
        art = {"ics": "ics", "vcard": "vcf", "csv-lotus": "lotus",
               "ldif": "claws", "claws": "claws"}.get(source)
        if source in ("thunderbird", "evolution"):
            art = {".ics": "ics", ".vcs": "ics", ".lcs": "ics", ".vcf": "vcf",
                   ".csv": "lotus", ".xml": "claws", ".ldif": "claws", ".ldi": "claws"}.get(
                       os.path.splitext(path)[1].lower())
        if art is None:
            raise ValueError(self.translate("The file has an unsupported format."))
        with open(path, "rb") as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError(self.translate("The import file is larger than 32 megabytes."))
        result = self.parse(art, raw, path)
        result["art"] = art
        return result

    def discover(self, account_type, server, user, password):
        import uuid
        from magnolie_nextcloud import DavHttpClient, NextcloudDav, validate_account_type
        client = DavHttpClient(server, user, password)
        client.account_type = validate_account_type(account_type)
        dav = NextcloudDav(client)
        calendars = dav.collections("calendar")
        books = dav.collections("addressbook")
        token = uuid.uuid4().hex
        self.connections[token] = (client.account_type, client.server, client.user, password)
        return {"token": token, "calendars": calendars, "addressBooks": books}

    def commit_connection(self, token):
        kind, server, user, password = self.connections[token]
        self.connection_store().save(True, False, server, user, password, account_type=kind)

    def close(self):
        self.connections.clear()


class SetupPhoneServices:
    """Temporary native listeners; pairing decisions use the existing protocols."""

    def __init__(self, root, display_name, daemon_active=lambda: False, translate=lambda text: text,
                 phone=None, kde=None, borrowed=False, ipc=None):
        import threading
        import queue
        self.root, self.display_name, self.daemon_active = root, display_name, daemon_active
        self.translate = translate
        self.phone, self.kde = phone, kde
        self.borrowed = borrowed
        self.ipc = ipc
        self.remote_session = None
        self._active_pairing_token = None
        self._owned_pairing_token = None
        self._initial_pairing_token = None
        self._restore_pairing_window = False
        self._owned_kde_pairing = None
        self._kde_selected = ""
        self._started_phone = False
        self._previous_phone_enabled = None
        self._startup_committed = False
        self.events = queue.Queue()
        self.closed = threading.Event()
        self.connected_ids = {}

    def capabilities(self):
        import importlib.util
        import shutil
        # Listing transports must not reserve a daemon pairing session.
        # The actual connection acquires the lease on demand.
        return [{"transport": kind, "available": available, "canAutoStart": True,
                 "reason": "This phone transport is unavailable."}
                for kind, available in (("wifi", importlib.util.find_spec("cryptography") is not None),
                    ("kdeconnect", importlib.util.find_spec("OpenSSL") is not None),
                    ("bluetooth", shutil.which("bluetoothctl") is not None))]

    def connect(self, transport, prompt):
        import time
        import queue
        if self.closed.is_set():
            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        if not self.borrowed and (self.remote_session is not None or self.daemon_active()):
            self._remote("phone_setup_connect", transport=transport)
            while not self.closed.wait(.15):
                state = self._remote("phone_setup_status")
                if state["state"] == "failed":
                    raise RuntimeError(self.translate(state["error"]))
                if state["state"] == "connected":
                    result = state["result"]
                    if result.get("authenticated") is not True or transport not in state["connected"]:
                        raise RuntimeError(self.translate("The phone is no longer connected."))
                    self.connected_ids[transport] = result["deviceId"]
                    return result
                request = state.get("prompt")
                if request:
                    answer = prompt(request)
                    if self.closed.is_set(): break
                    self._remote("phone_setup_confirm", prompt=request["id"], answer=answer)
            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        if not any(item["transport"] == transport and item["available"] for item in self.capabilities()):
            raise RuntimeError(self.translate("This phone transport is unavailable."))
        deadline = time.monotonic() + 120
        own_id = None
        if transport == "kdeconnect":
            if self.kde is None:
                from magnolie_kdeconnect import create_backend
                self.kde = create_backend(os.path.join(self.root(), "kdeconnect"), callback=lambda *_: None)
            if getattr(self.kde, 'native', False):
                from magnolie_kdeconnect import NATIVE_KDE_LIMIT
                choices = [{'uid': d['device_id'], 'name': d['device_name']}
                           for d in self.kde.status()['devices'] if d['sms_send']]
                if not choices:
                    raise RuntimeError(self.translate(NATIVE_KDE_LIMIT))
                selected = choices[0]['uid'] if len(choices) == 1 else prompt({'kind': 'select', 'devices': choices})
                current = next((d for d in self.kde.status()['devices']
                                if d['device_id'] == selected and d['sms_send']), None)
                if current is None or self.closed.is_set():
                    raise RuntimeError(self.translate('The phone is no longer connected.'))
                self.connected_ids[transport] = selected
                return {'transport': transport, 'deviceId': selected,
                        'name': current['device_name'], 'authenticated': True}
            devices = self.kde.discover(timeout=5)
            if not self.kde.store.peers:
                choices = [{"uid": d.identity["deviceId"], "name": d.identity["deviceName"]} for d in devices]
                if not choices:
                    raise RuntimeError(self.translate("No phone was found. Open the phone app and try again."))
                selected = choices[0]["uid"] if len(choices) == 1 else prompt({"kind": "select", "devices": choices})
                if not selected:
                    raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
                self._kde_selected = selected
                pairing = self.kde.begin_pairing(device_id=selected, replace_stored=False)
                self._owned_kde_pairing = getattr(self.kde, "pairing", None)
                accepted = prompt({"kind": "confirm", "devices": [{"uid": selected, "name": pairing["device_name"]}], "code": pairing["code"]})
                self.kde.confirm_pairing(accepted == "accept")
                if accepted != "accept":
                    raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
            while not self.closed.is_set() and time.monotonic() < deadline:
                status = self.kde.status(timeout=0)
                if status.get("available") and status.get("paired_count", 0) > 0:
                    device_id = status["device_id"]
                    self.connected_ids[transport] = device_id
                    return {"transport": transport, "deviceId": device_id, "name": status.get("peer_name", device_id), "authenticated": True}
                self.closed.wait(.25)
        else:
            if self.phone is None:
                from magnolie_telefon import PhoneService
                try:
                    self.phone = PhoneService(os.path.join(self.root(), "telefon"), self.display_name(),
                        callback=lambda event, payload: self.events.put((event, payload)) if event == "pairing_code" else None)
                except RuntimeError as error:
                    # Only our storage diagnostics are message keys, not arbitrary OS details.
                    if str(error) in {
                        "Telefonidentitaet ist beschaedigt.",
                        "Telefon-Speicherschluessel ist beschaedigt.",
                        "Telefonablage ist beschaedigt.",
                        "Telefon-Gegenstellenliste ist beschaedigt.",
                    }:
                        raise RuntimeError(self.translate("The phone settings are damaged.")) from error
                    raise
                self.phone.personal_sync_available = lambda: False
            if self._previous_phone_enabled is None:
                self._previous_phone_enabled = self.phone.enabled
                self._initial_pairing_token = self.phone.pairing_token
                self._restore_pairing_window = bool(self.borrowed and self.phone.server and self.phone.enabled and
                    self.phone.pairing_token and time.monotonic() < self.phone.pairing_until and not self.phone.store.peers)
            if not self.phone.server:
                self.phone.enabled = True  # Runtime only, not startup consent.
                self._started_phone = True
            if self.closed.is_set() or not self.phone.server and not self.phone.start():
                raise RuntimeError(self.translate("The phone listener could not start."))
            if transport == "wifi" and not self.phone.store.peers:
                return self._connect_wifi(prompt, deadline)
            if transport == "bluetooth" and not self.phone.store.peers:
                return self._connect_bluetooth(prompt, deadline)
            if transport == "bluetooth":
                if any(p.get("transport") == "wifi" for p in self.phone.report()["peers"]):
                    raise RuntimeError(self.translate("Disconnect WLAN on the phone to use Bluetooth fallback."))
                peers = [p for p in self.phone.store.peers if p.get("state") == "paired"]
                if len(peers) != 1:
                    raise RuntimeError(self.translate("Pair Magnolie over WLAN before using Bluetooth."))
                devices = self.phone.bluetooth_backend.paired_devices()
                if not devices:
                    raise RuntimeError(self.translate("Pair your phone in the OS Bluetooth settings first."))
                selected = prompt({"kind": "select", "devices": [{"uid": d["address"], "name": d["name"]} for d in devices]})
                if not selected:
                    raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
                self.phone.set_bluetooth(peers[0]["device_id"], True, selected)
            elif not self.phone.store.peers:
                self.phone.open_pairing()
            while not self.closed.is_set() and time.monotonic() < deadline:
                try:
                    _event, challenge = self.events.get_nowait()
                except queue.Empty:
                    challenge = None
                if challenge:
                    accepted = prompt({"kind": "confirm", "devices": [{"uid": challenge["device_id"], "name": challenge["display_name"]}],
                                       "code": challenge["code"], "canMarkOwn": True})
                    self.phone.confirm_pairing(challenge["attempt_id"], accepted in ("accept", "accept-own"))
                    if accepted not in ("accept", "accept-own"):
                        raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
                    if accepted == "accept-own":
                        own_id = challenge["device_id"]
                for peer in self.phone.report()["peers"]:
                    stored = self.phone.store.peer(peer["device_id"])
                    if peer.get("state") == "online_" + transport and stored and stored.get("state") == "paired":
                        device_id = peer["device_id"]
                        if own_id == device_id:
                            self.phone.set_personal_sync(device_id, True, auto_wifi=False)
                        self.connected_ids[transport] = device_id
                        return {"transport": transport, "deviceId": device_id, "name": peer["display_name"], "authenticated": True}
                self.closed.wait(.25)
        raise RuntimeError(self.translate("Phone connection cancelled or timed out."))

    def _connect_bluetooth(self, prompt, deadline):
        import socket
        import threading
        import time
        import queue
        from magnolie_telefon import BLUETOOTH_UUID, BLUETOOTH_FALLBACK_SECONDS, receive_frame, send_frame, valid_uuid, unb64
        with self.phone.lock:
            if self.phone.pairing_attempt_active or self.phone.store.peers:
                raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
            self.phone.pairing_until = 0
        backend = self.phone.bluetooth_backend
        if not backend.availability()[0]:
            raise RuntimeError(self.translate("Bluetooth is unavailable. Check the radio and OS permissions."))
        devices = backend.discover_devices(self.closed)
        if not devices:
            raise RuntimeError(self.translate("No phone was found. Open the phone app and try again."))
        selected = prompt({"kind": "select", "devices": [{"uid": d["address"], "name": d["name"]} for d in devices]})
        device = next((d for d in devices if d["address"] == selected), None)
        if not device or self.closed.is_set() or time.monotonic() >= deadline:
            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        try:
            backend.pair_device(device, prompt, self.closed)
        except Exception as error:
            raise RuntimeError(self.translate("Bluetooth system pairing was not confirmed.")) from error
        try:
            sock = backend.connect(selected, BLUETOOTH_UUID, self.closed)
        except Exception as error:
            raise RuntimeError(self.translate("Open the phone connection screen and try again.")) from error
        if self.closed.is_set():
            sock.close()
            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        stopped = threading.Event()
        network_deadline = min(deadline, time.monotonic() + 3)
        offer = None
        def watch():
            while not stopped.wait(.1):
                if self.closed.is_set() or time.monotonic() >= network_deadline:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return
        threading.Thread(target=watch, daemon=True).start()
        try:
            if str(sock.getpeername()[0]).upper() != selected or not backend.paired(selected):
                raise RuntimeError(self.translate("Wrong Bluetooth device."))
            sock.settimeout(3)
            available = receive_frame(sock, 2048)
            protocol = "magnolie-phone-invite/1"
            if (set(available) != {"p", "type", "device_id", "nonce"} or available["p"] != protocol or
                    available["type"] != "bluetooth_available" or not valid_uuid(available["device_id"])):
                raise ValueError("Invalid Bluetooth invitation")
            target, nonce = available["device_id"], available["nonce"]
            unb64(nonce, 16)
            offer = self.phone.open_setup_pairing(target, selected, "bluetooth")
            self._active_pairing_token = offer["token"]
            self._owned_pairing_token = offer["token"]
            send_frame(sock, {"p": protocol, "type": "bluetooth_offer", "target": target, "nonce": nonce, "ttl": 60, **offer})
            def control(kind):
                return {"p": protocol, "type": kind, "nonce": nonce}
            until = min(deadline, time.monotonic() + 60)
            network_deadline = until
            for _ in range(240):
                if self.closed.is_set() or time.monotonic() >= until:
                    raise TimeoutError()
                send_frame(sock, control("wait"))
                sock.settimeout(2)
                reply = receive_frame(sock, 2048)
                if reply == control("accepted"):
                    break
                if reply != control("pending"):
                    raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
                self.closed.wait(.25)
            else:
                raise TimeoutError()
            network_deadline = deadline
            complete = threading.Event()
            def pair():
                try:
                    self.phone._handle(sock, "bluetooth:" + selected, "bluetooth")
                finally:
                    complete.set()
            threading.Thread(target=pair, daemon=True).start()
            configured = own = False
            while not self.closed.is_set() and time.monotonic() < deadline:
                try:
                    _event, challenge = self.events.get_nowait()
                except queue.Empty:
                    challenge = None
                if challenge:
                    if challenge["device_id"] != target:
                        self.phone.confirm_pairing(challenge["attempt_id"], False)
                        continue
                    answer = prompt({"kind": "confirm", "devices": [{"uid": target, "name": challenge["display_name"]}],
                                     "code": challenge["code"], "canMarkOwn": True})
                    self.phone.confirm_pairing(challenge["attempt_id"], answer in ("accept", "accept-own"))
                    if answer not in ("accept", "accept-own"):
                        raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
                    own = answer == "accept-own"
                if complete.is_set() and not configured:
                    peer = self.phone.store.peer(target)
                    if not peer or peer.get("state") not in ("paired", "pair_commit_pending"):
                        raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
                    if peer.get("state") == "paired":
                        self.phone.set_bluetooth(target, True, selected)
                        self.phone.wifi_missing_since[target] = time.monotonic() - BLUETOOTH_FALLBACK_SECONDS
                        configured = True
                    else:
                        self.phone.wifi_missing_since.setdefault(target, time.monotonic() - BLUETOOTH_FALLBACK_SECONDS)
                for peer in self.phone.report()["peers"]:
                    if peer["device_id"] == target and peer.get("state") == "online_bluetooth":
                        if own:
                            self.phone.set_personal_sync(target, True, auto_wifi=False)
                        self.connected_ids["bluetooth"] = target
                        return {"transport": "bluetooth", "deviceId": target, "name": peer["display_name"], "authenticated": True}
                self.closed.wait(.2)
            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        except (ValueError, EOFError, OSError) as error:
            raise RuntimeError(self.translate("Phone connection cancelled or timed out.")) from error
        finally:
            stopped.set()
            if offer is not None:
                self.phone.end_setup_pairing(offer["token"])
                self._active_pairing_token = None
            sock.close()

    def _connect_wifi(self, prompt, deadline):
        import socket
        import time
        import queue
        from magnolie_telefon import discover_setup_phones, send_frame, receive_frame, PORT
        devices = discover_setup_phones()
        if not devices:
            raise RuntimeError(self.translate("No phone was found. Open the phone app and try again."))
        selected = prompt({"kind": "select", "devices": devices})
        device = next((d for d in devices if d["uid"] == selected), None)
        if not device or self.closed.is_set() or time.monotonic() >= deadline:
            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        try:
            offer = self.phone.open_setup_pairing(selected, device["address"])
            self._active_pairing_token = offer["token"]
            self._owned_pairing_token = offer["token"]
        except ValueError as error:
            raise RuntimeError(self.translate("Phone connection cancelled or timed out.")) from error
        own = False
        try:
            with socket.create_connection((device["address"], device["port"]), timeout=3) as invitation:
                send_frame(invitation, {"p": "magnolie-phone-invite/1", "type": "offer", "target": selected,
                    "nonce": device["nonce"], "port": PORT, "ttl": 60, **offer})
                # The invitation socket stays open while the phone asks its user.
                # Closing setup interrupts this wait without taking the phone listener.
                invitation.settimeout(.25)
                import select
                until = min(deadline, time.monotonic() + 60)
                while not self.closed.is_set() and time.monotonic() < until:
                    if select.select([invitation], [], [], .2)[0]:
                        invitation.settimeout(2)
                        response = receive_frame(invitation, 2048)
                        if response != {"p": "magnolie-phone-invite/1", "type": "accepted", "nonce": device["nonce"]}:
                            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
                        break
                else:
                    raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
            while not self.closed.is_set() and time.monotonic() < deadline:
                try:
                    _event, challenge = self.events.get_nowait()
                except queue.Empty:
                    challenge = None
                if challenge:
                    if challenge["device_id"] != selected:
                        self.phone.confirm_pairing(challenge["attempt_id"], False)
                        continue
                    accepted = prompt({"kind": "confirm", "devices": [{"uid": selected, "name": challenge["display_name"]}],
                                       "code": challenge["code"], "canMarkOwn": True})
                    self.phone.confirm_pairing(challenge["attempt_id"], accepted in ("accept", "accept-own"))
                    if accepted not in ("accept", "accept-own"):
                        raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
                    own = accepted == "accept-own"
                for peer in self.phone.report()["peers"]:
                    stored = self.phone.store.peer(selected)
                    if peer["device_id"] == selected and peer.get("state") == "online_wifi" and stored and stored.get("state") == "paired":
                        if own:
                            self.phone.set_personal_sync(selected, True, auto_wifi=False)
                        self.connected_ids["wifi"] = selected
                        return {"transport": "wifi", "deviceId": selected, "name": peer["display_name"], "authenticated": True}
                self.closed.wait(.2)
            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        finally:
            self.phone.end_setup_pairing(offer["token"])
            self._active_pairing_token = None

    def connected(self):
        if self.remote_session is not None:
            return self._remote("phone_setup_status")["connected"]
        result = []
        if self.phone:
            for peer in self.phone.report()["peers"]:
                transport = peer.get("transport")
                stored = self.phone.store.peer(peer["device_id"])
                if stored and stored.get("state") == "paired" and peer.get("state") == "online_" + str(transport) and self.connected_ids.get(transport) == peer["device_id"]:
                    result.append(transport)
        if self.kde and self.connected_ids.get("kdeconnect"):
            status = self.kde.status(timeout=0)
            if getattr(self.kde, 'native', False):
                if any(d['device_id'] == self.connected_ids['kdeconnect'] and d['sms_send'] for d in status['devices']):
                    result.append('kdeconnect')
                return result
            if status.get("available") and status.get("paired_count", 0) > 0 and status.get("device_id") == self.connected_ids["kdeconnect"]:
                result.append("kdeconnect")
        return result

    def commit_startup(self, transports):
        if self.remote_session is not None:
            self._remote("phone_setup_commit", transports=list(transports))
            self._startup_committed = bool(transports)
            return
        return self._commit_startup_local(transports)

    def _commit_startup_local(self, transports, settings_getter=None, settings_setter=None, start_service=True):
        if not isinstance(transports, (list, tuple)) or len(transports) != len(set(transports)) or any(t not in ("wifi", "bluetooth", "kdeconnect") for t in transports):
            raise ValueError("invalid phone startup services")
        if self.closed.is_set():
            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        live = self.connected()
        if any(transport not in live for transport in transports):
            raise RuntimeError(self.translate("The phone is no longer connected."))
        if not transports:
            # Persist connection consent without enabling the daemon or login startup.
            if any(t in ("wifi", "bluetooth") for t in live):
                self.phone.store.save_settings(True)
            return
        import magnolie_hintergrund as background
        import copy
        get = settings_getter or background.read_settings
        put = settings_setter or background.write_settings
        if get is background.read_settings and os.path.exists(background.settings_path()):
            with open(background.settings_path(), encoding="utf-8") as source:
                raw = json.load(source)
            if (not isinstance(raw, dict) or any(key in raw and not isinstance(raw[key], bool) for key in
                    ("enabled", "autostart", "kde_clipboard_enabled", "kde_file_enabled", "kde_choose_directory")) or
                    "permissions" in raw and (not isinstance(raw["permissions"], dict) or any(not isinstance(v, bool) for v in raw["permissions"].values()))):
                raise ValueError(self.translate("The background settings could not be saved."))
        previous = get()
        committed_before = self._startup_committed
        settings = copy.deepcopy(previous)
        settings["enabled"] = settings["autostart"] = True
        settings["phone_setup_services"] = list(transports)
        needs_phone = any(t in ("wifi", "bluetooth") for t in live)
        if any(t in ("wifi", "bluetooth") for t in transports):
            settings["permissions"]["phone_monitor"] = True
        if "kdeconnect" in transports and not getattr(self.kde, 'native', False):
            settings["permissions"]["kde_pairing"] = True
        previous_phone = self.phone.store.settings()["enabled"] if needs_phone else None
        if needs_phone and os.path.exists(self.phone.store.settings_path):
            with open(self.phone.store.settings_path, encoding="utf-8") as source:
                value = json.load(source)
            if not isinstance(value, dict) or set(value) != {"enabled"} or not isinstance(value["enabled"], bool):
                raise ValueError(self.translate("The background settings could not be saved."))
        autostart_before = None
        native_files = get is background.read_settings
        if native_files and os.path.lexists(background.autostart_path()):
            with open(background.autostart_path(), encoding="utf-8") as source:
                autostart_before = source.read(65537)
            if len(autostart_before) > 65536: raise ValueError(self.translate("The background settings could not be saved."))
        try:
            if needs_phone:
                self.phone.store.save_settings(True)
            put(settings)
            if start_service:
                if self.phone and not self.borrowed: self.phone.stop()
                if self.kde and not self.borrowed: self.kde.stop()
                if background.daemon_available():
                    background.ipc_request("set_settings", {"settings": settings})
                elif not background.start_service():
                    raise RuntimeError(self.translate("The background service could not start."))
            self._startup_committed = True
        except Exception as failure:
            self._startup_committed = committed_before
            rollback_errors = []
            try:
                if needs_phone: self.phone.store.save_settings(previous_phone)
            except Exception as error:
                rollback_errors.append(error)
            try:
                put(previous)
            except Exception as error:
                rollback_errors.append(error)
            finally:
                if native_files:
                    try:
                        background.write_settings(previous, update_autostart=False)
                        if autostart_before is not None:
                            background._atomic_text(background.autostart_path(), autostart_before, 0o600)
                        elif os.path.isfile(background.autostart_path()):
                            with open(background.autostart_path(), encoding="utf-8") as source:
                                ours = source.read() == background.autostart_contents()
                            if ours: os.unlink(background.autostart_path())
                    except Exception as error:
                        rollback_errors.append(error)
            if rollback_errors:
                raise RuntimeError(self.translate("The background settings could not be saved.")) from failure
            raise

    def finish_setup(self, write_state, selections):
        transports = list(selections.get("phoneBackgroundServices", []))
        if self.closed.is_set():
            raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        # A failed optional pairing must not block finishing the organizer setup.
        try:
            live = self.connected()
        except (OSError, RuntimeError):
            if transports:
                raise
            write_state("complete", selections)
            return dict(selections, _phoneForeground=False)
        if not transports and not live:
            write_state("complete", selections)
            return dict(selections, _phoneForeground=False)
        if any(t not in live for t in transports):
            raise RuntimeError(self.translate("The phone is no longer connected."))
        if self.closed.is_set(): raise RuntimeError(self.translate("Phone connection cancelled or timed out."))
        write_state("complete", selections)
        try:
            self.commit_startup(transports)
        except Exception:
            write_state("pending")
            raise
        return dict(selections, _phoneForeground=any(t in ("wifi", "bluetooth") for t in live))

    def close(self):
        self.closed.set()
        if self.remote_session is not None:
            for _ in range(3):
                try:
                    if self._remote("phone_setup_cancel").get("released"): break
                except Exception:
                    break
            self.remote_session = None
            return
        if self.phone and self._active_pairing_token:
            self.phone.end_setup_pairing(self._active_pairing_token)
        if self.phone and (not self.borrowed or self._started_phone and not self._startup_committed):
            self.phone.stop()
            if self.borrowed and self._previous_phone_enabled is not None:
                self.phone.enabled = self._previous_phone_enabled
        if self.kde and self._owned_kde_pairing is not None:
            with self.kde._state_lock:
                if self.kde.pairing is self._owned_kde_pairing:
                    self.kde.confirm_pairing(False)
            self._owned_kde_pairing = None
        if self.kde and not self.borrowed:
            self.kde.stop()

    def _remote(self, operation, **arguments):
        from magnolie_hintergrund import ipc_request, IPCError
        request = self.ipc or ipc_request
        if self.remote_session is None:
            try:
                self.remote_session = request("phone_setup_begin", {})["session"]
            except Exception as error:
                if str(error) == "Another phone setup session is active.":
                    raise IPCError(self.translate("Another phone setup session is active.")) from error
                raise RuntimeError(self.translate("Phone setup is unavailable in this background service. Restart the background service and try again.")) from error
        try:
            return request(operation, {"session": self.remote_session, **arguments})
        except IPCError as error:
            message = str(error)
            from magnolie_kdeconnect import NATIVE_KDE_LIMIT, NATIVE_KDE_UNAVAILABLE
            visible = {
                NATIVE_KDE_LIMIT, NATIVE_KDE_UNAVAILABLE,
                "Another phone setup session is active.",
                "The phone setup session expired. Reopen phone setup and try again.",
                "The phone setup session belongs to another client.",
                "The phone setup request is no longer current.",
                "The phone is no longer connected.",
                "The background settings could not be saved.",
                "The background service could not start.",
            }
            raise IPCError(self.translate(message if message in visible else "Phone connection failed.")) from error

    def restore_borrowed_state(self):
        if not self._restore_pairing_window or not self.phone or self._started_phone:
            return
        from magnolie_telefon import b64
        import time
        with self.phone.lock:
            scope = getattr(self.phone, "setup_pairing", None)
            ours = (scope and b64(scope["token"]) == self._owned_pairing_token) or (
                self._owned_pairing_token is None and self.phone.pairing_token == self._initial_pairing_token and self.phone.pairing_until <= time.monotonic())
            if ours and self.phone.server and self.phone.enabled and not self.phone.store.peers and not self.phone.pairing_attempt_active:
                self.phone.open_pairing()
            self._restore_pairing_window = False

    def owns_pairing_event(self, payload):
        if not self.phone or not self._active_pairing_token:
            return False
        from magnolie_telefon import b64
        scope = getattr(self.phone, "setup_pairing", None)
        return bool(scope and b64(scope["token"]) == self._active_pairing_token and
                    payload.get("device_id") == scope["target"] and payload.get("attempt_id") in self.phone.pairings)


class PhoneSetupSessions:
    """One bounded GUI setup lease on daemon-owned transports, not a trust store."""
    def __init__(self, phone_getter, kde_getter, root, display_name, startup=None, clock=None):
        import threading
        import time
        self.phone_getter, self.kde_getter = phone_getter, kde_getter
        self.root, self.display_name, self.startup = root, display_name, startup
        self.clock = clock or time.monotonic
        self.lock = threading.RLock()
        self.current = None

    @staticmethod
    def _owner_handle(owner):
        try:
            uid, pid = owner
            if not hasattr(os, "pidfd_open") or os.stat("/proc/%d" % pid).st_uid != uid:
                return None
            return os.pidfd_open(pid)
        except (OSError, TypeError, ValueError):
            return None

    @staticmethod
    def _owner_exited(entry):
        import select
        descriptor = entry.get("owner_fd")
        if descriptor is None:
            return False
        poller = select.poll()
        poller.register(descriptor, select.POLLIN)
        return any(events & select.POLLIN for _fd, events in poller.poll(0))

    def _check(self, owner, token):
        import hmac
        entry = self.current
        if entry and (self.clock() >= entry["expires"] or self._owner_exited(entry)):
            self._cancel_locked(entry)
            entry = None
        if not entry or entry["state"] == "closing" or not isinstance(token, str) or not hmac.compare_digest(entry["token"], token):
            raise RuntimeError("The phone setup session expired. Reopen phone setup and try again.")
        if entry["owner"] != owner:
            raise RuntimeError("The phone setup session belongs to another client.")
        return entry

    def begin(self, owner):
        import threading
        with self.lock:
            if self.current and (self.clock() >= self.current["expires"] or self._owner_exited(self.current)):
                self._cancel_locked(self.current)
            release = self.current.get("release") if self.current and self.current["state"] == "closing" else None
        # Let a cancelled/dead client's cleanup finish without holding its lock.
        # A still-running worker retains the lease and cannot be taken over.
        if release is not None:
            release.join(1)
        with self.lock:
            if self.current:
                if self.current["owner"] != owner or self.current["state"] == "closing":
                    raise RuntimeError("Another phone setup session is active.")
                return {"session": self.current["token"], "ttl": max(0, int(self.current["expires"] - self.clock()))}
            adapter = SetupPhoneServices(self.root, self.display_name, borrowed=True)
            token = os.urandom(32).hex()
            entry = {"token": token, "owner": owner, "expires": self.clock() + 600,
                     "adapter": adapter, "state": "idle", "prompt": None, "result": None,
                      "worker": None, "target": "", "transport": "", "error": "", "timer": None}
            entry["owner_fd"] = self._owner_handle(owner)
            self.current = entry
            timer = threading.Timer(600, self.expire, args=(token,))
            timer.daemon = True
            entry["timer"] = timer
            timer.start()
            return {"session": token, "ttl": 600}

    def expire(self, token):
        with self.lock:
            if self.current and self.current["token"] == token:
                self._cancel_locked(self.current)

    def _cancel_locked(self, entry):
        import threading
        if entry["state"] == "closing": return
        entry["state"] = "closing"
        entry["timer"].cancel()
        entry["adapter"].closed.set()
        request = entry["prompt"]
        if request:
            request["answer"] = None
            request["event"].set()
            entry["prompt"] = None
        def release():
            try:
                entry["adapter"].close()
                worker = entry["worker"]
                if worker is not None: worker.join(130)
                if worker is None or not worker.is_alive():
                    entry["adapter"].close()
                    entry["adapter"].restore_borrowed_state()
                with self.lock:
                    if self.current is entry and (worker is None or not worker.is_alive()):
                        self.current = None
                        descriptor = entry.pop("owner_fd", None)
                        if descriptor is not None:
                            os.close(descriptor)
            except Exception:
                pass  # Keep the lease closing rather than risk a duplicate owner.
        entry["release"] = threading.Thread(target=release, name="magnolie-phone-setup-close", daemon=True)
        entry["release"].start()

    def close(self):
        with self.lock:
            if self.current: self._cancel_locked(self.current)

    def wait_closed(self, timeout=5):
        with self.lock:
            release = self.current.get("release") if self.current else None
        if release is not None: release.join(timeout)
        return release is None or not release.is_alive()

    @property
    def phone_lease(self):
        with self.lock:
            return bool(self.current and self.current["adapter"]._started_phone and not self.current["adapter"].closed.is_set())

    def adopt_phone_owner(self):
        with self.lock:
            if self.current: self.current["adapter"]._startup_committed = True

    @property
    def connecting_transport(self):
        with self.lock:
            return self.current["transport"] if self.current and self.current["state"] in ("connecting", "closing") else ""

    def kde_event(self, event, payload):
        if event != "pairing": return False
        with self.lock:
            entry = self.current
            if not entry or entry["transport"] != "kdeconnect": return False
            adapter = entry["adapter"]
            pending = getattr(adapter.kde, "pairing", None)
            return bool(pending and pending.get("direction") == "outgoing" and
                        pending.get("identity", {}).get("deviceId") == adapter._kde_selected)

    def phone_event(self, event, payload):
        if event != "pairing_code": return False
        with self.lock:
            entry = self.current
            if entry and entry["adapter"].owns_pairing_event(payload):
                if entry["adapter"].closed.is_set() or self.clock() >= entry["expires"]:
                    entry["adapter"].phone.confirm_pairing(payload["attempt_id"], False)
                else:
                    entry["adapter"].events.put((event, payload))
                return True
        return False

    def operation(self, owner, operation, args):
        import copy
        import threading
        with self.lock:
            if operation == "phone_setup_cancel" and self.current and \
                    self.current["owner"] == owner and self.current["token"] == args["session"]:
                self._cancel_locked(self.current)
                return {"cancelled": True}
            entry = self._check(owner, args["session"])
            adapter = entry["adapter"]
            if operation == "phone_setup_cancel":
                self._cancel_locked(entry)
                return {"cancelled": True}
            if operation == "phone_setup_connect":
                if entry["state"] == "connecting": raise RuntimeError("Another phone setup session is active.")
                transport = args["transport"]
                if transport in ("wifi", "bluetooth"):
                    adapter.phone = self.phone_getter(True)
                    if adapter.phone is None: raise RuntimeError("This phone transport is unavailable.")
                    if adapter.phone.pairing_attempt_active or adapter.phone.pairings:
                        raise RuntimeError("Another phone setup session is active.")
                else:
                    adapter.kde = self.kde_getter()
                    if adapter.kde is None: raise RuntimeError("This phone transport is unavailable.")
                    if adapter.kde.pairing is not None: raise RuntimeError("Another phone setup session is active.")
                entry.update(state="connecting", transport=transport, target="", identity="", result=None, error="", operation_expires=self.clock() + 120)
                def prompt(value):
                    devices = value.get("devices", [])
                    if value.get("kind") not in ("select", "confirm") or not 1 <= len(devices) <= 32:
                        raise RuntimeError("The selected phone changed. Try again.")
                    clean = {"id": os.urandom(16).hex(), "kind": value["kind"],
                        "devices": [{"uid": str(d["uid"]), "name": str(d["name"])[:120]} for d in devices],
                        "code": str(value.get("code", ""))[:256], "canMarkOwn": value.get("canMarkOwn") is True}
                    if any(not 1 <= len(d["uid"]) <= 256 for d in clean["devices"]):
                        raise RuntimeError("The selected phone changed. Try again.")
                    request = {"value": clean, "answer": None, "event": threading.Event(), "expires": min(entry["expires"], entry["operation_expires"])}
                    with self.lock:
                        self._check(owner, entry["token"])
                        if adapter.closed.is_set(): raise RuntimeError("Phone connection cancelled or timed out.")
                        if clean["kind"] == "confirm" and (clean["canMarkOwn"] or transport == "kdeconnect"):
                            if len(clean["devices"]) != 1: raise RuntimeError("The selected phone changed. Try again.")
                            entry["identity"] = clean["devices"][0]["uid"]
                        entry["prompt"] = request
                    while not request["event"].wait(.1):
                        if adapter.closed.is_set() or self.clock() >= request["expires"]:
                            return None
                    return request["answer"]
                def connect():
                    try:
                        result = adapter.connect(transport, prompt)
                        if result.get("authenticated") is not True or transport not in adapter.connected():
                            raise RuntimeError("The phone is no longer connected.")
                        if adapter.connected_ids.get(transport) != result.get("deviceId") or entry["identity"] and entry["identity"] != result["deviceId"] or \
                                transport != "bluetooth" and entry["target"] and entry["target"] != result["deviceId"]:
                            raise RuntimeError("The selected phone changed. Try again.")
                        with self.lock:
                            if self.current is entry and not adapter.closed.is_set():
                                entry.update(state="connected", result=result, target=result["deviceId"])
                    except Exception as error:
                        with self.lock:
                            if self.current is entry and entry["state"] != "closing":
                                entry.update(state="failed", error=str(error)[:300], prompt=None)
                entry["worker"] = threading.Thread(target=connect, name="magnolie-phone-setup", daemon=True)
                entry["worker"].start()
                return {"started": True}
            if operation == "phone_setup_confirm":
                request = entry["prompt"]
                if not request or request["value"]["id"] != args["prompt"] or self.clock() >= request["expires"]:
                    raise RuntimeError("The phone setup request is no longer current.")
                value, answer = request["value"], args["answer"]
                allowed = ([d["uid"] for d in value["devices"]] if value["kind"] == "select" else
                           ["accept", "accept-own"] if value["canMarkOwn"] else ["accept"])
                if answer is not None and answer not in allowed:
                    raise RuntimeError("The phone setup request is no longer current.")
                if value["kind"] == "select" and answer is not None: entry["target"] = answer
                request["answer"] = answer
                entry["prompt"] = None
                request["event"].set()
                return {"answered": True}
            if operation == "phone_setup_commit":
                if entry["state"] == "connecting": raise RuntimeError("Another phone setup session is active.")
                if self.startup is None: raise RuntimeError("The background settings could not be saved.")
                self.startup(adapter, args["transports"])
                return {"committed": True}
            if operation not in ("phone_setup_status", "phone_setup_list"):
                raise RuntimeError("The phone setup request is no longer current.")
            snapshot = {"state": entry["state"], "prompt": copy.deepcopy(entry["prompt"]["value"]) if entry["prompt"] else None,
                        "result": copy.deepcopy(entry["result"]), "target": entry["target"], "error": entry["error"]}
        live = adapter.connected()
        with self.lock:
            self._check(owner, args["session"])
        snapshot["connected"] = live
        if operation == "phone_setup_list": snapshot["capabilities"] = adapter.capabilities()
        return snapshot
