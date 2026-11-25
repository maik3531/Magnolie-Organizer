"""Opt-in, test-only phase measurements for #753; no product telemetry.

Only fixed phase names, counts and monotonic durations are recorded. Arguments,
results, exception text, paths, peer identifiers and photo contents are not kept.
No product getter/lock is used to capture a running call. Inclusive times overlap;
even exclusive times from different threads must not be added as wall time.
"""
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
import json
from pathlib import Path
import threading
import time


@dataclass
class _Span:
    phase: str
    started_ns: int
    children_ns: int = 0


class PhaseRecorder:
    """One measurement window, with thread-local nesting and a frozen cutoff."""

    def __init__(self, clock=time.perf_counter_ns):
        self._clock = clock
        self._lock = threading.Lock()
        self._enabled = False
        self._started_ns = None
        self._phases = {}
        self._stacks = {}
        self._lanes = {}
        self._marks = {}
        self._events = {}
        self._frozen = None

    def start(self):
        with self._lock:
            if self._started_ns is not None:
                raise RuntimeError('measurement window already started')
            self._started_ns = self._clock()
            self._enabled = True

    def mark(self, phase):
        with self._lock:
            if self._enabled and phase not in self._marks:
                self._marks[phase] = self._clock() - self._started_ns

    def event(self, name):
        with self._lock:
            if self._enabled:
                self._events[name] = self._events.get(name, 0) + 1
                if name not in self._marks:
                    self._marks[name] = self._clock() - self._started_ns

    def call(self, phase, function, *args, **kwargs):
        if not self._enabled:
            return function(*args, **kwargs)
        thread = threading.get_ident()
        with self._lock:
            if self._enabled:
                stack = self._stacks.setdefault(thread, [])
                self._lanes.setdefault(thread, len(self._lanes) + 1)
                span = _Span(phase, self._clock())
                stack.append(span)
                row = self._phases.setdefault(phase, dict(started=0, completed=0,
                    errors=0, active=0, inclusive_ns=0, exclusive_ns=0, max_ns=0))
                row['started'] += 1
            else:
                span = None
        # Neither the original call nor its I/O runs under the recorder lock.
        if span is None:
            return function(*args, **kwargs)
        failed = False
        try:
            return function(*args, **kwargs)
        except BaseException:
            failed = True
            raise
        finally:
            with self._lock:
                if self._enabled:
                    elapsed = self._clock() - span.started_ns
                    stack.pop()
                    if stack:
                        stack[-1].children_ns += elapsed
                    row['completed'] += 1
                    row['errors'] += int(failed)
                    row['inclusive_ns'] += elapsed
                    row['exclusive_ns'] += elapsed - span.children_ns
                    row['max_ns'] = max(row['max_ns'], elapsed)

    def _snapshot_locked(self):
        now = self._clock() if self._started_ns is not None else None
        rows = deepcopy(self._phases)
        active = []
        for thread, stack in self._stacks.items():
            for depth, span in enumerate(stack):
                elapsed = now - span.started_ns
                child = now - stack[depth + 1].started_ns if depth + 1 < len(stack) else 0
                own = elapsed - span.children_ns - child
                row = rows[span.phase]
                row['active'] += 1
                row['inclusive_ns'] += elapsed
                row['exclusive_ns'] += own
                row['max_ns'] = max(row['max_ns'], elapsed)
                active.append(dict(lane=self._lanes[thread], depth=depth,
                    phase=span.phase, elapsed_ns=elapsed, self_ns=own))
        return dict(elapsed_ns=None if now is None else now - self._started_ns,
            phases=rows, active_spans=active, marks_ns=dict(self._marks), events=dict(self._events))

    def snapshot(self):
        with self._lock:
            return deepcopy(self._frozen) if self._frozen is not None else self._snapshot_locked()

    def freeze(self):
        with self._lock:
            if self._frozen is None:
                self._frozen = self._snapshot_locked()
                self._enabled = False
            return deepcopy(self._frozen)


