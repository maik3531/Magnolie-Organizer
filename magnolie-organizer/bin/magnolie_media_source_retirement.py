"""Live native completed-source archival (#406), never deletion or restart.

Keep every cache byte and original reference. Only an actual completed sender
plus independently verified local source backup can hand off drained READ to a
no-replace archive move while the original book/OS lane remains owned.
"""
from dataclasses import dataclass
from hashlib import sha256
import copy
import os
import stat
import threading

from magnolie_file_control import _hex
from magnolie_file_transfer import FileManifest,TransferError
from magnolie_media_trash import _move_no_replace
from magnolie_telefon import canonical,strict_json


@dataclass(frozen=True)
class NativeSourceRetirementObservation:
    version: str
    _body: dict
    @property
    def body(self):return copy.deepcopy(self._body)
    @property
    def grants_read_authority(self):return False
    @property
    def is_saved_receipt(self):return False
    @property
    def permits_deletion(self):return False
    @property
    def permits_slot_reuse(self):return False


class _NativeSourceRetirementJournal:
    MAX_BYTES=16384
    def __init__(self,jobs):
        self._jobs=jobs;self._prefix=jobs._catalog._retirement

    def _read(self,db,key,job):
        name=self._prefix+job;row=db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()
        if row is None:return None
        cipher=row[0]
        if type(cipher) is not bytes or not 29<=len(cipher)<=self.MAX_BYTES+28:raise TransferError('media_source_retirement_invalid_record')
        plain=self._jobs._authority.protection.unseal(cipher,name);body=strict_json(plain)
        if (type(body) is not dict or set(body)!={'format','scope','database_key','job_id','nonce','ready_version','exchange_version',
                'state','stage','archive','root_key','parent_key','manifest','proof_witness','backup'}
                or type(body['format']) is not int or body['format']!=1 or body['scope']!=self._jobs._scope
                or body['database_key']!=list(key) or body['job_id']!=job or body['state'] not in ('archive_planned','archived')
                or any(not _hex(body[name]) for name in ('nonce','ready_version','exchange_version'))
                or body['stage']!='.magnolie-source-'+self._jobs._scope[:32]+'.part'
                or body['archive']!='.magnolie-source-'+self._jobs._scope[:32]+'-'+job+'.retired'
                or canonical(body)!=plain):raise TransferError('media_source_retirement_invalid_record')
        manifest=FileManifest.parse(body['manifest'])
        if manifest.source_id!=job or len(manifest.files)!=1:raise TransferError('media_source_retirement_invalid_record')
        for field in ('root_key','parent_key'):
            value=body[field]
            if type(value) is not list or len(value)!=2 or any(type(n) is not int or not 0<=n<2**64 for n in value) or value[1]==0:
                raise TransferError('media_source_retirement_invalid_record')
        proof=body['proof_witness']
        if (type(proof) is not dict or set(proof)!={'key','sha256','size'} or not _hex(proof['sha256'])
                or type(proof['size']) is not int or not 29<=proof['size']<=65564
                or type(proof['key']) is not list or len(proof['key'])!=2
                or any(type(n) is not int or not 0<=n<2**64 for n in proof['key']) or proof['key'][1]==0):
            raise TransferError('media_source_retirement_invalid_record')
        backup=body['backup']
        from magnolie_media_backup_codec import content_key
        if (type(backup) is not dict or set(backup)!={'scope','root_key','storage_parent','version_id','record_sha256','object_key'}
                or any(not _hex(backup[field]) for field in ('scope','version_id','record_sha256'))
                or backup['object_key']!=content_key(manifest.files[0].size,manifest.files[0].sha256)):
            raise TransferError('media_source_retirement_invalid_record')
        from magnolie_file_acceptance import NativeAcceptedDestination
        NativeAcceptedDestination.parse(backup['storage_parent'])
        root=backup['root_key']
        if type(root) is not list or len(root)!=2 or any(type(n) is not int or not 0<=n<2**64 for n in root) or root[1]==0:
            raise TransferError('media_source_retirement_invalid_record')
        return NativeSourceRetirementObservation(sha256(cipher).hexdigest(),body)

    def lookup(self,job):
        with self._jobs._database() as (db,key):
            db.execute('BEGIN');catalog=self._jobs._catalog.verify(db,key);result=self._read(db,key,job)
        self._jobs._catalog.observe(catalog);return result

    def write(self,owner,expected,body):
        from magnolie_media_source_recovery import _NativeSourceRetirementRecovery
        if type(owner) not in (_NativeSourceRetirement,_NativeSourceRetirementRecovery) or owner._journal is not self:
            raise TransferError('media_source_retirement_live_owner_required')
        if type(owner) is _NativeSourceRetirementRecovery and expected is None:
            raise TransferError('media_source_retirement_original_intent_required')
        owner._current();job=owner._job
        with self._jobs._database() as (db,key):
            db.execute('BEGIN IMMEDIATE');catalog=self._jobs._catalog.verify(db,key);before=self._read(db,key,job)
            if expected is None:
                if before is not None:raise TransferError('media_source_retirement_existing_intent_held')
                body=dict(body,format=1,scope=self._jobs._scope,database_key=list(key),job_id=job)
                if body['state']!='archive_planned':raise TransferError('media_source_retirement_invalid_transition')
            elif (before is None or before.version!=expected.version or before.body['state']!='archive_planned'
                    or body!=dict(before.body,state='archived')):raise TransferError('media_source_retirement_original_intent_required')
            plain=canonical(body)
            if len(plain)>self.MAX_BYTES:raise TransferError('media_source_retirement_record_size')
            name=self._prefix+job;cipher=self._jobs._authority.protection.seal(plain,name)
            db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(name,cipher))
            self._read(db,key,job);self._jobs._catalog.advance(db,key,catalog);owner._current()
        owner._current();result=self.lookup(job)
        if result is None or result.version!=sha256(cipher).hexdigest():raise TransferError('media_source_retirement_readback_failed')
        return result


