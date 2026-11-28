"""Private metadata-only challenge for a complete PC photo+video pass.

The native caller owns the authenticated WLAN channel, actual controls,
settings token and monotonic deadline. This codec never grants or opens I/O.
"""
from copy import deepcopy
from threading import Event
from dataclasses import asdict
from hashlib import sha256
import re
from uuid import uuid4

from magnolie_file_transfer import NativeTransferBinding, TransferError
from magnolie_media_sync import FIELDS, effective
from magnolie_telefon import canonical, valid_uuid

REQUEST = 'file_transfer.media_mixed_preflight'
RESULT = 'file_transfer.media_mixed_preflight.result'
TTL_MS = 10_000
_MAX_WALL = 253402300799999
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_FIELDS = {'type', 'v', 'message_id', 'kind', 'created_ms', 'expires_ms', 'body'}
_BODY = {'format', 'settings_sha256', 'binding_sha256'}


def _invalid():
    return TransferError('media_mixed_preflight_invalid')


def _witness(settings, binding):
    values = effective(settings)
    if (set(values) != set(FIELDS) or values['enabled'] is not True or values['photos_enabled'] is not True
            or values['videos_enabled'] is not True or values['direction'] != 'pc_to_phone'
            or values['collection_mode'] != 'entire_collection' or type(binding) is not NativeTransferBinding
            or binding.destination_token != '0'*64):
        raise _invalid()
    return dict(format=1, settings_sha256=sha256(b'magnolie-mixed-settings-v1\0'+canonical(settings)).hexdigest(),
                binding_sha256=sha256(b'magnolie-mixed-control-v1\0'+canonical(asdict(binding))).hexdigest())


def _frame(kind, body, now, expiry):
    if type(now) is not int or type(expiry) is not int or not 0 <= now < expiry <= _MAX_WALL or expiry-now > TTL_MS:
        raise _invalid()
    return dict(type='message', v=1, message_id=str(uuid4()), kind=kind, created_ms=now, expires_ms=expiry, body=body)


def _parse(message, kind, fields, now):
    if (type(message) is not dict or set(message) != _FIELDS or type(now) is not int
            or message['type'] != 'message' or type(message['v']) is not int or message['v'] != 1
            or message['kind'] != kind or not valid_uuid(message['message_id'], 4)
            or type(message['created_ms']) is not int or type(message['expires_ms']) is not int
            or not 0 <= now < message['expires_ms'] <= _MAX_WALL
            or not 0 <= message['created_ms'] <= now
            or message['expires_ms']-message['created_ms'] > TTL_MS):
        raise _invalid()
    body = message['body']
    if (type(body) is not dict or set(body) != fields or type(body['format']) is not int or body['format'] != 1
            or any(type(body[name]) is not str or not _HEX.fullmatch(body[name])
                   for name in ('settings_sha256', 'binding_sha256'))):
        raise _invalid()
    return body


def create_request(settings, binding, now):
    return _frame(REQUEST, _witness(settings, binding), now, now+TTL_MS)


def read_request(request, settings, binding, now):
    body = _parse(request, REQUEST, _BODY, now)
    if body != _witness(settings, binding):
        raise _invalid()
    return request['message_id']


def create_ready_result(request, settings, binding, now):
    """Positive only: call after the same native owner proves BOTH RECEIVE rights."""
    request_id = read_request(request, settings, binding, now)
    return _frame(RESULT, dict(request['body'], request_id=request_id), now, request['expires_ms'])


def require_ready_result(message, request, settings, binding, now):
    request_id = read_request(request, settings, binding, now)
    body = _parse(message, RESULT, _BODY | {'request_id'}, now)
    if (message['message_id'] == request_id or message['created_ms'] < request['created_ms']
            or message['expires_ms'] != request['expires_ms'] or body != dict(request['body'], request_id=request_id)):
        raise _invalid()


class PendingMixedPreflight:
    """One request; callers serialize access in the original connection lane."""
    def __init__(self, settings, binding, *, wall, monotonic_ms, current):
        self._settings = deepcopy(settings)
        self._binding = binding
        self._wall = wall
        self._clock = monotonic_ms
        self._current = current
        self._started = self._clock()
        self._request = create_request(self._settings, binding, self._wall())
        self._written = self._ready = self._closed = False
        self._changed = Event()

    def require_current(self):
        if (self._closed or not 0 <= self._clock() - self._started < TTL_MS
                or self._current() is not True):
            self._closed = True
            raise _invalid()
        read_request(self._request, self._settings, self._binding, self._wall())

    def request(self):
        self.require_current()
        if self._written:
            raise _invalid()
        return deepcopy(self._request)

    def mark_written(self):
        self.require_current()
        if self._written:
            raise _invalid()
        self._written = True

    def observe(self, reply):
        self.require_current()
        if not self._written or self._ready:
            raise _invalid()
        require_ready_result(reply, self._request, self._settings, self._binding, self._wall())
        self._ready = True
        self._changed.set()

    def wait_for_reply(self, stopped):
        # The receiver may own the connection gate; only consume/revalidate
        # the proof under that gate after returning from this bounded wait.
        while not stopped() and 0 <= self._clock() - self._started < TTL_MS:
            if self._changed.wait(.1):
                return self._ready and not self._closed and not stopped()
        return False

    def consume(self):
        self.require_current()
        if not self._ready:
            raise _invalid()
        self.close()

    def close(self):
        self._closed = True
        self._changed.set()


class MixedPcPassAdmission:
    """The original proof may admit one worker, not a subsequent pass.

    The request's short deadline is checked at consumption. Thereafter only
    this bounded worker and its original live witnesses may use the admission.
    """
    def __init__(self, token, preferences, roots, book, *, deadline, clock, current, boundary_current=None):
        self.token, self.preferences, self.roots, self.book = token, preferences, roots, book
        self._deadline, self._clock, self._current = deadline, clock, current
        self._boundary_current = boundary_current or current
        self._started = self._clock()
        self._worker = None
        self._mapping_snapshot = None
        self._closed = False

    def require_current(self):
        if self._closed or not self._started <= self._clock() < self._deadline or self._current() is not True:
            self.close()
            raise TransferError('media_mixed_pass_original_owner_required')

    def claim(self, worker):
        self.require_current()
        if self._worker is not None or worker is None:
            raise TransferError('media_mixed_pass_original_worker_required')
        self._worker = worker

    def require_worker(self, worker):
        self.require_current()
        if worker is None or self._worker is not worker:
            raise TransferError('media_mixed_pass_original_worker_required')

    def require_boundary(self, worker):
        self.require_worker(worker)
        if self._boundary_current() is not True:
            self.close()
            raise TransferError('media_mixed_pass_original_owner_required')

    def require_unmapped_sources(self, worker, mappings):
        """Both domains must pass protected mapping review before inventory.

        This narrow pass never treats a mapped phone original as a new PC row.
        Keep the single mapping snapshot for the subsequent worker boundaries.
        """
        self.require_worker(worker)
        snapshot = None
        for kind in ('images', 'video'):
            snapshot, records, cursor = mappings.candidate_page(kind, expected=snapshot, limit=1)
            if records or cursor is not None:
                self.close()
                raise TransferError('media_source_mapped_phone_update_unavailable')
        self.require_worker(worker)
        self._mapping_snapshot = snapshot
        return snapshot

    def require_mapping_snapshot(self, worker, mappings):
        self.require_worker(worker)
        if self._mapping_snapshot is None or mappings.read() != self._mapping_snapshot:
            self.close()
            raise TransferError('photo_mappings_candidate_snapshot_changed')

    def close(self):
        self._closed = True
        self._worker = None
