"""Dedicated Linux daemon-to-GTK display lane. No JSON or persistent media."""

import math
import os
import secrets
import select
import socket
import struct
import sys
import threading
import time
import uuid


_CREDENTIALS = struct.Struct('3i')  # Linux struct ucred, native order.
_HEADER = struct.Struct('!I')
_MAX_JPEG = 1_048_576
_OFFER = struct.Struct('!8s16sHH')
_READY = struct.Struct('!8s16s')
_OFFER_MAGIC = b'MGSVL001'
_READY_MAGIC = b'MGSVACK1'
DAEMON_REQUEST_PREFIX = b'\x01'
_DAEMON_REQUEST = struct.Struct('!8s16s')
_DAEMON_CANDIDATE = struct.Struct('!8s16sd')
_REQUEST_MAGIC = DAEMON_REQUEST_PREFIX + b'MGSV001'
_CANDIDATE_MAGIC = b'MGSVSEL1'
_APPROVAL_MAGIC = b'MGSVYES1'


def local_peer(sock):
    """Read a connected Unix stream's kernel peer, not a supplied PID."""
    if type(sock) is not socket.socket or sock.family != socket.AF_UNIX or sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
        raise ValueError('screen_local_connected_unix_stream_required')
    sock.getpeername()
    pid, uid, _gid = _CREDENTIALS.unpack(sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _CREDENTIALS.size))
    if pid <= 0 or uid < 0:
        raise PermissionError('screen_local_peer_unavailable')
    return pid, uid


class PhoneScreenPeerLifetime:
    """Retain the peer process object of the exact accepted Unix stream.

    Do not reopen a numeric PID from SO_PEERCRED; that would race PID reuse.
    A live process is not a viewing grant. The admitting native owner must
    supply and retain its separate consent/context guard.
    """

    def __init__(self, sock, *, expected_peer):
        if sys.platform != 'linux' or local_peer(sock) != expected_peer:
            raise PermissionError('screen_local_original_peer_required')
        self._sock = sock
        self._lock = threading.Lock()
        if not hasattr(socket, 'SO_PEERPIDFD') and os.uname().machine not in ('x86_64', 'aarch64', 'i386', 'i686', 'riscv64'):
            raise OSError('screen_local_peer_pidfd_unavailable')
        # Linux asm-generic SO_PEERPIDFD is 77; some Python versions do not
        # define the symbol even when the running kernel supports it.
        option = getattr(socket, 'SO_PEERPIDFD', 77)
        self._pidfd, = struct.unpack('i', sock.getsockopt(socket.SOL_SOCKET, option, struct.calcsize('i')))
        try:
            os.set_inheritable(self._pidfd, False)
            self.require_current()
        except BaseException:
            self.close()
            raise

    def require_current(self):
        with self._lock:
            if self._pidfd is None or self._sock.fileno() < 0:
                raise PermissionError('screen_local_peer_retired')
            poll = select.poll()
            poll.register(self._pidfd, select.POLLIN)
            if poll.poll(0):
                raise PermissionError('screen_local_peer_process_ended')

    def close(self):
        with self._lock:
            if self._pidfd is not None:
                fd, self._pidfd = self._pidfd, None
                os.close(fd)


def peer_pidfd_available():
    """Read-only capability probe on a private socket pair owned by this process."""
    try:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        with left, right:
            original = PhoneScreenPeerLifetime(left, expected_peer=(os.getpid(), os.getuid()))
            try:
                original.require_current()
            finally:
                original.close()
        return True
    except OSError:
        return False


def _view_size(width, height):
    if (type(width) is not int or type(height) is not int or not 2 <= width <= 1920 or
            not 2 <= height <= 1920 or width * height > 1920 * 1080):
        raise ValueError('screen_local_view_size_invalid')


