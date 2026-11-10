"""One explicitly activated PhoneService webcam owner (Refs #503).

No constructor starts capture, native outputs or a listener. The real service
registers this original owner before starting its bounded control/media worker.
Only that service's explicit native UI entry may create an owner; packets cannot.
"""
import copy
from collections import deque
import queue
import socket
import threading
import time

from magnolie_phone_camera_control import REQUEST, REPORT, validate_body
from magnolie_phone_camera_exchange import DesktopWebcamControlExchange


class NativePhoneWebcamOwner:
    def __init__(self, service, peer, channel, device, *, muted=False, front=False, output_factory=None):
        self.service, self.store, self.channel = service, service.store, channel
        self.peer_id, self.key, self.generation = peer['device_id'], peer['static_public'], service._generation
        self.device, self.muted, self.front = device, muted, front
        self.output_factory = output_factory
        self.stopping, self.done = threading.Event(), threading.Event()
        self.incoming = queue.Queue(maxsize=4)
        self.worker = threading.Thread(target=self._work, name='Magnolie original webcam control', daemon=True)
        self.exchange = self.listener = self.accepted = None
        self.error = None
        self.cleanup_confirmed = False
        self.pending_cleanup_owner = None
        self.ack_token = object()
        self._activity = False
        self.announced = False
        self._probe_claimed = False

    def context_current(self):
        # Called under SecureChannel's writer lock as well: atomic native owner
        # checks only. NEVER take PhoneService.lock or perform storage IO here.
        peer = next((value for value in self.store.peers if value.get('device_id') == self.peer_id), None)
        if (self.service._native_webcam_owner is not self or
                self.service.store is not self.store or self.service._generation != self.generation or
                not self.service.enabled or self.service.stop_event.is_set() or
                self.service.connections.get(self.peer_id) is not self.channel or
                self.channel.sock.fileno() < 0 or
                self.service.connection_transports.get(self.peer_id) != 'wifi' or
                not peer or peer.get('static_public') != self.key or peer.get('state') != 'paired'):
            self.retire()
            raise PermissionError('webcam_original_native_owner_retired')

    def current(self):
        self.context_current()
        if self.stopping.is_set():
            raise PermissionError('webcam_original_native_owner_retired')

    def belongs(self, peer, channel):
        return channel is self.channel and peer.get('device_id') == self.peer_id and peer.get('static_public') == self.key

    def submit(self, kind, body):
        self.current()
        validate_body(body, kind)
        if kind != REQUEST:
            raise ValueError('webcam_phone_request_required')
        if body['op'] == 'probe':
            with self.service.lock:
                self.current()
                history = self.service._webcam_probe_tokens.setdefault(self.channel, deque(maxlen=16))
                if self._probe_claimed or any(body['request_id'] == entry[0] or body['nonce'] == entry[1] for entry in history):
                    raise PermissionError('webcam_original_probe_already_used')
                self._probe_claimed = True
                history.append((body['request_id'], body['nonce']))
        else:
            exchange = self.exchange
            original = exchange.probe if exchange is not None else None
            if (original is None or body['request_id'] != original['request_id'] or body['nonce'] != original['nonce'] or
                    body.get('session') != exchange.identity):
                # Reject late OLD controls before they can enter this owner's
                # worker and accidentally retire a different original session.
                raise PermissionError('webcam_control_foreign_exchange')
        self.incoming.put_nowait(dict(body))  # Never enqueue a persistent message.

    def _send(self, kind, body):
        self.current()
        validate_body(body, kind)
        self.service._send_native_webcam_ephemeral(self, kind, body)

    def retire(self):
        """Nonblocking original-IO cancellation, safe under service monitors."""
        self.stopping.set()
        for value in (self.accepted, self.listener):
            if value is not None:
                try: value.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                value.close()

    def is_completely_stopped(self):
        return self.done.is_set() and not self.worker.is_alive() and self.cleanup_confirmed

    def is_streaming(self):
        exchange = self.exchange
        run = exchange.run if exchange is not None else None
        return bool(not self.stopping.is_set() and run is not None and not run.ended.is_set() and
            run.state == 'streaming' and not run.outputs.closed and
            all(track in run.outputs.positions for track in (('video',) if self.muted else ('video', 'audio'))))

    def _notify_activity(self):
        active = self.is_streaming()
        if active != self._activity:
            self._activity = active
            self.service.callback('personal_sync_activity', {})

    def _work(self):
        try:
            self.current()
            # Clone the last control ACTUALLY sent on this parent; preserve all
            # existing Bluetooth/sync availability. Do not persist v24/start.
            baseline = copy.deepcopy(self.channel.last_capabilities)
            if baseline is None:
                raise PermissionError('webcam_fresh_desktop_control_required')
            versions = baseline['items']['device_status']['versions']
            if 24 in versions or len(versions) >= 16:
                raise ValueError('webcam_control_discovery_budget_invalid')
            versions.append(24); versions.sort()
            baseline['revision'] = self.store.next_revision('capabilities.update')
            self.service._send_native_webcam_ephemeral(self, 'capabilities.update', baseline)
            self.announced = True
            deadline = time.monotonic() + 60
            prepared = False
            while not self.stopping.is_set():
                self.current()
                if self.exchange is None or self.exchange.phase != 'sending':
                    if time.monotonic() >= deadline:
                        raise TimeoutError('webcam_original_start_timeout')
                try:
                    body = self.incoming.get(timeout=.05)
                except queue.Empty:
                    body = None
                if body is not None:
                    op = body['op']
                    if op == 'probe':
                        if self.exchange is not None:
                            raise PermissionError('webcam_original_probe_already_used')
                        self.exchange = DesktopWebcamControlExchange(self.channel, self.channel.sock, self.current)
                        listener = socket.socket(self.channel.sock.family, socket.SOCK_STREAM)
                        self.listener = listener
                        local = self.channel.sock.getsockname()
                        listener.bind((local[0], 0) if len(local) == 2 else (local[0], 0, local[2], local[3]))
                        listener.listen(1); listener.settimeout(.05)
                        offer = self.exchange.offer(self.channel, body, listener, muted=self.muted, front=self.front)
                        self._send(REPORT, offer)
                    elif op == 'prepared' and self.exchange is not None:
                        self.exchange.prepared(self.channel, body)
                        prepared = True
                    elif op in ('stop', 'error') and self.exchange is not None:
                        if op == 'error':
                            self.error = PermissionError('webcam_' + body['reason'])
                        self.exchange.stop(self.channel, body)
                        self.retire()
                    else:
                        raise PermissionError('webcam_control_out_of_phase')
                if prepared and self.accepted is None:
                    try: self.accepted, _ = self.listener.accept()
                    except socket.timeout: continue
                    self.current()
                    self.exchange.bind_receiver(self.channel, self.accepted, self.device,
                        lambda value: self._send(REPORT, value), output_factory=self.output_factory)
                if self.exchange is not None and self.exchange.run is not None and self.exchange.run.ended.is_set():
                    self.error = self.exchange.run.error
                    self.retire()
                self._notify_activity()
        except Exception as error:
            self.error = error
        finally:
            self.retire()
            try: self._notify_activity()
            except Exception: pass
            if self.exchange is not None and self.exchange.probe is not None:
                try:
                    stop = dict(self.exchange.probe, op='stop', session=self.exchange.identity)
                    validate_body(stop, REPORT)
                    self.service._send_native_webcam_ephemeral(self, REPORT, stop, stopping=True)
                except Exception:
                    pass  # Lost original parent: no reconnect/foreign STOP.
            if self.announced:
                try:
                    witness = self.channel.last_capabilities
                    baseline = copy.deepcopy(witness)
                    versions = baseline['items']['device_status']['versions']
                    if 24 in versions:
                        versions.remove(24)
                        baseline['revision'] = self.store.next_revision('capabilities.update')
                        self.service._send_native_webcam_ephemeral(self, 'capabilities.update', baseline,
                            stopping=True, expected_capabilities=witness)
                except Exception:
                    pass  # Never restore old metadata over another actual control update.
            try:
                if self.exchange is not None:
                    self.exchange.close()
                    run = self.exchange.run
                    if run is not None:
                        # A receiver-thread exit alone does not prove successful
                        # original native unload. Recheck that exact output owner.
                        run.outputs.close()
                self.pending_cleanup_owner = getattr(self.error, 'native_cleanup_owner', None)
                self.cleanup_confirmed = self.pending_cleanup_owner is None
            except Exception as error:
                self.error = error  # Retain the slot on uncertain native cleanup.
                self.pending_cleanup_owner = getattr(error, 'native_cleanup_owner', None)
            self.done.set()
            with self.service.lock:
                self.service._workers.discard(self.worker)
