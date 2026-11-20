"""GTK/Xvfb component checks. Frames here are test pixels, not phone capture."""

import ast
import base64
import hmac
import json
import socket
import struct
import sys
import threading
import uuid
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

pytest.importorskip("gi")
pytest.importorskip("cairo")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_phone_screen_window import Gdk, GdkPixbuf, GLib, Gtk, PhoneScreenJpegReceiver, PhoneScreenSessionLock, PhoneScreenWindow
from magnolie_phone_screen_transport import PhoneScreenReceiveRun
from magnolie_phone_screen_control import REQUEST
from magnolie_telefon import PROTOCOL, PhoneService, SecureChannel, b64, canonical, now_ms, receive_frame, send_frame, strict_json


@pytest.fixture(autouse=True)
def display():
    if not Gtk.init_check()[0]:
        pytest.skip("GTK display required (run with xvfb-run)")


def wait_for(condition):
    context = GLib.MainContext.default()
    deadline = monotonic() + 3
    while monotonic() < deadline:
        while context.pending() and monotonic() < deadline:
            context.iteration(False)
        if condition():
            return
        sleep(.005)
    assert condition(), "GTK condition timed out"


def pixel(widget, x, y):
    pixbuf = Gdk.pixbuf_get_from_window(widget.get_window(), x, y, 1, 1)
    return tuple(pixbuf.get_pixels()[:3]) if pixbuf else None


def test_independent_window_letterbox_latest_frames_and_show_again():
    stops = []
    main = Gtk.Window(title="Test Organizer")
    view = PhoneScreenWindow("Test phone view", is_current=lambda: True,
                             request_stop=lambda: stops.append("original"))
    window = view._window
    try:
        main.show_all()
        assert not window.get_visible()
        assert window.get_transient_for() is None and view.show()
        assert view.offer_rgb(4, 3, b"\xff\x00\x00" * 12)
        assert view.offer_rgb(4, 3, b"\x00\xff\x00" * 12)
        wait_for(lambda: pixel(window, 240, 320) == (0, 255, 0))
        assert pixel(window, 240, 16) == (0, 0, 0)

        main.hide()  # Same visibility change as hide-to-tray, not shutdown.
        assert not main.get_visible() and window.get_visible()
        # New aspect (already oriented by the sender/decoder) and new pixels.
        assert view.offer_rgb(2, 5, b"\x00\x00\xff" * 10)
        wait_for(lambda: pixel(window, 240, 16) == (0, 0, 255))
        assert pixel(window, 16, 320) == (0, 0, 0)
        window.hide()
        assert view.show() and view._window is window
        assert window.get_visible() and stops == []
        window.close()
        wait_for(lambda: stops == ["original"])
        assert not view.show() and not window.get_visible()
    finally:
        view.stop()
        main.destroy()


@pytest.mark.parametrize("reason", ["disconnect", "revocation", "lock", "exit"])
def test_terminal_stop_rejects_late_frames_and_never_reopens(reason):
    active = True
    stops = []
    view = PhoneScreenWindow("Test phone view", is_current=lambda: active,
                             request_stop=lambda: stops.append("original"))
    window = view._window
    try:
        assert view.show()
        assert view.offer_rgb(1, 1, b"rgb")
        if reason in ("lock", "exit"):
            view.stop()
        else:
            active = False
        wait_for(lambda: stops == ["original"])
        late = []
        worker = Thread(target=lambda: late.append(view.offer_rgb(1, 1, b"rgb")))
        worker.start()
        worker.join(1)
        assert late == [False] and not window.get_visible()
        assert view._picture is None and view._pending is None and view._timer == 0
        active = True
        assert not view.show() and stops == ["original"]
    finally:
        view.stop()


def test_invalid_frame_and_failed_stop_do_not_revive_the_window():
    requested = []
    failure = OSError("controlled failure requesting capture stop")

    def stop_owner():
        requested.append("original")
        view.stop()  # Reentrant stop must not recurse or signal twice.
        raise failure

    view = PhoneScreenWindow("Test phone view", is_current=lambda: True, request_stop=stop_owner)
    try:
        for width, height, pixels in ((0, 1, b""), (1, 4097, b""), (4096, 4096, b""),
                                      (True, 1, b"rgb"), (1, 1, b"ab"), (1, 1, bytearray(b"rgb"))):
            assert not view.offer_rgb(width, height, pixels)
        view.stop()
        assert requested == ["original"] and view.stop_error is failure
        assert not view.show()
    finally:
        view.stop()


