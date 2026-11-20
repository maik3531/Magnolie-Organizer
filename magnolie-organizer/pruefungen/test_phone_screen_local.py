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
from magnolie_phone_screen_local import PhoneScreenLocalAttach, PhoneScreenLocalLane, begin_daemon_screen, local_peer
from magnolie_telefon import PhoneService, SecureChannel, now_ms, receive_frame


def lane(sock, writing, guard=lambda: None):
    return PhoneScreenLocalLane(sock, expected_peer=(os.getpid(), os.getuid()), require_original=guard, writing=writing)


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
            try:
                writer = daemon.daemon_offer(720, 1280)
                writer.write(b'fixture', require_current=lambda: None)
            except Exception as error:
                outcomes.append(error)
            finally:
                ended.set()

        def accept():
            try:
                outcomes.append(gui.gui_accept(attach).read())
            except Exception as error:
                outcomes.append(error)

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
                        assert receive_frame(peer, 8192)['seq'] == 2  # Original encrypted offer.
                        local.close()
                        assert receive_frame(peer, 8192)['seq'] == 3  # Only original view STOP, not parent close.
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
