"""Private dispatch attachment, for a native caller only. No requests are queued."""

from dataclasses import dataclass, field
from threading import Event, Lock

from magnolie_desktop_screen_control import DesktopScreenDraftChannel


def _paired_peer(store, peer_id):
    return next((peer for peer in store.peers if peer.get('device_id') == peer_id and
                 peer.get('state') == 'paired'), None)


@dataclass(frozen=True, eq=False)
class _OriginalSelection:
    dispatch: object = field(repr=False)
    store: object = field(repr=False)
    generation: int
    peer_id: str
    channel: object = field(repr=False)
    key: str = field(repr=False)
    label: str

    def require_parent(self):
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


class _OriginalReader:
    def __init__(self, selection, receive):
        self.dispatch, self._selection = selection.dispatch, selection
        self.store, self.generation = selection.store, selection.generation
        self.peer_id, self.channel = selection.peer_id, selection.channel
        self.key, self.label = selection.key, selection.label
        self.retired = Event()
        self.receive = receive
        self.delivering = False  # Under the dispatch lock only.
        self.wire = DesktopScreenDraftChannel(self.channel, self._require_live)

    def _require_live(self):
        if self.retired.is_set():
            raise PermissionError('desktop_screen_draft_reader_retired')
        self._selection.require_parent()

    def require_terminal_parent(self):
        """Transport-only guard for terminal STOP, never capture authority."""
        if self.dispatch._owner is not self:
            raise PermissionError('desktop_screen_draft_reader_released')
        self._selection.require_parent()

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

    def _selection(self, peer_id, channel):
        service = self.service
        store, generation = service.store, service._generation
        peer = _paired_peer(store, peer_id)
        return _OriginalSelection(self, store, generation, peer_id, channel,
            (peer or {}).get('static_public', ''), (peer or {}).get('display_name') or peer_id)

    def select(self, peer_id):
        """Freeze the displayed peer's current WLAN, without reserving a slot."""
        with self.service.lock:
            selection = self._selection(peer_id, self.service.connections.get(peer_id))
            if selection.channel is None:
                raise PermissionError('desktop_screen_draft_reader_retired')
            DesktopScreenDraftChannel(selection.channel, selection.require_parent)
            return selection

    def require_selection(self, selection):
        if type(selection) is not _OriginalSelection or selection.dispatch is not self:
            raise PermissionError('desktop_screen_draft_original_selection_required')
        selection.require_parent()

    def attach(self, peer_id, channel, receive, *, selection=None):
        """Take one local slot. Reader callback must not run GTK or join
        workers and must fence handoff with the supplied lease. Attachment
        itself is not local capture consent.
        """
        with self._lock:
            if self._owner is not None:
                raise PermissionError('desktop_screen_draft_reader_busy')
            if selection is None:
                selection = self._selection(peer_id, channel)
            else:
                self.require_selection(selection)
                if selection.peer_id != peer_id or selection.channel is not channel:
                    raise PermissionError('desktop_screen_draft_original_selection_required')
            original = _OriginalReader(selection, receive)
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