class PhoneScreenLocalAttach:
    """One bounded setup conversation on the exact admitted local socket.

    Run these blocking operations in an owner worker, not GTK's main loop.
    `require_original` must already enforce one original native user choice,
    plus the peer and desktop/daemon lifetime. Echo proves receipt only, not
    user consent. Both endpoints receive the *same* already fixed deadline.
    """

    def __init__(self, sock, *, expected_peer, require_original, deadline):
        self._sock = sock
        self._peer = expected_peer
        self._guard = require_original
        self._deadline = deadline
        self._used = False
        self._phase_lock = threading.Lock()
        self._process = None

    def _check(self):
        self._guard()
        if self._process is not None:
            self._process.require_current()
        remaining = self._deadline - time.monotonic()
        if not 0 < remaining <= 60:
            raise TimeoutError('screen_local_attach_deadline')
        return remaining

    def _claim(self):
        with self._phase_lock:
            if self._used:
                raise PermissionError('screen_local_attach_already_used')
            self._used = True

    def _prepare(self):
        self._check()
        if self._process is None:
            self._process = PhoneScreenPeerLifetime(self._sock, expected_peer=self._peer)
        self._sock.setblocking(False)

    def _transfer(self, data, *, writing):
        poll = select.poll()
        poll.register(self._sock, select.POLLOUT if writing else select.POLLIN)
        operation = self._sock.send if writing else self._sock.recv_into
        remaining = memoryview(data)
        while remaining:
            timeout = min(50, math.ceil(1000 * self._check()))
            try:
                count = operation(remaining)
            except BlockingIOError:
                poll.poll(timeout)
                continue
            if not count:
                raise EOFError('screen_local_attach_disconnected')
            remaining = remaining[count:]
        self._check()

    def daemon_offer(self, width, height):
        """Return the write lane only after the original GUI attached a view."""
        self._claim()
        try:
            _view_size(width, height)
            self._prepare()
            token = secrets.token_bytes(16)
            self._transfer(_OFFER.pack(_OFFER_MAGIC, token, width, height), writing=True)
            ready = bytearray(_READY.size)
            self._transfer(ready, writing=False)
            if _READY.unpack(ready) != (_READY_MAGIC, token):
                raise PermissionError('screen_local_original_view_not_confirmed')
            lane = PhoneScreenLocalLane(self._sock, expected_peer=self._peer, require_original=self._guard,
                                        writing=True, process=self._process)
            lane.require_open()
            self._process = None
            return lane
        except BaseException:
            self.close()
            raise

    def gui_accept(self, attach):
        """`attach` must hand the exact read lane to GTK and return only after
        it is attached; it must never wait for a first frame. The GTK reader
        gets only after-setup bytes. The write of READY uses this same socket.
        """
        self._claim()
        lane = None
        try:
            self._prepare()
            offer = bytearray(_OFFER.size)
            self._transfer(offer, writing=False)
            magic, token, width, height = _OFFER.unpack(offer)
            if magic != _OFFER_MAGIC:
                raise ValueError('screen_local_attach_offer_invalid')
            _view_size(width, height)
            lane = PhoneScreenLocalLane(self._sock, expected_peer=self._peer, require_original=self._guard,
                                        writing=False, process=self._process)
            view = attach(lane, width, height, self._deadline)
            lane.require_open()
            self._transfer(_READY.pack(_READY_MAGIC, token), writing=True)
            self._process = None
            return view
        except BaseException:
            if lane is not None:
                lane.close()
            else:
                self.close()
            raise

    def close(self):
        try:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
        finally:
            if self._process is not None:
                self._process.close()


class PhoneScreenLocalLane:
    """Own one already admitted native socket. Callers must prove the original
    opt-in and exact peer process before admitting it, and keep that guard live.
    Peer credentials alone don't grant capture or allow reuse of a consent.
    Empty records are liveness, never displayed. No messages travel in reverse.
    """

    def __init__(self, sock, *, expected_peer, require_original, writing, process=None):
        self._sock = sock
        self._guard = require_original
        self._writing = writing
        self._process = process
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
        if self._process is not None:
            self._process.require_current()
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

    def read(self, *, first_header_deadline=None, require_current=lambda: None):
        with self._io:
            try:
                if self._writing:
                    raise ValueError('screen_local_direction_invalid')
                now = time.monotonic()
                expiry = now + 2 if first_header_deadline is None else min(now + 60, first_header_deadline)
                header = bytearray(_HEADER.size)
                self._transfer(header, self._sock.recv_into, expiry, require_current)
                size, = _HEADER.unpack(header)
                if size > _MAX_JPEG:
                    raise ValueError('screen_local_record_invalid')
                data = bytearray(size)
                if first_header_deadline is not None:
                    expiry = min(expiry, time.monotonic() + 2)
                self._transfer(data, self._sock.recv_into, expiry, require_current)
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
            if self._process is not None:
                try:
                    self._process.close()
                except OSError as error:
                    if self.cleanup_error is None:
                        self.cleanup_error = error


class PhoneScreenLocalDisplay:
    """Owned background decoder for a GUI's already admitted local lane.

    The GUI must close it on lock, exit or window stop; the original daemon
    then sees EOF. Loss of the daemon closes the GUI worker as well.
    """

    def __init__(self, lane, width, height, *, setup_deadline, require_view, offer_rgb):
        self._lane = lane
        self._width, self._height = width, height
        self._offer_rgb = offer_rgb
        self._require_view = require_view
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

            def require_current():
                self._require_view()
                if self._stopped.is_set():
                    raise PermissionError('screen_local_view_retired')

            def current():
                require_current()
                self._lane.require_open()
                return True

            decoder = PhoneScreenJpegReceiver(self._width, self._height, is_current=current, offer_rgb=self._offer_rgb)
            first = self._setup_deadline
            while not self._stopped.is_set():
                data = self._lane.read(first_header_deadline=first, require_current=require_current)
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


