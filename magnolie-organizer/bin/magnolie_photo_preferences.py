"""Protected desktop photo policy, separate from peer/default personal grants.

Construction/passive absent reads create nothing. Only an exact native UI action
can create this dedicated store or update consent. No worker/timer is started.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import base64
import fcntl
import os
import secrets
import sqlite3
import stat
import threading
import time

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_control import FileGrantState, NativeLocalFileGrant, MAX_REVISION, _hex
from magnolie_file_native_authority import NativeDesktopFileAuthority
from magnolie_photo_destination import (NativePhotoDestinationAction, NativePhotoDestinationChoice, NativePhotoDestinationController,
    NativeVideoDestinationChoice, NativeVideoDestinationController)
from magnolie_file_transfer import TransferError
from magnolie_telefon import canonical, strict_json

@dataclass(frozen=True)
class VideoPreferences:
    enabled: bool = False
    destination: NativeAcceptedDestination | None = None
    destination_token: str | None = None

    def wire(self):
        return dict(enabled=self.enabled,destination=self.destination.wire() if self.destination is not None else None,
            destination_token=self.destination_token)

    @classmethod
    def parse(cls,value):
        if (type(value) is not dict or set(value)!={'enabled','destination','destination_token'}
                or type(value['enabled']) is not bool):raise TransferError('video_preferences_invalid_record')
        destination=NativeAcceptedDestination.parse(value['destination']) if value['destination'] is not None else None
        if ((destination is None)!=(value['destination_token'] is None)
                or destination is not None and not _hex(value['destination_token'])
                or value['enabled'] and destination is None):raise TransferError('video_preferences_invalid_destination')
        return cls(value['enabled'],destination,value['destination_token'])

@dataclass(frozen=True)
class PhotoPreferences:
    revision: int
    permission_epoch: str
    pairing_epoch: str
    enabled: bool
    mode: str
    phone_to_pc_delete: bool
    pc_to_phone_delete: bool
    destination: NativeAcceptedDestination | None
    destination_token: str | None
    videos: VideoPreferences | None = None
    separate_animations: bool | None = None
    separate_own_recordings: bool | None = None

    def wire(self):
        value=dict(format=1,revision=self.revision,permission_epoch=self.permission_epoch,pairing_epoch=self.pairing_epoch,
            enabled=self.enabled,mode=self.mode,phone_to_pc_delete=self.phone_to_pc_delete,pc_to_phone_delete=self.pc_to_phone_delete,
            destination=self.destination.wire() if self.destination is not None else None,destination_token=self.destination_token)
        if self.videos is not None:value['videos']=self.videos.wire()
        if self.separate_animations is not None:value['separate_animations']=self.separate_animations
        if self.separate_own_recordings is not None:value['separate_own_recordings']=self.separate_own_recordings
        return value # Unchanged legacy policies keep exactly their original shape.

    @classmethod
    def parse(cls,value):
        required={'format','revision','permission_epoch','pairing_epoch','enabled','mode',
                'phone_to_pc_delete','pc_to_phone_delete','destination','destination_token'}
        if (type(value) is not dict or not required<=set(value) or not set(value)<=required|{'videos','separate_animations','separate_own_recordings'}
                or 'separate_animations' in value and type(value['separate_animations']) is not bool
                or 'separate_own_recordings' in value and type(value['separate_own_recordings']) is not bool
                or type(value['format']) is not int or value['format']!=1
                or type(value['revision']) is not int or not 2<=value['revision']<=MAX_REVISION
                or not _hex(value['permission_epoch']) or not _hex(value['pairing_epoch'])
                or any(type(value[key]) is not bool for key in ('enabled','phone_to_pc_delete','pc_to_phone_delete'))
                or value['pc_to_phone_delete']
                or value['mode'] not in ('manual','automatic')):
            raise TransferError('photo_preferences_invalid_record')
        destination=NativeAcceptedDestination.parse(value['destination']) if value['destination'] is not None else None
        if ((destination is None)!=(value['destination_token'] is None) or destination is not None and not _hex(value['destination_token'])
                or value['enabled'] and destination is None):
            raise TransferError('photo_preferences_invalid_destination')
        videos=VideoPreferences.parse(value['videos']) if 'videos' in value else None
        return cls(value['revision'],value['permission_epoch'],value['pairing_epoch'],value['enabled'],value['mode'],
            value['phone_to_pc_delete'],value['pc_to_phone_delete'],destination,value['destination_token'],videos,
            value.get('separate_animations'),value.get('separate_own_recordings'))

@dataclass(frozen=True)
class PhotoPreferencesSnapshot:
    version: str
    policy: PhotoPreferences | None
    associated: bool
    destination_available: bool
    @property
    def mode(self):return self.policy.mode if self.policy is not None else 'manual'
    @property
    def include_videos(self):
        # Requested protected setting only, never native Video READ/readiness.
        return bool(self.associated and self.policy is not None and self.policy.enabled
            and self.policy.videos is not None and self.policy.videos.enabled)
    @property
    def separate_animations(self):
        return bool(self.associated and self.policy is not None and self.policy.enabled
            and self.policy.separate_animations is True)
    @property
    def separate_own_recordings(self):
        return bool(self.associated and self.policy is not None and self.policy.enabled
            and self.policy.separate_own_recordings is True)

class ProtectedPhotoPreferences:
    MAX_DATABASE_BYTES=512*1024
    MAX_RECORD_BYTES=65536
    _SCHEMA={
        'owner':'CREATE TABLE owner (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)',
        'policy':'CREATE TABLE policy (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)'}

    def __init__(self,authority,*,monotonic_ms=lambda:time.monotonic_ns()//1_000_000):
        if type(authority) is not NativeDesktopFileAuthority:raise TransferError('photo_preferences_native_authority_required')
        self._authority=authority;self._clock=monotonic_ms
        binding=authority.binding
        self._subject=dict(local_id=authority.identity.receiver_id,local_identity=authority.identity.receiver_identity_sha256,
                           peer_id=binding.peer_id,peer_identity=sha256(base64.b64decode(binding.static_public,validate=True)).hexdigest())
        self._scope=sha256(canonical(self._subject)).hexdigest()
        self._name='photo-preferences-v1-'+self._scope
        self._domain='magnolie-photo-preferences-v1/'+self._scope+'/'
        self._absent=sha256((self._domain+'absent').encode()).hexdigest()
        self._gate=threading.Lock();self._closed=threading.Event();self._uncertain=False
        self._parent_fd=self._root_fd=self._lock_fd=self._db_fd=None;self._db=None
        self._root_key=self._lock_key=self._db_key=None;self._last=None

    def issue_action(self):
        if self._closed.is_set():raise TransferError('photo_preferences_closed')
        return NativePhotoDestinationAction(self,self._clock)

    def _peer(self):
        if self._closed.is_set() or self._uncertain:raise TransferError('photo_preferences_closed_or_pending')
        peer=self._authority.current_peer()
        if peer is None or self._closed.is_set():raise TransferError('photo_preferences_authority_changed')
        return peer

    @staticmethod
    def _key(value):return value.st_dev,value.st_ino

    @staticmethod
    def _private(value,*,directory=False):
        if (not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)) or value.st_uid!=os.geteuid()
                or value.st_mode&0o077 or not directory and value.st_nlink!=1):
            raise TransferError('photo_preferences_unsafe_native_entry')

    @contextmanager
    def _operation(self):
        if not self._gate.acquire(blocking=False):raise TransferError('photo_preferences_busy')
        try:
            self._peer()
            yield
        finally:
            self._gate.release()
            if self._closed.is_set():self._close_handles()

    def _open(self,*,create=False,validate=lambda:None):
        try:return self._open_impl(create=create,validate=validate)
        except BaseException:
            self._close_open_handles()
            raise

    def _open_impl(self,*,create=False,validate=lambda:None):
        self._peer()
        if self._db is not None:return True
        if self._parent_fd is None:
            self._parent_fd=os.open(self._authority.binding.native_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        if self._key(os.fstat(self._parent_fd))!=self._authority.protection.native_directory_identity:
            raise TransferError('photo_preferences_native_root_changed')
        created=False
        try:self._root_fd=os.open(self._name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self._parent_fd)
        except FileNotFoundError:
            if not create:return False
            validate();self._peer()
            os.mkdir(self._name,mode=0o700,dir_fd=self._parent_fd);created=True
            self._root_fd=os.open(self._name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self._parent_fd)
        self._private(os.fstat(self._root_fd),directory=True);self._root_key=self._key(os.fstat(self._root_fd))
        flags=os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK
        if created:flags|=os.O_CREAT|os.O_EXCL
        self._lock_fd=os.open('prefs.lock',flags,0o600,dir_fd=self._root_fd);self._lock_key=self._key(os.fstat(self._lock_fd))
        self._db_fd=os.open('prefs.sqlite',flags,0o600,dir_fd=self._root_fd);self._db_key=self._key(os.fstat(self._db_fd))
        with self._locked():
            path=Path(self._authority.binding.native_directory)/self._name/'prefs.sqlite'
            self._db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0,check_same_thread=False)
            self._db.execute('PRAGMA busy_timeout=0');self._db.execute('PRAGMA synchronous=FULL')
            if created:
                self._db.execute('PRAGMA journal_mode=DELETE');self._db.execute('PRAGMA max_page_count=128')
                with self._db:
                    for sql in self._SCHEMA.values():self._db.execute(sql)
                    self._db.execute('PRAGMA user_version=1')
                    self._db.execute('INSERT INTO owner VALUES(1,?)',(self._protect(dict(revision=1,policy_sha256=None),'owner'),))
                    self._fresh();validate()
                self._sync()
            self._schema();self._snapshot()
        return True

    def _fresh(self):
        self._peer()
        self._private(os.fstat(self._parent_fd),directory=True)
        if self._key(os.fstat(self._parent_fd))!=self._authority.protection.native_directory_identity:
            raise TransferError('photo_preferences_native_root_changed')
        root=os.stat(self._name,dir_fd=self._parent_fd,follow_symlinks=False);self._private(root,directory=True)
        if self._key(root)!=self._root_key or self._key(os.fstat(self._root_fd))!=self._root_key:
            raise TransferError('photo_preferences_root_changed')
        for name,fd,key in [('prefs.lock',self._lock_fd,self._lock_key),('prefs.sqlite',self._db_fd,self._db_key)]:
            value=os.stat(name,dir_fd=self._root_fd,follow_symlinks=False);self._private(value);self._private(os.fstat(fd))
            if self._key(value)!=key or self._key(os.fstat(fd))!=key:raise TransferError('photo_preferences_entry_changed')
        if os.fstat(self._lock_fd).st_size!=0 or os.fstat(self._db_fd).st_size>self.MAX_DATABASE_BYTES:
            raise TransferError('photo_preferences_native_size')
        with os.scandir(self._root_fd) as entries:
            for index,entry in enumerate(entries):
                allowed=entry.name in ('prefs.lock','prefs.sqlite') or entry.name=='prefs.sqlite-journal' and self._db is not None and self._db.in_transaction
                if index>=3 or not allowed:raise TransferError('photo_preferences_unknown_entry_preserved')
                self._private(entry.stat(follow_symlinks=False))

    @contextmanager
    def _locked(self):
        # Another native owner may currently have a live SQLite journal. Take
        # the nonwaiting gate before inspecting transaction-only entries; a
        # concurrent writer is busy, not evidence of corrupt stored metadata.
        value=os.stat('prefs.lock',dir_fd=self._root_fd,follow_symlinks=False)
        self._private(value);self._private(os.fstat(self._lock_fd))
        if self._key(value)!=self._lock_key or self._key(os.fstat(self._lock_fd))!=self._lock_key:
            raise TransferError('photo_preferences_entry_changed')
        try:fcntl.flock(self._lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise TransferError('photo_preferences_busy') from error
        try:
            self._fresh();yield;self._fresh()
        finally:fcntl.flock(self._lock_fd,fcntl.LOCK_UN)

    def _schema(self):
        found=dict(self._db.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        if found!=self._SCHEMA or self._db.execute('PRAGMA user_version').fetchone()!=(1,) or self._db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:
            raise TransferError('photo_preferences_invalid_schema')

    def _protect(self,payload,label):
        self._fresh()
        value=dict(format=1,subject=self._subject,root_key=list(self._root_key),database_key=list(self._db_key),lock_key=list(self._lock_key),payload=payload)
        raw=canonical(value)
        if len(raw)>self.MAX_RECORD_BYTES:raise TransferError('photo_preferences_record_size')
        blob=self._authority.protection.seal(raw,self._domain+label);self._fresh()
        return blob

    def _unprotect(self,blob,label):
        if type(blob) is not bytes or not 28<=len(blob)<=self.MAX_RECORD_BYTES+28:raise TransferError('photo_preferences_record_size')
        plain=self._authority.protection.unseal(blob,self._domain+label);value=strict_json(plain)
        if (type(value) is not dict or set(value)!={'format','subject','root_key','database_key','lock_key','payload'}
                or type(value['format']) is not int or value['format']!=1 or value['subject']!=self._subject
                or value['root_key']!=list(self._root_key) or value['database_key']!=list(self._db_key) or value['lock_key']!=list(self._lock_key)
                or canonical(value)!=plain):raise TransferError('photo_preferences_native_identity_changed')
        self._fresh();return value['payload']

    def _snapshot(self):
        owners=self._db.execute('SELECT id,payload FROM owner').fetchall();policies=self._db.execute('SELECT id,payload FROM policy').fetchall()
        if len(owners)!=1 or owners[0][0]!=1 or len(policies)>1 or policies and policies[0][0]!=1:raise TransferError('photo_preferences_invalid_rows')
        head=self._unprotect(owners[0][1],'owner')
        if (type(head) is not dict or set(head)!={'revision','policy_sha256'} or type(head['revision']) is not int
                or not 1<=head['revision']<=MAX_REVISION):raise TransferError('photo_preferences_invalid_head')
        policy=None;version=self._absent
        if not policies:
            if head!=dict(revision=1,policy_sha256=None):raise TransferError('photo_preferences_missing_policy_preserved')
        else:
            version=sha256(policies[0][1]).hexdigest();policy=PhotoPreferences.parse(self._unprotect(policies[0][1],'policy'))
            if head['policy_sha256']!=version or head['revision']!=policy.revision:raise TransferError('photo_preferences_head_changed')
        mark=head['revision'],version
        if self._last is not None and (mark[0]<self._last[0] or mark[0]==self._last[0] and mark[1]!=self._last[1]):
            self._uncertain=True;raise TransferError('photo_preferences_revision_rollback')
        self._last=mark
        peer=self._peer();available=False
        if policy is not None and policy.destination is not None:
            try:
                policy.destination.verify();available=os.access(policy.destination.path,os.W_OK|os.X_OK,effective_ids=True)
            except (OSError,TransferError):available=False
        return PhotoPreferencesSnapshot(version,policy,policy is not None and policy.pairing_epoch==peer.pairing_epoch,available)

    def _sync(self):
        os.fsync(self._db_fd);os.fsync(self._root_fd);os.fsync(self._parent_fd);self._fresh()

    def read(self):
        try:
            with self._operation():
                if not self._open():return PhotoPreferencesSnapshot(self._absent,None,False,False)
                with self._locked():
                    self._schema();snapshot=self._snapshot();self._sync();return snapshot
        except Exception as error:
            transient=isinstance(error,TransferError) and str(error) in ('photo_preferences_busy','photo_preferences_closed_or_pending','photo_preferences_authority_changed')
            if not transient:self._uncertain=True
            raise

    def configure(self,action,expected,*,enabled,mode,phone_to_pc_delete=False,pc_to_phone_delete=False,destination_choice=None,
            include_videos=None,video_destination_choice=None,separate_animations=None,separate_own_recordings=None):
        if type(action) is not NativePhotoDestinationAction:raise TransferError('photo_preferences_native_action_required')
        action.consume(self)
        if (type(expected) is not PhotoPreferencesSnapshot or any(type(value) is not bool for value in (enabled,phone_to_pc_delete,pc_to_phone_delete))
                or mode not in ('manual','automatic')):raise TransferError('photo_preferences_invalid_settings')
        if pc_to_phone_delete:raise TransferError('photo_preferences_reverse_delete_unavailable')
        if include_videos is not None and type(include_videos) is not bool:raise TransferError('video_preferences_invalid_settings')
        if separate_animations is not None and type(separate_animations) is not bool:raise TransferError('animation_preferences_invalid_settings')
        if separate_own_recordings is not None and type(separate_own_recordings) is not bool:raise TransferError('capture_preferences_invalid_settings')
        if enabled and destination_choice is None and (expected.policy is None or expected.policy.destination is None):
            raise TransferError('photo_preferences_destination_required')
        with self._operation():
            self._open(create=True,validate=lambda:action.validate(self))
            with self._locked():
                self._schema()
                current=self._snapshot()
                if expected.version!=current.version:raise TransferError('photo_preferences_cas_conflict')
                destination=current.policy.destination if current.policy is not None else None
                token=current.policy.destination_token if current.policy is not None else None
                if destination_choice is not None:
                    if (type(destination_choice) is not NativePhotoDestinationChoice or type(destination_choice.owner) is not NativePhotoDestinationController
                            or destination_choice.owner._authority is not self._authority):raise TransferError('photo_preferences_foreign_destination_choice')
                    destination=destination_choice.owner.verify_choice(destination_choice);token=destination_choice.destination_token
                if enabled and destination is not None:destination.verify()
                if enabled and destination is None:raise TransferError('photo_preferences_destination_required')
                videos=current.policy.videos if current.policy is not None else None
                animations=current.policy.separate_animations if current.policy is not None else None
                recordings=current.policy.separate_own_recordings if current.policy is not None else None
                if animations is not None and not current.associated:animations=False
                if recordings is not None and not current.associated:recordings=False
                if separate_animations is not None:animations=separate_animations
                if separate_own_recordings is not None:recordings=separate_own_recordings
                if videos is not None and not current.associated:
                    # Re-pairing preserves destination metadata, never silently
                    # re-enables the separately selected video scope.
                    videos=VideoPreferences(False,videos.destination,videos.destination_token)
                if include_videos is not None or video_destination_choice is not None:
                    old=videos or VideoPreferences()
                    video_destination,video_token=old.destination,old.destination_token
                    if video_destination_choice is not None:
                        if (type(video_destination_choice) is not NativeVideoDestinationChoice
                                or type(video_destination_choice.owner) is not NativeVideoDestinationController
                                or video_destination_choice.owner._authority is not self._authority):
                            raise TransferError('video_preferences_foreign_destination_choice')
                        video_destination=video_destination_choice.owner.verify_choice(video_destination_choice)
                        video_token=video_destination_choice.destination_token
                    video_enabled=old.enabled if include_videos is None else include_videos
                    if video_enabled:
                        if video_destination is None:raise TransferError('video_preferences_destination_required')
                        video_destination.verify()
                    videos=VideoPreferences.parse(VideoPreferences(video_enabled,video_destination,video_token).wire())
                revision=(current.policy.revision if current.policy is not None else 1)+1
                if revision>MAX_REVISION:raise TransferError('photo_preferences_revision_limit')
                policy=PhotoPreferences(revision,secrets.token_hex(32),self._peer().pairing_epoch,enabled,mode,phone_to_pc_delete,False,
                    destination,token,videos,animations,recordings)
                blob=self._protect(policy.wire(),'policy');head=self._protect(dict(revision=revision,policy_sha256=sha256(blob).hexdigest()),'owner')
                action.validate(self);self._peer();mutated=False
                try:
                    self._db.execute('BEGIN IMMEDIATE')
                    self._db.execute('INSERT OR REPLACE INTO policy VALUES(1,?)',(blob,));mutated=True
                    self._db.execute('UPDATE owner SET payload=? WHERE id=1',(head,))
                    self._fresh();action.validate(self);self._db.commit();self._sync()
                    result=self._snapshot()
                    action.validate(self)
                    if result.policy!=policy or result.version!=sha256(blob).hexdigest():raise TransferError('photo_preferences_readback_failed')
                    return result
                except BaseException:
                    if self._db.in_transaction:self._db.rollback()
                    if mutated:self._uncertain=True
                    raise

    def local_grant(self,handlers_ready):
        if type(handlers_ready) is not bool:raise TransferError('photo_preferences_native_handlers_required')
        snapshot=self.read();peer=self._peer();policy=snapshot.policy
        enabled=handlers_ready and policy is not None and policy.enabled and snapshot.associated and snapshot.destination_available
        revision=policy.revision if policy is not None else 1
        epoch=policy.permission_epoch if snapshot.associated and policy is not None else sha256(canonical(dict(scope=self._scope,pairing=peer.pairing_epoch,closed=snapshot.version))).hexdigest()
        return NativeLocalFileGrant(FileGrantState(revision,epoch,False,enabled),self,handlers_ready)

    def _close_handles(self):
        if not self._gate.acquire(blocking=False):return False
        try:
            self._close_open_handles()
            return True
        finally:self._gate.release()

    def _close_open_handles(self):
        if self._db is not None:self._db.close();self._db=None
        for name in ('_db_fd','_lock_fd','_root_fd','_parent_fd'):
            fd=getattr(self,name)
            if fd is not None:os.close(fd);setattr(self,name,None)

    def close(self):
        self._closed.set();return self._close_handles() # Active I/O retains handles until its finally.
