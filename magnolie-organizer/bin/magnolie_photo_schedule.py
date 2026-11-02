"""Native manual/automatic photo-run coordination (#329), inert on import.

No timer/thread, store, network, source scan or implicit consent is created.
The existing desktop event loop must supply a fresh native binding callback and
drive take_due; only the real worker-end callback may release the active run.
"""
from dataclasses import dataclass
import re
import secrets
import threading

from magnolie_file_transfer import NativeTransferBinding, TransferError


@dataclass(frozen=True, eq=False)
class NativePhotoSyncScope:
    binding: NativeTransferBinding
    source_epoch: str
    owner: object

    def __post_init__(self):
        if (type(self.binding) is not NativeTransferBinding or self.owner is None
                or self.binding.sender_id == self.binding.receiver_id
                or type(self.source_epoch) is not str or re.fullmatch(r"[0-9a-f]{64}", self.source_epoch) is None):
            raise TransferError("photo_schedule_invalid_native_scope")


@dataclass(frozen=True, eq=False)
class NativePhotoRun:
    id: str
    scope: NativePhotoSyncScope
    trigger: str


class PhotoSyncSchedule:
    """Scheduling is not transfer/publication permission or a saved receipt.

    Manual is always the initial mode. Persisted UI settings must be protected
    and explicitly applied by the native desktop controller, not inferred from
    pairing or Android READ permission. Mode changes do not alter file bindings,
    manifests, accepted members, source rights or shared baselines.
    """
    INTERVAL_MS = 60_000
    DEBOUNCE_MS = 1_000

    def __init__(self, current_scope, monotonic_ms):
        self._current_scope = current_scope
        self._clock = monotonic_ms
        self._gate = threading.RLock()
        self._mode = "manual"
        self._active = None
        self._due = None
        self._dirty = False
        self._closed = False
        self._last_time = None

    @property
    def mode(self):
        with self._gate:
            return self._mode

    @property
    def active(self):
        with self._gate:
            return self._active

    def _now(self):
        value = self._clock()
        if type(value) is not int or not 0 <= value <= 2**63 - 1 - self.INTERVAL_MS or self._last_time is not None and value < self._last_time:
            raise TransferError("photo_schedule_clock_changed")
        self._last_time = value
        return value

    def _ready(self):
        if self._closed:
            raise TransferError("photo_schedule_closed")

    def _scope(self):
        value = self._current_scope()
        if value is not None and type(value) is not NativePhotoSyncScope:
            raise TransferError("photo_schedule_invalid_native_scope")
        return value

    @staticmethod
    def _same(first, second):
        return (second is not None and first.binding == second.binding and first.source_epoch == second.source_epoch
                and first.owner is second.owner)

    def set_mode(self, mode):
        with self._gate:
            self._ready()
            if type(mode) is not str or mode not in {"manual", "automatic"}:
                raise TransferError("photo_schedule_invalid_mode")
            if mode == self._mode:
                return
            now = self._now()
            self._mode = mode
            self._dirty = False
            self._due = now if mode == "automatic" else None

    def request_now(self):
        with self._gate:
            self._ready()
            self._now()
            # Show the current run's progress, never start a parallel scan.
            if self._active is not None:
                return self._active
            scope = self._scope()
            if scope is None:
                raise TransferError("photo_schedule_not_ready")
            return self._begin(scope, "manual")

    def hint_changed(self):
        with self._gate:
            self._ready()
            if self._mode != "automatic":
                return
            now = self._now()
            if self._active is not None:
                self._dirty = True
            else:
                wanted = now + self.DEBOUNCE_MS
                self._due = wanted if self._due is None else min(self._due, wanted)

    def take_due(self):
        with self._gate:
            self._ready()
            if self._mode != "automatic" or self._active is not None:
                return None
            now = self._now()
            if self._due is None or now < self._due:
                return None
            scope = self._scope()
            if scope is None:  # Offline/locked/revoked is pause, not missing-photo evidence.
                return None
            return self._begin(scope, "automatic")

    def _begin(self, scope, trigger):
        self._active = NativePhotoRun(secrets.token_hex(16), scope, trigger)
        self._due = None
        self._dirty = False
        return self._active

    def cancellation_requested(self, run):
        with self._gate:
            if run is None or self._closed or self._active is not run:
                return True
            return not self._same(run.scope, self._scope())

    def finished(self, run):
        """Exact native worker END only, never a wire ACK or cancel request."""
        with self._gate:
            if self._active is not run or run is None:
                return False
            now = self._now()
            self._active = None
            if not self._closed and self._mode == "automatic":
                self._due = now + (self.DEBOUNCE_MS if self._dirty else self.INTERVAL_MS)
            self._dirty = False
            return True

    def close(self):
        with self._gate:
            self._closed = True
            self._mode = "manual"
            self._due = None
            self._dirty = False
            # Keep active ownership until its actual native worker has ended.
