"""Derived saved-book retention policy, never a phone/content permission.

Only the existing private phone.db/meta and storage.key are used. A paused
record is durable BEFORE saving a changed book; postcommit publication uses
the exact pause token. A failed publication leaves cleanup disabled.
"""
from contextlib import contextmanager
from hashlib import sha256
import fcntl
import os
from pathlib import Path
import secrets
import sqlite3
import time

from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError
from magnolie_media_trash import NativeMediaRetentionPermit
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_telefon import canonical,strict_json


class NativeMediaBackupCopyPermit:
    """Active local-copy book witness; never a purge/compression permit."""
    def __init__(self,book_version,current):
        if (type(book_version) is not str or len(book_version)!=64 or any(c not in '0123456789abcdef' for c in book_version)
                or not callable(current)):raise TransferError('media_retention_lease_changed')
        self.book_version=book_version;self._current=current;self._revoked=False

    def require_current(self):
        try:allowed=self._current()
        except BaseException:
            self._revoked=True;raise
        if self._revoked or allowed is not True:
            self._revoked=True;raise TransferError('media_retention_lease_changed')
        return True

    @property
    def grants_write_authority(self):return False


class NativeMediaRetention:
    KEY='media_trash_retention:local:v1'
    DOMAIN='media-trash-retention-v1/local'
    MAX_ACTIVE_COPY_SECONDS=2*60*60

    def __init__(self,native_directory):
        self._protection=ExistingFileTransferProtection(native_directory)
        self._fd=None;self._db=None;self._activity_held=False
        try:
            root=Path(self._protection.native_directory)
            self._fd=os.open(root/'phone.db',os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
            self._identity=self._protection._key(os.fstat(self._fd))
            self._path=root/'phone.db';self._fresh()
            self._db=sqlite3.connect(self._path.as_uri()+'?mode=rw',uri=True,timeout=5)
            self._db.execute('PRAGMA synchronous=FULL')
            if self._db.execute('PRAGMA table_info(meta)').fetchall()!=[
                    (0,'key','TEXT',0,None,1),(1,'value','BLOB',1,None,0)]:
                raise TransferError('media_retention_existing_meta_required')
            self._fresh()
        except BaseException:
            self.close();raise

    def _fresh(self):
        self._protection._read_key()
        held=os.fstat(self._fd);named=os.stat(self._path,follow_symlinks=False)
        ProtectedPhotoPreferences._private(held);ProtectedPhotoPreferences._private(named)
        if self._protection._key(held)!=self._identity or self._protection._key(named)!=self._identity:
            raise TransferError('media_retention_database_changed')

    @contextmanager
    def _transaction(self):
        self._fresh();self._db.execute('BEGIN IMMEDIATE')
        try:
            self._fresh();yield;self._fresh();self._db.commit()
        except BaseException:
            self._db.rollback();raise

    def _read(self):
        self._fresh()
        row=self._db.execute('SELECT value FROM meta WHERE key=?',(self.KEY,)).fetchone()
        if row is None:return None
        value=strict_json(self._protection.unseal(row[0],self.DOMAIN))
        if (type(value) is not dict or set(value)!={'format','token','days','book_sha256','book_file'}
                or type(value['format']) is not int or value['format']!=1
                or type(value['token']) is not str or len(value['token'])!=64
                or any(char not in '0123456789abcdef' for char in value['token'])
                or value['days'] is not None and (type(value['days']) is not int or value['days'] not in (0,7,30,90,365))
                or value['book_sha256'] is not None and (type(value['book_sha256']) is not str
                    or len(value['book_sha256'])!=64 or any(char not in '0123456789abcdef' for char in value['book_sha256']))
                or (value['days'] is None)!=(value['book_sha256'] is None)
                or (value['days'] is None)!=(value['book_file'] is None)
                or value['book_file'] is not None and (type(value['book_file']) is not list or len(value['book_file'])!=9
                    or any(type(number) is not int or number<0 for number in value['book_file']))):
            raise TransferError('media_retention_invalid_policy')
        self._fresh();return value

    def _book_file(self):
        # Also fence archive restore, re-encryption and other writers that do
        # not use the UI save queue. No changed book may inherit cached days.
        self._fresh()
        path=Path(self._protection.native_directory).parent/'daten.json'
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        try:
            held=os.fstat(fd);named=os.stat(path,follow_symlinks=False)
            ProtectedPhotoPreferences._private(held);ProtectedPhotoPreferences._private(named)
            signature=self._protection._signature(held)
            if self._protection._signature(named)!=signature:raise TransferError('media_retention_book_changed')
            self._fresh();return list(signature)
        finally:os.close(fd)

    def _write(self,value):
        blob=self._protection.seal(canonical(value),self.DOMAIN)
        self._db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(self.KEY,blob))
        if self._read()!=value:raise TransferError('media_retention_readback_failed')

    def pause(self):
        with self._transaction():
            self._read() # Never overwrite an unauthenticated/corrupt policy.
            token=secrets.token_hex(32)
            self._write(dict(format=1,token=token,days=None,book_sha256=None,book_file=None))
        return token

    def publish_saved(self,token,saved_book):
        # The caller supplies its already committed native book, not a bridge
        # request carrying an independent retention value.
        settings=saved_book.get('einstellungen',{}) if type(saved_book) is dict else {}
        trash=settings.get('papierkorb',{}) if type(settings) is dict else {}
        days=trash.get('tage') if type(trash) is dict else None
        if type(days) is not int or days not in (0,7,30,90,365):
            raise TransferError('media_retention_saved_setting_required')
        with self._transaction():
            current=self._read()
            if current is None or current['token']!=token or current['days'] is not None:
                raise TransferError('media_retention_save_superseded')
            self._write(dict(format=1,token=token,days=days,book_sha256=sha256(canonical(saved_book)).hexdigest(),
                book_file=self._book_file()))

    def adopt_existing_saved(self,decode_book=None,current=lambda:True):
        """First adoption only, from the actual fixed native file, never the UI.

        Do not revive a deliberately paused policy after a failed save, or guess
        policy for an externally replaced book. Encrypted books require the
        native unlocked owner's decoder; an unattended first read stays HOLD.
        """
        with self._transaction():
            if self._read() is not None:return False
            if current() is not True:raise TransferError('media_retention_lease_changed')
            try:signature=self._book_file()
            except FileNotFoundError:return False
            path=Path(self._protection.native_directory).parent/'daten.json'
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as source:
                if list(self._protection._signature(os.fstat(source.fileno())))!=signature:
                    raise TransferError('media_retention_book_changed')
                # Large/uncertain first adoption is held, never treated as empty.
                if signature[2]>64*1024*1024:raise TransferError('media_retention_book_read_bound')
                raw=source.read(64*1024*1024+1)
                if len(raw)!=signature[2] or self._book_file()!=signature:
                    raise TransferError('media_retention_book_changed')
            saved=decode_book(raw.decode('utf-8')) if decode_book is not None else strict_json(raw)
            if type(saved) is not dict:raise TransferError('media_retention_saved_setting_required')
            settings=saved.get('einstellungen',{})
            trash=settings.get('papierkorb',{}) if type(settings) is dict else {}
            days=trash.get('tage') if type(trash) is dict else None
            if type(days) is not int or days not in (0,7,30,90,365):return False
            if current() is not True or self._book_file()!=signature:
                raise TransferError('media_retention_lease_changed')
            self._write(dict(format=1,token=secrets.token_hex(32),days=days,
                book_sha256=sha256(canonical(saved)).hexdigest(),book_file=signature))
            return True

    @contextmanager
    def activity(self,current=lambda:True,*,exclusive=False):
        """Cross-process media activity on the EXISTING native phone DB inode.

        flock is independent of SQLite byte-range locks: an active copy never
        holds a DB transaction and concurrent saved-book writers can retire it.
        No extra lock path/key/metadata or missing-lock bootstrap is needed.
        Maintenance uses exclusive admission; copies/sync use shared admission.
        """
        if self._activity_held or type(exclusive) is not bool or not callable(current):
            raise TransferError('media_retention_activity_owner_required')
        self._fresh()
        if current() is not True:raise TransferError('media_retention_lease_changed')
        try:fcntl.flock(self._fd,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
        except BlockingIOError:
            yield None;return
        self._activity_held=True;active=[True]
        def require():
            if not active[0] or not self._activity_held:raise TransferError('media_retention_activity_ended')
            self._fresh()
            if current() is not True:raise TransferError('media_retention_lease_changed')
            return True
        try:
            require();yield require
        finally:
            active[0]=False;self._activity_held=False
            fcntl.flock(self._fd,fcntl.LOCK_UN)

    @contextmanager
    def active_copy_permit(self,current):
        """Recheck the actual saved book without holding a DB writer lock.

        Backup/recovery only creates a new file; unlike destructive cleanup it does not
        need to serialize every other phone/book write behind the entire copy.
        Any pause/save/root/lock-owner change retires the captured witness.
        """
        with self.activity(current) as activity:
            if activity is None:raise TransferError('media_retention_maintenance_busy')
            with self._active_copy_permit(activity) as permit:yield permit

    @contextmanager
    def _active_copy_permit(self,current):
        value=self._read()
        if value is None or value['days'] is None:
            yield None;return
        started=time.monotonic();deadline=started+self.MAX_ACTIVE_COPY_SECONDS
        def require():
            now=time.monotonic()
            if (now<started or now>=deadline or current() is not True or self._read()!=value
                    or self._book_file()!=value['book_file']):raise TransferError('media_retention_lease_changed')
            return True
        require()
        yield NativeMediaBackupCopyPermit(sha256(canonical(value)).hexdigest(),require)

    def saved_book_version(self):
        """Immutable witness, revalidated using each I/O thread's own DB owner.

        This is not an activity lease or write/deletion permission.
        """
        value=self._read()
        if value is None or value['days'] is None:
            raise TransferError('media_backup_current_saved_book_required')
        if self._book_file()!=value['book_file']:
            raise TransferError('media_retention_book_changed')
        return sha256(canonical(value)).hexdigest()

    @contextmanager
    def permit(self,current=lambda:True):
        with self.activity(current,exclusive=True) as activity:
            if activity is None:
                yield None;return
            with self._maintenance_permit(activity) as permit:yield permit

    @contextmanager
    def _maintenance_permit(self,current):
        # One purge at a time under SQLite's cross-process writer lease. A save
        # cannot publish/commit a new policy while these bytes are being released.
        deadline=time.monotonic()+60
        with self._transaction():
            value=self._read()
            if value is None or value['days'] is None:
                yield None;return
            if self._book_file()!=value['book_file']:
                raise TransferError('media_retention_book_changed')
            def days():
                if (time.monotonic()>=deadline or current() is not True or self._read()!=value
                        or self._book_file()!=value['book_file']):
                    raise TransferError('media_retention_lease_changed')
                return value['days']
            yield NativeMediaRetentionPermit(value['days'],days)

    def close(self):
        if self._db is not None:self._db.close();self._db=None
        if self._fd is not None:os.close(self._fd);self._fd=None
        self._protection.close()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()


@contextmanager
def saved_book_retention(native_directory,saved_book):
    """Pause before native commit; derived failure never undoes a saved book."""
    result={}
    try:policy=NativeMediaRetention(native_directory)
    except FileNotFoundError:
        # A withdrawn key beside an existing policy DB cannot be treated as an
        # unconfigured installation: restoring that key could revive old days.
        if os.path.lexists(Path(native_directory)/'phone.db'):raise
        yield result;return # No phone root/key/database creation just for settings.
    try:
        token=policy.pause()
        yield result
        try:policy.publish_saved(token,saved_book)
        except Exception as error:result['repair_error']=type(error).__name__
    finally:policy.close()


def maintain_native_media_trash(native_directory,current=lambda:True):
    """Serial caller-owned maintenance; no worker, network request or bootstrap.

    At most 16 operations / 400 MiB per invocation. An unknown scope holds the
    run instead of inventing an empty history. Never/manual skips byte release.
    """
    from magnolie_media_trash_ui import NativeMediaTrashUi
    view=NativeMediaTrashUi(native_directory,current)
    scopes=view._scopes()
    if not scopes:return 0
    completed=0;admitted=0;total=0
    try:policy=NativeMediaRetention(native_directory)
    except FileNotFoundError:return 0
    with policy:
        policy.adopt_existing_saved(current=view._current)
        for scope in scopes:
            with view._owner(scope) as owner:
                snapshot,entries=owner.read()
                for entry in entries:
                    if entry.state not in ('trashed','purge_prepared'):continue
                    with policy.permit(view._current) as permit:
                        if permit is None:return completed
                        if entry.state!='purge_prepared' and not entry.expired(permit.days,owner._wall_clock_ms()):continue
                        if admitted>=16 or total+entry.mapping.saved_size>400*1024*1024:return completed
                        admitted+=1;total+=entry.mapping.saved_size
                        snapshot,result=owner.purge_expired(owner.issue_action(),snapshot,entry.operation,permit)
                        if result.state=='purged':completed+=1
    return completed
