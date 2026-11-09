"""Explicit native mapped-PC source inspection (#338), not an uploader.

Historical mappings identify candidates only. Actual shared two-way agreement,
independent positive local sending consent, explicit native action, saved book
and original owned descriptors must all remain current during bounded reading.
An observation is metadata, never a reusable source READ/cache/Saved grant.
"""
from contextlib import contextmanager,nullcontext
from dataclasses import dataclass
from hashlib import sha256
import fcntl
import os
import stat
import threading

from magnolie_file_transfer import CHUNK_BYTES,MAX_FILE_BYTES,TransferError
from magnolie_media_retention import NativeMediaRetention
from magnolie_media_transport import NativeMediaSettingsTransport
from magnolie_photo_destination import NativePhotoDestinationAction,require_media_directory
from magnolie_photo_mappings import ProtectedPhotoMappings,PhotoMappingsSnapshot
from magnolie_photo_preferences import ProtectedPhotoPreferences,PhotoPreferencesSnapshot


@dataclass(frozen=True)
class NativeMediaSourceObservation:
    size: int
    sha256: str
    file_key: tuple
    signature: tuple
    _original_reference: tuple

    @property
    def original_reference(self):return dict(self._original_reference)
    @property
    def grants_read_authority(self):return False
    @property
    def proves_deletion(self):return False
    @property
    def is_saved_receipt(self):return False


@dataclass(frozen=True)
class _PreparedSource:
    cache: object
    permission: object
    book_version: str
    failed: object
    original_mapping: object
    restored_source: object = None
    repreparation: object = None