def organizer_hooks():
    # Execute the exact Fenster methods without loading a profile, bridge,
    # phone or desktop service. The menu items and view are actual GTK widgets.
    source = Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer"
    code = ast.parse(source.read_text())
    window = next(node for node in code.body if isinstance(node, ast.ClassDef) and node.name == "Fenster")
    names = {"_phone_screen_begin_original", "_phone_screen_attach", "_phone_screen_stop", "_phone_screen_drained", "_phone_screen_ui",
             "_tray_telefone_aktualisieren", "_beenden_endgueltig"}
    hooks = ast.Module(body=[node for node in window.body if isinstance(node, ast.FunctionDef) and node.name in names],
                       type_ignores=[])
    namespace = {"Gtk": Gtk, "GLib": GLib, "PhoneService": PhoneService, "threading": threading, "_": lambda text: text}
    exec(compile(hooks, str(source), "exec"), namespace)
    return type("OrganizerHooks", (Gtk.Window,), {name: namespace[name] for name in names})()


def test_advanced_entry_requires_native_confirmation_and_same_original_probe():
    from types import SimpleNamespace

    app = organizer_hooks()
    app._gesperrt = app._beenden_angefragt = app._wirklich_beenden = False
    phone = PhoneService.__new__(PhoneService)
    phone.store = SimpleNamespace(peers=[dict(device_id="test", state="paired", display_name="Test Notes")])
    token = [object()]
    phone.native_screen_candidate = lambda _peer: token[0]
    phone.native_screen_available = lambda _peer: True
    calls, responses = [], []

    def begin(peer, width, height, density, _start, *, expected):
        if expected is not token[0]:
            raise PermissionError("old probe")
        calls.append((peer, width, height, density))

    phone.begin_native_screen = begin
    app._telefon = phone
    desktop = PhoneScreenSessionLock()
    app._phone_screen_session_lock = desktop
    app.antwort = lambda handler, reply: responses.append((handler, reply))
    command = dict(cmd="telefon_screen_start", requestId="sample", peer="test")
    app.show()
    try:
        phone.native_screen_included = False
        app._phone_screen_ui(command)
        assert not getattr(app, "_phone_screen_question", None)
        assert responses[-1][1]["ok"] is False and calls == []
        phone.native_screen_included = True
        app._phone_screen_ui(command)
        assert calls == [] and not getattr(app, "_phone_screen_question", None)
        desktop._lease = object()
        app._phone_screen_ui(command)
        assert calls == [] and app._phone_screen_question.get_visible()
        app._phone_screen_question.response(Gtk.ResponseType.CANCEL)
        assert calls == [] and app._phone_screen_question is None
        app._phone_screen_ui(command)
        token[0] = object()
        app._phone_screen_question.response(Gtk.ResponseType.OK)
        assert calls == [] and responses[-1][1]["ok"] is False
        app._phone_screen_ui(command)
        desktop._lease = object()  # A lock/unlock while confirmation was visible.
        app._phone_screen_question.response(Gtk.ResponseType.OK)
        assert calls == [] and responses[-1][1]["ok"] is False
        app._phone_screen_ui(command)
        app._phone_screen_question.response(Gtk.ResponseType.OK)
        assert calls == [("test", 720, 1280, 160)] and responses[-1][1]["ok"] is True
    finally:
        desktop.close()
        app.destroy()