class PhotoReceiveTiming(PhaseRecorder):
    def __init__(self):
        super().__init__()
        self.report = None

    def checkpoint(self, *, deadline_met, automatic_mode):
        # Call before an assertion can enter fixture cleanup. Do not call
        # session.snapshot(), receiver.progress(), or any authority check here.
        snapshot = self.freeze()
        events = snapshot['events']
        wait_started = snapshot['marks_ns'].get('deadline_wait_started')
        self.report = dict(format=1, issue=753, scope='synthetic-wifi-photo-receive',
            clock='perf_counter_ns', limit_seconds=12, checkpoint_reached=True,
            deadline_event='activity_ended', deadline_met=deadline_met,
            wait_elapsed_ns=None if wait_started is None else snapshot['elapsed_ns'] - wait_started,
            automatic_mode=automatic_mode, chunk_requests=events.get('chunk_request', 0),
            saved_messages=events.get('saved_message', 0), peer_errors=events.get('peer_error', 0),
            activity_started=events.get('activity_started', 0), activity_ended=events.get('activity_ended', 0),
            status_requests=events.get('status', 0), discover_requests=events.get('discover', 0), timing=snapshot)

    def write(self, output):
        if self.report is None:
            # An earlier failure must not appear as a completed deadline probe.
            self.report = dict(format=1, issue=753, scope='synthetic-wifi-photo-receive',
                clock='perf_counter_ns', limit_seconds=12, deadline_event='activity_ended', deadline_met=None,
                checkpoint_reached=False, timing=self.freeze())
        Path(output).write_text(json.dumps(self.report, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def install_receive_timing(monkeypatch, recorder):
    """Wrap exact methods for this fixture; preserve original calls/exceptions."""
    from magnolie_file_desktop_connection import NativeDesktopFileConnection, NativePhotoAlbumWorker
    from magnolie_file_receive import NativeFileReceiveOperation
    from magnolie_photo_preferences import ProtectedPhotoPreferences
    from magnolie_photo_mappings import ProtectedPhotoMappings
    import test_file_desktop_album_worker as peer_fixture
    from test_media_transport import PeerWire

    points = [
        (NativeDesktopFileConnection, '_receive_chunk', 'connection.receive_chunk'),
        (NativeDesktopFileConnection, 'accept_pending_offer', 'connection.accept_pending_offer'),
        (NativeDesktopFileConnection, 'review_pending_photos', 'connection.review_pending_photos'),
        (NativeDesktopFileConnection, 'request_next_chunk', 'connection.request_next_chunk'),
        (NativeDesktopFileConnection, 'publish_received', 'connection.publish_received'),
        (NativeDesktopFileConnection, '_commit_saved_media', 'connection.commit_saved_media'),
        (NativeDesktopFileConnection, '_receive_binding', 'connection.receive_binding'),
        (NativeDesktopFileConnection, '_receiving_policy', 'connection.receiving_policy'),
        (NativeDesktopFileConnection, '_verify_catalog_witness', 'connection.catalog_witness'),
        (NativeDesktopFileConnection, 'finish_saved_receive', 'connection.finish_saved_receive'),
        (NativeFileReceiveOperation, 'receive_chunk_message', 'receiver.receive_chunk'),
        (NativeFileReceiveOperation, 'publish_completed', 'receiver.publish_completed'),
        (NativeFileReceiveOperation, 'commit_saved_receipts', 'receiver.commit_saved_receipts'),
        (NativeFileReceiveOperation, 'saved_receipt_message', 'receiver.saved_receipt_message'),
        (ProtectedPhotoPreferences, 'read', 'preferences.read'),
        (ProtectedPhotoPreferences, '_sync', 'preferences.sync'),
        (ProtectedPhotoMappings, 'checkpoint', 'mappings.checkpoint'),
        (ProtectedPhotoMappings, 'validate_availability', 'mappings.validate_availability'),
        (ProtectedPhotoMappings, '_sync', 'mappings.sync'),
        (NativePhotoAlbumWorker, '_wait', 'worker.wait_and_call'),
        (PeerWire, 'receive', 'peer.receive'),
        (PeerWire, 'send', 'peer.deliver'),
    ]
    # Resolve inherited _sync before patching either class; otherwise the
    # mapping sync would also be counted as a preference sync.
    originals = [(owner, name, label, getattr(owner, name)) for owner, name, label in points]
    for owner, name, label, original in originals:
        def make_wrapper(owner, label, original):
            @wraps(original)
            def measured(self, *args, **kwargs):
                if type(self) is not owner:
                    return original(self, *args, **kwargs)
                return recorder.call(label, original, self, *args, **kwargs)
            return measured
        monkeypatch.setattr(owner, name, make_wrapper(owner, label, original))
    # Only the synthetic peer's local select alias; no global socket/I/O hook.
    original_select = peer_fixture.select
    monkeypatch.setattr(peer_fixture, 'select',
        lambda *args, **kwargs: recorder.call('peer.wait_readable', original_select, *args, **kwargs))
