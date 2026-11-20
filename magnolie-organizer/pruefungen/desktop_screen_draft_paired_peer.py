"""Private #245 interop fixture: two production FS1 readers, synthetic portal.

Peer stores contain disposable pins. This never performs discovery or pairing.
"""

from pathlib import Path
from select import select
import sys
from tempfile import TemporaryDirectory
from threading import Event, Lock
from time import monotonic, time_ns
from unittest.mock import patch
from uuid import uuid4

from desktop_screen_draft_interop_peer import SyntheticLocalRun, draft, listener, GLib
import magnolie_desktop_screen_control as control
from magnolie_desktop_screen_dispatch import DesktopScreenDraftDispatch
from magnolie_telefon import PhoneService, now_ms, unb64
from test_telefon import FakeBluetooth, _complete_peer


class Desktop(PhoneService):
    ping_id = None

    def _payload(self, peer, channel, payload, scoped_reference=None):
        super()._payload(peer, channel, payload, scoped_reference)
        if self.ping_id is not None and payload.get('type') == 'pong' and payload['ping_id'] == self.ping_id:
            self.pong.set()


def main(stop_before_phone_approval=False, stop_after_phone_approval=False, desktop_clock_behind=False):
    desktop_stops = stop_before_phone_approval or stop_after_phone_approval
    with TemporaryDirectory(prefix='magnolie-screen-paired-') as root, listener() as endpoint:
        service = Desktop(str(Path(root) / 'telefon'), 'Isolated desktop', bluetooth_backend=FakeBluetooth())
        service.enabled = True
        service._native_photo_built = service._native_camera_built = False
        service.pong = Event()
        identity = service.store.identity
        print(endpoint.getsockname()[1], identity['device_id'], identity['static_public'], flush=True)
        peer_id, public = sys.stdin.readline().split()
        peer = _complete_peer(peer_id, public=unb64(public, 32))
        peer['grants'] = {}  # The initial peer's revision 1 has not yet been received.
        service.store.peers = [peer]
        service.store.save_peers()
        channel_socket, _ = endpoint.accept()
        dispatch = service._desktop_screen_draft_dispatch = DesktopScreenDraftDispatch(service)
        deadline = monotonic() + 19
        loop = GLib.MainLoop()
        state = Lock()
        original = run = pending = cleanup = None
        armed = stopped_here = False
        viewer_drained = not desktop_stops
        errors = []

        def receive(actual, body, packet):
            nonlocal pending
            actual.require_current()
            if stop_before_phone_approval and body['op'] in ('prepared', 'stop'):
                errors.append(AssertionError('unapproved PREPARED or echoed STOP'))
            with state:
                active = run
                if active is None:
                    if pending is None and body['op'] == 'request' and body['mode'] == 2:
                        pending = body
                        return True
                    return False
            return active.receive(actual.channel, packet)

        def ended(result):
            nonlocal cleanup
            cleanup = result

        def tick():
            nonlocal original, run, armed, stopped_here, viewer_drained
            try:
                if monotonic() >= deadline:
                    raise TimeoutError('paired draft did not finish')
                if original is None:
                    channel = service.connections.get(peer_id)
                    if channel is not None:
                        original = dispatch.attach(peer_id, channel, receive)
                        # An unsolicited but syntactically well-framed draft is
                        # dropped even before the explicit native phone action.
                        channel.send(dict(type='desktop_screen_draft', body={}))
                        service.ping_id = str(uuid4())
                        channel.send(dict(type='ping', ping_id=service.ping_id, sent_ms=now_ms()))
                elif not armed:
                    if service.pong.is_set():
                        service.pong.clear()
                        service.ping_id = None
                        armed = True
                        print('armed', flush=True)
                elif run is None:
                    with state:
                        if pending is not None:
                            run = draft.DesktopScreenDraftAttempt(original.channel, pending, original.require_current,
                                bus=None, provider=None, mode='extend', parent_window='synthetic', width=57, height=33,
                                deadline=deadline, ended=ended)
                            run.begin()
                elif desktop_stops and not stopped_here and select([sys.stdin], [], [], 0)[0]:
                    assert sys.stdin.readline() == 'stop\n'
                    stopped_here = True
                    run.stop()
                elif cleanup is not None and service.ping_id is None:
                    assert cleanup == draft.DesktopScreenAttemptCleanup(draft.ScreenRunCleanup(True, True, True), True)
                    service.ping_id = str(uuid4())
                    original.channel.send(dict(type='ping', ping_id=service.ping_id, sent_ms=now_ms()))
                elif service.pong.is_set():
                    # No parent close can be mistaken for viewer retirement.
                    if not viewer_drained:
                        if not select([sys.stdin], [], [], 0)[0]:
                            return True
                        assert sys.stdin.readline() == 'viewer-drained\n'
                        viewer_drained = True
                    original.retire()
                    assert original.release()
                    original.channel.send(dict(type='close', reason='normal'))
                    print('same-parent-pong', flush=True)
                    loop.quit()
                    return False
                return True
            except Exception as error:
                errors.append(error)
                loop.quit()
                return False

        GLib.timeout_add(25, tick)
        try:
            def wall_ns():
                return time_ns() - (2_000_000_000 if desktop_clock_behind else 0)

            with (patch.object(draft, 'DesktopScreenLocalRun', SyntheticLocalRun),
                  patch.object(control, 'time_ns', wall_ns)):
                assert service._start_handler(channel_socket, '127.0.0.1', 'wifi')
                loop.run()
            assert not errors, errors
            assert stopped_here is desktop_stops and viewer_drained
            assert service.pong.is_set()
        finally:
            if run is not None:
                run.stop()
            service.stop_event.set()
            channel_socket.close()
            for worker in list(service._workers):
                worker.join(3)
                assert not worker.is_alive()


if __name__ == '__main__':
    main(stop_before_phone_approval='--desktop-stop-before-phone-approval' in sys.argv[1:],
         stop_after_phone_approval='--desktop-stop-after-phone-approval' in sys.argv[1:],
         desktop_clock_behind='--desktop-clock-behind' in sys.argv[1:])