def test_desktop_lock_and_session_loss_permanently_revoke_the_exact_view():
    from types import SimpleNamespace

    monitor = PhoneScreenSessionLock()
    props = {"LockedHint": GLib.Variant("b", False), "Active": GLib.Variant("b", True)}
    owner = [":1.9"]
    proxy = SimpleNamespace(get_name_owner=lambda: owner[0], get_cached_property=props.get)
    monitor._proxy = proxy
    monitor._update(proxy)
    original = monitor.claim()

    def is_current():
        original()
        return True

    stops = []
    view = PhoneScreenWindow("Phone screen", is_current=is_current, request_stop=lambda: stops.append(True))
    try:
        assert view.show()
        monitor._signal(proxy, owner[0], "Lock", None)
        monitor._properties(proxy, GLib.Variant("a{sv}", {}), [])
        assert not monitor.available  # An unrelated update cannot undo Lock.
        wait_for(lambda: stops == [True])
        monitor._signal(proxy, owner[0], "Unlock", None)
        unlocked = monitor.claim()
        unlocked()
        with pytest.raises(PermissionError):
            original()
        assert not view.show()
        props.pop("Active")
        monitor._properties(proxy, GLib.Variant("a{sv}", {}), ["Active"])
        with pytest.raises(PermissionError):
            unlocked()
        assert not monitor.available
        owner[0] = None
        monitor._owner_changed(proxy)
        assert not monitor.available
    finally:
        monitor._proxy = None
        monitor.close()
        view.stop()


def test_actual_organizer_menu_and_exit_use_exact_window_and_wait_for_join():
    app = organizer_hooks()
    app._gesperrt = app._wirklich_beenden = app._beenden_angefragt = False
    app._telefon = None
    app._tray_telefone = Gtk.MenuItem(label="Phones")
    requested = []
    current = True

    def attach():
        return app._phone_screen_attach(is_current=lambda: current, request_stop=requested.append)

    def actions():
        return {child.get_label(): child for child in app._tray_telefone.get_submenu().get_children()}

    first = attach()
    second = None
    try:
        assert set(actions()) == {"Show phone screen", "Stop screen mirroring"}
        assert app._tray_telefone.get_visible()
        first._window.hide()
        actions()["Show phone screen"].activate()
        assert first._window.get_visible()
        old_menu = app._tray_telefone.get_submenu()
        stale_stop = actions()["Stop screen mirroring"]
        stale_stop.activate()
        assert requested == [first] and not first.available
        assert app._beenden_endgueltig() is True and not app._wirklich_beenden
        with pytest.raises(PermissionError):
            attach()
        wait_for(lambda: not actions() and not app._tray_telefone.get_visible())

        app._phone_screen_drained(first)
        second = attach()
        app._phone_screen_drained(first)
        stale_stop.activate()
        assert old_menu is not app._tray_telefone.get_submenu()
        assert second.available and requested == [first]
        app._gesperrt = True
        wait_for(lambda: requested == [first, second])
        assert not second.available
        app._phone_screen_drained(second)
        with pytest.raises(PermissionError):
            attach()
    finally:
        app._phone_screen_stop()
        app._tray_telefone.destroy()


def test_viewer_source_is_in_linux_package_recipes():
    root = Path(__file__).resolve().parents[1]
    for name in ("debian/install", "rpm/magnolie-organizer.spec", "werkzeuge/appimage_bauen.sh"):
        assert "magnolie_phone_screen_window.py" in (root / name).read_text(), name
    flatpak = json.loads((root / "flatpak/io.gitlab.maik3531.MagnolieOrganizer.json").read_text())
    assert any("magnolie_phone_screen_window.py" in command for module in flatpak["modules"] if isinstance(module, dict)
               for command in module.get("build-commands", []))


def jpeg_fixture(width, height, color=0xf82023ff):
    picture = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    picture.fill(color)
    ok, data = picture.save_to_bufferv("jpeg", ["quality"], ["80"])
    assert ok
    return bytes(data)


def test_native_jpeg_decoder_worker_publishes_only_packed_rgb_to_window():
    current = True
    view = PhoneScreenWindow("Test phone view", is_current=lambda: current, request_stop=lambda: None)
    received = []

    def publish(width, height, pixels):
        received.append((width, height, len(pixels)))
        return view.offer_rgb(width, height, pixels)

    receiver = PhoneScreenJpegReceiver(17, 16, is_current=lambda: current, offer_rgb=publish)
    data = jpeg_fixture(17, 16)
    result = []
    worker = Thread(target=lambda: result.append(receiver.receive(data)))
    try:
        assert view.show()
        worker.start()
        worker.join(2)
        assert not worker.is_alive() and result == [True]
        assert received == [(17, 16, 17 * 16 * 3)]

        def visible_red():
            rgb = pixel(view._window, 240, 320)
            return rgb is not None and rgb[0] > 230 and rgb[1] < 60 and rgb[2] < 60

        wait_for(visible_red)
    finally:
        view.stop()


