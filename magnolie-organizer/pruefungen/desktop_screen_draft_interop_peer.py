"""Opt-in desktop fixture: generated JPEG on two IPv4 loopback sockets."""

from io import BytesIO
from pathlib import Path
import socket
import sys
from time import monotonic

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_desktop_screen_control import DesktopScreenDraftChannel, DesktopScreenDraftControl
from magnolie_desktop_screen_encode import DesktopScreenJpeg
from magnolie_desktop_screen_send import DesktopScreenSendLane
from magnolie_telefon import SecureChannel


def listener():
    endpoint = socket.socket()
    try:
        endpoint.bind(('127.0.0.1', 0))
        endpoint.listen(1)
        endpoint.settimeout(5)
        return endpoint
    except BaseException:
        endpoint.close()
        raise


def main():
    with listener() as original, listener() as media:
        print(original.getsockname()[1], flush=True)
        control_socket, remote = original.accept()
        with control_socket:
            control_socket.settimeout(.5)
            parent = SecureChannel(control_socket, bytes(16), b'\x02' * 32, b'\x05' * 4, b'\x01' * 32, b'\x04' * 4)
            wire = DesktopScreenDraftChannel(parent, lambda: None)
            request = wire.body_from(parent, parent.receive())
            control = DesktopScreenDraftControl(parent, request, wire.require_current, deadline=monotonic() + 5)
            assert request['mode'] == 2
            session, secret = bytes(range(16)), bytes(range(32, 64))  # Disposable fixture keys.
            control.publish_offer(session=session.hex(), secret=secret.hex(), port=media.getsockname()[1],
                                  width=57, height=33, write_original=wire.write)
            accepted, data_peer = media.accept()
            with accepted:
                assert data_peer[0] == remote[0]
                lane = DesktopScreenSendLane(accepted, session, secret, 2, 57, 33,
                                             control.setup_deadline, control.require_current)
                try:
                    transcript = lane.prove()
                    assert control.receive(parent, wire.body_from(parent, parent.receive()))
                    with Image.new('RGB', (57, 33), (7, 110, 228)) as image:
                        output = BytesIO()
                        image.save(output, format='JPEG')
                        jpeg = DesktopScreenJpeg(0, output.getvalue())
                    lane.authorize_send(transcript, lambda: bool(jpeg.data),
                                        lambda guard: control.publish_send(transcript, guard, wire.write))
                    lane.write_record(None)
                    lane.write_record(jpeg)
                    assert control.receive(parent, wire.body_from(parent, parent.receive()))
                    try:
                        lane.write_record(None)
                    except PermissionError:
                        assert lane.drained
                    else:
                        raise AssertionError('original STOP did not retire the media lane')
                    # Evidence that ordinary traffic is still possible on the
                    # exact parent; this test does not start a Notes dispatcher.
                    assert parent.receive() == {'type': 'ping'}
                    parent.send({'type': 'pong'})
                finally:
                    lane.stop()


if __name__ == '__main__':
    main()
