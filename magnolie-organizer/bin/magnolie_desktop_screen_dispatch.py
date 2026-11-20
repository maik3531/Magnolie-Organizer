"""Private dispatch attachment, for a native caller only. No requests are queued."""

from threading import Event, Lock

from magnolie_desktop_screen_control import DesktopScreenDraftChannel


def _paired_peer(store, peer_id):
    return next((peer for peer in store.peers if peer.get('device_id') == peer_id and
                 peer.get('state') == 'paired'), None)


class _OriginalReader:
    def __init__(self, dispatch, peer_id, channel, receive):
        self.dispatch = dispatch
        service = dispatch.service
        self.store, self.generation = service.store, service._generation
        self.peer_id, self.channel = peer_id, channel
        peer = _paired_peer(self.store, peer_id)
        self.key = peer and peer.get('static_public')
        self.label = (peer or {}).get('display_name') or peer_id
        self.retired = Event()
        self.receive = receive
        self.delivering = False  # Under the dispatch lock only.
        self.wire = DesktopScreenDraftChannel(channel, self._require_live)

    def _require_live(self):
        if self.retired.is_set():
            raise PermissionError('desktop_screen_draft_reader_retired')
        self._require_parent()

    def require_terminal_parent(self):
        """Transport-only guard for terminal STOP, never capture authority."""
        if self.dispatch._owner is not self:
            raise PermissionError('desktop_screen_draft_reader_released')
        self._require_parent()

    def _require_parent(self):
        service = self.dispatch.service
        if (service._desktop_screen_draft_dispatch is not self.dispatch or
                self.store is not service.store or self.generation != service._generation or
                not service.enabled or service.stop_event.is_set() or
                service.connections.get(self.peer_id) is not self.channel or
                service.connection_transports.get(self.peer_id) != 'wifi'):
            raise PermissionError('desktop_screen_draft_reader_retired')
        peer = _paired_peer(self.store, self.peer_id)
        if not self.key or not peer or peer.get('static_public') != self.key:
            raise PermissionError('desktop_screen_draft_reader_pairing_changed')

    def require_current(self):
        """Worker-safe origin guard; a native caller must also check its consent."""
        self.wire.require_current()

    def retire(self):
        self.dispatch._retire(expected=self)

    def release(self):
        """Release after native cleanup. Never replace a retiring owner early."""
        return self.dispatch._release(self)


class DesktopScreenDraftDispatch:
    def __init__(self, service):
        self.service = service
        self._lock = Lock()
        self._owner = None

    def attach(self, peer_id, channel, receive):
        """Take one local slot. Reader callback must not run GTK or join
        workers and must fence handoff with the supplied lease. Attachment
        itself is not local capture consent.
        """
        with self._lock:
            if self._owner is not None:
                raise PermissionError('desktop_screen_draft_reader_busy')
            original = _OriginalReader(self, peer_id, channel, receive)
            self._owner = original
            return original

    def receive_authenticated(self, store, generation, peer, channel, packet):
        with self._lock:
            original = self._owner
        if (original is None or original.channel is not channel or original.store is not store or
                original.generation != generation or peer.get('device_id') != original.peer_id or
                peer.get('static_public') != original.key):
            return False
        try:
            body = original.wire.body_from(channel, packet)
        except ValueError:
            return False  # A malformed draft is never an ordinary message or ACK.
        except OSError:
            original.retire()
            return False
        with self._lock:
            if self._owner is not original or original.retired.is_set() or original.delivering:
                return False
            original.delivering = True
        try:
            return original.receive(original, body, packet)
        except Exception:
            original.retire()  # Failure of this optional lane does not close Notes.
            return False
        finally:
            with self._lock:
                original.delivering = False

    def retire(self, channel=None):
        self._retire(channel=channel)

    def _retire(self, *, channel=None, expected=None):
        with self._lock:
            original = self._owner
            if (original is None or original.retired.is_set() or
                    (channel is not None and original.channel is not channel) or
                    (expected is not None and original is not expected)):
                return
            original.retired.set()

    def _release(self, original):
        with self._lock:
            if self._owner is not original or not original.retired.is_set():
                raise PermissionError('desktop_screen_draft_reader_not_retired')
            if original.delivering:
                return False
            self._owner = None
            return True
