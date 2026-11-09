"""Native local media trash and no-replace restore, not a wire/UI delete handler.

An encrypted append-only journal precedes each move. Recoverable original bytes
stay at a random private filename in the ORIGINAL parent, on the same filesystem.
No unlink, automatic purge, guessed absence tombstone or cross-device ACK exists.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from hashlib import sha256
import ctypes
import os
import secrets
import stat
import sys
import threading
import time

from magnolie_file_control import MAX_REVISION, _hex
from magnolie_file_transfer import CHUNK_BYTES, TransferError
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_photo_destination import NativePhotoDestinationAction,require_media_directory
from magnolie_photo_mappings import ProtectedPhotoMappings, PhotoMappingAssociation, NativeSavedPhotoMapping
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_telefon import canonical, strict_json
from magnolie_transfer_job_catalog import NativeJobCatalogIdentity


@dataclass(frozen=True)
class _LocalTrashBinding:
    native_directory: str


@dataclass(frozen=True)
class _LocalTrashScope:
    peer_id: str
    identity_sha256: str
    pairing_epoch: str | None


class NativeLocalMediaTrashAuthority:
    """Existing local recovery only: no channel, peer grants, READ or new trash.

    The native Organizer owner supplies its own existing telephone root and an
    opaque anchor scope, never a path from the browser/phone. Authenticated local
    history is usable even after disconnect/unpair; no peer is impersonated.
    """
    def __init__(self,native_directory,scope,*,local_guard=lambda:True):
        if not _hex(scope):raise TransferError('media_trash_local_scope_required')
        if not callable(local_guard) or local_guard() is not True:raise TransferError('media_trash_local_guard_required')
        self._local_guard=local_guard
        self.protection=ExistingFileTransferProtection(native_directory)
        self._revoked=threading.Event();self._history_epoch=None;self.scope=scope
        self.binding=_LocalTrashBinding(str(native_directory))
        self._anchor_name='media-trash-anchor-v1-'+scope+'.seal'
        parent=None;fd=None
        try:
            parent=os.open(native_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
            if (os.fstat(parent).st_dev,os.fstat(parent).st_ino)!=self.protection.native_directory_identity:
                raise TransferError('media_trash_original_root_changed')
            fd=os.open(self._anchor_name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=parent)
            before=os.fstat(fd);ProtectedPhotoPreferences._private(before)
            if not 28<=before.st_size<=8192:raise TransferError('media_trash_original_anchor_changed')
            blob=os.read(fd,8193);after=os.fstat(fd);named=os.stat(self._anchor_name,dir_fd=parent,follow_symlinks=False)
            signature=ExistingFileTransferProtection._signature
            if len(blob)!=before.st_size or signature(before)!=signature(after) or signature(after)!=signature(named):
                raise TransferError('media_trash_original_anchor_changed')
            plain=self.protection.unseal(blob,'magnolie-media-trash-v1/'+scope+'/anchor')
            value=strict_json(plain)
            if (type(value) is not dict or set(value)!={'format','subject','root_key','database_key','lock_key'}
                    or type(value['format']) is not int or value['format']!=1 or canonical(value)!=plain):
                raise TransferError('media_trash_original_anchor_changed')
            subject=value['subject']
            if (type(subject) is not dict or set(subject)!={'local_id','local_identity','peer_id','peer_identity'}
                    or sha256(canonical(subject)).hexdigest()!=scope):
                raise TransferError('media_trash_local_scope_required')
            self.identity=NativeJobCatalogIdentity(subject['local_id'],subject['local_identity'])
            NativeJobCatalogIdentity(subject['peer_id'],subject['peer_identity'])
            self.subject=dict(subject)
            self._anchor_identity=((before.st_dev,before.st_ino),sha256(blob).hexdigest())
        except BaseException:
            self.close();raise
        finally:
            if fd is not None:os.close(fd)
            if parent is not None:os.close(parent)

    def bind_history_epoch(self,epoch):
        if not _hex(epoch) or self._history_epoch is not None and epoch!=self._history_epoch:
            raise TransferError('media_trash_local_history_changed')
        self._history_epoch=epoch

    def current_peer(self):
        # A local historical namespace, deliberately not NativeFilePeerSnapshot:
        # there is no control_peer()/transport/grant conversion on this object.
        if self._revoked.is_set():return None
        try:
            if self._local_guard() is not True:
                self.revoke();return None
            self.protection._read_key()
        except BaseException:
            self.revoke();raise
        return _LocalTrashScope(self.subject['peer_id'],self.subject['peer_identity'],self._history_epoch)

    def revoke(self):self._revoked.set()

    def close(self):
        self.revoke();self.protection.close()


@dataclass(frozen=True)
class MediaTrashSnapshot:
    version: str
    revision: int
    count: int
    associated: bool


@dataclass(frozen=True)
class NativeMediaPurgeLocation:
    name: str
    key: tuple
    retention_days: int
    manual: bool = False

    def wire(self):
        value=dict(name=self.name,key=list(self.key),retention_days=self.retention_days)
        if self.manual:value['manual']=True
        return value

    @classmethod
    def parse(cls,value,operation,mapping):
        fields={'name','key','retention_days'}
        if (type(value) is not dict or not fields<=set(value) or not set(value)<=fields|{'manual'}
                or 'manual' in value and value['manual'] is not True or value['name']!='.magnolie-purge-'+operation
                or type(value['retention_days']) is not int
                or value['retention_days'] not in ((0,) if value.get('manual') is True else (7,30,90,365))
                or type(value['key']) is not list or len(value['key'])!=2
                or any(type(number) is not int or not 0<=number<2**64 for number in value['key'])
                or value['key'][1]==0 or value['key'][0]!=mapping.file_key[0]):
            raise TransferError('media_trash_invalid_purge_location')
        return cls(value['name'],tuple(value['key']),value['retention_days'],value.get('manual',False))


class NativeMediaRetentionPermit:
    """Nonserializable native setting witness; never a remote deletion grant."""
    def __init__(self,days,current_days):
        if type(days) is not int or days not in (0,7,30,90,365) or not callable(current_days):
            raise TransferError('media_trash_invalid_retention')
        self.days=days;self._current=current_days;self._revoked=False

    def require_current(self):
        try:current=self._current()
        except BaseException:
            self._revoked=True;raise
        if self._revoked or type(current) is not int or current!=self.days:
            self._revoked=True;raise TransferError('media_trash_retention_changed')
        return self.days


class _ManualMediaPurgePermit:
    """Only the selected original operation, while the native UI is current."""
    days=0

    def __init__(self,owner,operation,current):
        if not callable(current):raise TransferError('media_trash_native_confirmation_required')
        self.owner=owner;self.operation=operation;self._current=current;self._revoked=False

    def require_current(self):
        try:allowed=self._current()
        except BaseException:
            self._revoked=True;raise
        if self._revoked or allowed is not True:
            self._revoked=True;raise TransferError('media_trash_native_confirmation_changed')
        return 0


@dataclass(frozen=True)
class NativeMediaTrashEntry:
    operation: str
    state: str
    mapping: NativeSavedPhotoMapping
    sequence: int
    changed_ms: int | None = None
    trashed_ms: int | None = None
    purge: NativeMediaPurgeLocation | None = None

    @property
    def grants_write_authority(self):return False

    @property
    def is_counterpart_ack(self):return False

    @property
    def payload_name(self):return '.magnolie-trash-'+self.operation

    def expired(self,retention_days,now_ms):
        """Local confirmed trash time only; never a peer/file mtime or absence."""
        if type(retention_days) is not int or retention_days not in (0,7,30,90,365):
            raise TransferError('media_trash_invalid_retention')
        if type(now_ms) is not int or not 0<=now_ms<=253402300799999:
            raise TransferError('media_trash_invalid_clock')
        return bool(retention_days and self.state in ('trashed','purge_prepared') and self.trashed_ms is not None
            and now_ms>=self.trashed_ms+retention_days*86400000)


def _move_no_replace(parent,source,target,*,target_parent=None):
    if sys.platform!='linux':raise TransferError('media_trash_native_platform_required')
    libc=ctypes.CDLL(None,use_errno=True)
    rename=getattr(libc,'renameat2',None)
    if rename is None:raise TransferError('media_trash_no_replace_required')
    rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    rename.restype=ctypes.c_int
    if rename(parent,os.fsencode(source),parent if target_parent is None else target_parent,os.fsencode(target),1)!=0:
        error=ctypes.get_errno();raise OSError(error,os.strerror(error))


class ProtectedMediaTrash(ProtectedPhotoPreferences):
    MAX_DATABASE_BYTES=64*1024*1024
    MAX_OPERATIONS=128 # No eviction. Four event slots are reserved per operation.
    _SCHEMA={
        'owner':'CREATE TABLE owner (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)',
        'events':'CREATE TABLE events (sequence INTEGER PRIMARY KEY, operation TEXT NOT NULL, payload BLOB NOT NULL)'}
    _NEXT={None:('prepared',),'prepared':('trashed','canceled'),
        'trashed':('restore_prepared','purge_prepared'),'restore_prepared':('restored',),
        'purge_prepared':('purged','restored')}

    def __init__(self,authority,*,boundary=lambda _:None,wall_clock_ms=lambda:time.time_ns()//1_000_000,**kwargs):
        if not callable(wall_clock_ms):raise TransferError('media_trash_invalid_clock')
        self._wall_clock_ms=wall_clock_ms
        self._recovery_only=type(authority) is NativeLocalMediaTrashAuthority
        if self._recovery_only:
            if set(kwargs)-{'monotonic_ms'}:raise TransferError('media_trash_local_options_invalid')
            self._initialize_store(authority,authority.subject,kwargs.get('monotonic_ms',lambda:time.monotonic_ns()//1_000_000))
        else:super().__init__(authority,**kwargs)
        self._name='media-trash-v1-'+self._scope
        self._domain='magnolie-media-trash-v1/'+self._scope+'/'
        self._absent=sha256((self._domain+'absent').encode()).hexdigest()
        self._boundary=boundary
        self._anchor='media-trash-anchor-v1-'+self._scope+'.seal'
        self._anchor_identity=None

    def _anchor_value(self):
        return dict(format=1,subject=self._subject,root_key=list(self._root_key),
            database_key=list(self._db_key),lock_key=list(self._lock_key))

    def _read_anchor(self):
        fd=os.open(self._anchor,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=self._parent_fd)
        try:
            before=os.fstat(fd);self._private(before)
            if not 28<=before.st_size<=8192:raise TransferError('media_trash_original_anchor_changed')
            blob=os.read(fd,8193);after=os.fstat(fd)
            named=os.stat(self._anchor,dir_fd=self._parent_fd,follow_symlinks=False)
            if (len(blob)!=before.st_size or self._key(before)!=self._key(named) or before.st_size!=after.st_size
                    or before.st_mtime_ns!=after.st_mtime_ns or before.st_ctime_ns!=after.st_ctime_ns):
                raise TransferError('media_trash_original_anchor_changed')
            return self._key(before),blob
        finally:os.close(fd)

    def _fresh(self):
        super()._fresh()
        if self._anchor_identity is not None:
            key,blob=self._read_anchor()
            if (key,sha256(blob).hexdigest())!=self._anchor_identity:
                raise TransferError('media_trash_original_anchor_changed')

    def _open(self,*,create=False,validate=lambda:None):
        # The independent native-root anchor makes a missing/replaced journal a
        # held original, not an empty replacement after reconnect/restart.
        parent=os.open(self._authority.binding.native_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            if self._key(os.fstat(parent))!=self._authority.protection.native_directory_identity:
                raise TransferError('media_trash_original_root_changed')
            def exists(name):
                try:os.stat(name,dir_fd=parent,follow_symlinks=False);return True
                except FileNotFoundError:return False
            present,anchored=exists(self._name),exists(self._anchor)
            if present!=anchored or not present and (self._recovery_only or self._anchor_identity is not None):
                raise TransferError('media_trash_original_anchor_required')
            if not present and not create:return False
            result=super()._open(create=create,validate=validate)
            if not present:
                validate();self._fresh()
                blob=self._authority.protection.seal(canonical(self._anchor_value()),self._domain+'anchor')
                fd=os.open(self._anchor,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self._parent_fd)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(blob);stream.flush();os.fsync(stream.fileno())
                os.fsync(self._parent_fd)
            key,blob=self._read_anchor()
            plain=self._authority.protection.unseal(blob,self._domain+'anchor')
            if strict_json(plain)!=self._anchor_value() or canonical(self._anchor_value())!=plain:
                raise TransferError('media_trash_original_anchor_changed')
            identity=key,sha256(blob).hexdigest()
            if self._recovery_only and identity!=self._authority._anchor_identity:
                raise TransferError('media_trash_original_anchor_changed')
            if self._anchor_identity is not None and self._anchor_identity!=identity:
                raise TransferError('media_trash_original_anchor_changed')
            self._anchor_identity=identity;self._fresh();return result
        finally:os.close(parent)

    def _initial_owner(self):
        return dict(revision=1,count=0,events=0,events_sha256=sha256(b'').hexdigest(),pairing_epoch=self._peer().pairing_epoch)

    def _entries(self):
        digest=sha256();entries={};count=0
        for sequence,operation,blob in self._db.execute('SELECT sequence,operation,payload FROM events ORDER BY sequence'):
            if (type(sequence) is not int or sequence!=count+1 or count>=self.MAX_OPERATIONS*4
                    or type(operation) is not str or len(operation)!=32 or not _hex(operation*2)):
                raise TransferError('media_trash_invalid_event')
            value=self._unprotect(blob,'event/'+str(sequence))
            fields={'operation','state','mapping','mapping_sha256'}
            if (type(value) is not dict or not fields<=set(value) or not set(value)<=fields|{'changed_ms','purge'} or value['operation']!=operation
                    or type(value['state']) is not str or type(value['mapping']) is not dict):
                raise TransferError('media_trash_invalid_event')
            raw=value['mapping'].get('association')
            if type(raw) is not dict or set(raw)!={'source_epoch','photo_id','media_type'}:
                raise TransferError('media_trash_invalid_association')
            association=PhotoMappingAssociation(**raw)
            mapping=NativeSavedPhotoMapping.parse(value['mapping'],association,value['mapping_sha256'])
            previous=entries.get(operation)
            changed_ms=value.get('changed_ms')
            if ('changed_ms' in value and (type(changed_ms) is not int or not 0<=changed_ms<=253402300799999)
                    or previous is not None and previous.changed_ms is not None and (changed_ms is None or changed_ms<previous.changed_ms)):
                raise TransferError('media_trash_invalid_clock')
            if (value['state'] not in self._NEXT.get(previous.state if previous else None,())
                    or previous is not None and previous.mapping!=mapping):
                raise TransferError('media_trash_event_chain_changed')
            purge=NativeMediaPurgeLocation.parse(value['purge'],operation,mapping) if 'purge' in value else None
            if (purge is not None and (value['state'] not in ('purge_prepared','purged','restored')
                    or previous is None or previous.purge is None and value['state']!='purge_prepared'
                    or previous.purge is not None and previous.purge!=purge)
                    or purge is None and (value['state'] in ('purge_prepared','purged') or previous is not None and previous.purge is not None)):
                raise TransferError('media_trash_purge_chain_changed')
            if value['state']=='purge_prepared' and not purge.manual and (previous.trashed_ms is None or changed_ms is None
                    or changed_ms<previous.trashed_ms+purge.retention_days*86400000):
                raise TransferError('media_trash_purge_time_unproven')
            trashed_ms=changed_ms if value['state']=='trashed' else previous.trashed_ms if previous else None
            entries[operation]=NativeMediaTrashEntry(operation,value['state'],mapping,sequence,changed_ms,trashed_ms,purge)
            if len(entries)>self.MAX_OPERATIONS:raise TransferError('media_trash_history_full')
            digest.update(str(sequence).encode('ascii')+operation.encode('ascii')+sha256(blob).digest());count+=1
        self._fresh()
        return entries,count,digest.hexdigest()

    def _snapshot(self):
        rows=self._db.execute('SELECT id,payload FROM owner').fetchall()
        if len(rows)!=1 or rows[0][0]!=1:raise TransferError('media_trash_owner_required')
        blob=rows[0][1];owner=self._unprotect(blob,'owner')
        if (type(owner) is not dict or set(owner)!={'revision','count','events','events_sha256','pairing_epoch'}
                or any(type(owner[key]) is not int for key in ('revision','count','events'))
                or not 1<=owner['revision']<=MAX_REVISION or not _hex(owner['pairing_epoch']) or not _hex(owner['events_sha256'])):
            raise TransferError('media_trash_invalid_owner')
        if self._recovery_only:self._authority.bind_history_epoch(owner['pairing_epoch'])
        entries,count,digest=self._entries()
        if (owner['count'],owner['events'],owner['events_sha256'],owner['revision'])!=(len(entries),count,digest,count+1):
            raise TransferError('media_trash_history_changed')
        version=sha256(blob).hexdigest()
        if self._last is not None and (owner['revision']<self._last[0] or owner['revision']==self._last[0] and version!=self._last[1]):
            self._uncertain=True;raise TransferError('media_trash_owner_rollback')
        self._last=owner['revision'],version
        associated=owner['pairing_epoch']==self._peer().pairing_epoch
        return MediaTrashSnapshot(self._absent if not count and associated else version,owner['revision'],len(entries),associated)

    def read(self):
        with self._operation():
            if not self._open():return MediaTrashSnapshot(self._absent,0,0,False),()
            with self._locked():
                self._schema();snapshot=self._snapshot();entries,_,_=self._entries();self._sync()
                return snapshot,tuple(entries.values())

    def _require(self,action,expected):
        action.validate(self);self._schema();current=self._snapshot()
        if current.version!=expected.version:raise TransferError('media_trash_stale_choice')
        if not current.associated:raise TransferError('media_trash_reassociation_required')
        return current

    def _append(self,action,current,operation,state,mapping,*,purge=None):
        entries,count,_=self._entries();previous=entries.get(operation)
        if (state not in self._NEXT.get(previous.state if previous else None,()) or previous is not None and previous.mapping!=mapping
                or previous is None and len(entries)>=self.MAX_OPERATIONS or count+2>MAX_REVISION):
            raise TransferError('media_trash_transition_unavailable')
        sequence=count+1
        now=self._wall_clock_ms()
        if type(now) is not int or not 0<=now<=253402300799999:raise TransferError('media_trash_invalid_clock')
        changed_ms=max(now,previous.changed_ms or 0) if previous is not None else now
        payload=dict(operation=operation,state=state,mapping=mapping.wire(),mapping_sha256=mapping.protected_record_sha256,changed_ms=changed_ms)
        purge=purge if purge is not None else previous.purge if previous is not None else None
        if purge is not None:payload['purge']=purge.wire()
        try:
            self._db.execute('BEGIN IMMEDIATE')
            self._require(action,current)
            self._db.execute('INSERT INTO events VALUES(?,?,?)',(sequence,operation,self._protect(payload,'event/'+str(sequence))))
            members,total,digest=self._entries()
            owner=dict(revision=total+1,count=len(members),events=total,events_sha256=digest,pairing_epoch=self._peer().pairing_epoch)
            self._db.execute('UPDATE owner SET payload=? WHERE id=1',(self._protect(owner,'owner'),))
            action.validate(self);self._fresh();self._db.commit();self._sync()
            result=self._snapshot();return result,members[operation]
        except BaseException:
            if self._db.in_transaction:self._db.rollback()
            # Commit/fsync may be uncertain. Never report completion or reset.
            self._uncertain=True
            raise

    @staticmethod
    def _action(action,expected):
        if type(action) is not NativePhotoDestinationAction or type(expected) is not MediaTrashSnapshot:
            raise TransferError('media_trash_native_action_required')

    def prepare_local(self,action,expected,mappings,association,expected_mapping_sha256):
        """Explicit native selection, not a missing-scan inference or remote claim."""
        self._action(action,expected);action.consume(self)
        if self._recovery_only:raise TransferError('media_trash_local_recovery_only')
        if type(mappings) is not ProtectedPhotoMappings or mappings._authority is not self._authority:
            raise TransferError('media_trash_original_mapping_store_required')
        mapping_snapshot,records=mappings.lookup((association,));mapping=records[0]
        if not mapping_snapshot.associated or mapping is None or mapping.protected_record_sha256!=expected_mapping_sha256:
            raise TransferError('media_trash_original_mapping_changed')
        require_media_directory(os.path.join(mapping.destination.path,mapping.relative_path))
        with self._operation():
            self._open(create=True,validate=lambda:action.validate(self))
            with self._locked():
                current=self._require(action,expected);entries,_,_=self._entries()
                if any(entry.mapping.association==association and entry.state not in ('restored','canceled') for entry in entries.values()):
                    raise TransferError('media_trash_original_operation_required')
                result=self._append(action,current,secrets.token_hex(16),'prepared',mapping)
                self._boundary('prepared');return result

    def trash(self,action,expected,operation,native_gate):
        return self._execute(action,expected,operation,native_gate,restore=False)

    def preview(self,action,expected,operation,native_gate,*,mode='thumbnail'):
        """Read ONLY the exact retained trash payload; no move or event append."""
        from magnolie_media_preview import preview_held_file,SIZES
        from magnolie_media_retention import NativeMediaRetention
        self._action(action,expected);action.consume(self)
        if mode not in SIZES or not callable(native_gate):raise TransferError('media_preview_native_source_required')
        with self._operation():
            if not self._open():raise TransferError('media_trash_original_operation_required')
            with self._locked():
                current=self._require(action,expected);entries,_,_=self._entries();entry=entries.get(operation)
                if entry is None or entry.state not in ('prepared','trashed','restore_prepared','purge_prepared'):
                    raise TransferError('media_trash_preview_not_current')
                def fresh():
                    action.validate(self);self._fresh()
                    if native_gate() is not True:raise TransferError('media_trash_native_gate_revoked')
                    return True
                with NativeMediaRetention(self._authority.protection.native_directory) as retention:
                    with retention.activity(fresh) as activity:
                        if activity is None:raise TransferError('media_retention_maintenance_busy')
                        with self._target_context(entry,fresh) as (parent,_,directories,opened):
                            from contextlib import ExitStack
                            with ExitStack() as held:
                                source_parent,name=parent,entry.payload_name
                                if entry.state=='purge_prepared':
                                    capsule,check=held.enter_context(self._purge_context(entry,parent,directories))
                                    archived,staged=self._exists(parent,name),self._exists(capsule,'payload')
                                    if archived==staged:raise TransferError('media_trash_preview_payload_unproven')
                                    if staged:source_parent,name=capsule,'payload'
                                else:check=directories
                                fd,signature=held.enter_context(opened(name,parent=source_parent,links=(1,)))
                                def unchanged():
                                    fresh();activity();check()
                                    value=os.fstat(fd);named=os.stat(name,dir_fd=source_parent,follow_symlinks=False)
                                    def key(item):return (item.st_dev,item.st_ino,item.st_size,item.st_mode,item.st_uid,item.st_gid,item.st_nlink,item.st_mtime_ns,item.st_ctime_ns)
                                    if key(value)!=signature or key(named)!=signature:raise TransferError('media_trash_original_content_changed')
                                    return True
                                unchanged();result=preview_held_file(fd,entry.mapping.saved_size,entry.mapping.association.media_type,mode,unchanged)
                                unchanged();self._require(action,current);return result

    def restore(self,action,expected,operation,native_gate):
        return self._execute(action,expected,operation,native_gate,restore=True)

    def cancel_prepared(self,action,expected,operation,native_gate):
        self._action(action,expected);action.consume(self)
        if not callable(native_gate):raise TransferError('media_trash_native_gate_required')
        with self._operation():
            if not self._open():raise TransferError('media_trash_original_operation_required')
            with self._locked():
                current=self._require(action,expected);entries,_,_=self._entries();entry=entries.get(operation)
                if entry is None or entry.state!='prepared':raise TransferError('media_trash_cancel_not_current')
                def fresh():
                    action.validate(self);self._fresh()
                    if native_gate() is not True:raise TransferError('media_trash_native_gate_revoked')
                self._move(entry,fresh,restore=False,cancel=True)
                fresh();return self._append(action,current,operation,'canceled',entry.mapping)

    def _execute(self,action,expected,operation,native_gate,*,restore):
        self._action(action,expected);action.consume(self)
        if self._recovery_only and not restore:raise TransferError('media_trash_local_recovery_only')
        if not callable(native_gate):raise TransferError('media_trash_native_gate_required')
        with self._operation():
            if not self._open():raise TransferError('media_trash_original_operation_required')
            with self._locked():
                current=self._require(action,expected);entries,_,_=self._entries();entry=entries.get(operation)
                if entry is None:raise TransferError('media_trash_original_operation_required')
                def fresh():
                    action.validate(self);self._fresh()
                    if native_gate() is not True:raise TransferError('media_trash_native_gate_revoked')
                if restore:
                    if entry.state=='purge_prepared':
                        self._restore_purge(entry,fresh)
                        fresh();return self._append(action,current,operation,'restored',entry.mapping)
                    if entry.state=='prepared':
                        # Local/offline recovery may confirm an ALREADY moved
                        # original, never perform a new trash move as "restore".
                        self._move(entry,fresh,restore=False,observe_moved=True)
                        current,entry=self._append(action,current,operation,'trashed',entry.mapping)
                    if entry.state=='trashed':
                        current,entry=self._append(action,current,operation,'restore_prepared',entry.mapping)
                        self._boundary('restore_prepared')
                    if entry.state!='restore_prepared':raise TransferError('media_trash_restore_not_current')
                elif entry.state!='prepared':raise TransferError('media_trash_delete_not_current')
                self._move(entry,fresh,restore=restore)
                fresh()
                result=self._append(action,current,operation,'restored' if restore else 'trashed',entry.mapping)
                self._boundary(result[1].state);return result

    @contextmanager
    def _target_context(self,entry,fresh):
        mapping=entry.mapping;names=mapping.relative_path.split('/');fds=[]
        require_media_directory(os.path.join(mapping.destination.path,*names))
        def directories():
            fresh();mapping.destination.verify()
            for index,fd in enumerate(fds):
                value=os.fstat(fd)
                if (not stat.S_ISDIR(value.st_mode) or (value.st_dev,value.st_ino)!=mapping.parent_keys[index]
                        or value.st_uid!=os.geteuid() or value.st_mode&0o022):
                    raise TransferError('media_trash_original_parent_changed')
                if index:
                    named=os.stat(names[index-1],dir_fd=fds[index-1],follow_symlinks=False)
                    if not stat.S_ISDIR(named.st_mode) or (named.st_dev,named.st_ino)!=mapping.parent_keys[index]:
                        raise TransferError('media_trash_original_parent_changed')
        @contextmanager
        def opened(name,*,parent=None,links=(1,2),empty=False,writable=False):
            directories()
            parent=fds[-1] if parent is None else parent
            fd=os.open(name,(os.O_RDWR if writable else os.O_RDONLY)|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=parent)
            try:
                before=os.fstat(fd)
                if (not stat.S_ISREG(before.st_mode) or (before.st_dev,before.st_ino)!=mapping.file_key
                        or before.st_uid!=os.geteuid() or before.st_mode&0o077 or before.st_nlink not in links
                        or before.st_size!=mapping.saved_size and not (empty and before.st_size==0)):
                    raise TransferError('media_trash_original_file_changed')
                digest=sha256();remaining=before.st_size
                while remaining:
                    directories();part=os.read(fd,min(CHUNK_BYTES,remaining))
                    if not part:raise TransferError('media_trash_original_content_changed')
                    digest.update(part);remaining-=len(part)
                after=os.fstat(fd);named=os.stat(name,dir_fd=parent,follow_symlinks=False)
                def signature(value):
                    return (value.st_dev,value.st_ino,value.st_size,value.st_mode,value.st_uid,value.st_gid,
                        value.st_nlink,value.st_mtime_ns,value.st_ctime_ns)
                if (os.read(fd,1) or digest.hexdigest()!=mapping.saved_sha256 and not (empty and before.st_size==0)
                        or signature(before)!=signature(after) or signature(after)!=signature(named)):
                    raise TransferError('media_trash_original_content_changed')
                directories();yield fd,signature(after)
            finally:os.close(fd)
            directories()
        try:
            fds.append(os.open(mapping.destination.path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC))
            directories()
            for name in names[:-1]:
                fds.append(os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fds[-1]));directories()
            yield fds[-1],names[-1],directories,opened
        finally:
            for fd in reversed(fds):os.close(fd)

    def _move(self,entry,fresh,*,restore,cancel=False,observe_moved=False):
        with self._target_context(entry,fresh) as (parent,original,directories,opened):
            def verify(name):
                with opened(name):pass
            source,target=(entry.payload_name,original) if restore else (original,entry.payload_name)
            source_exists=target_exists=False
            try:os.stat(source,dir_fd=parent,follow_symlinks=False);source_exists=True
            except FileNotFoundError:pass
            try:os.stat(target,dir_fd=parent,follow_symlinks=False);target_exists=True
            except FileNotFoundError:pass
            if cancel:
                if not source_exists or target_exists:raise TransferError('media_trash_cancel_move_uncertain')
                verify(source);return # Only a proven NOT moved original can cancel.
            if not source_exists and target_exists:
                verify(target) # Exact post-move crash recovery, not a new move.
            else:
                if observe_moved:raise TransferError('media_trash_restore_payload_unproven')
                if not source_exists or target_exists:raise TransferError('media_trash_move_conflict')
                verify(source);directories();self._boundary('before_move');directories()
                _move_no_replace(parent,source,target)
                self._boundary('restored_move' if restore else 'moved')
                try:verify(target)
                except BaseException:
                    # Preserve a raced candidate; rollback also cannot replace.
                    # Revocation forbids even rollback: keep bytes held for an
                    # explicit current-owner recovery instead of moving again.
                    try:
                        directories();_move_no_replace(parent,target,source);os.fsync(parent)
                    except (OSError,TransferError):pass
                    raise
            os.fsync(parent);directories()

    @staticmethod
    def _exists(parent,name):
        try:os.stat(name,dir_fd=parent,follow_symlinks=False);return True
        except FileNotFoundError:return False

    @contextmanager
    def _purge_context(self,entry,parent,directories):
        location=entry.purge
        if type(location) is not NativeMediaPurgeLocation:raise TransferError('media_trash_original_purge_required')
        fd=os.open(location.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
        def check():
            directories()
            held=os.fstat(fd);named=os.stat(location.name,dir_fd=parent,follow_symlinks=False)
            self._private(held,directory=True);self._private(named,directory=True)
            if self._key(held)!=location.key or self._key(named)!=location.key:
                raise TransferError('media_trash_original_purge_changed')
            with os.scandir(fd) as items:
                for index,item in enumerate(items):
                    if index or item.name!='payload':raise TransferError('media_trash_unknown_purge_entry')
        try:check();yield fd,check
        finally:os.close(fd)

    def _prepare_purge(self,entry,fresh,permit):
        with self._target_context(entry,fresh) as (parent,_,directories,opened):
            with opened(entry.payload_name,links=(1,)):
                directories();self._boundary('before_purge_prepare');directories()
                name='.magnolie-purge-'+entry.operation
                os.mkdir(name,mode=0o700,dir_fd=parent) # Never adopt a prior unknown directory.
                fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
                try:
                    value=os.fstat(fd);self._private(value,directory=True)
                    named=os.stat(name,dir_fd=parent,follow_symlinks=False)
                    if self._key(value)!=self._key(named):raise TransferError('media_trash_original_purge_changed')
                    value=dict(name=name,key=list(self._key(value)),retention_days=permit.days)
                    if type(permit) is _ManualMediaPurgePermit:value['manual']=True
                    location=NativeMediaPurgeLocation.parse(value,entry.operation,entry.mapping)
                    os.fsync(fd);os.fsync(parent);directories();return location
                finally:os.close(fd)

    def purge_expired(self,action,expected,operation,permit):
        """Configured local retention only; retain the tombstone and a zero-byte
        private completion marker. No pathname unlink can delete a raced file.
        """
        if type(permit) is not NativeMediaRetentionPermit:raise TransferError('media_trash_native_retention_required')
        return self._purge(action,expected,operation,permit)

    def purge_manual(self,action,expected,operation,native_gate):
        """Explicit selected-entry confirmation, including never/undated trash.
        Does not edit settings or confer a remote deletion permission.
        """
        return self._purge(action,expected,operation,_ManualMediaPurgePermit(self,operation,native_gate))

    def _purge_due(self,entry,permit):
        if type(permit) is _ManualMediaPurgePermit:
            if permit.owner is not self or permit.operation!=entry.operation:
                raise TransferError('media_trash_foreign_confirmation')
            permit.require_current();return True
        return entry.expired(permit.days,self._wall_clock_ms())

    def _purge(self,action,expected,operation,permit):
        self._action(action,expected);action.consume(self)
        if type(permit) not in (NativeMediaRetentionPermit,_ManualMediaPurgePermit):
            raise TransferError('media_trash_native_retention_required')
        with self._operation():
            if not self._open():raise TransferError('media_trash_original_operation_required')
            with self._locked():
                current=self._require(action,expected);entries,_,_=self._entries();entry=entries.get(operation)
                if entry is None or entry.state not in ('trashed','purge_prepared'):
                    raise TransferError('media_trash_purge_not_current')
                def fresh():
                    action.validate(self);self._fresh();permit.require_current()
                fresh()
                if entry.state=='trashed':
                    if not self._purge_due(entry,permit):return current,entry
                    location=self._prepare_purge(entry,fresh,permit)
                    fresh();current,entry=self._append(action,current,operation,'purge_prepared',entry.mapping,purge=location)
                    self._boundary('purge_prepared')
                if not self._purge_payload(entry,fresh,permit):return current,entry
                fresh();result=self._append(action,current,operation,'purged',entry.mapping)
                self._boundary('purged');return result

    def _purge_payload(self,entry,fresh,permit):
        with self._target_context(entry,fresh) as (parent,_,directories,opened):
            with self._purge_context(entry,parent,directories) as (capsule,check):
                source=self._exists(parent,entry.payload_name);target=self._exists(capsule,'payload')
                if source and target:raise TransferError('media_trash_purge_move_conflict')
                if not target:
                    if not source:raise TransferError('media_trash_purge_payload_missing')
                    if not self._purge_due(entry,permit):return False
                    with opened(entry.payload_name,links=(1,)):pass
                    check();self._boundary('before_purge_move');check()
                    if not self._purge_due(entry,permit):return False
                    _move_no_replace(parent,entry.payload_name,'payload',target_parent=capsule)
                    self._boundary('purge_moved')
                    try:
                        with opened('payload',parent=capsule,links=(1,)):pass
                        check()
                    except BaseException:
                        try:
                            check();_move_no_replace(capsule,'payload',entry.payload_name,target_parent=parent)
                            os.fsync(capsule);os.fsync(parent)
                        except (OSError,TransferError):pass
                        raise
                due=self._purge_due(entry,permit)
                peek=os.stat('payload',dir_fd=capsule,follow_symlinks=False)
                if not due and (peek.st_size or entry.mapping.saved_size==0):return False
                with opened('payload',parent=capsule,links=(1,),empty=True,writable=due) as (fd,signature):
                    check();value=os.fstat(fd)
                    if value.st_size or entry.mapping.saved_size==0:
                        if not self._purge_due(entry,permit):return False
                        self._boundary('before_purge_bytes');check()
                        if not self._purge_due(entry,permit):return False
                        value=os.fstat(fd)
                        actual=(value.st_dev,value.st_ino,value.st_size,value.st_mode,value.st_uid,value.st_gid,
                            value.st_nlink,value.st_mtime_ns,value.st_ctime_ns)
                        named=os.stat('payload',dir_fd=capsule,follow_symlinks=False)
                        if actual!=signature or self._key(named)!=entry.mapping.file_key:
                            raise TransferError('media_trash_original_content_changed')
                        # The held descriptor targets ONLY the verified original
                        # inode, even if its private pathname is raced/replaced.
                        os.ftruncate(fd,0);os.fsync(fd);self._boundary('purge_bytes_released')
                    value=os.fstat(fd);named=os.stat('payload',dir_fd=capsule,follow_symlinks=False)
                    if value.st_size or self._key(value)!=entry.mapping.file_key or self._key(named)!=entry.mapping.file_key:
                        raise TransferError('media_trash_purge_completion_uncertain')
                    os.fsync(fd);check()
                os.fsync(capsule);os.fsync(parent);check();return True

    def _restore_purge(self,entry,fresh):
        with self._target_context(entry,fresh) as (parent,original,directories,opened):
            with self._purge_context(entry,parent,directories) as (capsule,check):
                archived=self._exists(parent,entry.payload_name);staged=self._exists(capsule,'payload')
                if self._exists(parent,original):
                    if archived or staged:raise TransferError('media_trash_move_conflict')
                    with opened(original):pass # Exact post-restore crash recovery.
                else:
                    if archived==staged:raise TransferError('media_trash_restore_payload_unproven')
                    source_parent,name=(capsule,'payload') if staged else (parent,entry.payload_name)
                    with opened(name,parent=source_parent):pass # Truncated data cannot restore.
                    check();self._boundary('before_move');check()
                    _move_no_replace(source_parent,name,original,target_parent=parent)
                    self._boundary('restored_move')
                    with opened(original):pass
                os.fsync(capsule);os.fsync(parent);check()
