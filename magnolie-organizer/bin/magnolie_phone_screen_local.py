"""Dedicated Linux daemon-to-GTK display lane. No JSON or persistent media."""

import math
import select
import socket
import struct
import threading
import time


_CREDENTIALS = struct.Struct('3i')  # Linux struct ucred, native order.
_HEADER = struct.Struct('!I')
_MAX_JPEG = 1_048_576


def local_peer(sock):
    """Read a connected Unix stream's kernel peer, not a supplied PID."""
    if type(sock) is not socket.socket or sock.family != socket.AF_UNIX or sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
        raise ValueError('screen_local_connected_unix_stream_required')
    sock.getpeername()
    pid, uid, _gid = _CREDENTIALS.unpack(sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _CREDENTIALS.size))
    if pid <= 0 or uid < 0:
        raise PermissionError('screen_local_peer_unavailable')
    return pid, uid


class PhoneScreenLocalLane:
    """Own one already admitted native socket. Callers must prove the original
    opt-in and exact peer process before admitting it, and keep that guard live.
    Peer credentials alone don't grant capture or allow reuse of a consent.
    Empty records are liveness, never displayed. No messages travel in reverse.
    """

    def __init__(self, sock, *, expected_peer, require_original, writing):
        self._sock = sock
        self._guard = require_original
        self._writing = writing
        self._terminal = threading.Event()
        self._close_lock = threading.Lock()
        self._io = threading.Lock()
        self.cleanup_error = None
        try:
            require_original()
            if type(writing) is not bool or local_peer(sock) != expected_peer:
                raise PermissionError('screen_local_original_peer_required')
            sock.setblocking(False)
            require_original()
        except BaseException:
            self.close()
            raise

    def require_open(self):
        if self._terminal.is_set():
            raise OSError('screen_local_lane_retired')
        self._guard()
        if self._terminal.is_set():
            raise OSError('screen_local_lane_retired')
        if self._writing and self._wait(select.POLLIN, 0):
            # Readability on a send-only connection means EOF or forbidden
            # reverse input. Neither can authorize more data.
            raise OSError('screen_local_view_disconnected_or_sent_data')

    def _wait(self, events, milliseconds):
        poll = select.poll()  # No select() descriptor-number ceiling.
        poll.register(self._sock, events)
        return poll.poll(milliseconds)

    def _transfer(self, data, operation, deadline, require_current):
        pending = memoryview(data)
        while pending:
            self.require_open()
            require_current()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('screen_local_record_timeout')
            try:
                used = operation(pending)
            except BlockingIOError:
                events = select.POLLIN | select.POLLOUT if self._writing else select.POLLIN
                self._wait(events, min(50, math.ceil(remaining * 1000)))
                continue
            if not used:
                raise EOFError('screen_local_disconnected')
            pending = pending[used:]
        self.require_open()
        require_current()
        if time.monotonic() >= deadline:
            raise TimeoutError('screen_local_record_timeout')

    def write(self, jpeg, *, require_current):
        with self._io:
            try:
                if not self._writing or type(jpeg) is not bytes or len(jpeg) > _MAX_JPEG:
                    raise ValueError('screen_local_record_invalid')
                expiry = time.monotonic() + 2
                self._transfer(_HEADER.pack(len(jpeg)), self._sock.send, expiry, require_current)
                self._transfer(jpeg, self._sock.send, expiry, require_current)
            except BaseException:
                self.close()
                raise

    def read(self, *, first_header_deadline=None):
        with self._io:
            try:
                if self._writing:
                    raise ValueError('screen_local_direction_invalid')
                now = time.monotonic()
                expiry = now + 2 if first_header_deadline is None else min(now + 60, first_header_deadline)
                header = bytearray(_HEADER.size)
                self._transfer(header, self._sock.recv_into, expiry, lambda: None)
                size, = _HEADER.unpack(header)
                if size > _MAX_JPEG:
                    raise ValueError('screen_local_record_invalid')
                data = bytearray(size)
                if first_header_deadline is not None:
                    expiry = min(expiry, time.monotonic() + 2)
                self._transfer(data, self._sock.recv_into, expiry, lambda: None)
                return bytes(data)
            except BaseException:
                self.close()
                raise

    def close(self):
        with self._close_lock:
            if self._terminal.is_set():
                return
            self._terminal.set()
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError as error:
                self.cleanup_error = error


class PhoneScreenLocalDisplay:
    """Owned background decoder for a GUI's already admitted local lane.

    The GUI must close it on lock, exit or window stop; the original daemon
    then sees EOF. Loss of the daemon closes the GUI worker as well.
    """

    def __init__(self, lane, width, height, *, setup_deadline, offer_rgb):
        self._lane = lane
        self._width, self._height = width, height
        self._offer_rgb = offer_rgb
        self._setup_deadline = setup_deadline
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._started = False
        self.failure = None
        self._worker = threading.Thread(target=self._run, name='magnolie-screen-local-display', daemon=True)

    def start(self):
        with self._lock:
            if self._started or self._stopped.is_set():
                raise RuntimeError('screen_local_display_already_used')
            self._started = True
            try:
                self._worker.start()
            except BaseException:
                self.stop()
                raise

    def _run(self):
        try:
            from magnolie_phone_screen_window import PhoneScreenJpegReceiver

            def current():
                self._lane.require_open()
                return not self._stopped.is_set()

            decoder = PhoneScreenJpegReceiver(self._width, self._height, is_current=current, offer_rgb=self._offer_rgb)
            first = self._setup_deadline
            while not self._stopped.is_set():
                data = self._lane.read(first_header_deadline=first)
                first = None
                if data and decoder.receive(data) is not True:
                    raise PermissionError('screen_local_view_retired')
        except Exception as error:
            if not self._stopped.is_set():
                self.failure = error
        finally:
            self.stop()

    def stop(self):
        self._stopped.set()
        self._lane.close()

    def is_drained(self):
        with self._lock:
            return self._stopped.is_set() and not self._worker.is_alive() and self._lane.cleanup_error is None

    @property
    def retired(self):
        return self._stopped.is_set()
