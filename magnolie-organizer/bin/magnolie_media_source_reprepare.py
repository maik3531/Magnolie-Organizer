"""Fresh actual native ORIGINAL re-preparation (#410), not history adoption.

Called only after a new explicit native action has fully read the current mapped
original under its real descriptor/book/consent/intent lease. Matching metadata
alone cannot install a preparation. No cache, job, wire or retirement is mutated.
"""
from pathlib import Path
import os
import threading

from magnolie_file_control import _hex
from magnolie_file_transfer import FileManifest,TransferError
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_cache import FrozenNativeMediaSource
from magnolie_media_source_recovery import verify_encrypted_source
from magnolie_media_source_retirement import _private,_NativeSourceRetirementJournal,verify_archived_cache,verify_retirement_exchange


class _NativeSourceRepreparation:
    def __init__(self,source,job_id,job_version,kind):
        from magnolie_media_source import NativeMappedMediaSource
        if (type(source) is not NativeMappedMediaSource or type(job_id) is not str or len(job_id)!=32 or not _hex(job_id*2)
                or not _hex(job_version) or kind not in ('images','video')):
            raise TransferError('media_source_reprepare_native_selection_required')
        self._source=source;self._job=job_id;self._version=job_version;self._kind=kind
        self._jobs=_NativeSourceJobs(source._authority);self._used=False

    def _slot(self,parent,record,current):
        catalog=self._jobs._catalog;expected={'.magnolie-source-'+self._jobs._scope[:32]+'.part'}
        journal=_NativeSourceRetirementJournal(self._jobs)
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');head=catalog.verify(db,key);versions=dict(head.body['members'])
            if catalog._retirement+self._job in versions:raise TransferError('media_source_reprepare_retirement_held')
            for name,_ in head.body['members']:
                if not name.startswith(self._jobs._prefix) or name==self._jobs._key(self._job):continue
                current();job=name[len(self._jobs._prefix):];ready=self._jobs._read(db,key,job);retired=journal._read(db,key,job)
                if ready is None or retired is None or ready.state!='cache_ready' or retired.body['state']!='archived':
                    raise TransferError('media_source_reprepare_other_job_held')
                body=retired.body;original=ready.body
                if (body['ready_version']!=ready.version or body['nonce']!=original['nonce'] or body['manifest']!=original['manifest']
                        or body['root_key']!=original['root_key'] or body['parent_key']!=original['parent_key']
                        or body['proof_witness']['sha256']!=original['proof_sha256'] or versions.get(catalog._exchange+job)!=body['exchange_version']):
                    raise TransferError('media_source_reprepare_original_catalog_required')
                verify_retirement_exchange(self._jobs,db,key,ready,body)
                verify_archived_cache(self._jobs,parent,body,current);expected.add(body['archive'])
        catalog.observe(head)
        prefix='.magnolie-source-'+self._jobs._scope[:32];found=set();count=0
        with os.scandir(parent) as entries:
            for entry in entries:
                count+=1
                if count>4096:raise TransferError('media_source_slot_directory_capacity')
                if entry.name.startswith(prefix):found.add(entry.name)
        if found!=expected:raise TransferError('media_source_slot_unknown_stage')
        current();self._jobs.require_version(self._job,record.version)

    def complete(self,mapping,observed,book_version,current):
        # Never directly callable with a metadata-shaped observation. The exact
        # original descriptor read mints an unexported permit on its owning thread.
        permit=getattr(self._source._cache_scope,'repreparing',None)
        if permit is None or permit[0] is not self or permit[1] is not observed or permit[2]!=threading.get_ident() or self._used:
            raise TransferError('media_source_reprepare_actual_original_read_required')
        self._used=True;current();record=self._jobs.require_version(self._job,self._version);body=record.body
        if record.state!='cache_ready' or body['book_version']!=book_version:raise TransferError('media_source_original_book_required')
        manifest=FileManifest.parse(body['manifest']);file=manifest.files[0]
        if (observed.size!=file.size or observed.sha256!=file.sha256
                or body['original_references']!={file.id:mapping.phone_original_reference()}):
            raise TransferError('media_source_reprepare_original_bytes_required')
        directory=Path(self._source._authority.binding.native_directory);stage='.magnolie-source-'+self._jobs._scope[:32]+'.part'
        parent=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            value=os.fstat(parent);_private(value,directory=True)
            if [value.st_dev,value.st_ino]!=body['parent_key']:raise TransferError('media_source_reprepare_original_parent_required')
            self._slot(parent,record,current)
            root=os.open(stage,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
            try:
                value=os.fstat(root);_private(value,directory=True)
                if [value.st_dev,value.st_ino]!=body['root_key']:raise TransferError('media_source_reprepare_original_root_required')
                fd=os.open('manifest.enc',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=root)
                try:
                    value=os.fstat(fd);_private(value)
                    if not 29<=value.st_size<=65564:raise TransferError('media_source_reprepare_original_proof_required')
                    proof=dict(key=[value.st_dev,value.st_ino],size=value.st_size,sha256=body['proof_sha256'])
                finally:os.close(fd)
            finally:os.close(root)
            witness=dict(stage=stage,archive='.magnolie-source-'+self._jobs._scope[:32]+'-'+self._job+'.retired',
                parent_key=body['parent_key'],root_key=body['root_key'],proof_witness=proof)
            intent=verify_encrypted_source(self._jobs,parent,stage,witness,body,self._kind,current,self._source._boundary)
            if ('restored_source' in intent or intent.get('source_signature')!=list(observed.signature)
                    or intent.get('original_mapping_sha256')!=mapping.protected_record_sha256
                    or intent.get('original_reference')!=mapping.phone_original_reference() or intent.get('source_path')!=mapping.relative_path):
                raise TransferError('media_source_reprepare_original_mapping_required')
            current();self._slot(parent,record,current)
            result=FrozenNativeMediaSource(directory/stage,manifest,tuple(body['root_key']),body['proof_sha256'],
                tuple((key,tuple(sorted(value.items()))) for key,value in sorted(body['original_references'].items())),
                book_version,body['nonce'],record.version)
            self._completed_cache=result
            return result
        finally:os.close(parent)
