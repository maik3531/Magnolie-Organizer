import os
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_phone_screen_local import PhoneScreenLocalAttach, PhoneScreenLocalLane, local_peer


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
