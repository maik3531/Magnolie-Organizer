"""Actual independently selected Linux PC sources, not a picker or autoloop.

The shared cache accepts only this exact live class or the original exact
mapped-source class. No synthetic phone mapping/reference is constructed.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
import threading

from magnolie_file_transfer import CHUNK_BYTES,TransferError
from magnolie_media_source import NativeMappedMediaSource,_PreparedSource
from magnolie_media_source_collection import NativeCollectionMember
from magnolie_media_source_roots import NativeMediaCollectionRootRecord
from magnolie_media_retention import NativeMediaRetention
from magnolie_media_sync import effective
from magnolie_telefon import canonical


def native_source_kind(owner):
    if type(owner) is NativeMappedMediaSource:return 'mapped'
    if type(owner) is NativeCollectionMediaSource:return 'collection'
    raise TransferError('media_source_exact_native_owner_required')


def validate_pc_origin(value):
    from magnolie_file_control import _hex
    if (type(value) is not dict or set(value)!={'format','root_id','root_version','root_key','root_birthtime','mount_id','file_key','file_birthtime','file_path'}
            or type(value['format']) is not int or value['format']!=1 or type(value['root_id']) is not str
            or len(value['root_id'])!=32 or not _hex(value['root_id']*2) or not _hex(value['root_version'])
            or type(value['mount_id']) is not int or value['mount_id']<=0):
        raise TransferError('media_collection_origin_invalid')
    for name in ('root_key','file_key'):
        key=value[name]
        if type(key) is not list or len(key)!=2 or any(type(n) is not int or not 0<=n<2**64 for n in key) or not key[1]:
            raise TransferError('media_collection_origin_invalid')
    for name in ('root_birthtime','file_birthtime'):
        birth=value[name]
        if type(birth) is not list or len(birth)!=2 or any(type(n) is not int for n in birth) or not 0<=birth[1]<1_000_000_000:
            raise TransferError('media_collection_origin_invalid')
    if value['root_key'][0]!=value['file_key'][0]:raise TransferError('media_collection_origin_invalid')
    from magnolie_media_source_collection import _leaf
    path=value['file_path']
    if type(path) is not str or len(path.split('/'))>17:raise TransferError('media_collection_origin_invalid')
    for part in path.split('/'):_leaf(part)
    if len(path.encode('utf-8'))>8192:raise TransferError('media_collection_origin_invalid')


@dataclass(frozen=True)
class _NativePcSelection:
    origin_bytes: bytes
    catalog_bytes: bytes
    path: str
    previous: object = None # Historical correlation only; never native READ authority.
    @property
    def origin(self):
        from magnolie_telefon import strict_json
        return strict_json(self.origin_bytes)
    @property
    def catalog(self):
        from magnolie_telefon import strict_json
        return strict_json(self.catalog_bytes)


class NativeCollectionMediaSource(NativeMappedMediaSource):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self._held={};self._selected={};self._handoff={}

    def _read(self,*args,**kwargs):
        raise TransferError('media_collection_native_root_selection_required')

    def _close_held(self):
        for root,member,catalog in self._held.values():
            try:member.close()
            finally:
                try:root.close()
                finally:catalog.close()
        self._held.clear()
        self._selected.clear()
        self._handoff.clear()

    def _handoff_original(self,retirement):
        from magnolie_media_source_retirement import _NativeSourceRetirement
        if type(retirement) is not _NativeSourceRetirement or not retirement._permits_pc_source_checkpoint(self,retirement._job):
            raise TransferError('media_collection_original_drain_owner_required')
        job=retirement._job;held=self._held.get(job)
        if held is None or job in self._handoff:raise TransferError('media_collection_original_drain_owner_required')
        held[1].close();held[0].close() # Synchronous drain, never an ACK witness.
        self._handoff[job]=retirement

    def close(self):
        super().close()
        if self._gate.acquire(blocking=False):
            try:self._close_held()
            finally:self._gate.release()

    @contextmanager
    def prepared_cache(self,job_id):
        try:
            held=self._held.get(job_id);selected=self._selected.get(job_id)
            if self._closed.is_set() or held is None or selected is None:raise TransferError('media_source_prepared_owner_required')
            catalog=held[2]
            with catalog.selected_root_lease(selected):
                with super().prepared_cache(job_id) as reader:yield reader
        except BaseException:
            if job_id in self._prepared:self._prepared[job_id].failed.set()
            raise
        finally:
            if job_id not in self._prepared or self._closed.is_set() or any(p.failed.is_set() for p in self._prepared.values()):self.close()

    def freeze(self,action,expected,selected,member,*,kind='images',native_current=lambda:True):
        return self._freeze(action,expected,selected,member,kind,native_current,False)

    def freeze_completed_successor(self,action,expected,selected,member,*,kind='images',native_current=lambda:True):
        return self._freeze(action,expected,selected,member,kind,native_current,True)

    def _freeze(self,action,expected,selected,member,kind,native_current,completed_successor):
        from magnolie_photo_destination import NativePhotoDestinationAction
        from magnolie_photo_preferences import PhotoPreferencesSnapshot
        if (type(action) is not NativePhotoDestinationAction or type(expected) is not PhotoPreferencesSnapshot
                or type(selected) is not NativeMediaCollectionRootRecord or type(member) is not NativeCollectionMember
                or kind not in ('images','video') or selected.media_type!=('images' if kind=='images' else 'videos')
                or not callable(native_current)):
            raise TransferError('media_collection_native_root_selection_required')
        action.consume(self._preferences)
        if not self._gate.acquire(blocking=False):raise TransferError('media_source_busy')
        root=lease=catalog=None;retired=threading.Event();retained=False
        try:
            if self._prepared:raise TransferError('media_source_prepared_capacity')
            original_permission,token=self._source_permission(action,expected,kind)
            original_permission()
            if expected.policy.mapping_store is not None:self._mappings.verify_witness(expected.policy.mapping_store)
            mapping_snapshot=self._mappings.require_independent_native_file(member.key)
            def permission():
                try:
                    if retired.is_set() or native_current() is not True:raise TransferError('media_collection_native_owner_revoked')
                    original_permission()
                    if effective(token.body)['collection_mode']!='entire_collection':raise TransferError('media_collection_entire_scope_required')
                    # Decode every historical mapping once at admission, then
                    # pin its complete authenticated owner/member digest. Any
                    # later change HOLDs; it cannot silently add a mapping.
                    if self._mappings.read()!=mapping_snapshot:raise TransferError('media_collection_original_mappings_changed')
                    return True
                except BaseException:retired.set();raise
            permission();catalog=self._preferences.open_collection_roots()
            root=catalog.open_root(selected,permission);lease=root.open_member(member)
            from magnolie_file_transfer import _portable_path
            _portable_path(member.name) # Refuse unsupported names, never normalize originals.
            origin=dict(format=1,root_id=selected.id,root_version=selected.version,root_key=list(selected.key),
                root_birthtime=list(selected.birthtime),mount_id=selected.mount_id,file_key=list(member.key),file_birthtime=list(member.birthtime),
                file_path='/'.join([p.name for p in member.parents]+[member.name]))
            validate_pc_origin(origin)
            catalog_bytes=canonical(catalog.witness().wire())
            with catalog.selected_root_lease(selected),NativeMediaRetention(self._authority.binding.native_directory) as retention:
                with retention.activity(permission,exclusive=True) as activity:
                    if activity is None:raise TransferError('media_source_media_io_busy')
                    with retention._active_copy_permit(activity) as book:
                        if book is None:raise TransferError('media_source_saved_book_required')
                        def current():book.require_current();lease._require();return True
                        def prefix_bytes(limit):
                            prefix=bytearray()
                            try:
                                while len(prefix)<min(member.size,limit):
                                    current();data=lease.read_exact(len(prefix),min(CHUNK_BYTES,min(member.size,limit)-len(prefix)))
                                    try:prefix.extend(data)
                                    finally:data[:]=b'\0'*len(data)
                                current();return prefix
                            except BaseException:prefix[:]=b'\0'*len(prefix);raise
                        from magnolie_media_mime import PREFIX_BYTES,identify
                        prefix=prefix_bytes(PREFIX_BYTES)
                        try:identify(prefix,member.size,kind);current()
                        finally:prefix[:]=b'\0'*len(prefix)
                        if kind=='images' and effective(token.body)['photos_only']:
                            from magnolie_photo_metadata import MAX_METADATA_BYTES,camera_photo_matches
                            prefix=prefix_bytes(MAX_METADATA_BYTES)
                            try:
                                current()
                                if not camera_photo_matches(prefix):raise TransferError('media_source_photo_metadata_required')
                            finally:prefix[:]=b'\0'*len(prefix)
                        from magnolie_media_source_cache import _NativeSourceCacheWriter
                        previous=None
                        if completed_successor:
                            from magnolie_media_source_jobs import _NativeSourceJobs
                            jobs=_NativeSourceJobs(self._authority);previous=jobs.completed_pc_origin(origin)
                            parent=os.open(self._authority.binding.native_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
                            try:
                                _NativeSourceCacheWriter._private(os.fstat(parent),directory=True)
                                jobs._catalog.require_free_slot(parent,current)
                            finally:os.close(parent)
                            # A matching size/old digest is not a fresh native
                            # observation. Hash the entire current held original
                            # before deciding no new cache/job/offer is needed.
                            digest=sha256();offset=0
                            while offset<member.size:
                                current();data=lease.read_exact(offset,min(CHUNK_BYTES,member.size-offset))
                                try:digest.update(data);offset+=len(data)
                                finally:data[:]=b'\0'*len(data)
                            current()
                            observed=jobs._catalog.lookup()
                            if observed is None or observed.version!=previous.catalog_version:
                                raise TransferError('media_collection_original_predecessor_changed')
                            if member.size==previous.size and digest.hexdigest()==previous.sha256:
                                raise TransferError('media_collection_latest_payload_already_sent')
                        selection=_NativePcSelection(canonical(origin),catalog_bytes,member.name,previous)
                        with _NativeSourceCacheWriter(self,None,member.size,lease._signature,token,expected,kind,book.book_version,current,
                                pc_selection=selection) as cache:
                            digest=sha256();offset=0;index=0
                            while offset<member.size:
                                current();data=lease.read_exact(offset,min(CHUNK_BYTES,member.size-offset))
                                try:
                                    self._boundary('source_chunk_read');current();digest.update(data);cache.chunk(index,data)
                                    offset+=len(data);index+=1
                                finally:data[:]=b'\0'*len(data)
                            current();result=cache.finish(digest.hexdigest())
                        version=book.book_version
            def prepared_permission():
                handoff=self._handoff.get(result.manifest.source_id)
                if handoff is None:lease._require()
                else:
                    if not handoff._permits_pc_source_checkpoint(self,result.manifest.source_id):
                        raise TransferError('media_collection_original_drain_owner_required')
                    permission() # Cleanup checkpoint only; original files drained.
                return True
            prepared_permission()
            self._prepared[result.manifest.source_id]=_PreparedSource(result,prepared_permission,version,threading.Event(),None)
            self._held[result.manifest.source_id]=(root,lease,catalog);retained=True
            self._selected[result.manifest.source_id]=selected
            return result
        finally:
            if not retained:
                if lease is not None:lease.close()
                if root is not None:root.close()
                if catalog is not None:catalog.close()
            self._gate.release()
            if self._closed.is_set():self.close()