def _private(value,*,directory=False):
    if (value.st_uid!=os.geteuid() or value.st_mode&0o077 or not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))
            or not directory and value.st_nlink!=1):raise TransferError('media_source_retirement_unsafe_entry')


def verify_archived_cache(jobs,parent,body,current):
    current();value=os.fstat(parent);_private(value,directory=True)
    if [value.st_dev,value.st_ino]!=body['parent_key']:raise TransferError('media_source_retirement_original_parent_required')
    try:root=os.open(body['archive'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
    except FileNotFoundError:raise TransferError('media_source_retirement_original_archive_required')
    try:
        value=os.fstat(root);_private(value,directory=True)
        if [value.st_dev,value.st_ino]!=body['root_key']:raise TransferError('media_source_retirement_original_archive_required')
        manifest=FileManifest.parse(body['manifest']);expected={'intent.enc','copying.enc','manifest.enc'}
        expected|={'chunk-%08x.enc'%i for i in range(manifest.files[0].chunks)}
        if set(os.listdir(root))!=expected:raise TransferError('media_source_retirement_archive_layout_changed')
        for name in expected:_private(os.stat(name,dir_fd=root,follow_symlinks=False))
        fd=os.open('manifest.enc',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=root)
        try:
            before=os.fstat(fd);_private(before);proof=body['proof_witness']
            if [before.st_dev,before.st_ino]!=proof['key'] or before.st_size!=proof['size']:
                raise TransferError('media_source_retirement_original_proof_required')
            cipher=os.pread(fd,before.st_size+1,0);after=os.fstat(fd);named=os.stat('manifest.enc',dir_fd=root,follow_symlinks=False)
            signature=lambda v:(v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_nlink,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
            if (signature(before)!=signature(after) or signature(named)!=signature(after) or len(cipher)!=proof['size']
                    or sha256(cipher).hexdigest()!=proof['sha256']):raise TransferError('media_source_retirement_original_proof_required')
        finally:os.close(fd)
        named=os.stat(body['archive'],dir_fd=parent,follow_symlinks=False);_private(named,directory=True)
        if [named.st_dev,named.st_ino]!=body['root_key']:raise TransferError('media_source_retirement_original_archive_required')
        current()
    finally:os.close(root)


def verified_source_backup(backups,selected,expected,protection,current):
    from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupVersion
    from magnolie_media_source_backup import source_provenance
    if type(backups) is not NativeMediaBackups or type(selected) is not NativeMediaBackupVersion:
        raise TransferError('media_source_retirement_exact_local_backup_required')
    current();source=source_provenance(backups,selected)
    if (any(source.get(key)!=value for key,value in expected.items())
            or backups.protection.native_directory_identity!=protection.native_directory_identity):
        raise TransferError('media_source_retirement_exact_local_backup_required')
    with backups._operation():
        value=backups._record('versions',selected.id)
        if value is None or backups._version(value)!=selected:
            raise TransferError('media_source_retirement_complete_local_backup_required')
        obj=backups._record('objects',value['object_key'])
        if obj is None or obj['prepared']:raise TransferError('media_source_retirement_complete_local_backup_required')
        backups._verify_object(obj)
    current()
    return dict(scope=backups.scope,root_key=list(backups._root_key),storage_parent=backups.storage_parent.wire(),
        version_id=selected.id,record_sha256=selected.record_sha256,object_key=selected.object_key)


class _NativeSourceRetirement:
    def __init__(self,sender,backups,selected,*,boundary=lambda _:None):
        from magnolie_media_source_sender import _NativeMediaSourceSender
        from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupVersion
        if (type(sender) is not _NativeMediaSourceSender or type(backups) is not NativeMediaBackups
                or type(selected) is not NativeMediaBackupVersion or not callable(boundary)):
            raise TransferError('media_source_retirement_native_completed_owner_required')
        self._sender=sender;self._job=sender._job;self._backups=backups;self._selected=selected;self._boundary=boundary
        self._jobs=sender._jobs;self._journal=_NativeSourceRetirementJournal(self._jobs)
        self._reader=None;self._permit=None;self._record=None;self._closed=threading.Event();self._thread=None

    def close(self):self._closed.set() # Never release another thread's actual IO.

    def _current(self):
        sender=self._sender
        if self._closed.is_set() or self._thread!=threading.get_ident() or self._reader is None:
            raise TransferError('media_source_retirement_live_lease_required')
        sender._permission()
        if getattr(sender._source._cache_scope,'permit',None) is not self._permit:
            raise TransferError('media_source_retirement_live_lease_required')
        self._permit[2]()
        if sender._record is None or sender._record.body['phase']!='peer_saved':
            raise TransferError('media_source_retirement_actual_completed_sender_required')
        sender._journal.require(sender._record)
        if sender._controls.binding(sender._binding.destination_token,sender_is_local=True)!=sender._binding:
            raise TransferError('media_source_sender_binding_changed')

    def _backup_proof(self):
        cache=self._sender._cache
        expected=dict(job_id=self._job,job_nonce=cache._job_nonce,job_version=cache._job_version,
            proof_sha256=cache.proof_sha256,book_version=cache._book_version,manifest=cache.manifest.wire())
        return verified_source_backup(self._backups,self._selected,expected,self._sender._authority.protection,self._current)

    def _require_planned(self):
        self._current();record=self._journal.lookup(self._sender._job)
        if self._record is None or record is None or record.version!=self._record.version or record.body['state']!='archive_planned':
            raise TransferError('media_source_retirement_original_intent_required')

    def run(self):
        sender=self._sender
        if not sender._gate.acquire(blocking=False):raise TransferError('media_source_sender_busy')
        parent=None;handed=False
        try:
            with sender._source.prepared_cache(sender._job) as reader:
                self._reader=reader;self._thread=threading.get_ident();self._permit=sender._source._cache_scope.permit
                self._current();sender._active.reader=reader
                try:
                    sender._current();backup=self._backup_proof();cache=sender._cache
                    parent=os.open(sender._authority.binding.native_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
                    value=os.fstat(parent);parent_key=[value.st_dev,value.st_ino]
                    archive='.magnolie-source-'+self._jobs._scope[:32]+'-'+sender._job+'.retired'
                    body=dict(nonce=cache._job_nonce,ready_version=cache._job_version,exchange_version=sender._record.version,
                        state='archive_planned',stage=cache.directory.name,archive=archive,root_key=list(cache.root_key),parent_key=parent_key,
                        manifest=cache.manifest.wire(),proof_witness=copy.deepcopy(reader._proof_witness),backup=backup)
                    self._record=self._journal.write(self,None,body);self._boundary('source_retirement_planned');self._require_planned()
                    reader._handoff_retirement(self);handed=True
                    self._current();_move_no_replace(parent,body['stage'],archive);os.fsync(parent)
                    self._boundary('source_retirement_moved');self._current();verify_archived_cache(self._jobs,parent,body,self._current)
                    self._backup_proof();self._require_planned()
                    self._record=self._journal.write(self,self._record,dict(self._record.body,state='archived'))
                    self._boundary('source_retirement_archived');self._current();result=self._record
                finally:sender._active.reader=None
            return result
        except BaseException:
            sender.close();raise
        finally:
            if parent is not None:os.close(parent)
            if handed:sender.close()
            self._reader=None;self._permit=None;self._thread=None;sender._gate.release()
