"""Join ONE original approved binary channel to ONE native AV output lifetime.

No peer discovery, approvals, saved autostart, driver installation or capture.
The pairing/Android/UI integration must admit the connected socket and original
one-use secret before entering this backend. Stream activity is NOT OBS usage.
"""
import threading

from magnolie_phone_camera_transport import WebcamMediaSocket
from magnolie_phone_webcam import NativeWebcamSession, WebcamUnavailable


class WebcamReceiveRun:
    def __init__(self, sock, session, secret, device, guard, *, muted=False, output_factory=NativeWebcamSession,
                 receiver_ready=None, data_guard=None):
        self.outputs = self.channel = None
        self.error = None
        self.ended = threading.Event()
        self.stopping = threading.Event()
        self._state = 'starting'
        admitted = False
        def original():
            guard()
            if self.stopping.is_set():
                raise WebcamUnavailable('webcam_session_retired')
            if admitted and data_guard is not None:
                data_guard()
        try:
            if ((receiver_ready is not None and not callable(receiver_ready)) or
                    (data_guard is not None and not callable(data_guard)) or
                    receiver_ready is not None and data_guard is None):
                raise ValueError('webcam_explicit_receiver_ready_requires_live_data_guard')
            self.outputs = output_factory(device, original, muted=muted, identity=session, prepare_only=True)
            def current():
                original()
                if self.outputs.closed:
                    raise self.outputs.error or WebcamUnavailable('webcam_output_retired')
            # Original capture/opt-in authority can prepare native outputs, but
            # is NOT bilateral data admission. Only after actual endpoints are
            # ready may the authenticated controller announce receiver-ready.
            # The callback must use its original bounded control-send path.
            current()
            if receiver_ready is not None:
                receiver_ready()
            admitted = True
            current()  # A callback/flag alone cannot replace the actual agreement.
            self.outputs.arm_media_deadline()  # Timing only; no fresh permission/PTS anchor.
            self.channel = WebcamMediaSocket(sock, session, secret, current, sending=False)
        except BaseException:
            sock.close()
            if self.outputs is not None:
                self.outputs.close()
            raise
        self.worker = threading.Thread(target=self._receive, name='Magnolie webcam receiver', daemon=True)
        self.worker.start()

    @property
    def state(self):
        if self.ended.is_set():
            return 'failed' if self.error is not None else 'stopped'
        if self.stopping.is_set():
            return 'stopping'
        return self._state

    def _receive(self):
        try:
            while True:
                packet = self.channel.receive()
                self.outputs.write(*packet)
                required = ('video',) if self.outputs.muted else ('video', 'audio')
                if all(track in self.outputs.positions for track in required):
                    self._state = 'streaming'
        except Exception as error:
            if not self.stopping.is_set():
                self.error = error
        finally:
            try:
                self.channel.close()
                self.outputs.close()
            except Exception as error:
                self.error = error
            finally:
                self.ended.set()

    def stop(self):
        # Closing the original socket interrupts a pending read immediately.
        # The worker finally retires both native outputs. No restart path.
        if not self.ended.is_set():
            self.stopping.set()
            self.channel.close()
        if not self.ended.wait(timeout=8):
            raise WebcamUnavailable('webcam_native_shutdown_pending')
        self.worker.join(timeout=1)
        self.outputs.monitor.join(timeout=1)
        if self.worker.is_alive() or self.outputs.monitor.is_alive():
            raise WebcamUnavailable('webcam_native_shutdown_pending')
