"""Native local media trash and no-replace restore, not a wire/UI delete handler.

An encrypted append-only journal precedes each move. Recoverable original bytes
stay at a random private filename in the ORIGINAL parent, on the same filesystem.
No unlink, automatic purge, guessed absence tombstone or cross-device ACK exists.
"""
from dataclasses import dataclass
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
from magnolie_photo_destination import NativePhotoDestinationAction
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
    def __init__(self,native_directory,scope):
        if not _hex(scope):raise TransferError('media_trash_local_scope_required')
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
        try:self.protection._read_key()
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
class NativeMediaTrashEntry:
    operation: str
    state: str
    mapping: NativeSavedPhotoMapping
    sequence: int

    @property
    def grants_write_authority(self):return False

    @property
    def is_counterpart_ack(self):return False

    @property
    def payload_name(self):return '.magnolie-trash-'+self.operation


def _move_no_replace(parent,source,target):
    if sys.platform!='linux':raise TransferError('media_trash_native_platform_required')
    libc=ctypes.CDLL(None,use_errno=True)
    rename=getattr(libc,'renameat2',None)
    if rename is None:raise TransferError('media_trash_no_replace_required')
    rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    rename.restype=ctypes.c_int
    if rename(parent,os.fsencode(source),parent,os.fsencode(target),1)!=0:
        error=ctypes.get_errno();raise OSError(error,os.strerror(error))


class ProtectedMediaTrash(ProtectedPhotoPreferences):
    MAX_DATABASE_BYTES=64*1024*1024
    MAX_OPERATIONS=128 # No eviction. Four event slots are reserved per operation.
    _SCHEMA={
        'owner':'CREATE TABLE owner (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)',
        'events':'CREATE TABLE events (sequence INTEGER PRIMARY KEY, operation TEXT NOT NULL, payload BLOB NOT NULL)'}
    _NEXT={None:('prepared',),'prepared':('trashed','canceled'),
        'trashed':('restore_prepared',),'restore_prepared':('restored',)}

    def __init__(self,authority,*,boundary=lambda _:None,**kwargs):
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
            if (type(value) is not dict or set(value)!={'operation','state','mapping','mapping_sha256'} or value['operation']!=operation
                    or type(value['state']) is not str or type(value['mapping']) is not dict):
                raise TransferError('media_trash_invalid_event')
            raw=value['mapping'].get('association')
            if type(raw) is not dict or set(raw)!={'source_epoch','photo_id','media_type'}:
                raise TransferError('media_trash_invalid_association')
            association=PhotoMappingAssociation(**raw)
            mapping=NativeSavedPhotoMapping.parse(value['mapping'],association,value['mapping_sha256'])
            previous=entries.get(operation)
            if (value['state'] not in self._NEXT.get(previous.state if previous else None,())
                    or previous is not None and previous.mapping!=mapping):
                raise TransferError('media_trash_event_chain_changed')
            entries[operation]=NativeMediaTrashEntry(operation,value['state'],mapping,sequence)
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

    def _append(self,action,current,operation,state,mapping):
        entries,count,_=self._entries();previous=entries.get(operation)
        if (state not in self._NEXT.get(previous.state if previous else None,()) or previous is not None and previous.mapping!=mapping
                or previous is None and len(entries)>=self.MAX_OPERATIONS or count+2>MAX_REVISION):
            raise TransferError('media_trash_transition_unavailable')
        sequence=count+1
        payload=dict(operation=operation,state=state,mapping=mapping.wire(),mapping_sha256=mapping.protected_record_sha256)
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
                if restore:
                    if entry.state=='trashed':
                        current,entry=self._append(action,current,operation,'restore_prepared',entry.mapping)
                        self._boundary('restore_prepared')
                    if entry.state!='restore_prepared':raise TransferError('media_trash_restore_not_current')
                elif entry.state!='prepared':raise TransferError('media_trash_delete_not_current')
                def fresh():
                    action.validate(self);self._fresh()
                    if native_gate() is not True:raise TransferError('media_trash_native_gate_revoked')
                self._move(entry,fresh,restore=restore)
                fresh()
                result=self._append(action,current,operation,'restored' if restore else 'trashed',entry.mapping)
                self._boundary(result[1].state);return result

    def _move(self,entry,fresh,*,restore,cancel=False):
        mapping=entry.mapping;names=mapping.relative_path.split('/');fds=[]
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
        def verify(name):
            directories()
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=fds[-1])
            try:
                before=os.fstat(fd)
                if (not stat.S_ISREG(before.st_mode) or (before.st_dev,before.st_ino)!=mapping.file_key
                        or before.st_uid!=os.geteuid() or before.st_mode&0o077 or before.st_nlink not in (1,2)
                        or before.st_size!=mapping.saved_size):raise TransferError('media_trash_original_file_changed')
                digest=sha256();remaining=before.st_size
                while remaining:
                    directories();part=os.read(fd,min(CHUNK_BYTES,remaining))
                    if not part:raise TransferError('media_trash_original_content_changed')
                    digest.update(part);remaining-=len(part)
                after=os.fstat(fd);named=os.stat(name,dir_fd=fds[-1],follow_symlinks=False)
                def signature(value):
                    return (value.st_dev,value.st_ino,value.st_size,value.st_mode,value.st_uid,value.st_gid,
                        value.st_nlink,value.st_mtime_ns,value.st_ctime_ns)
                if (os.read(fd,1) or digest.hexdigest()!=mapping.saved_sha256
                        or signature(before)!=signature(after) or signature(after)!=signature(named)):
                    raise TransferError('media_trash_original_content_changed')
            finally:os.close(fd)
            directories()
        try:
            fds.append(os.open(mapping.destination.path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC))
            directories()
            for name in names[:-1]:
                fds.append(os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fds[-1]));directories()
            source,target=(entry.payload_name,names[-1]) if restore else (names[-1],entry.payload_name)
            source_exists=target_exists=False
            try:os.stat(source,dir_fd=fds[-1],follow_symlinks=False);source_exists=True
            except FileNotFoundError:pass
            try:os.stat(target,dir_fd=fds[-1],follow_symlinks=False);target_exists=True
            except FileNotFoundError:pass
            if cancel:
                if not source_exists or target_exists:raise TransferError('media_trash_cancel_move_uncertain')
                verify(source);return # Only a proven NOT moved original can cancel.
            if not source_exists and target_exists:
                verify(target) # Exact post-move crash recovery, not a new move.
            else:
                if not source_exists or target_exists:raise TransferError('media_trash_move_conflict')
                verify(source);directories();self._boundary('before_move');directories()
                _move_no_replace(fds[-1],source,target)
                self._boundary('restored_move' if restore else 'moved')
                try:verify(target)
                except BaseException:
                    # Preserve a raced candidate; rollback also cannot replace.
                    # Revocation forbids even rollback: keep bytes held for an
                    # explicit current-owner recovery instead of moving again.
                    try:
                        directories();_move_no_replace(fds[-1],target,source);os.fsync(fds[-1])
                    except (OSError,TransferError):pass
                    raise
            os.fsync(fds[-1]);directories()
        finally:
            for fd in reversed(fds):os.close(fd)