def test_jpeg_header_bounds_and_guard_loss_cannot_publish():
    data = jpeg_fixture(16, 16)
    offered = []
    decoder = PhoneScreenJpegReceiver(16, 16, is_current=lambda: True,
                                      offer_rgb=lambda *args: offered.append(args))
    for invalid in (jpeg_fixture(17, 16), data[:-2], data + b"\xff\xd9" + b"x" * decoder.MAX_BYTES,
                    data.replace(b"\xff\xc0", b"\xff\xc2", 1), b"\xff\xd8" + b"\xff" * 16 + b"\xff\xd9"):
        with pytest.raises(ValueError):
            decoder.receive(invalid)
    checks = iter([True, False])
    decoder = PhoneScreenJpegReceiver(16, 16, is_current=lambda: next(checks),
                                      offer_rgb=lambda *args: offered.append(args))
    with pytest.raises(PermissionError):
        decoder.receive(data)
    assert offered == []


def test_owned_receive_run_requires_proof_and_live_send_to_display():
    a, b = socket.socketpair()
    b.settimeout(1)
    current = True
    sent = []
    session, key = bytes(range(16)), bytes(range(32))
    context = b"magnolie-phone-screen-view/1\0phone_to_desktop\0" + session + struct.pack("!HH", 17, 16)
    view = PhoneScreenWindow("Phone screen", is_current=lambda: current, request_stop=lambda: None)
    published = []

    def live():
        if not current:
            raise PermissionError("original lost")

    def require_sent():
        if sent != [True]:
            raise PermissionError("SEND missing")

    def offer(*args):
        published.append(True)
        return view.offer_rgb(*args)

    run = PhoneScreenReceiveRun(a, session, key, 17, 16, require_original=live,
                               authorize_send=lambda: sent.append(True), require_send=require_sent, offer_rgb=offer)
    try:
        assert view.show()
        run.start()
        challenge = b.recv(16, socket.MSG_WAITALL)
        assert len(challenge) == 16 and sent == [] and published == []
        b.sendall(hmac.digest(key, b"magnolie-phone-screen-proof/1\0" + context + challenge, "sha256"))
        wait_for(lambda: sent == [True])
        material = HKDF(algorithm=hashes.SHA256(), length=36, salt=session, info=context).derive(key)

        def send_frame(ordinal):
            jpeg = jpeg_fixture(17, 16)
            header = struct.pack("!IQ", len(jpeg) + 16, ordinal)
            b.sendall(header + AESGCM(material[:32]).encrypt(material[32:] + header[4:], jpeg, context + header))

        send_frame(0)
        wait_for(lambda: published == [True] and (pixel(view._window, 240, 320) or (0, 0, 0))[0] > 230)
        current = False
        wait_for(run.is_drained)
        assert isinstance(run.failure, PermissionError)
        assert a.fileno() == -1 and published == [True]
        with pytest.raises(RuntimeError):
            run.start()
    finally:
        run.stop()
        b.close()
        view.stop()


def test_invalid_proof_or_stop_before_proof_never_authorizes_send():
    for stop in (False, True):
        a, b = socket.socketpair()
        sent = []
        run = PhoneScreenReceiveRun(a, bytes(16), bytes(32), 17, 16, require_original=lambda: None,
                                   authorize_send=lambda: sent.append(True), require_send=lambda: None,
                                   offer_rgb=lambda *args: pytest.fail("no media expected"))
        try:
            b.settimeout(1)
            run.start()
            assert len(b.recv(16, socket.MSG_WAITALL)) == 16
            if stop:
                run.stop()
            else:
                b.sendall(bytes(32))
            wait_for(run.is_drained)
            assert a.fileno() == -1 and sent == []
            assert run.failure is None if stop else isinstance(run.failure, PermissionError)
        finally:
            run.stop()
            b.close()


