"""Private, nonblocking owner for the read-only Wayland output helper (#727)."""

import os
import socket
import subprocess
from time import monotonic

from magnolie_desktop_screen_output import KWinOutputFeed


_BASELINE_S = 2
_TERM_S = .5
_MAX_RECORD = 270


class KWinOutputObserver:
    """Own exactly one supplied connection and one trusted helper executable.

    On the same main context as the screen run, the private caller drives
    tick() until it returns False. Even after close(), keep driving tick()
    until the owned helper exits. No session discovery or fallback exists.
    """

    def __init__(self, executable, connected):
        with connected:
            if (not os.path.isabs(executable) or connected.family != socket.AF_UNIX or
                    connected.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM):
                raise ValueError('kwin_original_wayland_connection_required')
            connected.getpeername()
            fd = connected.fileno()
            self._child = subprocess.Popen([os.fspath(executable), str(fd)], pass_fds=(fd,),
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, bufsize=0)
        self._feed = KWinOutputFeed()
        self._pending = b''
        self._baseline_deadline = monotonic() + _BASELINE_S
        self._kill_at = None
        try:
            os.set_blocking(self._child.stdout.fileno(), False)
        except OSError:
            self.close()
            self._child.kill()
            self._child.wait(_TERM_S)
            raise

    @property
    def feed(self):
        if self._kill_at is None and self._feed.witness is not None and not self._feed.witness.lost:
            return self._feed
        return None

    @property
    def drained(self):
        return self._child.stdout.closed and self._child.poll() is not None

    def tick(self):
        if self._kill_at is None:
            try:
                if (self._child.poll() is not None or
                        self._feed.witness is not None and self._feed.witness.lost or
                        self._feed.witness is None and monotonic() >= self._baseline_deadline):
                    self.close()
                else:
                    self._read()
            except OSError:
                self.close()
        if self._kill_at is not None and not self.drained and monotonic() >= self._kill_at:
            self._child.kill()
            self._kill_at = float('inf')
        return not self.drained

    def _read(self):
        try:
            data = os.read(self._child.stdout.fileno(), 8192)
        except BlockingIOError:
            return
        if not data or self._child.poll() is not None:
            self.close()
            return
        *records, self._pending = (self._pending + data).split(b'\n')
        for record in records:
            if not self._feed.consume(record + b'\n'):
                self.close()
                return
        if len(self._pending) >= _MAX_RECORD:
            self.close()

    def close(self):
        if self._kill_at is not None:
            return
        self._kill_at = monotonic() + _TERM_S
        self._feed.close()
        self._pending = b''
        self._child.stdout.close()
        self._child.terminate()
