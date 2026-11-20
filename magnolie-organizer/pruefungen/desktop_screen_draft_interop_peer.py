"""Opt-in desktop fixture: generated JPEG on two IPv4 loopback sockets."""

from io import BytesIO
from pathlib import Path
from select import select
import socket
import sys
from threading import Event, Thread
from time import monotonic
from unittest.mock import patch

from gi.repository import GLib
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_desktop_screen_attempt as draft
from magnolie_desktop_screen_control import DesktopScreenDraftChannel
from magnolie_desktop_screen_encode import DesktopScreenJpeg
from magnolie_desktop_screen_run import ScreenRunCleanup
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


class SyntheticLocalRun:
    """Test substitute for the unavailable compositor, not a product fallback."""

    def __init__(self, _bus, _provider, mode, _window, width, height, guard, ended):
        assert mode == 'extend'
        self.guard, self.ended = guard, ended
        self.ready, self.closed = False, False
        with Image.new('RGB', (width, height), (7, 110, 228)) as image:
            output = BytesIO()
            image.save(output, format='JPEG')
        self.frame = DesktopScreenJpeg(0, output.getvalue())

    def begin(self):
        self.guard()
        self.ready = True

    def media_current(self):
        return self.ready

    def take_latest(self):
        self.guard()
        result, self.frame = self.frame, None
        return result

    def stop(self):
        if not self.closed:
            self.ready, self.closed = False, True
            self.ended(ScreenRunCleanup(True, True, True))


def main():
    with listener() as original:
        print(original.getsockname()[1], flush=True)
        control_socket, _ = original.accept()
        with control_socket:
            control_socket.settimeout(.5)
            parent = SecureChannel(control_socket, bytes(16), b'\x02' * 32, b'\x05' * 4, b'\x01' * 32, b'\x04' * 4)
            wire = DesktopScreenDraftChannel(parent, lambda: None)
            request = wire.body_from(parent, parent.receive())
            loop = GLib.MainLoop()
            finished, reader_stopped = Event(), Event()
            results, errors = [], []

            def ended(result):
                results.append(result)
                finished.set()

            with patch.object(draft, 'DesktopScreenLocalRun', SyntheticLocalRun):
                run = draft.DesktopScreenDraftAttempt(parent, request, wire.require_current,
                    bus=None, provider=None, mode='extend', parent_window='synthetic',
                    width=57, height=33, deadline=monotonic() + 5, ended=ended)

            def read():
                def receive():
                    if not select([control_socket], [], [], 5)[0]:
                        raise TimeoutError('test control receive expired')
                    return parent.receive()

                try:
                    assert run.receive(parent, receive())  # PREPARED
                    assert run.receive(parent, receive())  # STOP
                    assert finished.wait(2)
                    assert receive() == {'type': 'ping'}
                    parent.send({'type': 'pong'})
                except Exception as error:
                    errors.append(error)
                    run.stop()
                finally:
                    reader_stopped.set()

            reader = Thread(target=read, daemon=True)
            run.begin()
            reader.start()
            until = monotonic() + 9

            def check_end():
                if reader_stopped.is_set() and finished.is_set() or monotonic() >= until:
                    loop.quit()
                    return False
                return True

            GLib.timeout_add(25, check_end)
            try:
                loop.run()
                assert not errors, errors
                assert reader_stopped.is_set() and len(results) == 1 and results[0].transport_drained
            finally:
                run.stop()
                control_socket.close()
                reader.join(1)


if __name__ == '__main__':
    main()
