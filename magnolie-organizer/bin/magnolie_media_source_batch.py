"""Actual all-original Linux collection selection (Refs #330).

One consumed native action, selected root, intent and saved-book identity.
This is not a cache-ready record, sender, wire offer or restart factory.
No member view can reacquire native rights from the observation below.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import copy
import secrets
import threading

from magnolie_file_transfer import CHUNK_BYTES, MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, TransferError, _portable_path
from magnolie_media_retention import NativeMediaRetention
from magnolie_media_sync import effective
from magnolie_telefon import canonical


@dataclass(frozen=True)
class NativeCollectionBatchObservation:
    _body: dict
    @property
    def body(self): return copy.deepcopy(self._body)
    @property
    def grants_read_authority(self): return False
    @property
    def is_saved_receipt(self): return False
    @property
    def permits_retirement(self): return False


class NativeCollectionMediaBatch:
    def __init__(self, owner, action, expected, selected, members, kind, native_current, all_new_only=False):
        from magnolie_media_source_pc import NativeCollectionMediaSource
        if type(owner) is not NativeCollectionMediaSource or not owner._gate.locked():
            raise TransferError('media_source_batch_original_owner_required')
        self._owner = owner; self._selected = selected; self._members = tuple(members); self._kind = kind
        self._native_current = native_current
        self._all_new_only = all_new_only
        self._original_permission, self._token = owner._source_permission(action, expected, kind)
        if expected.policy.mapping_store is not None: owner._mappings.verify_witness(expected.policy.mapping_store)
        self._mapping_snapshot = owner._mappings.read()
        self._policy_version = expected.version
        self._cache = None
        self._selections = {}
        self._retirement = None
        self._closed = threading.Event(); self._catalog = self._root = None
        self._leases = {}; self._entries = {}; self._book_version = None
        self._active_thread = self._active_reader = self._active_book = None
        self._admitted = False
        self._id = secrets.token_hex(16)

    def _permission(self):
        try:
            if (self._closed.is_set() or self._owner._original_batch is not self or self._native_current() is not True):
                raise TransferError('media_source_batch_retired')
            self._original_permission()
            if (effective(self._token.body)['collection_mode'] != 'entire_collection'
                    or self._owner._mappings.read() != self._mapping_snapshot):
                raise TransferError('media_source_batch_original_scope_changed')
            return True
        except BaseException:
            self._closed.set(); raise

    def _require(self):
        if self._retirement is not None:
            self._permission()
            from magnolie_media_source_retirement import _NativeBatchSourceRetirement
            if (type(self._retirement) is not _NativeBatchSourceRetirement
                    or not self._retirement._permits_batch_checkpoint(self)):
                raise TransferError('media_source_batch_original_drain_owner_required')
            return
        if self._root is None:
            self._permission()
            raise TransferError('media_source_batch_original_owner_required')
        # open_root below binds this exact batch's _permission to the
        # catalog's native guard. It runs before and after all member checks;
        # surrounding that guard with more copies adds no observation.
        self._root._require_original_members(self._leases.values())

    def _admit_locked(self):
        """Called only by the owning native source while its real gate is held."""
        from magnolie_media_source_pc import validate_pc_origin, _NativePcSelection
        from magnolie_media_source_collection import NativeCollectionMember
        from magnolie_media_source_jobs import _NativeSourceJobs
        if (self._admitted or self._root is not None or self._catalog is not None or not self._owner._gate.locked()
                or type(self._members) is not tuple or not 1 <= len(self._members) <= MAX_FILES
                or any(type(member) is not NativeCollectionMember for member in self._members)
                or len({member.key for member in self._members}) != len(self._members)
                or any(not 1 <= member.size <= MAX_FILE_BYTES for member in self._members)
                or sum(member.size for member in self._members) > MAX_TOTAL_BYTES):
            raise TransferError('media_source_batch_original_members_required')
        self._permission()
        self._catalog = self._owner._preferences.open_collection_roots()
        self._root = self._catalog.open_root(self._selected, self._permission)
        self._catalog_witness = self._catalog.witness().wire()
        paths = set()
        for member in self._members:
            self._permission()
            path = '/'.join([part.name for part in member.parents] + [member.name])
            _portable_path(path)  # Reject, never normalize or re-find by basename.
            if path in paths: raise TransferError('media_source_batch_original_members_required')
            paths.add(path)
            lease = self._root.open_member(member)
            file_id = secrets.token_hex(16)
            if file_id in self._leases: lease.close(); raise TransferError('media_source_batch_original_members_required')
            self._leases[file_id] = lease
            self._owner._mappings.require_independent_native_file(member.key)
            origin = dict(format=1, root_id=self._selected.id, root_version=self._selected.version,
                root_key=list(self._selected.key), root_birthtime=list(self._selected.birthtime), mount_id=self._selected.mount_id,
                file_key=list(member.key), file_birthtime=list(member.birthtime), file_path=path)
            validate_pc_origin(origin)
            self._entries[file_id] = dict(path=path, size=member.size, local_origin=origin)
            jobs = _NativeSourceJobs(self._owner._authority)
            try: previous = jobs.completed_pc_origin(origin)
            except TransferError as error:
                if str(error) != 'media_collection_completed_source_required': raise
                jobs.require_new_pc_origin(origin); previous = None
            self._selections[file_id] = _NativePcSelection(canonical(origin), canonical(self._catalog_witness), member.name, previous)
            self._owner._boundary('source_batch_original_open')
            self._require()
        self._require()
        # One actual original-book lease covers ALL native media checks. These
        # descriptors are not closed or reacquired between individual files.
        with self._book_operation() as reader:
            from magnolie_media_mime import PREFIX_BYTES, identify_collection
            for file_id, entry in self._entries.items():
                prefix = reader._prefix(file_id, PREFIX_BYTES)
                try: identify_collection(prefix, entry['size'], self._kind)
                finally: prefix[:] = b'\0' * len(prefix)
                if self._kind == 'images' and effective(self._token.body)['photos_only']:
                    from magnolie_photo_metadata import MAX_METADATA_BYTES, camera_photo_matches
                    prefix = reader._prefix(file_id, MAX_METADATA_BYTES)
                    try:
                        if not camera_photo_matches(prefix): raise TransferError('media_source_photo_metadata_required')
                    finally: prefix[:] = b'\0' * len(prefix)
            reader._permission()
        self._require()
        self._admitted = True  # Private native completion, never imported from observation/packet metadata.

    @contextmanager
    def _book_operation(self):
        if self._active_thread is not None: raise TransferError('media_source_batch_busy')
        self._require()
        if self._catalog.witness().wire() != self._catalog_witness:
            raise TransferError('media_source_batch_original_scope_changed')
        with self._catalog.selected_root_lease(self._selected), NativeMediaRetention(self._owner._authority.binding.native_directory) as retention:
            with retention.activity(self._permission, exclusive=True) as activity:
                if activity is None: raise TransferError('media_source_media_io_busy')
                with retention._active_copy_permit(activity) as book:
                    if book is None: raise TransferError('media_source_saved_book_required')
                    if self._book_version is None: self._book_version = book.book_version
                    if book.book_version != self._book_version: raise TransferError('media_source_original_book_required')
                    self._active_thread = threading.get_ident(); self._active_book = book
                    reader = _NativeCollectionBatchReader(self); self._active_reader = reader
                    try:
                        reader._permission(); yield reader; reader._permission()
                    finally:
                        reader.close(); self._active_reader = self._active_book = self._active_thread = None

    @contextmanager
    def original_reader(self):
        """Typed in-process all-file lease; observations never open readers."""
        if not self._admitted: raise TransferError('media_source_batch_all_members_not_admitted')
        if not self._owner._gate.acquire(blocking=False): raise TransferError('media_source_batch_busy')
        try:
            with self._book_operation() as reader: yield reader
        except BaseException:
            self._closed.set(); raise
        finally:
            self._owner._gate.release()
            if self._closed.is_set() or self._owner._closed.is_set(): self._owner.close()

    def observation(self):
        if not self._admitted: raise TransferError('media_source_batch_all_members_not_admitted')
        self._require()
        return NativeCollectionBatchObservation(dict(format=1, batch_id=self._id, media_type=self._kind,
            root_catalog=self._catalog.witness().wire(), book_version=self._book_version,
            total_bytes=sum(entry['size'] for entry in self._entries.values()), members=copy.deepcopy(self._entries)))

    def freeze_cache(self):
        """Build one all-original encrypted cache; no legacy sender admission."""
        from magnolie_media_source_batch_cache import _NativeBatchCacheWriter
        if self._cache is not None: raise TransferError('media_source_batch_cache_already_prepared')
        with self.original_reader() as reader:
            writer = _NativeBatchCacheWriter(self, reader)
            try:
                result = writer.finish(); reader._permission(); self._cache = result
            finally: writer.close()
        return result

    @contextmanager
    def cached_reader(self):
        from magnolie_media_source_batch_cache import _NativeBatchCacheReader
        with self.original_reader() as original:
            reader = _NativeBatchCacheReader(self, original)
            try:
                yield reader
                if reader._retirement_handoff is not None: reader._permission()
                else: reader._layout(); reader._guard()
            finally: reader.close()

    def _drain_retirement_originals(self,owner):
        from magnolie_media_source_retirement import _NativeBatchSourceRetirement
        if (type(owner) is not _NativeBatchSourceRetirement or owner._batch is not self
                or self._retirement is not None or owner._handed):
            raise TransferError('media_source_batch_original_drain_owner_required')
        owner._require_planned(); self._require()
        for lease in self._leases.values(): lease.close()
        self._root.close()
        # The selected-root catalog and actual native book scope stay open.
        # Only the typed owning retirement establishes its checkpoint after
        # BOTH the original and cache descriptor drains have really returned.

    def close(self):
        self._closed.set(); self._owner.close()  # The source gate joins outstanding native IO first.

    def _close_owned(self):
        self._closed.set()
        failure = None
        for lease in reversed(tuple(self._leases.values())):
            try: lease.close()
            except BaseException as error:
                if failure is None: failure = error
        for resource in (self._root, self._catalog):
            if resource is not None:
                try: resource.close()
                except BaseException as error:
                    if failure is None: failure = error
        self._root = self._catalog = None
        if failure is not None: raise failure


class _NativeCollectionBatchReader:
    def __init__(self, owner):
        if (type(owner) is not NativeCollectionMediaBatch or owner._active_thread != threading.get_ident()
                or owner._active_book is None): raise TransferError('media_source_batch_live_lease_required')
        self._owner = owner; self._closed = threading.Event()

    def _permission(self):
        owner = self._owner
        if (self._closed.is_set() or owner._active_reader is not self or owner._active_thread != threading.get_ident()
                or owner._active_book is None): raise TransferError('media_source_batch_live_lease_required')
        owner._active_book.require_current(); owner._require()

    def read_chunk(self, file_id, index):
        self._permission()
        if type(file_id) is not str or file_id not in self._owner._entries or type(index) is not int or index < 0:
            raise TransferError('media_source_batch_invalid_chunk')
        entry = self._owner._entries[file_id]; offset = index * CHUNK_BYTES
        if offset >= entry['size']: raise TransferError('media_source_batch_invalid_chunk')
        return self._read(file_id, offset, min(CHUNK_BYTES, entry['size'] - offset))

    def _read(self, file_id, offset, count):
        self._permission()
        data = self._owner._leases[file_id].read_exact(offset, count)
        try:
            self._owner._owner._boundary('source_batch_original_read')
            self._permission(); return data
        except BaseException:
            data[:] = b'\0' * len(data); raise

    def _prefix(self, file_id, maximum):
        self._permission(); size = min(maximum, self._owner._entries[file_id]['size']); result = bytearray()
        try:
            while len(result) < size:
                data = self._read(file_id, len(result), min(CHUNK_BYTES, size - len(result)))
                try: result.extend(data)
                finally: data[:] = b'\0' * len(data)
            return result
        except BaseException:
            result[:] = b'\0' * len(result); raise

    def close(self): self._closed.set()  # Never closes original FDs or releases the parent's native IO lease.
