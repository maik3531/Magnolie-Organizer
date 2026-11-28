"""Refs #330: one native encrypted collection batch cache, never SEND rights.

Reuses the original cache's inode-bound encryption/durable IO primitives and
the existing job/catalog CAS. Neither observations nor sealed records reopen
an original source. Legacy readers/senders intentionally cannot use this type.
"""
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
import copy
import os
import secrets
import threading

from magnolie_file_transfer import CHUNK_BYTES, FileManifest, ManifestFile, TransferError
from magnolie_media_source_cache import _NativeSourceCacheWriter
from magnolie_telefon import canonical, strict_json


@dataclass(frozen=True)
class FrozenNativeMediaBatch:
    directory: Path
    manifest: FileManifest
    root_key: tuple
    proof_sha256: str
    _job_version: str
    _job_nonce: str
    _book_version: str
    @property
    def grants_read_authority(self): return False
    @property
    def is_saved_receipt(self): return False
    @property
    def permits_retirement(self): return False


def validate_batch_members(members):
    from magnolie_file_control import _hex
    from magnolie_file_transfer import MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, _portable_path
    from magnolie_media_source_pc import validate_pc_origin
    if type(members) is not dict or not 1 <= len(members) <= MAX_FILES:
        raise TransferError('media_source_batch_members_invalid')
    paths = set(); identities = set(); total = 0; roots = set()
    for file_id, entry in members.items():
        if (type(file_id) is not str or len(file_id) != 32 or not _hex(file_id * 2)
                or type(entry) is not dict or set(entry) != {'path', 'size', 'local_origin'}
                or type(entry['size']) is not int or not 1 <= entry['size'] <= MAX_FILE_BYTES):
            raise TransferError('media_source_batch_members_invalid')
        _portable_path(entry['path']); validate_pc_origin(entry['local_origin'])
        origin = entry['local_origin']; identity = tuple(origin['file_key'])
        roots.add(canonical({k: origin[k] for k in ('root_id', 'root_version', 'root_key', 'root_birthtime', 'mount_id')}))
        if entry['path'] != origin['file_path'] or entry['path'] in paths or identity in identities:
            raise TransferError('media_source_batch_members_invalid')
        paths.add(entry['path']); identities.add(identity); total += entry['size']
    if total > MAX_TOTAL_BYTES or len(roots) != 1: raise TransferError('media_source_batch_members_invalid')


def validate_batch_predecessors(members, predecessors):
    from magnolie_file_control import _hex
    from magnolie_file_transfer import MAX_FILE_BYTES
    if type(predecessors) is not dict or set(predecessors) != set(members):
        raise TransferError('media_source_batch_predecessors_invalid')
    for previous in predecessors.values():
        if previous is None: continue
        if (type(previous) is not dict or set(previous) != {'job_id', 'ready_version', 'retirement_version',
                'publication_sha256', 'size', 'sha256', 'catalog_version'}
                or type(previous['job_id']) is not str or len(previous['job_id']) != 32 or not _hex(previous['job_id'] * 2)
                or type(previous['size']) is not int or not 1 <= previous['size'] <= MAX_FILE_BYTES
                or any(not _hex(previous[k]) for k in ('ready_version', 'retirement_version', 'publication_sha256', 'sha256', 'catalog_version'))):
            raise TransferError('media_source_batch_predecessors_invalid')


