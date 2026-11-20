import os
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_phone_screen_control import PhoneScreenDesktopDispatch, REQUEST
from magnolie_phone_screen_local import PhoneScreenLocalAttach, PhoneScreenLocalLane, PhoneScreenPeerLifetime, begin_daemon_screen, local_peer, request_daemon_screen
from magnolie_hintergrund import IPCServer, ipc_request
from magnolie_telefon import PhoneService, SecureChannel, now_ms, receive_frame


def lane(sock, writing, guard=lambda: None):
    return PhoneScreenLocalLane(sock, expected_peer=(os.getpid(), os.getuid()), require_original=guard, writing=writing)


def test_no_daemon_screen_discovery_or_admission_without_kernel_peer_lifetime(tmp_path, monkeypatch):
    import magnolie_phone_screen_local as local

    monkeypatch.setattr(local, 'peer_pidfd_available', lambda: False)
    phone = SimpleNamespace(native_screen_included=True, report=lambda: {'peers': []})
    filename = str(tmp_path / 'runtime' / 'control.sock')
    daemon = IPCServer(None, filename, phone_backend=phone)
    daemon._native_screen_view_checked = True
    daemon.start()
    try:
        assert not daemon._native_screen_supported()
        assert ipc_request('phone_report', path=filename) == {'peers': []}
        with pytest.raises((OSError, EOFError)):
            request_daemon_screen(filename, str(uuid.uuid4()), require_gui=lambda: None,
                                  confirm=lambda _: pytest.fail('unavailable daemon requested approval'), attach=None)
        assert ipc_request('ping', path=filename)['running']
    finally:
        daemon.close()