class NativeMappedMediaSource:
    def __init__(self,preferences,mappings,transport,*,boundary=lambda _:None):
        if (type(preferences) is not ProtectedPhotoPreferences or type(mappings) is not ProtectedPhotoMappings
                or type(transport) is not NativeMediaSettingsTransport or not callable(boundary)
                or preferences._authority is not mappings._authority or transport._authority is not preferences._authority):
            raise TransferError('media_source_native_owner_required')
        self._preferences=preferences;self._mappings=mappings;self._transport=transport
        self._authority=preferences._authority;self._boundary=boundary;self._closed=threading.Event();self._gate=threading.Lock()
        self._prepared={};self._cache_scope=threading.local()

    def close(self):
        # A UI cancellation does not close descriptors or release the actual IO
        # lane while a provider/filesystem read is still outstanding.
        self._closed.set()

    @staticmethod
    def _key(value):return value.st_dev,value.st_ino

    @staticmethod
    def _signature(value):
        return (value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_nlink,value.st_size,value.st_mtime_ns,value.st_ctime_ns)

    @contextmanager
    def _file(self,mapping,current):
        require_media_directory(mapping.destination.path+'/'+mapping.relative_path)
        parts=mapping.relative_path.split('/');fds=[]
        try:
            current();mapping.destination.verify()
            fds.append(os.open(mapping.destination.path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC))
            for index,name in enumerate(parts):
                current();parent=os.fstat(fds[-1])
                if self._key(parent)!=mapping.parent_keys[index] or not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.geteuid():
                    raise TransferError('media_source_original_parent_required')
                if index<len(parts)-1:fds.append(os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fds[-1]))
            parent=fds[-1]
            fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=parent);fds.append(fd)
            value=os.fstat(fd)
            if (not stat.S_ISREG(value.st_mode) or value.st_uid!=os.geteuid() or value.st_nlink!=1
                    or self._key(value)!=mapping.file_key or not 1<=value.st_size<=MAX_FILE_BYTES):
                raise TransferError('media_source_original_file_required')
            fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            signature=self._signature(value)
            def unchanged():
                current();mapping.destination.verify()
                for index,parent_fd in enumerate(fds[:-1]):
                    actual=os.fstat(parent_fd)
                    if self._key(actual)!=mapping.parent_keys[index] or actual.st_uid!=os.geteuid():
                        raise TransferError('media_source_original_parent_required')
                    if index:
                        named=os.stat(parts[index-1],dir_fd=fds[index-1],follow_symlinks=False)
                        if not stat.S_ISDIR(named.st_mode) or self._key(named)!=mapping.parent_keys[index]:
                            raise TransferError('media_source_original_parent_required')
                named=os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
                if self._signature(os.fstat(fd))!=signature or self._signature(named)!=signature:
                    raise TransferError('media_source_content_changed')
                current()
            unchanged();yield fd,value.st_size,signature,unchanged
            unchanged()
        finally:
            for fd in reversed(fds):os.close(fd)

    def inspect(self,action,expected,association,record_sha256,*,kind='images'):
        return self._read(action,expected,association,record_sha256,kind=kind,freeze=False)

    def plan(self,action,expected,association,record_sha256,*,kind='images',native_current=None,mapping_snapshot=None):
        return self._read(action,expected,association,record_sha256,kind=kind,freeze=False,planning=True,
            native_current=native_current,mapping_snapshot=mapping_snapshot)

    def freeze(self,action,expected,association,record_sha256,*,kind='images'):
        return self._read(action,expected,association,record_sha256,kind=kind,freeze=True)

    def freeze_observed(self,action,expected,association,record_sha256,observation,*,kind='images',catalog_version=None,native_current=None,mapping_snapshot=None):
        from magnolie_file_control import _hex
        if type(observation) is not NativeMediaSourceObservation or catalog_version is not None and not _hex(catalog_version):
            raise TransferError('media_source_original_observation_required')
        return self._read(action,expected,association,record_sha256,kind=kind,freeze=True,
            expected_observation=observation,expected_catalog=catalog_version,native_current=native_current,mapping_snapshot=mapping_snapshot)

    def reprepare(self,action,expected,association,record_sha256,job_id,job_version,*,kind='images'):
        from magnolie_media_source_reprepare import _NativeSourceRepreparation
        preparation=_NativeSourceRepreparation(self,job_id,job_version,kind)
        return self._read(action,expected,association,record_sha256,kind=kind,freeze=False,reprepare=preparation)

    def inspect_restored(self,action,expected,restorations,operation,record_sha256,*,kind='images'):
        return self._restored(action,expected,restorations,operation,record_sha256,kind=kind,freeze=False)

    def freeze_restored(self,action,expected,restorations,operation,record_sha256,*,kind='images'):
        return self._restored(action,expected,restorations,operation,record_sha256,kind=kind,freeze=True)

    def _restored(self,action,expected,restorations,operation,record_sha256,*,kind,freeze):
        from magnolie_media_backups import NativeMediaBackupRestoreOwner
        from magnolie_telefon import canonical
        scope=sha256(canonical(dict(subject=self._preferences._subject,media_type=kind))).hexdigest()
        if (type(restorations) is not NativeMediaBackupRestoreOwner
                or restorations._journal._subject!=dict(local_backup_scope=scope)
                or restorations._journal.local_protection.native_directory_identity!=self._authority.protection.native_directory_identity):
            raise TransferError('media_source_restore_original_peer_scope_required')
        return self._read(action,expected,None,record_sha256,kind=kind,freeze=freeze,restoration=(restorations,operation))

    @contextmanager
    def prepared_cache(self,job_id):
        if type(job_id) is not str or job_id not in self._prepared:
            raise TransferError('media_source_prepared_owner_required')
        if not self._gate.acquire(blocking=False):raise TransferError('media_source_busy')
        prepared=self._prepared[job_id];reader=None
        try:
            if prepared.failed.is_set():raise TransferError('media_source_prepared_retired')
            prepared.permission()
            with NativeMediaRetention(self._authority.binding.native_directory) as retention:
                with retention.activity(prepared.permission,exclusive=True) as activity:
                    if activity is None:raise TransferError('media_source_media_io_busy')
                    with retention._active_copy_permit(activity) as book:
                        if book is None or book.book_version!=prepared.book_version:
                            raise TransferError('media_source_original_book_required')
                        def current():
                            if prepared.failed.is_set():raise TransferError('media_source_prepared_retired')
                            book.require_current();return True
                        self._cache_scope.permit=(job_id,prepared,current,threading.get_ident())
                        try:
                            from magnolie_media_source_reader import _NativeSourceCacheReader
                            with _NativeSourceCacheReader(self,job_id) as reader:yield reader
                            if getattr(reader,'_retirement_handoff',None) is None:current()
                            else:book.require_current()
                        finally:self._cache_scope.permit=None
        except BaseException:
            prepared.failed.set();raise
        finally:
            if reader is not None and getattr(reader,'_retirement_handoff',None) is not None:
                prepared.failed.set();self._prepared.pop(job_id,None)
            self._gate.release()

    def _source_permission(self,action,expected,kind):
        if type(action) is not NativePhotoDestinationAction or type(expected) is not PhotoPreferencesSnapshot or kind not in ('images','video'):
            raise TransferError('media_source_native_selection_required')
        token=self._transport.intent_for(kind,to_phone=True)
        def permission():
            action.validate(self._preferences)
            if self._closed.is_set() or token is None or self._transport.intent_for(kind,to_phone=True) is not token:
                raise TransferError('media_source_current_intent_required')
            peer=self._authority.current_peer();saved=self._preferences.read()
            consent=saved.policy.sending if saved.policy is not None else None
            if (saved!=expected or peer is None or consent is None or consent.pairing_epoch!=peer.pairing_epoch
                    or not (consent.photos if kind=='images' else consent.videos)
                    or kind=='video' and not self._authority.video_available()):
                raise TransferError('media_source_local_consent_required')
            return True
        return permission,token

    def _read(self,action,expected,association,record_sha256,*,kind,freeze,restoration=None,reprepare=None,planning=False,expected_observation=None,expected_catalog=None,native_current=None,mapping_snapshot=None):
        if type(action) is not NativePhotoDestinationAction or type(expected) is not PhotoPreferencesSnapshot or kind not in ('images','video'):
            raise TransferError('media_source_native_selection_required')
        if type(planning) is not bool or planning and (freeze or restoration is not None or reprepare is not None):
            raise TransferError('media_source_planning_selection_invalid')
        if expected_observation is not None and (type(expected_observation) is not NativeMediaSourceObservation
                or not freeze or planning or restoration is not None or reprepare is not None):
            raise TransferError('media_source_original_observation_required')
        if native_current is not None and not callable(native_current):
            raise TransferError('media_source_native_operation_required')
        if mapping_snapshot is not None and (type(mapping_snapshot) is not PhotoMappingsSnapshot or restoration is not None or reprepare is not None):
            raise TransferError('media_source_native_mapping_selection_required')
        action.consume(self._preferences)
        if not self._gate.acquire(blocking=False):raise TransferError('media_source_busy')
        try:
            if reprepare is not None:
                from magnolie_media_source_reprepare import _NativeSourceRepreparation
                if (type(reprepare) is not _NativeSourceRepreparation or reprepare._source is not self
                        or freeze or restoration is not None or self._prepared):
                    raise TransferError('media_source_reprepare_fresh_owner_required')
            permission,token=self._source_permission(action,expected,kind)
            if native_current is not None:
                original_permission=permission;ended=threading.Event()
                def permission():
                    if ended.is_set():raise TransferError('media_source_native_operation_ended')
                    try:current=native_current()
                    except BaseException:
                        ended.set();raise
                    if current is not True:
                        ended.set();raise TransferError('media_source_native_operation_ended')
                    return original_permission()
            permission()
            with NativeMediaRetention(self._authority.binding.native_directory) as retention:
                with retention.activity(permission,exclusive=True) as activity:
                    if activity is None:raise TransferError('media_source_media_io_busy')
                    with retention._active_copy_permit(activity) as book:
                        if book is None:raise TransferError('media_source_saved_book_required')
                        selection={} if mapping_snapshot is None else dict(expected=mapping_snapshot,latest=True)
                        records=(self._mappings.saved_record_lease(association,record_sha256,**selection) if restoration is None else
                            restoration[0].restored_source_lease(restoration[1],record_sha256))
                        with records as (mapping,mapping_current):
                            if mapping.association.media_type!=kind:raise TransferError('media_source_media_kind_changed')
                            def current():book.require_current();mapping_current();return True
                            with self._file(mapping,current) as (fd,size,signature,unchanged):
                                if expected_observation is not None and (
                                        expected_observation.size!=size or expected_observation.signature!=signature
                                        or expected_observation.file_key!=mapping.file_key
                                        or expected_observation.original_reference!=mapping.phone_original_reference()):
                                    raise TransferError('media_source_observed_content_changed')
                                if expected_observation is not None:
                                    from magnolie_media_source_jobs import _NativeSourceJobs
                                    catalog=_NativeSourceJobs(self._authority)._catalog.lookup()
                                    if (None if catalog is None else catalog.version)!=expected_catalog:
                                        raise TransferError('media_source_observed_history_changed')
                                from magnolie_media_sync import effective
                                if kind == 'images' and effective(token.body)['photos_only']:
                                    from magnolie_photo_metadata import MAX_METADATA_BYTES,camera_photo_matches
                                    prefix=bytearray(os.pread(fd,min(size,MAX_METADATA_BYTES),0))
                                    try:
                                        unchanged()
                                        selected=camera_photo_matches(prefix)
                                        unchanged()
                                    finally:prefix[:]=b'\0'*len(prefix)
                                    if not selected:raise TransferError('media_source_photo_metadata_required')
                                if freeze:
                                    from magnolie_media_source_cache import _NativeSourceCacheWriter
                                    target=_NativeSourceCacheWriter(self,mapping,size,signature,token,expected,kind,book.book_version,unchanged)
                                else:target=nullcontext(None)
                                with target as cache:
                                    digest=sha256();offset=0;index=0
                                    while offset<size:
                                        unchanged();wanted=min(CHUNK_BYTES,size-offset)
                                        chunk=bytearray(os.pread(fd,wanted,offset))
                                        try:
                                            self._boundary('source_chunk_read');unchanged()
                                            if len(chunk)!=wanted:raise TransferError('media_source_short_read')
                                            digest.update(chunk)
                                            if cache is not None:cache.chunk(index,chunk)
                                            offset+=len(chunk);index+=1
                                        finally:chunk[:]=b'\0'*len(chunk)
                                    unchanged()
                                    if os.pread(fd,1,size):raise TransferError('media_source_content_changed')
                                    unchanged()
                                    if expected_observation is not None and digest.hexdigest()!=expected_observation.sha256:
                                        raise TransferError('media_source_observed_content_changed')
                                    result=cache.finish(digest.hexdigest()) if cache is not None else NativeMediaSourceObservation(
                                        size,digest.hexdigest(),mapping.file_key,signature,tuple(sorted(mapping.phone_original_reference().items())))
                                    if planning:
                                        from magnolie_media_source_planning import compare_current_source
                                        result=compare_current_source(self,mapping,result,unchanged)
                                    if reprepare is not None:
                                        self._cache_scope.repreparing=(reprepare,result,threading.get_ident())
                                        try:result=reprepare.complete(mapping,result,book.book_version,unchanged)
                                        finally:self._cache_scope.repreparing=None
                            current()
                        book.require_current()
            permission()
            if freeze or reprepare is not None:
                if self._prepared:raise TransferError('media_source_prepared_capacity')
                original=mapping if restoration is None else mapping.original_mapping
                self._prepared[result.manifest.source_id]=_PreparedSource(result,permission,book.book_version,threading.Event(),original,
                    None if restoration is None else mapping,reprepare)
            return result
        finally:self._gate.release()