class _NativeBatchCacheWriter:
    # Shared physical format: existing per-inode domain, private mode, full
    # fsync + authenticated readback; distinct chunk names and logical format4.
    _key = staticmethod(_NativeSourceCacheWriter._key)
    _signature = staticmethod(_NativeSourceCacheWriter._signature)
    _private = staticmethod(_NativeSourceCacheWriter._private)
    _domain = _NativeSourceCacheWriter._domain
    _write = _NativeSourceCacheWriter._write
    _read = _NativeSourceCacheWriter._read
    _guard = _NativeSourceCacheWriter._guard
    close = _NativeSourceCacheWriter.close
    MAX_METADATA = CHUNK_BYTES

    def __init__(self, batch, reader):
        from magnolie_media_source_batch import NativeCollectionMediaBatch, _NativeCollectionBatchReader
        if (type(batch) is not NativeCollectionMediaBatch or type(reader) is not _NativeCollectionBatchReader
                or reader._owner is not batch or batch._active_reader is not reader or not batch._admitted
                or batch._cache is not None):
            raise TransferError('media_source_batch_live_cache_owner_required')
        reader._permission()
        self._batch = batch; self._reader = reader; self._owner = batch._owner; self._authority = self._owner._authority
        self._current = reader._permission; self._parent = self._root = None
        self._book_version = batch._book_version; self._entries = copy.deepcopy(batch._entries)
        self._selections = batch._selections
        self._predecessors = {fid:asdict(selection.previous) if selection.previous is not None else None for fid,selection in self._selections.items()}
        validate_batch_members(self._entries)
        validate_batch_predecessors(self._entries, self._predecessors)
        if any(selection.origin != self._entries[fid]['local_origin'] or selection.catalog != batch._catalog_witness
                or selection.path != self._entries[fid]['path'].rsplit('/',1)[-1] for fid,selection in self._selections.items()):
            raise TransferError('media_source_batch_predecessors_invalid')
        self._expected_hashes = {}
        if any(selection.previous is not None for selection in self._selections.values()):
            for fid,entry in self._entries.items():
                raw=sha256()
                for index in range((entry['size']+CHUNK_BYTES-1)//CHUNK_BYTES):
                    data=reader.read_chunk(fid,index)
                    try:raw.update(data)
                    finally:data[:]=b'\0'*len(data)
                self._expected_hashes[fid]=raw.hexdigest()
            if all(selection.previous is not None and
                    (self._entries[fid]['size'],self._expected_hashes[fid])==(selection.previous.size,selection.previous.sha256)
                    for fid,selection in self._selections.items()):
                raise TransferError('media_collection_latest_payload_already_sent')
            if batch._all_new_only:
                raise TransferError('media_collection_existing_source_held')
        peer = self._authority.current_peer()
        if peer is None: raise TransferError('media_source_cache_native_owner_required')
        self._scope = sha256(canonical(dict(local_id=self._authority.identity.receiver_id,
            local_key=self._authority.identity.receiver_identity_sha256, peer_id=peer.peer_id, peer_key=peer.identity_sha256))).hexdigest()
        self._name = '.magnolie-source-' + self._scope[:32] + '.part'
        self._directory = Path(self._authority.binding.native_directory)
        self._job = batch._id; self._job_nonce = secrets.token_hex(32)
        self._metadata = {}; self._chunks = {}; self._manifests = []
        from magnolie_media_source_jobs import _NativeSourceJobs
        self._jobs = _NativeSourceJobs(self._authority)
        try:
            self._parent = os.open(self._directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            value = os.fstat(self._parent); self._private(value, directory=True); self._parent_key = self._key(value)
            free = os.fstatvfs(self._parent); block = max(4096, free.f_frsize)
            count = sum((e['size'] + CHUNK_BYTES - 1) // CHUNK_BYTES for e in self._entries.values())
            budget = count * ((CHUNK_BYTES + 28 + block - 1) // block * block) + 4 * CHUNK_BYTES
            if free.f_bavail * free.f_frsize < budget + 1024 ** 3: raise TransferError('media_source_cache_insufficient_space')
            # Reject oversized metadata BEFORE creating any durable stage.
            intent = dict(format=4, state='planned', job_id=self._job, job_nonce=self._job_nonce,
                scope=self._scope, book_version=self._book_version, parent_key=list(self._parent_key),
                root_key=[0, 1], members=self._entries, predecessors=self._predecessors, media_type=batch._kind,
                root_catalog=copy.deepcopy(batch._catalog_witness), source_policy_sha256=batch._policy_version,
                pairing_epoch=peer.pairing_epoch, media_intent_sha256=sha256(canonical(batch._token.body)).hexdigest())
            if len(canonical(intent)) > self.MAX_METADATA - 128: raise TransferError('media_source_cache_record_size_limit')
            self._jobs._catalog.require_free_slot(self._parent, self._current)
            self._jobs.require_batch_selections(self._selections)
            self._current()
            try: os.mkdir(self._name, mode=0o700, dir_fd=self._parent)
            except FileExistsError: raise TransferError('media_source_cache_existing_hold')
            self._root = os.open(self._name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._parent)
            self._root_key = self._key(os.fstat(self._root)); self._guard(); os.fsync(self._parent)
            intent['root_key'] = list(self._root_key)
            self._intent = intent; self._intent_sha256 = sha256(canonical(intent)).hexdigest()
            self._metadata['intent.enc'] = self._write('intent.enc', canonical(intent))
            self._owner._boundary('source_cache_intent_durable'); self._guard()
            self._planned_job = self._jobs.plan_batch(self, intent)
            self._owner._boundary('source_cache_job_planned'); self._guard()
            self._metadata['copying.enc'] = self._write('copying.enc', canonical(dict(format=4, state='copying', intent_sha256=self._intent_sha256)))
        except BaseException:
            self.close(); raise

    def _planned(self):
        self._guard(); record = self._jobs.lookup(self._job)
        if record is None or record.version != self._planned_job.version or record.state != 'cache_planned':
            raise TransferError('media_source_jobs_plan_changed')

    @staticmethod
    def chunk_name(file_id, index): return 'chunk-' + file_id + '-%08x.enc' % index

    def finish(self):
        self._planned(); members = sha256(); witnesses = set()
        for file_id, entry in self._entries.items():
            raw = sha256(); self._chunks[file_id] = []
            count = (entry['size'] + CHUNK_BYTES - 1) // CHUNK_BYTES
            for index in range(count):
                self._planned(); data = self._reader.read_chunk(file_id, index)
                try:
                    raw.update(data); name = self.chunk_name(file_id, index); witness = self._write(name, data)
                finally: data[:] = b'\0' * len(data)
                identity = tuple(witness['key'])
                if identity in witnesses: raise TransferError('media_source_cache_original_member_required')
                witnesses.add(identity); self._chunks[file_id].append(witness)
                members.update(canonical(dict(file_id=file_id, index=index, **witness)))
                self._owner._boundary('source_cache_chunk_durable'); self._guard()
            self._manifests.append(ManifestFile(file_id, entry['path'], entry['size'], raw.hexdigest()))
            if file_id in self._expected_hashes and self._expected_hashes[file_id]!=raw.hexdigest():
                raise TransferError('media_source_cache_final_digest_changed')
        # Re-read ALL encrypted members against their original physical witnesses
        # after the final source read, not merely the most recently copied file.
        for file in self._manifests:
            raw = sha256()
            for index, witness in enumerate(self._chunks[file.id]):
                data = bytearray(self._read(self.chunk_name(file.id, index), witness))
                try: raw.update(data)
                finally: data[:] = b'\0' * len(data)
            if raw.hexdigest() != file.sha256: raise TransferError('media_source_cache_final_digest_changed')
        for name, witness in self._metadata.items():
            if strict_json(self._read(name, witness)) != (self._intent if name == 'intent.enc' else dict(format=4, state='copying', intent_sha256=self._intent_sha256)):
                raise TransferError('media_source_cache_intent_changed')
        names = set(self._metadata) | {self.chunk_name(fid, i) for fid, chunks in self._chunks.items() for i in range(len(chunks))}
        if set(os.listdir(self._root)) != names: raise TransferError('media_source_cache_unknown_entry')
        manifest = FileManifest(secrets.token_hex(16), self._job, self._authority.identity.receiver_id,
            self._authority.binding.peer_id, tuple(self._manifests), sum(e['size'] for e in self._entries.values()))
        proof = dict(format=4, state='sealed', intent_sha256=self._intent_sha256, job_nonce=self._job_nonce,
            book_version=self._book_version, manifest=manifest.wire(), chunks_sha256=members.hexdigest(),
            chunk_count=sum(map(len, self._chunks.values())), metadata=self._metadata, members=self._entries, predecessors=self._predecessors,
            root_catalog=self._intent['root_catalog'], media_type=self._batch._kind)
        witness = self._write('manifest.enc', canonical(proof)); self._guard()
        if set(os.listdir(self._root)) != names | {'manifest.enc'}: raise TransferError('media_source_cache_unknown_entry')
        self._owner._boundary('source_cache_sealed_durable'); self._planned()
        ready = self._jobs.ready_batch(self, manifest, witness['sha256'])
        self._owner._boundary('source_cache_job_ready'); self._guard()
        return FrozenNativeMediaBatch(self._directory / self._name, manifest, self._root_key, witness['sha256'],
            ready.version, self._job_nonce, self._book_version)


class _NativeBatchCacheReader:
    _key = staticmethod(_NativeSourceCacheWriter._key)
    _signature = staticmethod(_NativeSourceCacheWriter._signature)
    _private = staticmethod(_NativeSourceCacheWriter._private)
    _domain = _NativeSourceCacheWriter._domain
    _read = _NativeSourceCacheWriter._read
    _guard = _NativeSourceCacheWriter._guard

    def __init__(self, batch, original):
        from magnolie_media_source_batch import NativeCollectionMediaBatch, _NativeCollectionBatchReader
        if (type(batch) is not NativeCollectionMediaBatch or type(original) is not _NativeCollectionBatchReader
                or original._owner is not batch or batch._active_reader is not original or type(batch._cache) is not FrozenNativeMediaBatch):
            raise TransferError('media_source_batch_live_cache_owner_required')
        self._batch = batch; self._original = original; self._cache = batch._cache; self._authority = batch._owner._authority
        self._parent = self._root = None; self._thread = threading.get_ident(); self._closed = False
        self._retirement_handoff = None
        from magnolie_media_source_jobs import _NativeSourceJobs
        self._jobs = _NativeSourceJobs(self._authority); self._scope = self._jobs._scope
        self._directory = Path(self._authority.binding.native_directory); self._name = '.magnolie-source-' + self._scope[:32] + '.part'
        self._current = self._permission; self._root_key = self._cache.root_key
        self._chunks = {}; self._names = {'manifest.enc', 'intent.enc', 'copying.enc'}
        try:
            original._permission()
            self._ready = self._jobs.require_version(batch._id,self._cache._job_version)
            self._permission()
            if self._cache.directory != self._directory / self._name: raise TransferError('media_source_cache_original_directory_required')
            self._parent = os.open(self._directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            self._parent_key = self._key(os.fstat(self._parent))
            self._root = os.open(self._name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._parent)
            self._proof_witness, plain_proof = self._inspect_cipher('manifest.enc', proof_sha256=self._cache.proof_sha256)
            proof = strict_json(plain_proof)
            self._metadata = proof.get('metadata')
            if type(self._metadata) is not dict or set(self._metadata) != {'intent.enc', 'copying.enc'}:
                raise TransferError('media_source_cache_original_proof_required')
            intent = strict_json(self._read('intent.enc', self._metadata['intent.enc']))
            copying = strict_json(self._read('copying.enc', self._metadata['copying.enc']))
            record = self._ready.body
            expected_intent = dict(format=4, state='planned', job_id=batch._id, job_nonce=self._cache._job_nonce,
                scope=self._scope, book_version=batch._book_version, parent_key=list(self._parent_key), root_key=list(self._root_key),
                members=batch._entries, predecessors={fid:asdict(s.previous) if s.previous is not None else None for fid,s in batch._selections.items()},
                media_type=batch._kind, root_catalog=batch._catalog_witness,
                source_policy_sha256=batch._policy_version, pairing_epoch=record['pairing_epoch'],
                media_intent_sha256=sha256(canonical(batch._token.body)).hexdigest())
            if (intent != expected_intent or sha256(canonical(intent)).hexdigest() != record['intent_sha256']
                    or copying != dict(format=4, state='copying', intent_sha256=record['intent_sha256'])):
                raise TransferError('media_source_cache_original_intent_required')
            members = sha256(); identities = set()
            for file in self._cache.manifest.files:
                self._chunks[file.id] = []
                for index in range(file.chunks):
                    name = _NativeBatchCacheWriter.chunk_name(file.id, index); self._names.add(name)
                    witness = self._witness(name); identity = tuple(witness['key'])
                    if witness['size'] != min(CHUNK_BYTES, file.size - index * CHUNK_BYTES) + 28 or identity in identities:
                        raise TransferError('media_source_cache_original_member_required')
                    identities.add(identity); self._chunks[file.id].append(witness)
                    members.update(canonical(dict(file_id=file.id, index=index, **witness)))
            expected_proof = dict(format=4, state='sealed', intent_sha256=record['intent_sha256'], job_nonce=self._cache._job_nonce,
                book_version=batch._book_version, manifest=self._cache.manifest.wire(), chunks_sha256=members.hexdigest(),
                chunk_count=sum(map(len, self._chunks.values())), metadata=self._metadata, members=batch._entries,
                predecessors=expected_intent['predecessors'],
                root_catalog=expected_intent['root_catalog'], media_type=batch._kind)
            if proof != expected_proof: raise TransferError('media_source_cache_original_proof_required')
            self._layout(); self._guard()
        except BaseException:
            self.close(); raise

    def _permission(self):
        handed = self._retirement_handoff
        if handed is not None:
            from magnolie_media_source_retirement import _NativeBatchSourceRetirement
            if type(handed) is not _NativeBatchSourceRetirement or not handed._permits_cache_checkpoint(self):
                raise TransferError('media_source_batch_original_drain_owner_required')
        if (self._closed and handed is None) or self._thread != threading.get_ident() or self._original._owner is not self._batch:
            raise TransferError('media_source_batch_live_cache_owner_required')
        self._original._permission()
        if self._ready.version!=self._cache._job_version:
            raise TransferError('media_source_jobs_ready_record_required')
        self._jobs._require_original_ready_membership(self._batch._id,self._ready.version)
        record = self._ready.body
        if (record['format'] != 4 or record['members'] != self._batch._entries or record['manifest'] != self._cache.manifest.wire()
                or record['predecessors'] != {fid:asdict(s.previous) if s.previous is not None else None for fid,s in self._batch._selections.items()}
                or record['book_version'] != self._batch._book_version or record['nonce'] != self._cache._job_nonce
                or record['proof_sha256'] != self._cache.proof_sha256 or record['root_key'] != list(self._root_key)):
            raise TransferError('media_source_jobs_ready_record_required')

    def _witness(self, name):
        return self._inspect_cipher(name)[0]

    def _inspect_cipher(self, name, *, proof_sha256=None):
        self._guard(); fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=self._root)
        try:
            before = os.fstat(fd); self._private(before)
            if not 29 <= before.st_size <= CHUNK_BYTES + 28: raise TransferError('media_source_cache_record_size_limit')
            cipher = os.pread(fd, before.st_size + 1, 0)
            after = os.fstat(fd); named = os.stat(name, dir_fd=self._root, follow_symlinks=False)
            if len(cipher) != before.st_size or self._signature(before) != self._signature(after) or self._signature(after) != self._signature(named):
                raise TransferError('media_source_cache_original_member_required')
            witness = dict(key=list(self._key(after)), size=len(cipher), sha256=sha256(cipher).hexdigest())
            if proof_sha256 is None:
                return witness, None
            if witness['sha256'] != proof_sha256:
                raise TransferError('media_source_cache_original_proof_required')
            # Authenticate the same bytes under the same inode-bound domain.
            # No second name lookup/open between admission and authentication.
            plain = self._authority.protection.unseal(cipher, self._domain(name, self._key(after)))
            self._guard()
            if (self._signature(os.fstat(fd)) != self._signature(after)
                    or self._signature(os.stat(name, dir_fd=self._root, follow_symlinks=False)) != self._signature(after)):
                raise TransferError('media_source_cache_original_member_required')
            return witness, plain
        finally: os.close(fd)

    def close(self):
        self._closed = True
        # A foreign cancellation caller may retire this view, but only the
        # owning native scope drains and closes its descriptors after real IO.
        if self._thread == threading.get_ident(): _NativeSourceCacheWriter.close(self)

    def _layout(self):
        self._guard()
        if set(os.listdir(self._root)) != self._names: raise TransferError('media_source_cache_unknown_entry')

    def read_chunk(self, file_id, index):
        if self._retirement_handoff is not None: raise TransferError('media_source_batch_cache_reader_retired')
        self._layout()
        if (type(file_id) is not str or file_id not in self._chunks or type(index) is not int
                or not 0 <= index < len(self._chunks[file_id])): raise TransferError('media_source_batch_invalid_chunk')
        self._read('manifest.enc', self._proof_witness)
        for name, witness in self._metadata.items(): self._read(name, witness)
        return self._read_verified_payload(file_id,index)

    def _read_verified_payload(self,file_id,index):
        data = bytearray(self._read(_NativeBatchCacheWriter.chunk_name(file_id, index), self._chunks[file_id][index]))
        try:
            self._batch._owner._boundary('source_batch_cache_read'); self._layout(); self._guard(); return data
        except BaseException:
            data[:] = b'\0' * len(data); raise

    def verify(self):
        """Reread all members, then recheck all original cipher witnesses."""
        if self._retirement_handoff is not None: raise TransferError('media_source_batch_cache_reader_retired')
        # Whole-cache verification emits nothing. Authenticate the common
        # records at both ends of the sweep, not as a new send for every
        # chunk. Every chunk still checks the original owner and named cache
        # on entry, after the read, and after its explicit boundary.
        self._layout()
        self._read('manifest.enc',self._proof_witness)
        for name,witness in self._metadata.items(): self._read(name,witness)
        for file in self._cache.manifest.files:
            raw = sha256()
            for index in range(file.chunks):
                data = self._read_verified_payload(file.id,index)
                try: raw.update(data)
                finally: data[:] = b'\0' * len(data)
            if raw.hexdigest() != file.sha256: raise TransferError('media_source_cache_final_digest_changed')
        self._read('manifest.enc',self._proof_witness)
        for name,witness in self._metadata.items(): self._read(name,witness)
        for fid,chunks in self._chunks.items():
            for index,witness in enumerate(chunks):
                if self._witness(_NativeBatchCacheWriter.chunk_name(fid,index)) != witness:
                    raise TransferError('media_source_cache_original_member_required')
        self._layout(); self._guard()
