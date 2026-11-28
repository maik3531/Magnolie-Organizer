"""Backup and retire an already Saved PC job after its fresh readback.

Only the original source job can be used. No prepared sender is reconstructed,
and the encrypted cache is verified without reading its plaintext chunks.
"""
from contextlib import closing
from hashlib import sha256
import os
from pathlib import Path
import threading

from magnolie_file_transfer import CHUNK_BYTES, FileManifest, TransferError
from magnolie_media_backups import NativeMediaBackups, NativeMediaBackupLocations
from magnolie_media_retention import NativeMediaRetention
from magnolie_media_saved_recovery_proof import verify_recovered_pc_exchange
from magnolie_media_source_backup import _backup_source_file, batch_source_provenance_ready
from magnolie_media_source_exchange import _read_source_exchange
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_recovery import verify_encrypted_source
from magnolie_media_source_retirement import (
    _NativeSourceRetirementJournal, _move_no_replace, _private, verified_source_backup, verify_archived_cache,
)
from magnolie_telefon import canonical


class _MemberBackupRead:
    def __init__(self, original, file):
        self._original = original
        self._size = file.size

    def read_chunk(self, index):
        offset = index * CHUNK_BYTES
        return self._original.read_exact(offset, min(CHUNK_BYTES, self._size - offset))


