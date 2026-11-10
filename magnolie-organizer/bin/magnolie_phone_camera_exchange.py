"""One original desktop webcam exchange; no UI/discovery or accept worker.

Native integration must supply the REAL authenticated parent/socket and live
explicit Organizer opt-in guard. Nothing is loaded from saved peer metadata.
The caller transfers one listener and accepted socket; no URLs/reconnects or
second listener are selected here. Native output modules are imported lazily.
"""
import secrets
import socket
import threading
import time

from magnolie_phone_camera_control import REQUEST, REPORT, MAX_TTL_MS, validate_body


class DesktopWebcamControlExchange:
    def __init__(self, parent, control_socket, current, *, clock=time.monotonic):
        if not callable(current) or control_socket.family not in (socket.AF_INET, socket.AF_INET6):
            raise ValueError('webcam_original_tcp_control_required')
        current()
        self.parent, self.control_socket, self.current, self.clock = parent, control_socket, current, clock
        self.local, self.peer = control_socket.getsockname(), control_socket.getpeername()
        self.lock = threading.RLock()
        self.phase = 'new'
        self.issued = self.last = clock()
        self.listener = self.run = None
        self.identity = self.material = self.probe = None
        self.error = None

    def _same_parent(self, parent):
        if parent is not self.parent:
            raise PermissionError('webcam_original_parent_required')

    def _current(self):
        try:
            self.current()
            if self.control_socket.getsockname() != self.local or self.control_socket.getpeername() != self.peer:
                raise PermissionError('webcam_original_tcp_control_required')
            now = self.clock()
            with self.lock:
                if (self.phase == 'retired' or now < self.last or now < self.issued or
                        self.phase != 'sending' and now - self.issued >= MAX_TTL_MS / 1000):
                    raise PermissionError('webcam_original_control_retired')
                self.last = now
        except Exception as error:
            # A native IO guard must NOT join its own receiver/monitor thread.
            self._retire(error)
            raise

    def _retire(self, error=None):
        with self.lock:
            if self.phase == 'retired':
                return
            self.phase = 'retired'
            self.error = error
            if self.material is not None:
                self.material[:] = bytes(len(self.material))
                self.material = None
            listener = self.listener
            self.listener = None
        if listener is not None:
            listener.close()

    def offer(self, parent, probe, listener, *, muted=False, front=False):
        self._same_parent(parent)
        validate_body(probe, REQUEST)
        if probe['op'] != 'probe' or type(muted) is not bool or type(front) is not bool:
            raise ValueError('webcam_control_probe_required')
        try:
            self._current()
            address = listener.getsockname()
            if (listener.family != self.control_socket.family or
                    listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1 or
                    address[0] != self.local[0] or not 1024 <= address[1] <= 65535):
                raise PermissionError('webcam_original_bound_listener_required')
            with self.lock:
                if self.phase != 'new':
                    raise PermissionError('webcam_control_offer_already_used')
                self.listener, self.listen_address = listener, address
                self.probe = dict(probe)
                self.identity, self.material = secrets.token_hex(16), bytearray(secrets.token_bytes(32))
                self.muted = muted
                self.phase = 'offered'
                return dict(probe, op='offer', session=self.identity, secret=self.material.hex(),
                    port=address[1], muted=muted, front=front)
        except Exception as error:
            listener.close()
            self._retire(error)
            raise

    def _matching(self, parent, packet):
        self._same_parent(parent)
        validate_body(packet, REQUEST)
        with self.lock:
            if (self.probe is None or packet['request_id'] != self.probe['request_id'] or
                    packet['nonce'] != self.probe['nonce'] or packet.get('session') != self.identity):
                raise PermissionError('webcam_control_foreign_exchange')

    def prepared(self, parent, packet):
        self._matching(parent, packet)
        self._current()
        with self.lock:
            if self.phase != 'offered' or packet['op'] != 'prepared':
                raise PermissionError('webcam_control_prepared_out_of_phase')
            self.phase = 'prepared'

    def bind_receiver(self, parent, accepted, device, send_ready, *, output_factory=None):
        """Prepare actual endpoints, then send READY via the original bounded
        authenticated control path. No incoming media is read before that send
        succeeds AND its separate live data guard accepts the original phase.
        """
        self._same_parent(parent)
        run = None
        try:
            self._current()
            with self.lock:
                if self.phase != 'prepared' or self.run is not None:
                    raise PermissionError('webcam_actual_capture_prepared_required')
                if (accepted.family != self.control_socket.family or accepted.getpeername()[0] != self.peer[0] or
                        accepted.getsockname() != self.listen_address):
                    raise PermissionError('webcam_original_media_socket_required')
                self.phase = 'binding'
                material = bytes(self.material)
            def data_current():
                self._current()
                with self.lock:
                    if self.phase != 'sending':
                        raise PermissionError('webcam_actual_data_agreement_required')
            def ready():
                self._current()
                with self.lock:
                    if self.phase != 'binding':
                        raise PermissionError('webcam_receiver_ready_out_of_phase')
                    packet = dict(self.probe, op='send', session=self.identity)
                validate_body(packet, REPORT)
                send_ready(packet)  # No exchange monitor held during native/control IO.
                self._current()
                with self.lock:
                    if self.phase != 'binding':
                        raise PermissionError('webcam_receiver_ready_out_of_phase')
                    self.phase = 'sending'
            from magnolie_phone_camera_receiver import WebcamReceiveRun
            options = {} if output_factory is None else {'output_factory': output_factory}
            run = WebcamReceiveRun(accepted, self.identity, material, device, self._current,
                muted=self.muted, receiver_ready=ready, data_guard=data_current, **options)
            with self.lock:
                if self.phase != 'sending':
                    raise PermissionError('webcam_original_control_retired')
                self.run = run
                if self.material is not None:
                    self.material[:] = bytes(len(self.material)); self.material = None
                listener = self.listener
                self.listener = None
            if listener is not None:
                listener.close()
            return run
        except Exception as error:
            accepted.close()
            self._retire(error)
            if run is not None:
                run.stop()
            raise

    def stop(self, parent, packet):
        self._matching(parent, packet)
        if packet['op'] not in ('stop', 'error'):
            raise ValueError('webcam_control_stop_required')
        self._current()
        self.close()

    def close(self):
        self._retire()
        with self.lock:
            run = self.run
        if run is not None:
            run.stop()
