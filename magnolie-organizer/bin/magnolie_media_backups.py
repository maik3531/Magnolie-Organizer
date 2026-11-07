"""Native, content-addressed LOCAL media backup catalog (#392).

Immutable version references share verified private content objects, never
hardlinks to editable originals. This is not a remote deletion handler. Catalog
restore prepares a new file; a separate local owner journals its no-replace
publication and original lineage without manufacturing a remote Saved receipt.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
import copy
import fcntl
import os
import secrets
import sqlite3
import stat
import threading
import time

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_control import _hex
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError
from magnolie_media_backup_codec import (VerifiedBackupRepresentation, NativeBackupIdlePermit,
    compression_due, content_key, copy_unique, verify_raw, verify_xz, compress_candidate, restore_to_new_file)
from magnolie_media_trash import NativeMediaRetentionPermit
from magnolie_media_trash import _move_no_replace as _rename_no_replace
from magnolie_photo_mappings import ProtectedPhotoMappings, NativeSavedPhotoMapping, PhotoMappingAssociation
from magnolie_photo_destination import require_media_directory
from magnolie_photo_preferences import ProtectedPhotoPreferences,PhotoPreferences
from magnolie_photo_destination import NativePhotoDestinationAction
from magnolie_telefon import canonical, strict_json


@dataclass(frozen=True)
class NativeBackupLocationsSnapshot:
    version: str
    revision: int
    selected: NativeAcceptedDestination | None
    parents: tuple

    def current(self,default):
        if type(default) is not NativeAcceptedDestination:raise TransferError('media_backup_default_required')
        return default if self.selected is None else self.selected


class _ProtectedBackupLocations(ProtectedPhotoPreferences):
    """Descriptor/AEAD storage only; no transport peer or media grant authority."""
    MAX_RECORD_BYTES=256*1024
    MAX_DATABASE_BYTES=2*1024*1024
    MAX_PARENTS=64

    def __init__(self,directory,scope,guard,clock):
        self.local_protection=ExistingFileTransferProtection(directory)
        self.directory=directory;self.local_guard=guard
        self._initialize_store(None,dict(local_backup_scope=scope),clock)
        self._name='media-backup-locations-v1-'+self._scope
        self._domain='magnolie-media-backup-locations-v1/'+self._scope+'/'
        self._absent=sha256((self._domain+'absent').encode()).hexdigest()
        self._anchor=self._name+'.seal';self._anchor_identity=None

    def _native_directory(self):return self.directory
    def _protection(self):return self.local_protection

    def _close_handles(self):
        closed=super()._close_handles()
        if closed:self.local_protection.close()
        return closed

    def _peer(self):
        if self._closed.is_set() or self._uncertain or self.local_guard() is not True:
            raise TransferError('media_backup_local_owner_changed')
        self.local_protection._read_key()

    def _initial_owner(self):return dict(revision=1,locations_sha256=None)

    def _anchor_value(self):
        return dict(format=1,subject=self._subject,root_key=list(self._root_key),
            database_key=list(self._db_key),lock_key=list(self._lock_key))

    def _check_anchor(self):
        fd=os.open(self._anchor,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=self._parent_fd)
        try:
            before=os.fstat(fd);self._private(before)
            if not 28<=before.st_size<=8192:raise TransferError('media_backup_locations_anchor_changed')
            blob=os.read(fd,8193);after=os.fstat(fd);named=os.stat(self._anchor,dir_fd=self._parent_fd,follow_symlinks=False)
            self._private(named)
            signature=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
            if len(blob)!=before.st_size or signature(before)!=signature(after) or signature(before)!=signature(named):
                raise TransferError('media_backup_locations_anchor_changed')
            value=self.local_protection.unseal(blob,self._domain+'anchor')
            if value!=canonical(self._anchor_value()):raise TransferError('media_backup_locations_anchor_changed')
            identity=self._key(before),sha256(blob).hexdigest()
            if self._anchor_identity is not None and self._anchor_identity!=identity:
                raise TransferError('media_backup_locations_anchor_changed')
            self._anchor_identity=identity
        finally:os.close(fd)

    def _fresh(self):
        super()._fresh()
        if self._anchor_identity is not None:self._check_anchor()

    def _open(self,*,create=False,validate=lambda:None):
        self._peer()
        parent=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            if self._key(os.fstat(parent))!=self.local_protection.native_directory_identity:
                raise TransferError('media_backup_local_root_changed')
            def exists(name):
                try:os.stat(name,dir_fd=parent,follow_symlinks=False);return True
                except FileNotFoundError:return False
            present,anchored=exists(self._name),exists(self._anchor)
            if present!=anchored or not present and self._anchor_identity is not None:
                raise TransferError('media_backup_locations_original_required')
            if not present and not create:return False
            result=super()._open(create=create,validate=validate)
            if not present:
                validate();self._fresh()
                blob=self.local_protection.seal(canonical(self._anchor_value()),self._domain+'anchor')
                fd=os.open(self._anchor,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(blob);stream.flush();os.fsync(stream.fileno())
                os.fsync(parent)
            self._check_anchor();self._fresh();return result
        finally:os.close(parent)

    def _snapshot(self):
        owners=self._db.execute('SELECT id,payload FROM owner').fetchall()
        rows=self._db.execute('SELECT id,payload FROM policy').fetchall()
        if len(owners)!=1 or owners[0][0]!=1 or len(rows)>1 or rows and rows[0][0]!=1:
            raise TransferError('media_backup_locations_invalid_rows')
        head=self._unprotect(owners[0][1],'owner')
        if not rows:
            if head!=self._initial_owner():raise TransferError('media_backup_locations_missing_record')
            result=NativeBackupLocationsSnapshot(self._absent,1,None,())
        else:
            version=sha256(rows[0][1]).hexdigest();value=self._unprotect(rows[0][1],'locations')
            if (type(value) is not dict or set(value)!={'revision','selected','parents'}
                    or type(value['revision']) is not int or not 2<=value['revision']<2**53
                    or type(value['parents']) is not list or not 1<=len(value['parents'])<=self.MAX_PARENTS
                    or head!=dict(revision=value['revision'],locations_sha256=version)):
                raise TransferError('media_backup_locations_invalid_record')
            parents=tuple(NativeAcceptedDestination.parse(p) for p in value['parents'])
            if len(set(parents))!=len(parents):raise TransferError('media_backup_locations_duplicate_parent')
            for parent in parents:require_media_directory(parent.path)
            selected=None if value['selected'] is None else NativeAcceptedDestination.parse(value['selected'])
            if selected is not None and selected not in parents:raise TransferError('media_backup_locations_unknown_parent')
            result=NativeBackupLocationsSnapshot(version,value['revision'],selected,parents)
        mark=result.revision,result.version
        if self._last is not None and (mark[0]<self._last[0] or mark[0]==self._last[0] and mark[1]!=self._last[1]):
            self._uncertain=True;raise TransferError('media_backup_locations_rollback')
        self._last=mark;return result

    def read_locations(self):
        with self._operation():
            if not self._open():return NativeBackupLocationsSnapshot(self._absent,1,None,())
            with self._locked():self._schema();return self._snapshot()

    def choose(self,action,expected,default,parent):
        if type(action) is not NativePhotoDestinationAction:raise TransferError('media_backup_native_action_required')
        action.consume(self)
        if (type(expected) is not NativeBackupLocationsSnapshot or type(default) is not NativeAcceptedDestination
                or parent is not None and type(parent) is not NativeAcceptedDestination):
            raise TransferError('media_backup_native_parent_required')
        def validate():
            action.validate(self);self._peer()
            require_media_directory(default.path)
            if parent is not None:require_media_directory(parent.path)
            selected=default if parent is None else parent
            selected.verify()
            # Existing foreign Backup trees must never become writable storage.
            if os.path.lexists(os.path.join(selected.path,'Backup')):
                with NativeMediaBackups(default,self.local_protection,lambda:self.local_guard() is True,storage_parent=selected):pass
        with self._operation():
            self._open(create=True,validate=validate)
            with self._locked():
                self._schema();current=self._snapshot()
                if current.version!=expected.version:raise TransferError('media_backup_locations_cas_conflict')
                parents=list(current.parents)
                for retained in (default,parent):
                    if retained is not None and retained not in parents:parents.append(retained)
                if len(parents)>self.MAX_PARENTS:raise TransferError('media_backup_locations_parent_limit')
                validate()
                if current.selected==parent and current.parents==tuple(parents):return current
                revision=current.revision+1
                if revision>=2**53:raise TransferError('media_backup_locations_revision_limit')
                value=dict(revision=revision,selected=None if parent is None else parent.wire(),parents=[p.wire() for p in parents])
                blob=self._protect(value,'locations');version=sha256(blob).hexdigest()
                head=self._protect(dict(revision=revision,locations_sha256=version),'owner')
                try:
                    self._db.execute('BEGIN IMMEDIATE')
                    self._db.execute('INSERT OR REPLACE INTO policy VALUES(1,?)',(blob,))
                    self._db.execute('UPDATE owner SET payload=? WHERE id=1',(head,))
                    self._fresh();validate();self._db.commit();self._sync()
                    result=self._snapshot();action.validate(self);return result
                except BaseException:
                    if self._db.in_transaction:self._db.rollback()
                    self._uncertain=True;raise


class NativeMediaBackupLocations:
    """Local-only settings owner. Scope is supplied by native peer/domain metadata.

    No PhoneStore creation, current channel, pairing impersonation or source grant
    is involved. Passive reads neither create settings nor touch retained drives.
    """
    def __init__(self,directory,scope,local_guard,*,monotonic_ms=lambda:time.monotonic_ns()//1_000_000):
        if not _hex(scope) or not callable(local_guard) or not callable(monotonic_ms) or local_guard() is not True:
            raise TransferError('media_backup_local_owner_required')
        self._store=_ProtectedBackupLocations(directory,scope,local_guard,monotonic_ms)

    def read(self):return self._store.read_locations()

    @classmethod
    def open_existing_scope(cls,directory,internal_scope,local_guard):
        """Resolve an authenticated local anchor, not a peer or transport scope."""
        if not _hex(internal_scope) or not callable(local_guard) or local_guard() is not True:
            raise TransferError('media_backup_local_owner_required')
        with ExistingFileTransferProtection(directory) as protection:
            name='media-backup-locations-v1-'+internal_scope+'.seal'
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=protection._root_fd)
            try:
                before=os.fstat(fd);ProtectedPhotoPreferences._private(before)
                if not 28<=before.st_size<=8192:raise TransferError('media_backup_locations_anchor_changed')
                blob=os.read(fd,8193);after=os.fstat(fd);named=os.stat(name,dir_fd=protection._root_fd,follow_symlinks=False)
                if (len(blob)!=before.st_size or protection._signature(before)!=protection._signature(after)
                        or protection._signature(before)!=protection._signature(named)):
                    raise TransferError('media_backup_locations_anchor_changed')
                plain=protection.unseal(blob,'magnolie-media-backup-locations-v1/'+internal_scope+'/anchor');value=strict_json(plain)
                subject=value.get('subject') if type(value) is dict else None
                if (type(subject) is not dict or set(subject)!={'local_backup_scope'} or not _hex(subject['local_backup_scope'])
                        or sha256(canonical(subject)).hexdigest()!=internal_scope or canonical(value)!=plain):
                    raise TransferError('media_backup_locations_anchor_changed')
                local_guard_result=local_guard()
                if local_guard_result is not True:raise TransferError('media_backup_local_owner_changed')
            finally:os.close(fd)
        owner=cls(directory,subject['local_backup_scope'],local_guard)
        try:
            owner.read()
            if owner._store._scope!=internal_scope or owner._store._anchor_identity is None:
                raise TransferError('media_backup_locations_original_required')
            return owner
        except BaseException:owner.close();raise
    def issue_action(self):return self._store.issue_action()
    def choose(self,action,expected,default,parent):return self._store.choose(action,expected,default,parent)

    @staticmethod
    def source_id(parent):
        if type(parent) is not NativeAcceptedDestination:raise TransferError('media_backup_native_parent_required')
        return sha256(canonical(parent.wire())).hexdigest()

    def sources(self,default):
        if type(default) is not NativeAcceptedDestination:raise TransferError('media_backup_default_required')
        snapshot=self.read();parents=snapshot.parents
        if default not in parents:parents=(default,*parents)
        return tuple((self.source_id(parent),parent) for parent in parents)

    @contextmanager
    def _history(self,default,source_id):
        if not _hex(source_id):raise TransferError('media_backup_source_required')
        parent=next((parent for key,parent in self.sources(default) if key==source_id),None)
        if parent is None:raise TransferError('media_backup_source_not_retained')
        def current():
            self._store._peer()
            if (source_id,parent) not in self.sources(default):raise TransferError('media_backup_source_not_retained')
            return True
        # Never follow the active future-storage choice or fall back from an
        # unavailable historical source. Recovery needs no source channel/grant.
        # The catalog owns its own key descriptor until its IO has drained;
        # closing the settings facade invalidates current(), not that descriptor.
        with ExistingFileTransferProtection(self._store.directory) as protection:
            current()
            with NativeMediaBackups(default,protection,current,storage_parent=parent) as backups:
                yield backups

    def versions(self,default,source_id):
        with self._history(default,source_id) as backups:return backups.recovery_versions()

    def restore(self,default,source_id,version,candidate_fd):
        """Prepare a new owned file only; publication/phone mapping is separate."""
        with self._history(default,source_id) as backups:return backups.restore(version,candidate_fd)

    def close(self):return self._store.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class NativeMediaBackupRecoveryUi:
    """Bounded local source discovery; no PhoneStore or online peer admission."""
    MAX_SCOPES=128
    MAX_PARENT_ENTRIES=4096
    PAGE_SIZE=128

    def __init__(self,directory,local_guard,*,clock=time.monotonic):
        if not callable(local_guard) or not callable(clock):raise TransferError('media_backup_local_owner_required')
        self.directory=directory;self.guard=local_guard;self.clock=clock;self.deadline=clock()+60

    def _current(self):
        if self.clock()>=self.deadline or self.guard() is not True:raise TransferError('media_backup_local_owner_changed')
        return True

    def _legacy_policy(self,scope):
        """Authenticate existing policy metadata without inventing a live peer.

        This is a read-only legacy-location witness, never a preference store,
        grant, association decision or permission to save/receive media.
        """
        self._current()
        name='photo-preferences-v1-'+scope;fds=[];db=None
        with ExistingFileTransferProtection(self.directory) as protection:
            try:
                root=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=protection._root_fd);fds.append(root)
                lock=os.open('prefs.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=root);fds.append(lock)
                data=os.open('prefs.sqlite',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=root);fds.append(data)
                for index,fd in enumerate(fds):ProtectedPhotoPreferences._private(os.fstat(fd),directory=index==0)
                keys=[list(protection._key(os.fstat(fd))) for fd in fds]
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError as error:raise TransferError('media_backup_legacy_policy_busy') from error
                def current():
                    self._current();protection._read_key()
                    for index,(fd,parent,leaf) in enumerate(((root,protection._root_fd,name),(lock,root,'prefs.lock'),(data,root,'prefs.sqlite'))):
                        held=os.fstat(fd);named=os.stat(leaf,dir_fd=parent,follow_symlinks=False)
                        ProtectedPhotoPreferences._private(named,directory=index==0)
                        if list(protection._key(held))!=keys[index] or list(protection._key(named))!=keys[index]:
                            raise TransferError('media_backup_legacy_policy_changed')
                    if os.fstat(lock).st_size or os.fstat(data).st_size>ProtectedPhotoPreferences.MAX_DATABASE_BYTES:
                        raise TransferError('media_backup_legacy_policy_size')
                    with os.scandir(root) as entries:
                        for index,entry in enumerate(entries):
                            if index>=2 or entry.name not in ('prefs.lock','prefs.sqlite'):
                                raise TransferError('media_backup_legacy_policy_pending')
                current()
                db=sqlite3.connect('file:/proc/self/fd/'+str(root)+'/prefs.sqlite?mode=ro',uri=True,timeout=0)
                if (dict(db.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))!=ProtectedPhotoPreferences._SCHEMA
                        or db.execute('PRAGMA user_version').fetchone()!=(1,) or db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]):
                    raise TransferError('media_backup_legacy_policy_schema')
                owners=db.execute('SELECT id,payload FROM owner').fetchall();policies=db.execute('SELECT id,payload FROM policy').fetchall()
                if len(owners)!=1 or owners[0][0]!=1 or len(policies)>1 or policies and policies[0][0]!=1:
                    raise TransferError('media_backup_legacy_policy_rows')
                subject=None
                def opened(blob,label):
                    nonlocal subject
                    if type(blob) is not bytes or not 28<=len(blob)<=ProtectedPhotoPreferences.MAX_RECORD_BYTES+28:
                        raise TransferError('media_backup_legacy_policy_size')
                    plain=protection.unseal(blob,'magnolie-photo-preferences-v1/'+scope+'/'+label);value=strict_json(plain)
                    if (type(value) is not dict or set(value)!={'format','subject','root_key','database_key','lock_key','payload'}
                            or type(value['format']) is not int or value['format']!=1 or canonical(value)!=plain
                            or type(value['subject']) is not dict or sha256(canonical(value['subject'])).hexdigest()!=scope
                            or value['root_key']!=keys[0] or value['database_key']!=keys[2] or value['lock_key']!=keys[1]
                            or subject is not None and value['subject']!=subject):raise TransferError('media_backup_legacy_policy_changed')
                    subject=value['subject'];return value['payload']
                head=opened(owners[0][1],'owner');policy=None
                if (type(head) is not dict or set(head)!={'revision','policy_sha256'} or type(head['revision']) is not int):
                    raise TransferError('media_backup_legacy_policy_changed')
                if not policies:
                    if head!=dict(revision=1,policy_sha256=None):raise TransferError('media_backup_legacy_policy_missing')
                else:
                    policy=PhotoPreferences.parse(opened(policies[0][1],'policy'))
                    if head!=dict(revision=policy.revision,policy_sha256=sha256(policies[0][1]).hexdigest()):
                        raise TransferError('media_backup_legacy_policy_changed')
                current();return subject,policy
            finally:
                if db is not None:db.close()
                for fd in reversed(fds):os.close(fd)

    def _legacy_sources(self):
        import re
        with ExistingFileTransferProtection(self.directory) as protection:
            scopes=[]
            with os.scandir(protection._root_fd) as entries:
                for index,entry in enumerate(entries):
                    self._current()
                    if index>=self.MAX_PARENT_ENTRIES:raise TransferError('media_backup_recovery_scan_bound')
                    match=re.fullmatch(r'photo-preferences-v1-([0-9a-f]{64})',entry.name)
                    if match:scopes.append(match[1])
                    if len(scopes)>self.MAX_SCOPES:raise TransferError('media_backup_recovery_scope_bound')
        for scope in sorted(scopes):
            subject,policy=self._legacy_policy(scope)
            if policy is None:continue
            for media_type,parent in (('images',policy.destination),('video',policy.videos.destination if policy.videos else None)):
                if parent is None:continue
                outer=sha256(canonical(dict(subject=subject,media_type=media_type))).hexdigest()
                internal=sha256(canonical(dict(local_backup_scope=outer))).hexdigest()
                yield internal,outer,parent

    def sources(self):
        import re
        self._current()
        try:protection=ExistingFileTransferProtection(self.directory)
        except FileNotFoundError:
            if os.path.lexists(self.directory):raise
            self._current();return ()
        with protection:
            roots=set();anchors=set()
            with os.scandir(protection._root_fd) as entries:
                for index,entry in enumerate(entries):
                    self._current()
                    if index>=self.MAX_PARENT_ENTRIES:raise TransferError('media_backup_recovery_scan_bound')
                    match=re.fullmatch(r'media-backup-locations-v1-([0-9a-f]{64})(\.seal)?',entry.name)
                    if match:(anchors if match[2] else roots).add(match[1])
                    if len(roots|anchors)>self.MAX_SCOPES:raise TransferError('media_backup_recovery_scope_bound')
            if roots!=anchors:raise TransferError('media_backup_locations_original_required')
        result=[]
        for scope in sorted(roots):
            with NativeMediaBackupLocations.open_existing_scope(self.directory,scope,self._current) as locations:
                snapshot=locations.read()
                if not snapshot.parents:continue
                default=snapshot.parents[0]
                for source_id,parent in locations.sources(default):
                    result.append(dict(scope=scope,source_id=source_id,path=os.path.join(parent.path,'Backup'),
                        selected=parent==snapshot.current(default)))
        known={(row['scope'],row['source_id']) for row in result}
        for internal,_,parent in self._legacy_sources():
            source_id=NativeMediaBackupLocations.source_id(parent)
            if (internal,source_id) not in known:
                result.append(dict(scope=internal,source_id=source_id,path=os.path.join(parent.path,'Backup'),selected=internal not in roots))
                known.add((internal,source_id))
        self._current();return tuple(result)

    @contextmanager
    def _source(self,scope,source_id):
        self._current()
        if not _hex(scope) or not _hex(source_id):raise TransferError('media_backup_source_required')
        anchor=os.path.join(self.directory,'media-backup-locations-v1-'+scope+'.seal')
        root=os.path.join(self.directory,'media-backup-locations-v1-'+scope)
        if os.path.lexists(anchor) or os.path.lexists(root):
            owner=NativeMediaBackupLocations.open_existing_scope(self.directory,scope,self._current);default=None
        else:
            legacy=next(((outer,parent) for internal,outer,parent in self._legacy_sources() if internal==scope),None)
            if legacy is None:raise TransferError('media_backup_source_not_retained')
            outer,default=legacy;owner=NativeMediaBackupLocations(self.directory,outer,self._current)
        with owner as locations:
            snapshot=locations.read()
            if snapshot.parents:default=snapshot.parents[0]
            if default is None or not any(key==source_id for key,_ in locations.sources(default)):
                # An authenticated but empty location bootstrap must not hide
                # an older default catalog after a failed native choice/CAS.
                legacy=next((parent for internal,_,parent in self._legacy_sources()
                    if internal==scope and NativeMediaBackupLocations.source_id(parent)==source_id),None)
                if legacy is None:raise TransferError('media_backup_source_not_retained')
                default=legacy
            if not any(key==source_id for key,_ in locations.sources(default)):raise TransferError('media_backup_source_not_retained')
            yield locations,default

    def versions(self,scope,source_id,cursor=0):
        if type(cursor) is not int or not 0<=cursor<=NativeMediaBackups.MAX_VERSIONS:raise TransferError('media_backup_recovery_cursor_invalid')
        with self._source(scope,source_id) as (locations,default):
            rows=sorted(locations.versions(default,source_id),key=lambda row:(-row.saved_ms,row.id))
            if cursor>len(rows):raise TransferError('media_backup_recovery_page_changed')
            end=cursor+self.PAGE_SIZE
            return dict(entries=[dict(id=row.id,name=row.name,saved_ms=row.saved_ms,record_sha256=row.record_sha256)
                for row in rows[cursor:end]],next_cursor=end if end<len(rows) else None,total=len(rows))

    @staticmethod
    def validate_request(request):
        import re
        if (type(request) is not dict or request.get('cmd')!='medien_backup'
                or type(request.get('request_id')) is not str or re.fullmatch(r'[A-Za-z0-9_-]{8,80}',request['request_id']) is None):
            raise TransferError('media_backup_recovery_request_invalid')
        action=request.get('action');fields={'cmd','request_id','action'}
        if action=='sources':
            if not fields<=set(request)<=fields|{'cursor'}:raise TransferError('media_backup_recovery_request_invalid')
        elif action in ('versions','restore'):
            wanted=fields|{'scope','source_id'}|({'reference','reference_sha256'} if action=='restore' else set())
            if (not wanted<=set(request)<=wanted|({'cursor'} if action=='versions' else set())
                    or any(not _hex(request[key]) for key in wanted-fields)):
                raise TransferError('media_backup_recovery_request_invalid')
        else:raise TransferError('media_backup_recovery_request_invalid')
        cursor=request.get('cursor',0)
        if type(cursor) is not int or not 0<=cursor<=NativeMediaBackupRecoveryUi.MAX_SCOPES*(_ProtectedBackupLocations.MAX_PARENTS+2):
            raise TransferError('media_backup_recovery_cursor_invalid')
        return action

    def read_request(self,request):
        action=self.validate_request(request)
        if action=='sources':
            rows=self.sources();cursor=request.get('cursor',0)
            if cursor>len(rows):raise TransferError('media_backup_recovery_page_changed')
            end=cursor+self.PAGE_SIZE
            page=dict(entries=list(rows[cursor:end]),next_cursor=end if end<len(rows) else None,total=len(rows))
        elif action=='versions':page=self.versions(request['scope'],request['source_id'],request.get('cursor',0))
        else:raise TransferError('media_backup_native_confirmation_required')
        return dict(page,ok=True,supported=True,request_id=request['request_id'],action=action)

    def selection(self,scope,source_id,reference,reference_sha256):
        if not _hex(reference) or not _hex(reference_sha256):raise TransferError('media_backup_native_selection_required')
        with self._source(scope,source_id) as (locations,default):
            with locations._history(default,source_id) as backups:
                selected=next((row for row in backups.recovery_versions() if row.id==reference and row.record_sha256==reference_sha256),None)
                if selected is None:raise TransferError('media_backup_stale_selection')
                # This is original historical association, not the selected
                # source version's current bytes or a Saved receipt.
                return selected,backups._restore_lineage(selected)[0]

    def restore(self,scope,source_id,reference,reference_sha256,native_destination):
        if not _hex(reference) or not _hex(reference_sha256):raise TransferError('media_backup_native_selection_required')
        from magnolie_media_retention import NativeMediaRetention
        self._current()
        run=NativeMediaBackupRecoveryUi(self.directory,self.guard,clock=self.clock)
        run.deadline=self.clock()+NativeMediaRetention.MAX_ACTIVE_COPY_SECONDS
        return run._restore(scope,source_id,reference,reference_sha256,native_destination)

    def _restore(self,scope,source_id,reference,reference_sha256,native_destination):
        with self._source(scope,source_id) as (locations,default):
            selected=next((row for row in locations.versions(default,source_id) if row.id==reference and row.record_sha256==reference_sha256),None)
            if selected is None:raise TransferError('media_backup_stale_selection')
            outer_scope=locations._store._subject['local_backup_scope']
            with NativeMediaBackupRestoreOwner(self.directory,outer_scope,self._current) as owner:
                return owner.restore(owner.issue_action(),locations,default,source_id,selected,native_destination)


@dataclass(frozen=True)
class NativeMediaBackupVersion:
    id: str
    object_key: str
    saved_ms: int
    name: str
    record_sha256: str

    @property
    def grants_write_authority(self): return False


@dataclass(frozen=True)
class NativeMediaBackupRestoration:
    operation: str
    state: str
    name: str
    file_key: tuple
    original_mapping: NativeSavedPhotoMapping
    _source_version: dict | None = None

    @property
    def source_version(self):return copy.deepcopy(self._source_version)

    @property
    def is_saved_receipt(self):return False
    @property
    def grants_write_authority(self):return False


@dataclass(frozen=True)
class NativeRestoredMediaCandidate:
    """Historical new-file identity; never a reusable source READ grant."""
    destination: NativeAcceptedDestination
    relative_path: str
    file_key: tuple
    parent_keys: tuple
    protected_record_sha256: str
    original_mapping: NativeSavedPhotoMapping

    @property
    def association(self):return self.original_mapping.association
    def phone_original_reference(self):return self.original_mapping.phone_original_reference()
    @property
    def grants_read_authority(self):return False
    @property
    def is_saved_receipt(self):return False

    def wire(self):
        return dict(destination=self.destination.wire(),relative_path=self.relative_path,file_key=list(self.file_key),
            parent_keys=[list(key) for key in self.parent_keys],restore_record_sha256=self.protected_record_sha256,
            original_mapping_sha256=self.original_mapping.protected_record_sha256)


class _ProtectedBackupRestorations(_ProtectedBackupLocations):
    """Independent append-only local restoration evidence, not phone receipts."""
    MAX_RECORD_BYTES=1024*1024
    MAX_DATABASE_BYTES=4*1024*1024
    MAX_OPERATIONS=128

    def __init__(self,*args):
        super().__init__(*args)
        self._name='media-backup-restores-v1-'+self._scope
        self._domain='magnolie-media-backup-restores-v1/'+self._scope+'/'
        self._absent=sha256((self._domain+'absent').encode()).hexdigest()
        self._anchor=self._name+'.seal'

    def _initial_owner(self):return dict(revision=1,restores_sha256=None)

    @staticmethod
    def mapping(event):
        value=event['original_mapping'];association=value.get('association') if type(value) is dict else None
        if type(association) is not dict or set(association)!={'source_epoch','photo_id','media_type'}:
            raise TransferError('media_backup_restore_invalid_lineage')
        source=event.get('source_version')
        record_hash=event['reference'] if source is None else source['source']['original_mapping_sha256']
        return NativeSavedPhotoMapping.parse(value,PhotoMappingAssociation(**association),record_hash)

    def _snapshot(self):
        owners=self._db.execute('SELECT id,payload FROM owner').fetchall();rows=self._db.execute('SELECT id,payload FROM policy').fetchall()
        if len(owners)!=1 or owners[0][0]!=1 or len(rows)>1 or rows and rows[0][0]!=1:
            raise TransferError('media_backup_restore_invalid_rows')
        head=self._unprotect(owners[0][1],'owner');events=[];version=self._absent
        if type(head) is not dict or set(head)!={'revision','restores_sha256'} or type(head['revision']) is not int:
            raise TransferError('media_backup_restore_invalid_history')
        if not rows:
            if head!=self._initial_owner():raise TransferError('media_backup_restore_missing_history')
        else:
            version=sha256(rows[0][1]).hexdigest();events=self._unprotect(rows[0][1],'restores')
            if (type(events) is not list or not 1<=len(events)<=2*self.MAX_OPERATIONS
                    or head!=dict(revision=len(events)+1,restores_sha256=version)):
                raise TransferError('media_backup_restore_invalid_history')
        heads={}
        for event in events:
            fields={'operation','state','source_id','reference','reference_sha256',
                    'destination','stage','name','file_key','size','sha256','original_mapping'}
            if (type(event) is not dict or set(event) not in (fields,fields|{'source_version'})
                    or type(event['operation']) is not str or len(event['operation'])!=32 or not _hex(event['operation']*2)
                    or event['state'] not in ('prepared','restored')
                    or any(not _hex(event[key]) for key in ('source_id','reference','reference_sha256','sha256'))
                    or event['stage']!='.magnolie-restore-'+event['operation']+'.part'
                    or type(event['name']) is not str or not event['name'] or '/' in event['name'] or '\\' in event['name']
                    or event['name'] in ('.','..') or '\x00' in event['name']
                    or type(event['file_key']) is not list or len(event['file_key'])!=2
                    or any(type(v) is not int or not 0<=v<2**64 for v in event['file_key']) or event['file_key'][1]==0):
                raise TransferError('media_backup_restore_invalid_event')
            destination=NativeAcceptedDestination.parse(event['destination']);require_media_directory(destination.path)
            source=event.get('source_version')
            if 'source_version' in event:
                from magnolie_media_source_backup import _validate_source_version
                if type(source) is not dict:raise TransferError('media_backup_restore_invalid_lineage')
                _validate_source_version(source,event['reference'])
                if (sha256(canonical(source)).hexdigest()!=event['reference_sha256']
                        or source['source']['original_mapping']!=event['original_mapping']):
                    raise TransferError('media_backup_restore_invalid_lineage')
            mapping=self.mapping(event)
            if source is None:size,digest=mapping.saved_size,mapping.saved_sha256
            else:
                from magnolie_file_transfer import FileManifest
                file=FileManifest.parse(source['source']['manifest']).files[0];size,digest=file.size,file.sha256
            if (type(event['size']) is not int or event['size']!=size or event['sha256']!=digest
                    or event['file_key'][0]!=destination.ancestor_keys[0][0]):
                raise TransferError('media_backup_restore_invalid_content')
            previous=heads.get(event['operation'])
            if previous is None:
                if event['state']!='prepared' or len(heads)>=self.MAX_OPERATIONS:raise TransferError('media_backup_restore_invalid_transition')
            elif (previous['state']!='prepared' or event['state']!='restored'
                    or dict(previous,state='restored')!=event):raise TransferError('media_backup_restore_invalid_transition')
            heads[event['operation']]=event
        mark=len(events)+1,version
        if self._last is not None and (mark[0]<self._last[0] or mark[0]==self._last[0] and mark[1]!=self._last[1]):
            self._uncertain=True;raise TransferError('media_backup_restore_history_rollback')
        self._last=mark;return version,events,heads

    def append(self,event,current):
        _,events,_=self._snapshot();events=[*events,event]
        if len(events)>2*self.MAX_OPERATIONS:raise TransferError('media_backup_restore_history_capacity')
        blob=self._protect(events,'restores');version=sha256(blob).hexdigest()
        head=self._protect(dict(revision=len(events)+1,restores_sha256=version),'owner')
        try:
            self._db.execute('BEGIN IMMEDIATE')
            self._db.execute('INSERT OR REPLACE INTO policy VALUES(1,?)',(blob,))
            self._db.execute('UPDATE owner SET payload=? WHERE id=1',(head,))
            self._fresh();current();self._db.commit();self._sync()
            actual=self._snapshot()
            if actual[0]!=version:raise TransferError('media_backup_restore_readback_failed')
            current();return actual[2][event['operation']]
        except BaseException:
            if self._db.in_transaction:self._db.rollback()
            self._uncertain=True;raise


class NativeMediaBackupRestoreOwner:
    """Local explicit new-file publication with durable original-version lineage.

    The native caller owns the saved/unlocked-book guard. No synthetic transfer,
    trash operation, phone permission or Saved ACK is manufactured here.
    """
    def __init__(self,directory,scope,local_guard,*,monotonic_ms=lambda:time.monotonic_ns()//1_000_000,boundary=lambda _:None):
        if not _hex(scope) or not callable(local_guard) or not callable(monotonic_ms) or not callable(boundary):
            raise TransferError('media_backup_local_owner_required')
        self._journal=_ProtectedBackupRestorations(directory,scope,local_guard,monotonic_ms);self._boundary=boundary

    def issue_action(self):return self._journal.issue_action()

    def history(self):
        journal=self._journal
        with journal._operation():
            if not journal._open():return ()
            with journal._locked():
                journal._schema();_,_,heads=journal._snapshot()
                return tuple(NativeMediaBackupRestoration(event['operation'],event['state'],event['name'],
                    tuple(event['file_key']),journal.mapping(event),copy.deepcopy(event.get('source_version'))) for _,event in sorted(heads.items()))

    def phone_original_reference(self,operation):
        """Completed local restoration history only, not a file-read grant.

        Prepared copies and arbitrary caller mappings cannot supply return
        lineage. Actual source path/inode/content and current send consent must
        still be checked independently before any inventory or upload.
        """
        if type(operation) is not str or len(operation)!=32 or not _hex(operation*2):
            raise TransferError('media_backup_restore_original_operation_required')
        result=next((item for item in self.history() if item.operation==operation),None)
        if result is None or result.state!='restored':
            raise TransferError('media_backup_restore_completed_history_required')
        return result.original_mapping.phone_original_reference()

    @staticmethod
    def _candidate(journal,event):
        if event is None or event['state']!='restored':raise TransferError('media_backup_restore_completed_history_required')
        destination=NativeAcceptedDestination.parse(event['destination'])
        return NativeRestoredMediaCandidate(destination,event['name'],tuple(event['file_key']),
            (destination.ancestor_keys[0],),sha256(canonical(event)).hexdigest(),journal.mapping(event))

    def source_candidate(self,operation):
        if type(operation) is not str or len(operation)!=32 or not _hex(operation*2):
            raise TransferError('media_backup_restore_original_operation_required')
        journal=self._journal
        with journal._operation():
            if not journal._open():raise TransferError('media_backup_restore_completed_history_required')
            with journal._locked():
                journal._schema();_,_,heads=journal._snapshot()
                return self._candidate(journal,heads.get(operation))

    @contextmanager
    def restored_source_lease(self,operation,expected_record_sha256):
        if (type(operation) is not str or len(operation)!=32 or not _hex(operation*2) or not _hex(expected_record_sha256)):
            raise TransferError('media_backup_restore_original_operation_required')
        journal=self._journal
        with journal._operation():
            if not journal._open():raise TransferError('media_backup_restore_completed_history_required')
            with journal._locked():
                journal._schema();_,_,heads=journal._snapshot();event=heads.get(operation)
                candidate=self._candidate(journal,event)
                if candidate.protected_record_sha256!=expected_record_sha256:raise TransferError('media_backup_restore_source_selection_changed')
                def current():
                    journal._fresh();_,_,actual=journal._snapshot()
                    if actual.get(operation)!=event:raise TransferError('media_backup_restore_source_selection_changed')
                    return True
                current();yield candidate,current;current()

    def restore(self,action,locations,default,source_id,selected,destination):
        journal=self._journal
        if (type(action) is not NativePhotoDestinationAction or type(locations) is not NativeMediaBackupLocations
                or type(selected) is not NativeMediaBackupVersion or type(destination) is not NativeAcceptedDestination
                or locations._store._subject!=journal._subject or locations._store.directory!=journal.directory):
            raise TransferError('media_backup_restore_native_owner_required')
        action.consume(journal)
        from magnolie_media_retention import NativeMediaRetention
        started=journal._clock()
        def current():
            now=journal._clock()
            if (type(now) is not int or type(started) is not int or now<started
                    or now-started>=NativeMediaRetention.MAX_ACTIVE_COPY_SECONDS*1000):
                raise TransferError('media_backup_restore_run_expired')
            journal._peer();locations._store._peer()
            if (source_id,backups.storage_parent) not in locations.sources(default):raise TransferError('media_backup_source_not_retained')
            require_media_directory(destination.path);destination.verify();return True
        with journal._operation(),locations._history(default,source_id) as backups:
            current();mapping,size,digest,source_version=backups._restore_lineage(selected)
            journal._open(create=True,validate=current)
            with journal._locked():
                _,_,heads=journal._snapshot()
                pending=[event for event in heads.values() if event['state']=='prepared' and event['source_id']==source_id
                    and event['reference']==selected.id and event['destination']==destination.wire()]
                if len(pending)>1:raise TransferError('media_backup_restore_multiple_candidates')
                parent=os.open(destination.path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
                fd=None
                try:
                    def directories():
                        current()
                        if journal._key(os.fstat(parent))!=destination.ancestor_keys[0]:raise TransferError('media_backup_restore_parent_changed')
                    directories()
                    if pending:event=pending[0]
                    else:
                        if len(heads)>=journal.MAX_OPERATIONS:raise TransferError('media_backup_restore_history_capacity')
                        free=os.fstatvfs(parent)
                        if free.f_bavail*free.f_frsize<size+1024**3:raise TransferError('media_backup_insufficient_space')
                        operation=secrets.token_hex(16);stage='.magnolie-restore-'+operation+'.part'
                        leaf=PurePosixPath(selected.name).name;extension=PurePosixPath(leaf).suffix
                        if len(extension)>16:extension=''
                        stem=leaf[:-len(extension)] if extension else leaf
                        name=stem[:40]+' - restored '+operation+extension
                        fd=os.open(stage,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,0o600,dir_fd=parent)
                        event=dict(operation=operation,state='prepared',source_id=source_id,reference=selected.id,
                            reference_sha256=selected.record_sha256,destination=destination.wire(),stage=stage,name=name,
                            file_key=list(journal._key(os.fstat(fd))),size=size,sha256=digest,original_mapping=mapping.wire())
                        if source_version is not None:event['source_version']=source_version
                        directories();os.fsync(fd);os.fsync(parent)
                        journal.append(event,current);self._boundary('prepared')
                    if (event['reference_sha256']!=selected.record_sha256 or event['original_mapping']!=mapping.wire()
                            or event.get('source_version')!=source_version or event['size']!=size or event['sha256']!=digest):
                        raise TransferError('media_backup_restore_original_selection_required')
                    def observe(name):
                        directories()
                        try:value=os.stat(name,dir_fd=parent,follow_symlinks=False)
                        except FileNotFoundError:return None
                        journal._private(value)
                        if list(journal._key(value))!=event['file_key']:raise TransferError('media_backup_restore_original_candidate_required')
                        return value
                    stage_value=observe(event['stage']);published=stage_value is None
                    name=event['name'] if published else event['stage'];observed=observe(name)
                    if observed is None:raise TransferError('media_backup_restore_original_candidate_required')
                    if fd is None:fd=os.open(name,os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=parent)
                    journal._private(os.fstat(fd))
                    if list(journal._key(os.fstat(fd)))!=event['file_key']:raise TransferError('media_backup_restore_original_candidate_required')
                    def candidate_current():
                        directories()
                        if observe(name) is None:raise TransferError('media_backup_restore_original_candidate_required')
                        if list(journal._key(os.fstat(fd)))!=event['file_key']:raise TransferError('media_backup_restore_original_candidate_required')
                    if published:verify_raw(fd,event['size'],event['sha256'],candidate_current,candidate=True)
                    else:
                        # Only this journal's private unpublished inode may be
                        # restarted. A published/user file is never truncated.
                        if os.fstat(fd).st_size>event['size']:raise TransferError('media_backup_restore_candidate_changed')
                        complete=False
                        if os.fstat(fd).st_size==event['size']:
                            try:
                                verify_raw(fd,event['size'],event['sha256'],candidate_current,candidate=True);complete=True
                            except TransferError as error:
                                if str(error)!='media_backup_original_content_changed':raise
                        if not complete:
                            free=os.fstatvfs(parent);allocated=os.fstat(fd).st_blocks*512
                            if free.f_bavail*free.f_frsize+allocated<event['size']+1024**3:
                                raise TransferError('media_backup_insufficient_space')
                            candidate_current();os.ftruncate(fd,0);os.fsync(fd)
                            backups.restore(selected,fd);candidate_current()
                        verify_raw(fd,event['size'],event['sha256'],candidate_current,candidate=True)
                        self._boundary('copied');candidate_current()
                        _rename_no_replace(parent,event['stage'],event['name']);os.fsync(parent)
                        name=event['name'];candidate_current();self._boundary('published')
                    verify_raw(fd,event['size'],event['sha256'],candidate_current,candidate=True)
                    completed=journal.append(dict(event,state='restored'),current);self._boundary('restored')
                    return NativeMediaBackupRestoration(completed['operation'],'restored',completed['name'],tuple(completed['file_key']),mapping,
                        copy.deepcopy(source_version))
                finally:
                    if fd is not None:os.close(fd)
                    os.close(parent)

    def close(self):return self._journal.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class NativeMediaBackups:
    """One Backup folder per native storage parent; no adoption of foreign folders.

    Constructor opens EXISTING storage only. Explicit create is a native local
    choice guarded by the already saved/unlocked book, never a wire path/boolean.
    Storage and original data destination are independent; only saving original
    mappings requires the original data owner. Local history reads/restoration
    can keep using verified backup storage after those source files are gone.
    No thread, scheduler, keys, peers, retention settings or service is created.
    """
    MAX_VERSIONS = 4096
    MAX_DATABASE_BYTES = 64 * 1024**2
    MAX_MEMBERSHIP_BYTES = 2 * 1024**2
    SCHEMA = (
        'CREATE TABLE meta (name TEXT PRIMARY KEY NOT NULL, sealed BLOB NOT NULL)',
        'CREATE TABLE versions (id TEXT PRIMARY KEY NOT NULL, sealed BLOB NOT NULL)',
        'CREATE TABLE objects (id TEXT PRIMARY KEY NOT NULL, sealed BLOB NOT NULL)',
    )

    def __init__(self, destination, protection, native_gate, *, create=False, storage_parent=None,
            clock_ms=lambda: time.time_ns() // 1000000):
        if (type(destination) is not NativeAcceptedDestination or type(protection) is not ExistingFileTransferProtection
                or storage_parent is not None and type(storage_parent) is not NativeAcceptedDestination
                or not callable(native_gate) or not callable(clock_ms)):
            raise TransferError('media_backup_native_owner_required')
        self.destination, self.protection, self._native_gate, self._clock = destination, protection, native_gate, clock_ms
        self.storage_parent = destination if storage_parent is None else storage_parent
        self._gate = threading.Lock(); self._closed = False; self._revoked = False; self._uncertain = False; self._observed = None
        self._parent = self._root = self._lock = self._dbfile = None; self._db = None
        self.scope = sha256(canonical(self.storage_parent.wire())).hexdigest()
        self._domain = 'magnolie-media-backup-v1/' + self.scope + '/'
        self._native_owner_name='media-backup-owner-v1-'+self.scope+'.seal'
        self._native_owner_identity=self._catalog_owner_identity=None
        try:
            self._require_native(); self.storage_parent.verify()
            if create:require_media_directory(self.storage_parent.path)
            self._parent = os.open(self.storage_parent.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            if self._key(os.fstat(self._parent)) != self.storage_parent.ancestor_keys[0]:
                raise TransferError('media_backup_original_parent_required')
            if create:
                try:os.stat(self._native_owner_name,dir_fd=protection._root_fd,follow_symlinks=False)
                except FileNotFoundError:pass
                else:raise TransferError('media_backup_original_storage_required')
                # Probe the EXISTING key before creating any backup entry.
                protection.seal(b'probe', self._domain + 'probe')
                os.mkdir('Backup', 0o700, dir_fd=self._parent)
            self._root = os.open('Backup', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._parent)
            root = os.fstat(self._root); self._private(root, directory=True); self._root_key = self._key(root)
            if create:
                for name in ('catalog.sqlite3', '.lock'):
                    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._root)
                    os.close(fd)
            self._lock = os.open('.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._root)
            self._dbfile = os.open('catalog.sqlite3', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._root)
            self._private(os.fstat(self._lock)); self._private(os.fstat(self._dbfile))
            self._lock_key = self._key(os.fstat(self._lock)); self._db_key = self._key(os.fstat(self._dbfile))
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                self._metadata_files()
                if not create:
                    # Authenticate original storage BEFORE SQLite may create a
                    # WAL/SHM or change pragmas. Missing headers never bootstrap.
                    self._header_blob = self._read_file('.owner.seal', 16384)
                    if strict_json(protection.unseal(self._header_blob, self._domain + 'header')) != self._header():
                        raise TransferError('media_backup_original_storage_required')
                    self._check_native_owner()
                    self._db = sqlite3.connect(f'file:/proc/self/fd/{self._root}/catalog.sqlite3?mode=ro', uri=True,
                        isolation_level=None, check_same_thread=False)
                    self._verify()
                    self._db.close(); self._db = None
                self._db = sqlite3.connect(f'/proc/self/fd/{self._root}/catalog.sqlite3', isolation_level=None, check_same_thread=False)
                self._db.execute('PRAGMA journal_mode=WAL'); self._db.execute('PRAGMA synchronous=FULL')
                if create:
                    self._db.execute('BEGIN IMMEDIATE')
                    try:
                        for sql in self.SCHEMA: self._db.execute(sql)
                        self._write_membership(1); self._db.commit()
                    except BaseException:
                        self._db.rollback(); raise
                    self._write_new('.owner.seal', self.protection.seal(canonical(self._header()), self._domain + 'header'))
                    os.fsync(self._root); os.fsync(self._parent)
                self._header_blob = self._read_file('.owner.seal', 16384)
                if strict_json(protection.unseal(self._header_blob, self._domain + 'header')) != self._header():
                    raise TransferError('media_backup_original_storage_required')
                self._current()
                self._verify()
                if create:self._ensure_native_owner()
            finally: fcntl.flock(self._lock, fcntl.LOCK_UN)
        except BaseException:
            self.close(); raise

    @staticmethod
    def _key(value): return value.st_dev, value.st_ino

    @staticmethod
    def _private(value, *, directory=False):
        if ((not stat.S_ISDIR(value.st_mode) if directory else not stat.S_ISREG(value.st_mode) or value.st_nlink != 1)
                or value.st_uid != os.geteuid() or value.st_mode & 0o077):
            raise TransferError('media_backup_private_storage_required')

    def _header(self):
        return dict(format=1, scope=self.scope, parent=list(self.storage_parent.ancestor_keys[0]), root=list(self._root_key),
            database=list(self._db_key), lock=list(self._lock_key))

    def _owner_file(self,parent,name):
        try:fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=parent)
        except FileNotFoundError:return None
        try:
            before=os.fstat(fd);self._private(before)
            if not 28<=before.st_size<=16384:raise TransferError('media_backup_original_storage_required')
            blob=os.pread(fd,16385,0);after=os.fstat(fd);named=os.stat(name,dir_fd=parent,follow_symlinks=False)
            self._private(named)
            signature=self.protection._signature
            if len(blob)!=before.st_size or signature(before)!=signature(after) or signature(before)!=signature(named):
                raise TransferError('media_backup_original_storage_required')
            return self._key(before),blob
        finally:os.close(fd)

    def _native_owner_value(self):
        return dict(format=1,header=self._header(),header_sha256=sha256(self._header_blob).hexdigest(),
            native_directory=list(self.protection.native_directory_identity))

    def _check_native_owner(self):
        native=self._owner_file(self.protection._root_fd,self._native_owner_name)
        marker=self._owner_file(self._root,'.native-owner.required')
        if native is None:
            if marker is not None or self._native_owner_identity is not None:
                raise TransferError('media_backup_original_storage_required')
            return None # Authenticated legacy catalog; passive reads never migrate.
        value=self.protection.unseal(native[1],self._domain+'native-owner')
        if value!=canonical(self._native_owner_value()):raise TransferError('media_backup_original_storage_required')
        identity=native[0],sha256(native[1]).hexdigest()
        if self._native_owner_identity is not None and self._native_owner_identity!=identity:
            raise TransferError('media_backup_original_storage_required')
        if marker is not None:
            expected=dict(format=1,native_key=list(native[0]),native_sha256=identity[1],header_sha256=sha256(self._header_blob).hexdigest())
            if self.protection.unseal(marker[1],self._domain+'catalog-owner')!=canonical(expected):
                raise TransferError('media_backup_original_storage_required')
            marked=marker[0],sha256(marker[1]).hexdigest()
            if self._catalog_owner_identity is not None and self._catalog_owner_identity!=marked:
                raise TransferError('media_backup_original_storage_required')
            self._catalog_owner_identity=marked
        elif self._catalog_owner_identity is not None:raise TransferError('media_backup_original_storage_required')
        self._native_owner_identity=identity;return native

    def _atomic_owner_file(self,parent,name,blob):
        # Never publish a partially written ownership record. Interrupted legacy
        # binding leaves its old catalog readable; unknown temp files are kept.
        temporary='.magnolie-backup-owner-'+secrets.token_hex(16)+'.tmp'
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
        try:
            key=self._key(os.fstat(fd));offset=0
            while offset<len(blob):
                self._require_native();count=os.write(fd,blob[offset:])
                if count<=0:raise TransferError('media_backup_short_write')
                offset+=count
            os.fsync(fd);self._require_native();self.protection._read_key()
            if self._key(os.stat(temporary,dir_fd=parent,follow_symlinks=False))!=key:
                raise TransferError('media_backup_original_storage_required')
            _rename_no_replace(parent,temporary,name);os.fsync(parent)
        finally:os.close(fd)

    def _ensure_native_owner(self):
        self._current();native=self._check_native_owner()
        if native is None:
            blob=self.protection.seal(canonical(self._native_owner_value()),self._domain+'native-owner')
            self._atomic_owner_file(self.protection._root_fd,self._native_owner_name,blob)
            native=self._check_native_owner()
        if self._catalog_owner_identity is None:
            value=dict(format=1,native_key=list(native[0]),native_sha256=sha256(native[1]).hexdigest(),header_sha256=sha256(self._header_blob).hexdigest())
            self._atomic_owner_file(self._root,'.native-owner.required',self.protection.seal(canonical(value),self._domain+'catalog-owner'))
        self._check_native_owner();self._current()

    def _require_native(self):
        try:
            if self._closed or self._revoked or self._uncertain or self._native_gate() is not True:
                raise TransferError('media_backup_native_owner_changed')
        except BaseException:
            self._revoked = True; raise

    def _current(self):
        self._require_native(); self.protection._read_key(); self.storage_parent.verify()
        for fd, name, key, directory in ((self._root, 'Backup', self._root_key, True),):
            held = os.fstat(fd); named = os.stat(name, dir_fd=self._parent, follow_symlinks=False)
            self._private(held, directory=directory); self._private(named, directory=directory)
            if self._key(held) != key or self._key(named) != key: raise TransferError('media_backup_original_storage_required')
        for fd, name, key in ((self._lock, '.lock', self._lock_key), (self._dbfile, 'catalog.sqlite3', self._db_key)):
            value = os.stat(name, dir_fd=self._root, follow_symlinks=False); self._private(value)
            if self._key(value) != key or self._key(os.fstat(fd)) != key: raise TransferError('media_backup_original_storage_required')
        if self._read_file('.owner.seal', 16384) != self._header_blob: raise TransferError('media_backup_original_storage_required')
        self._check_native_owner()
        self._metadata_files()

    def _metadata_files(self):
        for name, bound in (('catalog.sqlite3', self.MAX_DATABASE_BYTES), ('catalog.sqlite3-wal', 2 * self.MAX_DATABASE_BYTES),
                ('catalog.sqlite3-shm', 1024**2)):
            try: value = os.stat(name, dir_fd=self._root, follow_symlinks=False)
            except FileNotFoundError:
                if name == 'catalog.sqlite3': raise
                continue
            self._private(value)
            if value.st_size > bound: raise TransferError('media_backup_catalog_capacity')

    def _read_file(self, name, bound):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=self._root)
        try:
            before = os.fstat(fd); self._private(before)
            if not 1 <= before.st_size <= bound: raise TransferError('media_backup_metadata_invalid')
            data = os.pread(fd, bound + 1, 0)
            after = os.fstat(fd); named = os.stat(name, dir_fd=self._root, follow_symlinks=False)
            if (len(data) != before.st_size or self._key(before) != self._key(named)
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise TransferError('media_backup_metadata_changed')
            return data
        finally: os.close(fd)

    def _write_new(self, name, data):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._root)
        try:
            offset = 0
            while offset < len(data):
                count = os.write(fd, data[offset:])
                if count <= 0: raise TransferError('media_backup_short_write')
                offset += count
            os.fsync(fd)
        finally: os.close(fd)

    def _members(self, table):
        count, largest = self._db.execute(f'SELECT count(*),COALESCE(max(length(sealed)),0) FROM {table}').fetchone()
        if count > self.MAX_VERSIONS or largest > 16384: raise TransferError('media_backup_catalog_capacity')
        rows = self._db.execute(f'SELECT id,sealed FROM {table} ORDER BY id LIMIT ?', (self.MAX_VERSIONS + 1,)).fetchall()
        if len(rows) != count: raise TransferError('media_backup_membership_changed')
        return [[key, sha256(blob).hexdigest()] for key, blob in rows]

    def _write_membership(self, revision):
        body = dict(format=1, revision=revision, versions=self._members('versions'), objects=self._members('objects'))
        pending=self._pending_members()
        if pending:body['pending']=pending
        blob = self.protection.seal(canonical(body), self._domain + 'membership')
        self._db.execute("INSERT OR REPLACE INTO meta VALUES('membership',?)", (blob,))

    def _pending_members(self):
        rows=self._db.execute("SELECT name,sealed FROM meta WHERE name!='membership' ORDER BY name LIMIT ?",
            (self.MAX_VERSIONS+1,)).fetchall()
        if len(rows)>self.MAX_VERSIONS:raise TransferError('media_backup_catalog_capacity')
        for name,blob in rows:
            if (type(name) is not str or not name.startswith('pending-') or not _hex(name[8:])
                    or type(blob) is not bytes or not 28<=len(blob)<=16384):
                raise TransferError('media_backup_pending_invalid')
        return [[name[8:],sha256(blob).hexdigest()] for name,blob in rows]

    def _verify(self):
        if tuple(row[0] for row in self._db.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name")) != tuple(sorted(self.SCHEMA, key=lambda sql: sql.split()[2])):
            raise TransferError('media_backup_schema_changed')
        length = self._db.execute("SELECT length(sealed) FROM meta WHERE name='membership'").fetchone()
        if length is None or not 28 <= length[0] <= self.MAX_MEMBERSHIP_BYTES:
            raise TransferError('media_backup_membership_required')
        blob = self._db.execute("SELECT sealed FROM meta WHERE name='membership'").fetchone()[0]
        value = strict_json(self.protection.unseal(blob, self._domain + 'membership'))
        pending=self._pending_members()
        if (type(value) is not dict or set(value) not in ({'format', 'revision', 'versions', 'objects'},
                    {'format', 'revision', 'versions', 'objects', 'pending'}) or type(value['format']) is not int or value['format'] != 1
                or type(value['revision']) is not int or not 1 <= value['revision'] <= 2**53 - 1
                or value['versions'] != self._members('versions') or value['objects'] != self._members('objects')
                or value.get('pending',[])!=pending):
            raise TransferError('media_backup_membership_changed')
        observed = value['revision'], sha256(blob).hexdigest()
        if self._observed is not None and (observed[0] < self._observed[0] or observed[0] == self._observed[0] and observed[1] != self._observed[1]):
            raise TransferError('media_backup_catalog_rollback')
        if not self._db.in_transaction: self._observed = observed
        return observed[0]

    @contextmanager
    def _operation(self):
        if not self._gate.acquire(blocking=False): raise TransferError('media_backup_worker_busy')
        locked = False
        try:
            self._current(); fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB); locked = True
            self._current(); self._verify(); yield; self._current()
        finally:
            if locked: fcntl.flock(self._lock, fcntl.LOCK_UN)
            self._gate.release()

    def _record(self, table, key):
        row = self._db.execute(f'SELECT sealed FROM {table} WHERE id=?', (key,)).fetchone()
        if row is None: return None
        value = strict_json(self.protection.unseal(row[0], self._domain + table + '/' + key))
        if type(value) is not dict or value.get('id') != key: raise TransferError('media_backup_record_invalid')
        if table == 'versions':
            self._validate_version(value,key)
        else:
            fields = {'id', 'size', 'sha256', 'codec', 'name', 'key', 'stored_size', 'stored_sha256', 'raw_name', 'raw_key', 'raw_retired', 'trial', 'prepared', 'candidate'}
            if (set(value) != fields or type(value['raw_retired']) is not bool or type(value['trial']) is not bool
                    or type(value['prepared']) is not bool
                    or type(value['stored_size']) is not int or value['stored_size'] < 0 or not _hex(value['stored_sha256'])
                    or value['id'] != content_key(value['size'], value['sha256']) or value['raw_name'] != 'object-' + key + '.raw'):
                raise TransferError('media_backup_record_invalid')
            for field in ('key', 'raw_key'):
                witness = value[field]
                if (type(witness) is not list or len(witness) != 2 or any(type(number) is not int or number < 0 for number in witness)
                        or witness[0] != self._root_key[0] or witness[1] == 0): raise TransferError('media_backup_record_invalid')
            if value['codec'] == 'raw':
                if (value['name'] != value['raw_name'] or value['key'] != value['raw_key'] or value['stored_size'] != value['size']
                        or value['stored_sha256'] != value['sha256'] or value['raw_retired']): raise TransferError('media_backup_record_invalid')
                if value['prepared'] and (value['trial'] or value['candidate'] is not None): raise TransferError('media_backup_record_invalid')
            elif value['codec'] == 'xz':
                prefix = 'object-' + key + '-'
                nonce = value['name'][len(prefix):-3] if type(value['name']) is str and value['name'].startswith(prefix) and value['name'].endswith('.xz') else ''
                if len(nonce) != 32 or not _hex(nonce * 2) or value['key'] == value['raw_key'] or not value['trial'] or value['prepared'] or value['candidate'] is not None:
                    raise TransferError('media_backup_record_invalid')
            else: raise TransferError('media_backup_record_invalid')
            candidate = value['candidate']
            if candidate is not None:
                if type(candidate) is not dict or set(candidate) != {'name', 'key'} or value['codec'] != 'raw': raise TransferError('media_backup_record_invalid')
                prefix = 'object-' + key + '-'
                nonce = candidate['name'][len(prefix):-3] if type(candidate['name']) is str and candidate['name'].startswith(prefix) and candidate['name'].endswith('.xz') else ''
                witness = candidate['key']
                if (len(nonce) != 32 or not _hex(nonce * 2) or type(witness) is not list or len(witness) != 2
                        or any(type(number) is not int or number < 0 for number in witness) or witness[0] != self._root_key[0]
                        or witness[1] == 0 or witness == value['raw_key']): raise TransferError('media_backup_record_invalid')
        return value

    @staticmethod
    def _validate_version(value,key):
        if type(value) is dict and 'source' in value:
            from magnolie_media_source_backup import _validate_source_version
            return _validate_source_version(value,key)
        if (type(value) is not dict or set(value) != {'id', 'object_key', 'saved_ms', 'name', 'mapping'}
                or value['id']!=key or not _hex(key) or type(value['saved_ms']) is not int
                or not 0 < value['saved_ms'] <= 253402300799999 or type(value['mapping']) is not dict
                or type(value['mapping'].get('association')) is not dict
                or set(value['mapping']['association'])!={'source_epoch','photo_id','media_type'}):
            raise TransferError('media_backup_record_invalid')
        association=PhotoMappingAssociation(**value['mapping']['association'])
        mapping=NativeSavedPhotoMapping.parse(value['mapping'],association,key)
        if value['object_key']!=content_key(mapping.saved_size,mapping.saved_sha256) or value['name']!=mapping.relative_path:
            raise TransferError('media_backup_record_invalid')
        return value

    def _pending(self,key):
        row=self._db.execute('SELECT sealed FROM meta WHERE name=?',('pending-'+key,)).fetchone()
        if row is None:return None
        value=strict_json(self.protection.unseal(row[0],self._domain+'pending/'+key))
        return self._validate_version(value,key)

    def _commit(self, *, version=None, obj=None, pending=None):
        revision = self._verify()
        try:
            self._db.execute('BEGIN IMMEDIATE'); self._current()
            for table, value in (('versions', version), ('objects', obj)):
                if value is not None:
                    blob = self.protection.seal(canonical(value), self._domain + table + '/' + value['id'])
                    verb = 'INSERT' if table == 'versions' else 'INSERT OR REPLACE'
                    self._db.execute(f'{verb} INTO {table} VALUES(?,?)', (value['id'], blob))
            if pending is not None:
                self._validate_version(pending,pending['id'])
                blob=self.protection.seal(canonical(pending),self._domain+'pending/'+pending['id'])
                self._db.execute('INSERT INTO meta VALUES(?,?)',('pending-'+pending['id'],blob))
            if version is not None:self._db.execute('DELETE FROM meta WHERE name=?',('pending-'+version['id'],))
            self._write_membership(revision + 1); self._current(); self._db.commit(); os.fsync(self._root)
            if self._verify() != revision + 1: raise TransferError('media_backup_commit_not_proven')
        except BaseException:
            if self._db.in_transaction: self._db.rollback()
            self._uncertain = True; raise

    @contextmanager
    def _object(self, obj, *, raw=False, writable=False):
        name, key = (obj['raw_name'], obj['raw_key']) if raw else (obj['name'], obj['key'])
        if (type(name) is not str or '/' in name or '\\' in name or not name.startswith('object-')
                or type(key) is not list or len(key) != 2): raise TransferError('media_backup_object_invalid')
        self._current()
        fd = os.open(name, (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=self._root)
        try:
            value = os.fstat(fd); self._private(value)
            if list(self._key(value)) != key or self._key(os.stat(name, dir_fd=self._root, follow_symlinks=False)) != tuple(key):
                raise TransferError('media_backup_original_object_changed')
            yield fd
            self._current()
            if self._key(os.stat(name, dir_fd=self._root, follow_symlinks=False)) != tuple(key): raise TransferError('media_backup_original_object_changed')
        finally: os.close(fd)

    def _representation(self, obj):
        if obj['prepared']: raise TransferError('media_backup_object_not_complete')
        result = VerifiedBackupRepresentation(obj['size'], obj['sha256'], obj['stored_size'], obj['stored_sha256'], tuple(obj['key']), obj['codec'])
        if obj['id'] != content_key(result.raw_size, result.raw_sha256) or result.codec not in ('raw', 'xz'):
            raise TransferError('media_backup_object_invalid')
        return result

    def _verify_object(self, obj):
        result = self._representation(obj)
        with self._object(obj) as fd:
            if result.codec == 'raw':
                value = verify_raw(fd, result.raw_size, result.raw_sha256, self._current)
                if result.stored_size != value.st_size or result.stored_sha256 != result.raw_sha256: raise TransferError('media_backup_object_invalid')
            elif verify_xz(fd, result.raw_size, result.raw_sha256, self._current) != result:
                raise TransferError('media_backup_original_object_changed')
        return result

    @contextmanager
    def _saved_file(self, mapping, current):
        fds = []; parts = mapping.relative_path.split('/')
        try:
            mapping.destination.verify()
            fds.append(os.open(mapping.destination.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC))
            for index, name in enumerate(parts):
                current()
                if self._key(os.fstat(fds[-1])) != mapping.parent_keys[index]: raise TransferError('media_backup_original_parent_required')
                if index == len(parts) - 1: break
                fds.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1]))
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fds[-1])
            fds.append(fd)
            if self._key(os.fstat(fd)) != mapping.file_key: raise TransferError('media_backup_original_saved_file_required')
            verify_raw(fd, mapping.saved_size, mapping.saved_sha256, current)
            yield fd
            if self._key(os.stat(parts[-1], dir_fd=fds[-2], follow_symlinks=False)) != mapping.file_key:
                raise TransferError('media_backup_original_saved_file_required')
            mapping.destination.verify(); current()
        finally:
            for fd in reversed(fds): os.close(fd)

    def save_from_mappings(self, mappings, association, expected_record_sha256):
        if type(mappings) is not ProtectedPhotoMappings or not _hex(expected_record_sha256): raise TransferError('media_backup_original_mapping_required')
        with self._operation(), mappings.saved_record_lease(association, expected_record_sha256) as (mapping, mapping_current):
            if mapping.destination != self.destination: raise TransferError('media_backup_original_mapping_changed')
            def mapping_now(): self._current(); mapping_current()
            version_id = mapping.protected_record_sha256
            with self._saved_file(mapping, mapping_now) as source:
                # Legacy ownership binding is an actual authenticated Saved
                # backup action, never a side effect of listing old catalogs.
                self._ensure_native_owner()
                before = self._record('versions', version_id)
                key = content_key(mapping.saved_size, mapping.saved_sha256); obj = self._record('objects', key)
                if obj is not None and not obj['prepared']: self._verify_object(obj)
                if before is not None:
                    if before['mapping'] != mapping.wire() or obj is None: raise TransferError('media_backup_original_mapping_changed')
                    return self._version(before)
                version=self._pending(version_id)
                if version is not None:
                    if version['mapping']!=mapping.wire():raise TransferError('media_backup_original_mapping_changed')
                else:
                    if len(self._members('versions'))+len(self._pending_members())>=self.MAX_VERSIONS:
                        raise TransferError('media_backup_catalog_capacity')
                    now=self._clock()
                    if type(now) is not int or not 0 < now <= 253402300799999:raise TransferError('media_backup_invalid_clock')
                    version=dict(id=version_id,object_key=key,saved_ms=now,name=mapping.relative_path,mapping=mapping.wire())
                    # Authenticated original lineage must survive even if the
                    # source disappears after payload but before final commit.
                    mapping_now();self._commit(pending=version)
                if obj is None:
                    free = os.fstatvfs(self._root)
                    if free.f_bavail * free.f_frsize < mapping.saved_size + 1024**3: raise TransferError('media_backup_insufficient_space')
                    name = 'object-' + key + '.raw'
                    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._root)
                    try:
                        file_key = list(self._key(os.fstat(fd)))
                        obj = dict(id=key, size=mapping.saved_size, sha256=mapping.saved_sha256, codec='raw', name=name, key=file_key,
                            stored_size=mapping.saved_size, stored_sha256=mapping.saved_sha256, raw_name=name, raw_key=file_key,
                            raw_retired=False, trial=False, prepared=True, candidate=None)
                        # Register the NEW owned inode before the first payload
                        # write. Interrupted copying can never adopt another file.
                        os.fsync(fd);os.fsync(self._root)
                        self._commit(obj=obj)
                    finally: os.close(fd)
                    os.fsync(self._root)
                if obj['prepared']:
                    if any(self._record('versions', item)['object_key'] == key for item, _ in self._members('versions')):
                        raise TransferError('media_backup_object_not_complete')
                    with self._object(obj, writable=True) as fd:
                        try: verify_raw(fd, mapping.saved_size, mapping.saved_sha256, mapping_now, candidate=True)
                        except TransferError as error:
                            if str(error) != 'media_backup_original_content_changed': raise
                            verify_raw(source, mapping.saved_size, mapping.saved_sha256, mapping_now)
                            mapping_now(); os.ftruncate(fd, 0)
                            copy_unique(source, fd, mapping.saved_size, mapping.saved_sha256, mapping_now)
                    obj = dict(obj, prepared=False)
                mapping_now(); self._commit(version=version, obj=obj)
                self._verify_object(obj); return self._version(version)

    @staticmethod
    def _version(value):
        return NativeMediaBackupVersion(value['id'], value['object_key'], value['saved_ms'], value['name'], sha256(canonical(value)).hexdigest())

    def versions(self):
        with self._operation():
            return tuple(self._version(self._record('versions', key)) for key, _ in self._members('versions'))

    def _recoverable_pending(self,key):
        value=self._pending(key)
        if value is None:return None
        if self._record('versions',key) is not None:raise TransferError('media_backup_pending_invalid')
        obj=self._record('objects',value['object_key'])
        if obj is None:return None # Intent was committed before inode creation.
        if obj['prepared']:
            with self._object(obj) as fd:
                try:verify_raw(fd,obj['size'],obj['sha256'],self._current)
                except TransferError as error:
                    if str(error)!='media_backup_original_content_changed':raise
                    return None # Partial/unverified bytes never become a version.
        else:self._verify_object(obj)
        return value

    def pending_recovery_versions(self):
        """Read-only verified bytes with original intent, not completed backups."""
        with self._operation():
            result=[]
            for key,_ in self._pending_members():
                value=self._recoverable_pending(key)
                if value is not None:result.append(self._version(value))
            return tuple(result)

    def recovery_versions(self):
        # Keep versions() completed-only. Local recovery can also use exact
        # fully verified interrupted copies without forging a Saved completion.
        with self._operation():
            result=[self._version(self._record('versions',key)) for key,_ in self._members('versions')]
            for key,_ in self._pending_members():
                value=self._recoverable_pending(key)
                if value is not None:result.append(self._version(value))
            return tuple(sorted(result,key=lambda value:value.id))

    def _selected_version(self,selected):
        value=self._record('versions',selected.id)
        if value is None:value=self._recoverable_pending(selected.id)
        if value is None or self._version(value)!=selected:raise TransferError('media_backup_stale_selection')
        return value

    def selected_mapping(self,selected):
        if type(selected) is not NativeMediaBackupVersion:raise TransferError('media_backup_native_selection_required')
        with self._operation():
            value=self._selected_version(selected)
            if 'source' in value:raise TransferError('media_backup_source_version_has_no_saved_mapping')
            association=value['mapping']['association']
            return NativeSavedPhotoMapping.parse(value['mapping'],PhotoMappingAssociation(**association),selected.id)

    def _restore_lineage(self,selected):
        if type(selected) is not NativeMediaBackupVersion:raise TransferError('media_backup_native_selection_required')
        with self._operation():
            value=self._selected_version(selected)
            if 'source' not in value:
                mapping=NativeSavedPhotoMapping.parse(value['mapping'],PhotoMappingAssociation(**value['mapping']['association']),selected.id)
                return mapping,mapping.saved_size,mapping.saved_sha256,None
            source=value['source']
            mapping=NativeSavedPhotoMapping.parse(source['original_mapping'],PhotoMappingAssociation(**source['original_mapping']['association']),
                source['original_mapping_sha256'])
            from magnolie_file_transfer import FileManifest
            file=FileManifest.parse(source['manifest']).files[0]
            return mapping,file.size,file.sha256,copy.deepcopy(value)

    def restore(self, selected, candidate_fd):
        if type(selected) is not NativeMediaBackupVersion: raise TransferError('media_backup_native_selection_required')
        with self._operation():
            value = self._selected_version(selected)
            obj = self._record('objects', selected.object_key)
            if obj is None: raise TransferError('media_backup_original_object_required')
            # Only an explicitly selected, freshly verified pending intent may
            # read a complete prepared object. Do not migrate the catalog here.
            if obj['prepared'] and self._record('versions',selected.id) is None:obj=dict(obj,prepared=False)
            representation = self._verify_object(obj)
            with self._object(obj) as fd:
                return restore_to_new_file(fd, candidate_fd, representation, self._current)

    def compress_one(self, object_key, idle, retention):
        if type(idle) is not NativeBackupIdlePermit or type(retention) is not NativeMediaRetentionPermit:
            raise TransferError('media_backup_native_maintenance_required')
        def current(): self._current(); idle.require_current(); retention.require_current()
        with self._operation():
            current(); obj = self._record('objects', object_key)
            if obj is None: raise TransferError('media_backup_original_object_required')
            if any(self._pending(key)['object_key']==object_key for key,_ in self._pending_members()):
                return False # Pending lineage pins bytes against maintenance.
            refs = [self._record('versions', key) for key, _ in self._members('versions')]
            refs = [ref for ref in refs if ref['object_key'] == object_key]
            if not refs: raise TransferError('media_backup_original_version_required')
            if any('source' in ref for ref in refs):return False # Source lifecycle has no retirement authority yet.
            now = self._clock(); newest = max(ref['saved_ms'] for ref in refs)
            if obj['codec'] == 'raw':
                if obj['prepared']: raise TransferError('media_backup_object_not_complete')
                if (obj['trial'] or not compression_due(newest, now, retention.days)
                        or retention.days and now - newest >= retention.days * 86400000): return False
                if obj['candidate'] is None:
                    free = os.fstatvfs(self._root)
                    if free.f_bavail * free.f_frsize < obj['size'] + 1024**3: raise TransferError('media_backup_insufficient_space')
                    name = 'object-' + object_key + '-' + secrets.token_hex(16) + '.xz'
                    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._root)
                    try:
                        obj = dict(obj, candidate=dict(name=name, key=list(self._key(os.fstat(fd)))))
                        self._commit(obj=obj)
                    finally: os.close(fd)
                name = obj['candidate']['name']
                candidate = dict(obj, name=name, key=obj['candidate']['key'])
                with self._object(candidate, writable=True) as fd:
                    # This is only the protected unpublished candidate, never
                    # the raw/shared object or a mutable user file.
                    current(); os.ftruncate(fd, 0)
                    with self._object(obj) as source:
                        result = compress_candidate(source, fd, obj['size'], obj['sha256'], idle.scoped(current), extra_bytes=16384)
                    current()
                    if result is None:
                        os.ftruncate(fd, 0); os.fsync(fd)
                        obj = dict(obj, trial=True); self._commit(obj=obj); return False
                    compressed = dict(obj, codec='xz', name=name, key=list(result.file_key), stored_size=result.stored_size,
                        stored_sha256=result.stored_sha256, trial=True, candidate=None)
                    current(); self._commit(obj=compressed); obj = compressed
            self._verify_object(obj); current()
            if not obj['raw_retired']:
                with self._object(obj, raw=True, writable=True) as raw:
                    if os.fstat(raw).st_size:
                        verify_raw(raw, obj['size'], obj['sha256'], current, candidate=True)
                        current(); os.ftruncate(raw, 0); os.fsync(raw)
                    current()
                    if os.fstat(raw).st_size != 0: raise TransferError('media_backup_retirement_not_proven')
                self._commit(obj=dict(obj, raw_retired=True))
            return True

    def compression_candidates(self,days):
        """Bounded metadata-only scheduling; never byte or retention authority."""
        with self._operation():
            if type(days) is not int or days not in (0,90,365):return ()
            pinned={self._pending(key)['object_key'] for key,_ in self._pending_members()}
            newest={}
            for key,_ in self._members('versions'):
                version=self._record('versions',key)
                if 'source' in version:pinned.add(version['object_key'])
                newest[version['object_key']]=max(newest.get(version['object_key'],0),version['saved_ms'])
            result=[];now=self._clock()
            for key,saved in newest.items():
                if key in pinned or not compression_due(saved,now,days) or days and now-saved>=days*86400000:continue
                obj=self._record('objects',key)
                if obj is None:raise TransferError('media_backup_original_object_required')
                if obj['prepared'] or obj['codec']=='raw' and obj['trial'] or obj['codec']=='xz' and obj['raw_retired']:continue
                result.append((saved,key,obj['size']))
            return tuple((key,size) for _,key,size in sorted(result))

    def close(self):
        if self._closed: return
        if not self._gate.acquire(blocking=False): raise TransferError('media_backup_worker_busy')
        try:
            self._closed = True
            try:
                if self._db is not None: self._db.close()
            finally:
                self._db = None
                for field in ('_dbfile', '_lock', '_root', '_parent'):
                    fd = getattr(self, field, None)
                    if fd is not None: os.close(fd); setattr(self, field, None)
        finally: self._gate.release()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class NativeMediaBackupMaintenance:
    """One bounded caller-owned idle pass, no timer/thread/network/bootstrap.

    Rotation is in-memory and carries no deletion/inventory authority. A missing
    or offline catalog is held independently, never considered empty or reset.
    """
    MAX_SOURCES=16
    MAX_INPUT_BYTES=400*1024**2
    MAX_SECONDS=60

    def __init__(self,directory,*,clock=time.monotonic):
        self.directory=directory;self.clock=clock;self._cursor=0;self._gate=threading.Lock()

    def run_once(self,idle,current=lambda:True):
        if type(idle) is not NativeBackupIdlePermit or not callable(current):
            raise TransferError('media_backup_native_maintenance_required')
        if not self._gate.acquire(blocking=False):raise TransferError('media_backup_worker_busy')
        try:
            started=self.clock()
            def active():
                now=self.clock()
                if now<started or now-started>=self.MAX_SECONDS or current() is not True:
                    raise TransferError('media_backup_maintenance_ended')
                idle.require_current();return True
            active()
            sources=NativeMediaBackupRecoveryUi(self.directory,active).sources()
            result=dict(checked=0,attempted=0,compressed=0,held=0)
            if not sources:return result
            from magnolie_media_retention import NativeMediaRetention
            with NativeMediaRetention(self.directory) as policy:
                for _ in range(min(self.MAX_SOURCES,len(sources))):
                    active();row=sources[self._cursor%len(sources)];self._cursor=(self._cursor+1)%len(sources)
                    result['checked']+=1
                    with policy.permit(active) as retention:
                        if retention is None:return result
                        if retention.days not in (0,90,365):return result
                        recovery=NativeMediaBackupRecoveryUi(self.directory,active)
                        try:
                            with recovery._source(row['scope'],row['source_id']) as (locations,default):
                                with locations._history(default,row['source_id']) as backups:
                                    for key,size in backups.compression_candidates(retention.days):
                                        active()
                                        if size>self.MAX_INPUT_BYTES:continue
                                        result['attempted']+=1
                                        if backups.compress_one(key,idle,retention):result['compressed']+=1
                                        return result # At most one actual trial per pass.
                        except Exception:
                            active();result['held']+=1 # Preserve offline/corrupt originals, no repair or fallback.
            return result
        finally:self._gate.release()
