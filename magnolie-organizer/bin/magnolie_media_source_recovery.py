"""Explicit local recovery of an existing archival intent (#407).

Never reconstruct a sender or a raw-cache READ lease. Fresh native action,
consent/intent and original saved-book ownership authorize local verification
of encrypted members only. The earlier native archival intent, exact approved
wire version and completed local source backup remain independently mandatory.
"""
from hashlib import sha256
import os
import threading

from magnolie_file_control import _hex
from magnolie_file_transfer import CHUNK_BYTES,FileManifest,TransferError
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_retirement import (_NativeSourceRetirementJournal,_private,_move_no_replace,
    verified_source_backup,verify_archived_cache,verify_retirement_exchange)
from magnolie_media_retention import NativeMediaRetention
from magnolie_photo_destination import NativePhotoDestinationAction
from magnolie_photo_preferences import PhotoPreferencesSnapshot
from magnolie_telefon import canonical,strict_json


def verify_encrypted_source(jobs,parent,name,retired,ready,kind,current,boundary):
    """Authenticate metadata/cipher membership; NEVER unseal media payload."""
    if name not in (retired['stage'],retired['archive']):raise TransferError('media_source_recovery_original_stage_required')
    current();value=os.fstat(parent);_private(value,directory=True)
    if [value.st_dev,value.st_ino]!=retired['parent_key']:raise TransferError('media_source_retirement_original_parent_required')
    root=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
    try:
        def guarded():
            current();value=os.fstat(root);named=os.stat(name,dir_fd=parent,follow_symlinks=False)
            for item in (value,named):
                _private(item,directory=True)
                if [item.st_dev,item.st_ino]!=ready['root_key']:raise TransferError('media_source_retirement_original_archive_required')
        def cipher(leaf,witness=None):
            guarded();fd=os.open(leaf,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=root)
            try:
                before=os.fstat(fd);_private(before)
                if not 29<=before.st_size<=CHUNK_BYTES+28:raise TransferError('media_source_recovery_original_member_required')
                raw=os.pread(fd,before.st_size+1,0);boundary('source_recovery_cipher_read');guarded()
                after=os.fstat(fd);named=os.stat(leaf,dir_fd=root,follow_symlinks=False)
                signature=lambda v:(v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_nlink,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
                actual=dict(key=[after.st_dev,after.st_ino],size=len(raw),sha256=sha256(raw).hexdigest())
                if (len(raw)!=before.st_size or signature(before)!=signature(after) or signature(named)!=signature(after)
                        or witness is not None and actual!=witness):raise TransferError('media_source_recovery_original_member_required')
                return raw,actual
            finally:os.close(fd)
        def metadata(leaf,witness):
            raw,actual=cipher(leaf,witness);key=actual['key'];root_key=ready['root_key']
            domain='native-media-source-cache-v1/'+jobs._scope+'/'+str(root_key[0])+':'+str(root_key[1])+'/'+leaf+'/'+str(key[0])+':'+str(key[1])
            plain=jobs._authority.protection.unseal(raw,domain);body=strict_json(plain);guarded()
            if type(body) is not dict or canonical(body)!=plain:raise TransferError('media_source_recovery_invalid_metadata')
            return body
        proof=metadata('manifest.enc',retired['proof_witness']);manifest=FileManifest.parse(ready['manifest']);file=manifest.files[0]
        if (set(proof)!={'format','state','intent_sha256','job_nonce','book_version','manifest','chunks_sha256','chunk_count','metadata','original_references'}
                or type(proof['format']) is not int or proof['format']!=2 or proof['state']!='sealed'
                or proof['intent_sha256']!=ready['intent_sha256'] or proof['job_nonce']!=ready['nonce']
                or proof['book_version']!=ready['book_version'] or proof['manifest']!=ready['manifest']
                or proof['original_references']!=ready['original_references'] or type(proof['chunk_count']) is not int
                or proof['chunk_count']!=file.chunks or type(proof['metadata']) is not dict
                or set(proof['metadata'])!={'intent.enc','copying.enc'}):raise TransferError('media_source_recovery_original_proof_required')
        references=ready['original_references']
        if set(references)!={file.id} or references[file.id].get('media_type')!=kind:
            raise TransferError('media_source_recovery_original_media_scope_required')
        intent=metadata('intent.enc',proof['metadata']['intent.enc']);copying=metadata('copying.enc',proof['metadata']['copying.enc'])
        if (type(intent.get('format')) is not int or intent.get('format')!=2 or intent.get('state')!='planned'
                or intent.get('scope')!=jobs._scope or intent.get('job_id')!=manifest.source_id or intent.get('job_nonce')!=ready['nonce']
                or intent.get('file_id')!=file.id or intent.get('size')!=file.size or intent.get('chunks')!=file.chunks
                or intent.get('media_type')!=kind or intent.get('book_version')!=ready['book_version']
                or intent.get('root_key')!=ready['root_key'] or intent.get('parent_key')!=ready['parent_key']
                or intent.get('pairing_epoch')!=ready['pairing_epoch'] or intent.get('source_policy_sha256')!=ready['source_policy_sha256']
                or sha256(canonical(intent)).hexdigest()!=ready['intent_sha256']
                or copying!=dict(format=2,state='copying',intent_sha256=ready['intent_sha256'])):
            raise TransferError('media_source_recovery_original_intent_required')
        expected={'intent.enc','copying.enc','manifest.enc'}|{'chunk-%08x.enc'%i for i in range(file.chunks)}
        if set(os.listdir(root))!=expected:raise TransferError('media_source_recovery_archive_layout_changed')
        members=sha256()
        for index in range(file.chunks):
            _,witness=cipher('chunk-%08x.enc'%index)
            if witness['size']!=min(CHUNK_BYTES,file.size-index*CHUNK_BYTES)+28:
                raise TransferError('media_source_recovery_original_member_required')
            members.update(canonical(dict(index=index,**witness)))
        if members.hexdigest()!=proof['chunks_sha256']:raise TransferError('media_source_recovery_cipher_membership_changed')
        guarded()
        if set(os.listdir(root))!=expected:raise TransferError('media_source_recovery_archive_layout_changed')
        return intent # Authenticated metadata only, never a source READ grant.
    finally:os.close(root)


class _NativeSourceRetirementRecovery:
    def __init__(self,source,job_id,retirement_version,backups,selected,*,kind='images',boundary=lambda _:None):
        from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupVersion
        if (type(source) is not NativeMappedMediaSource or type(job_id) is not str or len(job_id)!=32 or not _hex(job_id*2)
                or not _hex(retirement_version) or type(backups) is not NativeMediaBackups or type(selected) is not NativeMediaBackupVersion
                or kind not in ('images','video') or not callable(boundary)):
            raise TransferError('media_source_recovery_native_owner_required')
        self._source=source;self._job=job_id;self._expected_version=retirement_version;self._backups=backups;self._selected=selected
        self._kind=kind;self._boundary=boundary;self._jobs=_NativeSourceJobs(source._authority);self._journal=_NativeSourceRetirementJournal(self._jobs)
        self._closed=threading.Event();self._book=self._permission=self._ready=self._record=None;self._thread=None

    def close(self):self._closed.set() # Actual descriptors/OS ownership drain on the I/O thread.

    def _current(self):
        if self._closed.is_set() or self._thread!=threading.get_ident() or self._book is None or self._permission is None:
            raise TransferError('media_source_recovery_live_lease_required')
        self._permission();self._book.require_current()
        if self._ready is None or self._book.book_version!=self._ready.body['book_version']:
            raise TransferError('media_source_original_book_required')
        actual=self._jobs.require_version(self._job,self._ready.version)
        if actual.body!=self._ready.body:raise TransferError('media_source_recovery_original_job_required')
        if self._record is not None:
            members=dict(self._jobs._catalog.lookup().body['members'])
            if members.get(self._jobs._catalog._exchange+self._job)!=self._record.body['exchange_version']:
                raise TransferError('media_source_recovery_original_exchange_required')
            with self._jobs._database() as (db,key):
                db.execute('BEGIN');self._jobs._catalog.verify(db,key)
                verify_retirement_exchange(self._jobs,db,key,self._ready,self._record.body)

    def _require_planned(self):
        self._current();actual=self._journal.lookup(self._job)
        if actual is None or actual.version!=self._expected_version or actual.body['state']!='archive_planned':
            raise TransferError('media_source_retirement_original_intent_required')

    def _backup_proof(self):
        ready=self._ready.body
        expected=dict(job_id=self._job,job_nonce=ready['nonce'],job_version=self._ready.version,
            proof_sha256=ready['proof_sha256'],book_version=ready['book_version'],manifest=ready['manifest'])
        reference=verified_source_backup(self._backups,self._selected,expected,self._source._authority.protection,self._current)
        if reference!=self._record.body['backup']:raise TransferError('media_source_recovery_original_backup_required')

    def run(self,action,expected):
        if type(action) is not NativePhotoDestinationAction or type(expected) is not PhotoPreferencesSnapshot:
            raise TransferError('media_source_native_selection_required')
        action.consume(self._source._preferences)
        if not self._source._gate.acquire(blocking=False):raise TransferError('media_source_busy')
        parent=None
        try:
            self._permission,_=self._source._source_permission(action,expected,self._kind);self._permission()
            record=self._journal.lookup(self._job);ready=self._jobs.lookup(self._job)
            if (record is None or record.version!=self._expected_version or record.body['state']!='archive_planned'
                    or ready is None or ready.state!='cache_ready' or record.body['ready_version']!=ready.version):
                raise TransferError('media_source_retirement_original_intent_required')
            body=record.body;original=ready.body
            if (body['nonce']!=original['nonce'] or body['root_key']!=original['root_key'] or body['parent_key']!=original['parent_key']
                    or body['manifest']!=original['manifest'] or body['proof_witness']['sha256']!=original['proof_sha256']):
                raise TransferError('media_source_recovery_original_job_required')
            self._record=record;self._ready=ready
            with NativeMediaRetention(self._source._authority.binding.native_directory) as retention:
                with retention.activity(self._permission,exclusive=True) as activity:
                    if activity is None:raise TransferError('media_source_media_io_busy')
                    with retention._active_copy_permit(activity) as book:
                        self._book=book;self._thread=threading.get_ident()
                        if book is None:raise TransferError('media_source_saved_book_required')
                        self._require_planned();self._backup_proof()
                        parent=os.open(self._source._authority.binding.native_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
                        def present(name):
                            self._current()
                            try:os.stat(name,dir_fd=parent,follow_symlinks=False);return True
                            except FileNotFoundError:return False
                        staged,archived=present(body['stage']),present(body['archive'])
                        if staged==archived:raise TransferError('media_source_recovery_ambiguous_stage')
                        name=body['stage'] if staged else body['archive']
                        verify_encrypted_source(self._jobs,parent,name,body,original,self._kind,self._current,self._boundary)
                        self._boundary('source_recovery_cipher_verified');self._require_planned();self._backup_proof()
                        if staged:
                            _move_no_replace(parent,body['stage'],body['archive']);os.fsync(parent)
                            self._boundary('source_recovery_moved');self._current()
                        verify_encrypted_source(self._jobs,parent,body['archive'],body,original,self._kind,self._current,self._boundary)
                        verify_archived_cache(self._jobs,parent,body,self._current);self._backup_proof();self._require_planned()
                        result=self._journal.write(self,self._record,dict(body,state='archived'))
                        self._boundary('source_recovery_archived');self._current();return result
        finally:
            if parent is not None:os.close(parent)
            self._thread=self._book=self._permission=None;self._source._gate.release()