def begin_daemon_screen(phone, peer_id, candidate, sock, expected_gui, *, require_gui, attachment=None):
    """Private daemon owner adapter, after native GUI approval and admission.

    Never called by the general JSON proxy. `candidate` is the actual probe
    witness selected before the dialog; `require_gui` retains the exact lease.
    Transfers the socket on success, closes it on every failure.
    """
    from magnolie_phone_screen_control import PhoneScreenDesktopRun
    from magnolie_telefon import PhoneService

    relay = None
    owner = None

    def native_start(parent, probe, width, height, density, *, require_original, track, deadline):
        nonlocal attachment, relay, owner

        def current():
            require_gui()
            require_original()

        if attachment is None:
            attachment = PhoneScreenLocalAttach(sock, expected_peer=expected_gui, require_original=current, deadline=deadline)
        else:
            attachment._deadline = min(attachment._deadline, deadline)
        deadline = attachment._deadline
        relay = attachment.daemon_offer(width, height)
        owner = PhoneScreenDesktopRun(parent, probe, width, height, density, require_original=require_original,
                                      require_view=require_gui, local_lane=relay, track=track, deadline=deadline)
        owner.start()
        return owner

    try:
        if type(phone) is not PhoneService or not phone.native_screen_included or candidate is None:
            raise PermissionError('screen_original_daemon_view_not_admitted')
        require_gui()
        # Picture format is selected by the desktop, not a client's arbitrary
        # input or a phone-side extension.
        return phone.begin_native_screen(peer_id, 720, 1280, 160, native_start, expected=candidate)
    except BaseException:
        if owner is not None:
            owner.stop()
        elif relay is not None:
            relay.close()
        elif attachment is not None:
            attachment.close()
        else:
            sock.close()
        raise


def serve_daemon_screen(sock, phone, *, expected_uid, require_daemon):
    """Handle one binary selection on a dedicated connection, not a JSON op.

    Same-UID IPC is the local application trust boundary, not proof that a
    user accepted. The native client captures explicit approval on this exact
    connection. Genuine Android consent and phone SEND remain separate gates.
    """
    attachment = None
    try:
        peer = local_peer(sock)
        if peer[1] != expected_uid:
            raise PermissionError('screen_daemon_unrelated_user')
        require_daemon()
        attachment = PhoneScreenLocalAttach(sock, expected_peer=peer, require_original=require_daemon,
                                            deadline=time.monotonic() + 2)
        attachment._prepare()
        request = bytearray(_DAEMON_REQUEST.size)
        attachment._transfer(request, writing=False)
        magic, device_id = _DAEMON_REQUEST.unpack(request)
        if magic != _REQUEST_MAGIC or phone is None or not phone.native_screen_included:
            raise PermissionError('screen_daemon_not_available')
        peer_id = str(uuid.UUID(bytes=device_id))
        candidate = phone.native_screen_candidate(peer_id)
        channel, probe = candidate
        require_probe = probe[2]

        def current():
            require_daemon()
            require_probe()
            if phone.connections.get(peer_id) is not channel:
                raise PermissionError('screen_daemon_original_parent_retired')

        attachment._guard = current
        attachment._deadline = min(time.monotonic() + 30, probe[1])
        token = secrets.token_bytes(16)
        attachment._transfer(_DAEMON_CANDIDATE.pack(_CANDIDATE_MAGIC, token, attachment._deadline), writing=True)
        approval = bytearray(_READY.size)
        attachment._transfer(approval, writing=False)
        if _READY.unpack(approval) != (_APPROVAL_MAGIC, token):
            raise PermissionError('screen_daemon_original_approval_required')
        return begin_daemon_screen(phone, peer_id, candidate, sock, peer, require_gui=current, attachment=attachment)
    except BaseException:
        if attachment is None:
            sock.close()
        else:
            attachment.close()
        raise


def request_daemon_screen(path, peer_id, *, require_gui, confirm, attach):
    """Worker entry only: confirm and attach marshal to the original GTK owner.

    The exact connected daemon is pinned before the first request and retained
    in the display lane. No reconnect, saved option or ordinary subscriber ID.
    """
    require_gui()
    identity = uuid.UUID(peer_id)
    if str(identity) != peer_id:
        raise ValueError('screen_daemon_invalid_peer')
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    attachment = None
    try:
        sock.settimeout(2)
        sock.connect(path)
        peer = local_peer(sock)
        if peer[1] != os.getuid():
            raise PermissionError('screen_daemon_unrelated_user')
        attachment = PhoneScreenLocalAttach(sock, expected_peer=peer, require_original=require_gui,
                                            deadline=time.monotonic() + 2)
        attachment._prepare()
        attachment._transfer(_DAEMON_REQUEST.pack(_REQUEST_MAGIC, identity.bytes), writing=True)
        raw = bytearray(_DAEMON_CANDIDATE.size)
        attachment._transfer(raw, writing=False)
        magic, token, deadline = _DAEMON_CANDIDATE.unpack(raw)
        if magic != _CANDIDATE_MAGIC or not 0 < deadline - time.monotonic() <= 30:
            raise PermissionError('screen_daemon_invalid_candidate')
        attachment._deadline = deadline
        if confirm(deadline) is not True:
            raise PermissionError('screen_daemon_native_approval_denied')
        attachment._transfer(_READY.pack(_APPROVAL_MAGIC, token), writing=True)
        return attachment.gui_accept(attach)
    except BaseException:
        if attachment is None:
            sock.close()
        else:
            attachment.close()
        raise