def test_process_identity_is_from_the_connected_kernel_peer(tmp_path):
    # Real second PID, same UID: a correct UID alone must not be enough.
    filename = str(tmp_path / 'view.sock')
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(filename)
        listener.listen(1)
        listener.settimeout(2)
        child = subprocess.Popen([sys.executable, '-c', 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.recv(1)', filename])
        try:
            accepted, _ = listener.accept()
            with accepted:
                assert local_peer(accepted) == (child.pid, os.getuid())
                with pytest.raises(PermissionError):
                    lane(accepted, True)
                assert accepted.fileno() == -1
            assert child.wait(2) == 0
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(2)


def test_process_exit_revokes_peer_even_while_a_duplicate_holds_the_socket(tmp_path):
    filename = str(tmp_path / 'lifetime.sock')
    program = '''
import os, socket, sys
sock = socket.socket(socket.AF_UNIX)
sock.connect(sys.argv[1])
if os.fork() == 0:
    # Keep the socket open until the test closes this original stream.
    sock.recv(1)
    os._exit(0)
sys.stdin.buffer.read(1)
'''
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(filename)
        listener.listen(1)
        listener.settimeout(2)
        with subprocess.Popen([sys.executable, '-c', program, filename], stdin=subprocess.PIPE) as original:
            connection, _ = listener.accept()
            with connection:
                lifetime = PhoneScreenPeerLifetime(connection, expected_peer=(original.pid, os.getuid()))
                try:
                    lifetime.require_current()
                    original.stdin.close()
                    assert original.wait(2) == 0
                    connection.settimeout(.1)
                    with pytest.raises(socket.timeout):
                        connection.recv(1)  # Inherited descriptor remains open.
                    with pytest.raises(PermissionError, match='peer_process_ended'):
                        lifetime.require_current()
                finally:
                    lifetime.close()
                    original.stdin.close()


def test_dedicated_lane_carries_only_records_and_finish_is_terminal():
    a, b = socket.socketpair()
    with a, b:
        writer, reader = lane(a, True), lane(b, False)
        writer.write(b'', require_current=lambda: None)
        writer.write(b'fixture', require_current=lambda: None)
        assert reader.read() == b'' and reader.read() == b'fixture'
        reader.close()
        with pytest.raises(OSError):
            writer.write(b'late', require_current=lambda: None)
        assert a.fileno() == -1


@pytest.mark.parametrize('raw', [struct.pack('!I', 1_048_577), struct.pack('!I', 10) + b'cut'])
def test_reader_rejects_invalid_or_partial_records(raw):
    a, b = socket.socketpair()
    with a, b:
        reader = lane(a, False)
        b.sendall(raw)
        b.shutdown(socket.SHUT_WR)
        with pytest.raises((ValueError, EOFError)):
            reader.read()
        assert a.fileno() == -1


def test_revocation_during_backpressure_cannot_publish_a_complete_late_record():
    a, b = socket.socketpair()
    with a, b:
        a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        writer = lane(a, True)
        withdrawn = threading.Event()
        sent = []

        def current():
            if withdrawn.is_set():
                raise PermissionError('exact SEND withdrawn')

        def work():
            try:
                writer.write(bytes(1_048_576), require_current=current)
            except Exception as error:
                sent.append(error)

        worker = threading.Thread(target=work)
        worker.start()
        try:
            b.settimeout(1)
            assert b.recv(4, socket.MSG_WAITALL) == struct.pack('!I', 1_048_576)
            withdrawn.set()
            worker.join(1)
            assert not worker.is_alive() and isinstance(sent[0], PermissionError)
            assert a.fileno() == -1
        finally:
            writer.close()
            worker.join(2)


def test_reverse_input_retires_writer_even_with_valid_peer():
    a, b = socket.socketpair()
    with a, b:
        writer = lane(a, True)
        b.sendall(b'not a permitted command')
        with pytest.raises(OSError, match='disconnected_or_sent_data'):
            writer.write(b'', require_current=lambda: None)
        assert a.fileno() == -1


def test_attachment_waits_for_exact_native_gui_and_carries_no_secret_in_media():
    a, b = socket.socketpair()
    with a, b:
        deadline = time.monotonic() + 3
        peer = os.getpid(), os.getuid()
        daemon = PhoneScreenLocalAttach(a, expected_peer=peer, require_original=lambda: None, deadline=deadline)
        gui = PhoneScreenLocalAttach(b, expected_peer=peer, require_original=lambda: None, deadline=deadline)
        received, permit, ended = threading.Event(), threading.Event(), threading.Event()
        outcomes = []

        def attach(read, width, height, expiry):
            assert (width, height, expiry) == (720, 1280, deadline)
            received.set()
            assert permit.wait(2)
            return read

        def offer():
            writer = None
            try:
                writer = daemon.daemon_offer(720, 1280)
                writer.write(b'fixture', require_current=lambda: None)
            except Exception as error:
                outcomes.append(error)
            finally:
                if writer is not None:
                    writer.close()
                ended.set()

        def accept():
            reader = None
            try:
                reader = gui.gui_accept(attach)
                outcomes.append(reader.read())
            except Exception as error:
                outcomes.append(error)
            finally:
                if reader is not None:
                    reader.close()

        server, client = threading.Thread(target=offer), threading.Thread(target=accept)
        server.start()
        client.start()
        try:
            assert received.wait(1) and not ended.is_set()
            permit.set()
            server.join(2)
            client.join(2)
            assert not server.is_alive() and not client.is_alive() and outcomes == [b'fixture']
            with pytest.raises(PermissionError, match='already_used'):
                daemon.daemon_offer(720, 1280)
            with pytest.raises(PermissionError, match='already_used'):
                gui.gui_accept(attach)
        finally:
            permit.set()
            daemon.close()
            gui.close()
            server.join(2)
            client.join(2)


@pytest.mark.parametrize('event', ['unrelated_reply', 'expired', 'withdrawn'])
def test_attachment_cannot_release_media_lane_without_original_guard(event):
    a, b = socket.socketpair()
    with a, b:
        b.settimeout(1)
        withdrawn = threading.Event()
        outcome = []

        def guard():
            if withdrawn.is_set():
                raise PermissionError('withdrawn')

        def work():
            attach = PhoneScreenLocalAttach(a, expected_peer=(os.getpid(), os.getuid()),
                require_original=guard, deadline=time.monotonic() + (.2 if event == 'expired' else 2))
            try:
                outcome.append(attach.daemon_offer(720, 1280))
            except Exception as error:
                outcome.append(error)

        worker = threading.Thread(target=work)
        worker.start()
        try:
            assert b.recv(28, socket.MSG_WAITALL).startswith(b'MGSVL001')
            if event == 'unrelated_reply':
                b.sendall(b'MGSVACK1' + bytes(16))
            elif event == 'withdrawn':
                withdrawn.set()
            worker.join(2)
            assert not worker.is_alive()
            assert isinstance(outcome[0], TimeoutError if event == 'expired' else PermissionError)
            assert b.recv(1) == b''
        finally:
            b.close()
            worker.join(2)


def test_daemon_adapter_requires_live_original_candidate_and_closes_only_view_socket():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        with socket.create_connection(listener.getsockname(), timeout=2) as peer:
            native, _ = listener.accept()
            with native:
                native.settimeout(.2)
                channel = SecureChannel(native, bytes(16), bytes(32), bytes(4), bytes(32), b'\x01' * 4)
                channel.last_capabilities = {'items': {'device_status': {'available': True, 'versions': [26]}}}
                phone = PhoneService.__new__(PhoneService)
                paired = dict(device_id='phone', static_public='fixture', state='paired')
                phone.store = SimpleNamespace(peers=[paired])
                phone.enabled, phone._generation, phone.stop_event = True, 1, threading.Event()
                phone.connections, phone.connection_transports = {'phone': channel}, {'phone': 'wifi'}
                phone._screen_dispatch = PhoneScreenDesktopDispatch(phone)
                phone.native_screen_included = True

                def probe():
                    now = now_ms()
                    body = dict(version=26, request_id=str(uuid.uuid4()), nonce=uuid.uuid4().hex * 2, op='probe')
                    phone._payload(paired, channel, dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=REQUEST,
                                                        created_ms=now, expires_ms=now + 5000, body=body))
                    receive_frame(peer, 8192)
                    return phone.native_screen_candidate('phone')

                old = probe()
                current = probe()
                identity = os.getpid(), os.getuid()
                a, b = socket.socketpair()
                with a, b:
                    with pytest.raises(PermissionError, match='probe_changed'):
                        begin_daemon_screen(phone, 'phone', old, a, identity, require_gui=lambda: None)
                    assert b.recv(1) == b'' and native.fileno() >= 0

                a, b = socket.socketpair()
                with a, b:
                    attached = PhoneScreenLocalAttach(b, expected_peer=identity, require_original=lambda: None,
                                                      deadline=current[1][1])
                    outcome = []

                    def start():
                        try:
                            outcome.append(begin_daemon_screen(phone, 'phone', current, a, identity, require_gui=lambda: None))
                        except Exception as error:
                            outcome.append(error)

                    worker = threading.Thread(target=start)
                    worker.start()
                    local = None
                    daemon = None
                    try:
                        assert channel.send_seq == 2
                        local = attached.gui_accept(lambda lane, width, height, deadline: lane)
                        worker.join(2)
                        assert not worker.is_alive() and len(outcome) == 1
                        assert not isinstance(outcome[0], Exception), outcome
                        daemon = outcome[0]
                        assert receive_frame(peer, 8192)['seq'] == 2
                        local.close()
                        assert receive_frame(peer, 8192)['seq'] == 3
                        until = time.monotonic() + 2
                        while not daemon.is_drained() and time.monotonic() < until:
                            time.sleep(.01)
                        assert daemon.is_drained() and native.fileno() >= 0
                    finally:
                        if local is not None:
                            local.close()
                        if daemon is not None:
                            daemon.stop()
                        attached.close()
                        a.close()
                        worker.join(2)


@pytest.mark.parametrize('event', ['window-stop', 'daemon-shutdown-during-confirmation', 'daemon-shutdown-active'])
def test_daemon_binary_ingress_separates_confirmation_and_normal_ipc(tmp_path, event):
    filename = str(tmp_path / 'runtime' / 'control.sock')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        with socket.create_connection(listener.getsockname(), timeout=2) as peer:
            native, _ = listener.accept()
            with native:
                native.settimeout(.2)
                phone_id = str(uuid.uuid4())
                paired = dict(device_id=phone_id, static_public='fixture', state='paired')
                channel = SecureChannel(native, bytes(16), bytes(32), bytes(4), bytes(32), b'\x01' * 4)
                channel.last_capabilities = {'items': {'device_status': {'available': True, 'versions': [26]}}}
                phone = PhoneService.__new__(PhoneService)
                phone.store = SimpleNamespace(peers=[paired])
                phone.enabled, phone._generation, phone.stop_event = True, 1, threading.Event()
                phone.connections, phone.connection_transports = {phone_id: channel}, {phone_id: 'wifi'}
                phone._screen_dispatch = PhoneScreenDesktopDispatch(phone)
                phone.native_screen_included = True
                now = now_ms()
                body = dict(version=26, request_id=str(uuid.uuid4()), nonce=uuid.uuid4().hex * 2, op='probe')
                phone._payload(paired, channel, dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=REQUEST,
                                                    created_ms=now, expires_ms=now + 8000, body=body))
                receive_frame(peer, 8192)
                daemon = IPCServer(None, filename, phone_backend=phone).start()
                view = None
                try:
                    with pytest.raises((OSError, EOFError)):
                        request_daemon_screen(filename, phone_id, require_gui=lambda: None,
                                              confirm=lambda _: pytest.fail('disabled daemon offered a view'), attach=None)
                    assert ipc_request('ping', path=filename)['running']
                    daemon._native_screen_view_checked = True
                    def confirm(expiry):
                        assert expiry > time.monotonic()
                        assert channel.send_seq == 1
                        assert ipc_request('ping', path=filename)['running']
                        if event == 'daemon-shutdown-during-confirmation':
                            daemon.close()
                            assert daemon.screen_view_drained
                        return True

                    if event == 'daemon-shutdown-during-confirmation':
                        with pytest.raises((OSError, EOFError)):
                            request_daemon_screen(filename, phone_id, require_gui=lambda: None, confirm=confirm,
                                                  attach=lambda *_: pytest.fail('shutdown admitted a window'))
                        assert channel.send_seq == 1 and native.fileno() >= 0
                        return
                    view = request_daemon_screen(filename, phone_id, require_gui=lambda: None, confirm=confirm,
                                                 attach=lambda lane, width, height, expiry: lane)
                    assert receive_frame(peer, 8192)['seq'] == 1
                    if event == 'daemon-shutdown-active':
                        daemon.close()
                        assert daemon.screen_view_drained
                        with pytest.raises(EOFError):
                            view.read()
                    else:
                        view.close()
                        assert ipc_request('ping', path=filename)['running']
                    assert receive_frame(peer, 8192)['seq'] == 2
                    assert native.fileno() >= 0
                finally:
                    if view is not None:
                        view.close()
                    daemon.close()