class _NativePcSavedSourceEnd:
    def __init__(self, source, ready, exchange, permission):
        self._source = source
        self._jobs = _NativeSourceJobs(source._authority)
        self._journal = _NativeSourceRetirementJournal(self._jobs)
        self._ready = ready
        self._exchange = exchange
        self._permission = permission
        self._thread = self._book = None
        body = ready.body
        self._job = body['job_id']
        self._batch = body['format'] == 4
        self._manifest = FileManifest.parse(body['manifest'])

    def _current(self):
        if self._thread != threading.get_ident() or self._book is None:
            raise TransferError('media_saved_readback_end_live_owner_required')
        self._permission()
        self._book.require_current()
        return True

    def _original_exchange(self):
        self._current()
        with self._jobs._database() as (db, key):
            db.execute('BEGIN')
            catalog = self._jobs._catalog.verify(db, key)
            if (self._jobs._read(db, key, self._job) != self._ready or
                    _read_source_exchange(self._jobs, db, key, self._job, self._ready) != self._exchange):
                raise TransferError('media_saved_readback_original_exchange_required')
        self._jobs._catalog.observe(catalog)
        authority = self._source._authority
        peer = authority.current_peer()
        if peer is None or peer.pairing_epoch != self._ready.body['pairing_epoch']:
            raise TransferError('media_saved_readback_original_exchange_required')
        verify_recovered_pc_exchange(self._exchange.body, self._ready.body,
                                     authority.identity.receiver_identity_sha256, peer.identity_sha256)
        self._current()

    def _origins(self):
        body = self._ready.body
        if self._batch:
            return {file.id: body['members'][file.id]['local_origin'] for file in self._manifest.files}
        return {self._manifest.files[0].id: body['local_origin']}

    def _provenance(self, file):
        if self._batch:
            return batch_source_provenance_ready(self._ready, file)
        body = self._ready.body
        return dict(format=2, job_id=self._job, job_nonce=body['nonce'], job_version=self._ready.version,
                    proof_sha256=body['proof_sha256'], book_version=body['book_version'], manifest=body['manifest'],
                    local_origin=body['local_origin'], root_catalog=body['root_catalog'],
                    media_type='video', source_path=file.path)

    def _backup(self, root, backups, current):
        origins = self._origins()
        inventory = root.inventory()
        if inventory.needs_review:
            raise TransferError('media_saved_readback_original_inventory_required')
        paths = {'/'.join([*(parent.name for parent in item.parents), item.name]): item for item in inventory.members}
        versions = {}
        with backups._operation():
            backups._ensure_native_owner()
            for file in self._manifest.files:
                origin = origins[file.id]
                item = paths.get(origin['file_path'])
                if (item is None or item.size != file.size or list(item.key) != origin['file_key']
                        or list(item.birthtime) != origin['file_birthtime']):
                    raise TransferError('media_saved_readback_original_file_required')
                with closing(root.open_member(item)) as lease:
                    versions[file.id] = _backup_source_file(backups, file, self._provenance(file),
                        _MemberBackupRead(lease, file), current, lambda _: None, file.path)
                    root._require_original_members([lease])
        return versions

    def _stage(self, parent):
        original = self._ready.body
        stage = '.magnolie-source-'+self._jobs._scope[:32]+'.part'
        archive = '.magnolie-source-'+self._jobs._scope[:32]+'-'+self._job+'.retired'
        root = os.open(stage, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC, dir_fd=parent)
        try:
            file = os.stat('manifest.enc', dir_fd=root, follow_symlinks=False)
            _private(file)
        finally:
            os.close(root)
        return dict(format=3 if self._batch else 1, job_id=self._job, nonce=original['nonce'],
                    state='archive_planned', ready_version=self._ready.version, exchange_version=self._exchange.version,
                    root_key=original['root_key'], parent_key=original['parent_key'], manifest=original['manifest'],
                    stage=stage, archive=archive,
                    proof_witness=dict(key=[file.st_dev,file.st_ino], size=file.st_size, sha256=original['proof_sha256']))

    def run(self):
        source = self._source
        body = self._ready.body
        directory = source._authority.binding.native_directory
        preferences = source._preferences
        if not source._gate.acquire(blocking=False):
            raise TransferError('media_source_busy')
        try:
            if source._prepared or source._original_batch is not None:
                raise TransferError('media_saved_readback_end_live_owner_required')
            with NativeMediaRetention(directory) as retention, retention.activity(self._permission,exclusive=True) as activity:
                if activity is None:
                    raise TransferError('media_source_media_io_busy')
                with retention._active_copy_permit(activity) as book:
                    if book is None or book.book_version != body['book_version']:
                        raise TransferError('media_source_original_book_required')
                    self._book, self._thread = book, threading.get_ident()
                    self._original_exchange()
                    return self._run_owned(directory, preferences)
        finally:
            self._book = self._thread = None
            source._gate.release()

    def _run_owned(self, directory, preferences):
        body = self._ready.body
        kind = body['media_type']
        origin = next(iter(self._origins().values()))
        scope = sha256(canonical(dict(subject=preferences._subject, media_type=kind))).hexdigest()
        with closing(preferences.open_collection_roots()) as roots:
            if roots.witness().wire() != body['root_catalog']:
                raise TransferError('media_source_recovery_original_root_required')
            selected = next((root for root in roots.read().roots
                if root.id == origin['root_id'] and root.version == origin['root_version']), None)
            if selected is None:
                raise TransferError('media_source_recovery_original_root_required')
            with roots.selected_root_lease(selected) as root_current, \
                    NativeMediaBackupLocations(directory, scope, self._current) as locations:
                self._current()
                where = locations.read()
                if not where.parents:
                    where = locations.choose(locations.issue_action(), where, selected.directory, None)
                storage = where.current(selected.directory)

                def current():
                    self._current()
                    root_current()
                    if locations.read() != where:
                        raise TransferError('media_backup_locations_changed')
                    return True

                with NativeMediaBackups(selected.directory, self._source._authority.protection, current,
                        create=not os.path.lexists(Path(storage.path)/'Backup'), storage_parent=storage) as backups:
                    with closing(roots.open_root(selected, current)) as root:
                        versions = self._backup(root, backups, current)
                    return self._archive(directory, backups, versions, current)

    def _archive(self, directory, backups, versions, current):
        parent = os.open(directory, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            planned = self._stage(parent)

            def verify_cache(name):
                if self._batch:
                    verify_archived_cache(self._jobs, parent, planned, current, name=name)
                else:
                    verify_encrypted_source(self._jobs, parent, name, planned, self._ready.body,
                                            'video', current, lambda _: None)

            def backup_refs():
                return {file.id: verified_source_backup(backups, versions[file.id], self._provenance(file),
                    self._source._authority.protection, current) for file in self._manifest.files}

            verify_cache(planned['stage'])
            references = backup_refs()
            if self._batch:
                planned['backups'] = references
            else:
                planned['backup'] = next(iter(references.values()))
            self._original_exchange()
            record = self._journal.write(self, None, planned)
            self._original_exchange()
            _move_no_replace(parent, planned['stage'], planned['archive'])
            os.fsync(parent)
            verify_cache(planned['archive'])
            if backup_refs() != references:
                raise TransferError('media_source_recovery_original_backup_required')
            self._original_exchange()
            return self._journal.write(self, record, dict(record.body,state='archived'))
        finally:
            os.close(parent)