def test_entire_desktop_owner_with_encrypted_control_socket_until_original_stop():
    sid, tx, rx = bytes(16), bytes(range(32)), bytes(reversed(range(32)))
    ptx, prx = b"\x04" * 4, b"\x05" * 4
    probe = {"version": 26, "request_id": str(uuid.uuid4()), "nonce": "b" * 64, "op": "probe"}
    with socket.socket() as control_listener:
        control_listener.bind(("127.0.0.1", 0))
        control_listener.listen(1)
        with socket.create_connection(control_listener.getsockname(), timeout=1) as phone:
            desktop, _ = control_listener.accept()
            with desktop:
                desktop.settimeout(.3)
                parent = SecureChannel(desktop, sid, tx, ptx, rx, prx)
                app = organizer_hooks()
                app._gesperrt = app._wirklich_beenden = app._beenden_angefragt = False
                app._telefon = None
                app._tray_telefone = Gtk.MenuItem(label="Phones")
                run = None

                def read_control(sequence):
                    frame = receive_frame(phone, 8192)
                    header = {key: value for key, value in frame.items() if key != "ciphertext"}
                    assert header["seq"] == sequence and header["dir"] == "desktop_to_phone"
                    return strict_json(AESGCM(tx).decrypt(ptx + sequence.to_bytes(8, "big"),
                                       base64.b64decode(frame["ciphertext"]), canonical(header)))["body"]

                def write_control(sequence, body):
                    now = now_ms()
                    envelope = dict(type="message", v=1, message_id=str(uuid.uuid4()), kind=REQUEST,
                                    created_ms=now, expires_ms=now + 60_000, body=body)
                    header = dict(p=PROTOCOL, sid=b64(sid), seq=sequence, dir="phone_to_desktop")
                    data = AESGCM(rx).encrypt(prx + sequence.to_bytes(8, "big"), canonical(envelope), canonical(header))
                    send_frame(phone, dict(header, ciphertext=b64(data)))
                    assert run.receive(parent, parent.receive())

                try:
                    assert parent.send_seq == 0
                    run = app._phone_screen_begin_original(parent, probe, 17, 16, 160, require_original=lambda: None)
                    view = app._phone_screen_window
                    assert view._window.get_visible()
                    offer = read_control(0)
                    assert offer["op"] == "offer"
                    session, key = bytes.fromhex(offer["session"]), bytes.fromhex(offer["secret"])
                    context = b"magnolie-phone-screen-view/1\0phone_to_desktop\0" + session + struct.pack("!HH", 17, 16)
                    body = dict(probe, op="prepared", session=offer["session"])
                    with socket.create_connection(("127.0.0.1", offer["port"]), timeout=1) as data:
                        data.settimeout(.1)
                        with pytest.raises(socket.timeout):
                            data.recv(1)  # No proof traffic before PREPARED from the original control reader.
                        data.settimeout(1)
                        write_control(0, body)
                        with data.makefile("rb") as challenge:
                            value = challenge.read(16)
                        assert len(value) == 16
                        data.sendall(hmac.digest(key, b"magnolie-phone-screen-proof/1\0" + context + value, "sha256"))
                        assert read_control(1) == dict(body, op="send")
                        material = HKDF(algorithm=hashes.SHA256(), length=36, salt=session, info=context).derive(key)
                        jpeg = jpeg_fixture(17, 16)
                        header = struct.pack("!IQ", len(jpeg) + 16, 0)
                        data.sendall(header + AESGCM(material[:32]).encrypt(material[32:] + header[4:], jpeg, context + header))
                        wait_for(lambda: (pixel(view._window, 240, 320) or (0, 0, 0))[0] > 230)
                        for ordinal in (1, 2, 3):
                            sleep(.75)
                            header = struct.pack("!IQ", 16, ordinal)
                            data.sendall(header + AESGCM(material[:32]).encrypt(material[32:] + header[4:], b"", context + header))
                        assert not run.retired and run.failure is None
                        assert (pixel(view._window, 240, 320) or (0, 0, 0))[0] > 230
                        write_control(1, dict(body, op="stop"))
                        wait_for(lambda: run.is_drained() and app._phone_screen_window is None)
                        assert data.recv(1) == b"" and desktop.fileno() != -1 and run.failure is None
                        assert not app._tray_telefone.get_visible()
                        assert parent.send_seq == 2  # No STOP echo to an original peer that already stopped.
                finally:
                    if run is not None:
                        run.stop()
                    app._phone_screen_stop()
                    app._tray_telefone.destroy()
