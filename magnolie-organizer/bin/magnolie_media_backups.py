"""Native, content-addressed LOCAL media backup catalog (#392).

Immutable version references share verified private content objects, never
hardlinks to editable originals. This is not a remote deletion handler. Restore
only prepares a new file; the native publication/mapping owner remains required.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
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
from magnolie_photo_mappings import ProtectedPhotoMappings, NativeSavedPhotoMapping, PhotoMappingAssociation
from magnolie_photo_destination import require_media_directory
from magnolie_photo_preferences import ProtectedPhotoPreferences
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
    def issue_action(self):return self._store.issue_action()
    def choose(self,action,expected,default,parent):return self._store.choose(action,expected,default,parent)
    def close(self):return self._store.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


@dataclass(frozen=True)
class NativeMediaBackupVersion:
    id: str
    object_key: str
    saved_ms: int
    name: str
    record_sha256: str

    @property
    def grants_write_authority(self): return False


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
        try:
            self._require_native(); self.storage_parent.verify()
            if create:require_media_directory(self.storage_parent.path)
            self._parent = os.open(self.storage_parent.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            if self._key(os.fstat(self._parent)) != self.storage_parent.ancestor_keys[0]:
                raise TransferError('media_backup_original_parent_required')
            if create:
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
        blob = self.protection.seal(canonical(body), self._domain + 'membership')
        self._db.execute("INSERT OR REPLACE INTO meta VALUES('membership',?)", (blob,))

    def _verify(self):
        if tuple(row[0] for row in self._db.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name")) != tuple(sorted(self.SCHEMA, key=lambda sql: sql.split()[2])):
            raise TransferError('media_backup_schema_changed')
        lengths = self._db.execute('SELECT name,length(sealed) FROM meta LIMIT 2').fetchall()
        if len(lengths) != 1 or lengths[0][0] != 'membership' or not 28 <= lengths[0][1] <= self.MAX_MEMBERSHIP_BYTES:
            raise TransferError('media_backup_membership_required')
        rows = self._db.execute('SELECT name,sealed FROM meta LIMIT 2').fetchall()
        if len(rows) != 1 or rows[0][0] != 'membership': raise TransferError('media_backup_membership_required')
        blob = rows[0][1]; value = strict_json(self.protection.unseal(blob, self._domain + 'membership'))
        if (type(value) is not dict or set(value) != {'format', 'revision', 'versions', 'objects'} or type(value['format']) is not int or value['format'] != 1
                or type(value['revision']) is not int or not 1 <= value['revision'] <= 2**53 - 1
                or value['versions'] != self._members('versions') or value['objects'] != self._members('objects')):
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
            if (set(value) != {'id', 'object_key', 'saved_ms', 'name', 'mapping'} or not _hex(key)
                    or type(value['saved_ms']) is not int or not 0 < value['saved_ms'] <= 253402300799999):
                raise TransferError('media_backup_record_invalid')
            association = PhotoMappingAssociation(**value['mapping']['association'])
            mapping = NativeSavedPhotoMapping.parse(value['mapping'], association, key)
            if value['object_key'] != content_key(mapping.saved_size, mapping.saved_sha256) or value['name'] != mapping.relative_path:
                raise TransferError('media_backup_record_invalid')
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

    def _commit(self, *, version=None, obj=None):
        revision = self._verify()
        try:
            self._db.execute('BEGIN IMMEDIATE'); self._current()
            for table, value in (('versions', version), ('objects', obj)):
                if value is not None:
                    blob = self.protection.seal(canonical(value), self._domain + table + '/' + value['id'])
                    verb = 'INSERT' if table == 'versions' else 'INSERT OR REPLACE'
                    self._db.execute(f'{verb} INTO {table} VALUES(?,?)', (value['id'], blob))
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
                before = self._record('versions', version_id)
                key = content_key(mapping.saved_size, mapping.saved_sha256); obj = self._record('objects', key)
                if obj is not None and not obj['prepared']: self._verify_object(obj)
                if before is not None:
                    if before['mapping'] != mapping.wire() or obj is None: raise TransferError('media_backup_original_mapping_changed')
                    return self._version(before)
                if len(self._members('versions')) >= self.MAX_VERSIONS: raise TransferError('media_backup_catalog_capacity')
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
                now = self._clock()
                if type(now) is not int or not 0 < now <= 253402300799999: raise TransferError('media_backup_invalid_clock')
                version = dict(id=version_id, object_key=key, saved_ms=now, name=mapping.relative_path, mapping=mapping.wire())
                mapping_now(); self._commit(version=version, obj=obj)
                self._verify_object(obj); return self._version(version)

    @staticmethod
    def _version(value):
        return NativeMediaBackupVersion(value['id'], value['object_key'], value['saved_ms'], value['name'], sha256(canonical(value)).hexdigest())

    def versions(self):
        with self._operation():
            return tuple(self._version(self._record('versions', key)) for key, _ in self._members('versions'))

    def restore(self, selected, candidate_fd):
        if type(selected) is not NativeMediaBackupVersion: raise TransferError('media_backup_native_selection_required')
        with self._operation():
            value = self._record('versions', selected.id)
            if value is None or self._version(value) != selected: raise TransferError('media_backup_stale_selection')
            obj = self._record('objects', selected.object_key)
            if obj is None: raise TransferError('media_backup_original_object_required')
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
            refs = [self._record('versions', key) for key, _ in self._members('versions')]
            refs = [ref for ref in refs if ref['object_key'] == object_key]
            if not refs: raise TransferError('media_backup_original_version_required')
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
