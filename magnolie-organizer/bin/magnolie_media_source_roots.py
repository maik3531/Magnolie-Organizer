"""Protected append-only Linux source selections (#429), never SEND authority.

Uses the existing descriptor-bound AEAD/SQLite settings storage in its own
namespace. A current native action and held read-only root are required for
selection. No picker, automatic scan, receiving grant or file source is created.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from hashlib import sha256
import os
import secrets
import threading

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_control import _hex, MAX_REVISION
from magnolie_file_transfer import TransferError
from magnolie_media_source_collection import NativeCollectionRoot, _signature
from magnolie_photo_destination import NativePhotoDestinationAction, require_media_directory
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_telefon import canonical


@dataclass(frozen=True)
class NativeMediaCollectionRootRecord:
    id: str
    version: str
    media_type: str
    pairing_epoch: str
    directory: NativeAcceptedDestination
    key: tuple
    birthtime: tuple
    mount_id: int

    @property
    def grants_send_authority(self):return False

    def wire(self):
        return dict(format=1,id=self.id,version=self.version,media_type=self.media_type,pairing_epoch=self.pairing_epoch,
            directory=self.directory.wire(),key=list(self.key),birthtime=list(self.birthtime),mount_id=self.mount_id)

    @classmethod
    def parse(cls, value):
        if (type(value) is not dict or set(value)!={'format','id','version','media_type','pairing_epoch','directory','key','birthtime','mount_id'}
                or type(value['format']) is not int or value['format']!=1 or type(value['id']) is not str
                or len(value['id'])!=32 or not _hex(value['id']*2) or not _hex(value['version']) or not _hex(value['pairing_epoch'])
                or value['media_type'] not in ('images','videos') or type(value['key']) is not list or len(value['key'])!=2
                or any(type(n) is not int or n<0 for n in value['key']) or type(value['birthtime']) is not list or len(value['birthtime'])!=2
                or any(type(n) is not int for n in value['birthtime']) or not 0<=value['birthtime'][1]<1_000_000_000
                or type(value['mount_id']) is not int or value['mount_id']<=0):
            raise TransferError('media_collection_root_record_invalid')
        directory=NativeAcceptedDestination.parse(value['directory']);require_media_directory(directory.path)
        if tuple(value['key'])!=directory.ancestor_keys[0]:raise TransferError('media_collection_root_record_invalid')
        return cls(value['id'],value['version'],value['media_type'],value['pairing_epoch'],directory,
            tuple(value['key']),tuple(value['birthtime']),value['mount_id'])


@dataclass(frozen=True)
class NativeMediaCollectionRootsSnapshot:
    version: str
    revision: int
    roots: tuple

    @property
    def grants_send_authority(self):return False


@dataclass(frozen=True)
class NativeMediaCollectionRootsWitness:
    """Original storage identity for a future independently protected composer.

    Not authority, a catalog snapshot, or permission to reconstruct lost data.
    """
    scope: str
    root_key: tuple
    database_key: tuple
    lock_key: tuple
    anchor_key: tuple
    anchor_sha256: str

    def wire(self):
        return dict(format=1,scope=self.scope,root_key=list(self.root_key),database_key=list(self.database_key),
            lock_key=list(self.lock_key),anchor_key=list(self.anchor_key),anchor_sha256=self.anchor_sha256)

    @classmethod
    def parse(cls,value):
        if (type(value) is not dict or set(value)!={'format','scope','root_key','database_key','lock_key','anchor_key','anchor_sha256'}
                or type(value['format']) is not int or value['format']!=1 or not _hex(value['scope']) or not _hex(value['anchor_sha256'])):
            raise TransferError('media_collection_roots_original_witness_required')
        for name in ('root_key','database_key','lock_key','anchor_key'):
            key=value[name]
            if type(key) is not list or len(key)!=2 or any(type(n) is not int or not 0<=n<2**64 for n in key) or not key[1]:
                raise TransferError('media_collection_roots_original_witness_required')
        return cls(value['scope'],tuple(value['root_key']),tuple(value['database_key']),tuple(value['lock_key']),
            tuple(value['anchor_key']),value['anchor_sha256'])

    @property
    def grants_send_authority(self):return False


class ProtectedMediaCollectionRoots(ProtectedPhotoPreferences):
    MAX_ROOTS=32
    MAX_RECORD_BYTES=256*1024
    MAX_DATABASE_BYTES=2*1024*1024

    def __init__(self, authority, *, original=None, **kwargs):
        super().__init__(authority,**kwargs)
        self._name='media-source-roots-v1-'+self._scope
        self._domain='magnolie-media-source-roots-v1/'+self._scope+'/'
        self._absent=sha256((self._domain+'absent').encode()).hexdigest()
        self._anchor=self._name+'.seal';self._anchor_identity=None
        if original is not None and (type(original) is not NativeMediaCollectionRootsWitness or
                NativeMediaCollectionRootsWitness.parse(original.wire())!=original or original.scope!=self._scope):
            raise TransferError('media_collection_roots_original_witness_required')
        self._original=original
        self._selection_io=threading.local()

    def _witness(self):
        if self._anchor_identity is None:raise TransferError('media_collection_roots_original_witness_required')
        return NativeMediaCollectionRootsWitness(self._scope,self._root_key,self._db_key,self._lock_key,*self._anchor_identity)

    def _anchor_value(self, anchor_key):
        return dict(format=1,subject=self._subject,root_key=list(self._root_key),
            database_key=list(self._db_key),lock_key=list(self._lock_key),anchor_key=list(anchor_key))

    def _check_anchor(self):
        fd=os.open(self._anchor,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=self._parent_fd)
        try:
            before=os.fstat(fd);self._private(before)
            if not 28<=before.st_size<=8192:raise TransferError('media_collection_root_anchor_changed')
            blob=os.pread(fd,before.st_size+1,0);after=os.fstat(fd)
            named=os.stat(self._anchor,dir_fd=self._parent_fd,follow_symlinks=False);self._private(named)
            if len(blob)!=before.st_size or _signature(before)!=_signature(after) or _signature(before)!=_signature(named):
                raise TransferError('media_collection_root_anchor_changed')
            if self._protection().unseal(blob,self._domain+'anchor')!=canonical(self._anchor_value(self._key(before))):
                raise TransferError('media_collection_root_anchor_changed')
            identity=self._key(before),sha256(blob).hexdigest()
            if self._anchor_identity is not None and identity!=self._anchor_identity:
                raise TransferError('media_collection_root_anchor_changed')
            self._anchor_identity=identity
        finally:os.close(fd)

    def _fresh(self):
        super()._fresh()
        if self._anchor_identity is not None:
            self._check_anchor()
            if self._original is not None and self._witness()!=self._original:
                raise TransferError('media_collection_roots_original_witness_required')

    def _open(self, *, create=False, validate=lambda:None):
        self._peer()
        parent=os.open(self._native_directory(),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            if self._key(os.fstat(parent))!=self._protection().native_directory_identity:
                raise TransferError('media_collection_root_native_storage_changed')
            def exists(name):
                try:os.stat(name,dir_fd=parent,follow_symlinks=False);return True
                except FileNotFoundError:return False
            present,anchored=exists(self._name),exists(self._anchor)
            if present!=anchored or not present and (self._anchor_identity is not None or self._original is not None):
                raise TransferError('media_collection_root_original_catalog_required')
            if not present and not create:return False
            result=super()._open(create=create,validate=validate)
            if not present:
                validate();self._fresh()
                fd=os.open(self._anchor,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
                with os.fdopen(fd,'wb') as stream:
                    blob=self._protection().seal(canonical(self._anchor_value(self._key(os.fstat(stream.fileno())))),self._domain+'anchor')
                    stream.write(blob);stream.flush();os.fsync(stream.fileno())
                os.fsync(parent)
            self._check_anchor();self._fresh();return result
        finally:os.close(parent)

    def _initial_owner(self):return dict(revision=1,roots_sha256=None)

    def _require_external_path(self, directory):
        # Never inventory this authority's private key/catalog tree, including
        # through a broad ancestor selection. Source roots are not store roots.
        private=self._native_directory()
        if os.path.commonpath((directory.path,private)) in (directory.path,private):
            raise TransferError('media_collection_roots_private_storage_excluded')

    def _snapshot(self):
        owners=self._db.execute('SELECT id,payload FROM owner').fetchall();rows=self._db.execute('SELECT id,payload FROM policy').fetchall()
        if len(owners)!=1 or owners[0][0]!=1 or len(rows)>1 or rows and rows[0][0]!=1:
            raise TransferError('media_collection_roots_invalid_rows')
        head=self._unprotect(owners[0][1],'owner')
        if not rows:
            if head!=self._initial_owner():raise TransferError('media_collection_roots_missing_record')
            result=NativeMediaCollectionRootsSnapshot(self._absent,1,())
        else:
            version=sha256(rows[0][1]).hexdigest();body=self._unprotect(rows[0][1],'roots')
            if (type(body) is not dict or set(body)!={'revision','roots'} or type(body['revision']) is not int
                    or not 2<=body['revision']<=MAX_REVISION or type(body['roots']) is not list or not 1<=len(body['roots'])<=self.MAX_ROOTS
                    or head!=dict(revision=body['revision'],roots_sha256=version)):
                raise TransferError('media_collection_roots_invalid_record')
            roots=tuple(NativeMediaCollectionRootRecord.parse(item) for item in body['roots'])
            for selected in roots:self._require_external_path(selected.directory)
            if (len({r.id for r in roots})!=len(roots) or len({(r.media_type,r.key) for r in roots})!=len(roots)):
                raise TransferError('media_collection_roots_ambiguous_selection')
            result=NativeMediaCollectionRootsSnapshot(version,body['revision'],roots)
        mark=result.revision,result.version
        if self._last is not None and (mark[0]<self._last[0] or mark[0]==self._last[0] and mark[1]!=self._last[1]):
            self._uncertain=True;raise TransferError('media_collection_roots_rollback')
        self._last=mark;return result

    def read(self):
        with self._operation():
            if not self._open():return NativeMediaCollectionRootsSnapshot(self._absent,1,())
            with self._locked():self._schema();return self._snapshot()

    def witness(self):
        with self._operation():
            if not self._open():raise TransferError('media_collection_roots_original_witness_required')
            with self._locked():self._schema();self._snapshot();return self._witness()

    def add(self, action, expected, root, media_type):
        if type(action) is not NativePhotoDestinationAction:raise TransferError('media_collection_roots_native_action_required')
        action.consume(self)
        if type(expected) is not NativeMediaCollectionRootsSnapshot or type(root) is not NativeCollectionRoot or media_type not in ('images','videos'):
            raise TransferError('media_collection_roots_native_selection_required')
        original=(root._directory,root.key,root.birthtime,root.mount_id)
        epoch=self._peer().pairing_epoch
        def validate():
            action.validate(self);root._require();self._require_external_path(root._directory)
            if self._peer().pairing_epoch!=epoch or original!=(root._directory,root.key,root.birthtime,root.mount_id):
                raise TransferError('media_collection_roots_original_selection_required')
        with self._operation():
            # The primitive root's gate keeps close from racing native checks.
            with root._gate:
                validate();self._open(create=True,validate=validate)
                with self._locked():
                    self._schema();current=self._snapshot()
                    if current.version!=expected.version:raise TransferError('media_collection_roots_cas_conflict')
                    same=[r for r in current.roots if r.media_type==media_type and r.key==root.key]
                    if same:
                        selected=same[0]
                        if (selected.directory,selected.key,selected.birthtime,selected.mount_id)!=original or selected.pairing_epoch!=epoch:
                            raise TransferError('media_collection_roots_reassociation_required')
                        validate();return current
                    # A reused native path must not silently replace its old root.
                    if any(r.directory.path==root._directory.path for r in current.roots if r.key!=root.key):
                        raise TransferError('media_collection_roots_reassociation_required')
                    if len(current.roots)>=self.MAX_ROOTS or current.revision>=MAX_REVISION:
                        raise TransferError('media_collection_roots_capacity')
                    selected=NativeMediaCollectionRootRecord(secrets.token_hex(16),secrets.token_hex(32),media_type,epoch,*original)
                    body=dict(revision=current.revision+1,roots=[r.wire() for r in (*current.roots,selected)])
                    blob=self._protect(body,'roots');version=sha256(blob).hexdigest()
                    head=self._protect(dict(revision=body['revision'],roots_sha256=version),'owner')
                    try:
                        self._db.execute('BEGIN IMMEDIATE')
                        self._db.execute('INSERT OR REPLACE INTO policy VALUES(1,?)',(blob,))
                        self._db.execute('UPDATE owner SET payload=? WHERE id=1',(head,))
                        self._fresh();validate();self._db.commit();self._sync()
                        result=self._snapshot();validate();return result
                    except BaseException:
                        if self._db.in_transaction:self._db.rollback()
                        self._uncertain=True;raise

    @contextmanager
    def selected_root_lease(self,selected):
        """Pin authenticated membership while bounded source IO actually runs.

        The native lock excludes catalog writers; raw DB signature checks still
        detect writes bypassing that lock. No cached permission crosses leases.
        """
        if type(selected) is not NativeMediaCollectionRootRecord:
            raise TransferError('media_collection_roots_original_selection_required')
        with self._operation():
            if not self._open():raise TransferError('media_collection_roots_original_selection_required')
            with self._locked():
                self._schema();snapshot=self._snapshot()
                if selected not in snapshot.roots or self._peer().pairing_epoch!=selected.pairing_epoch:
                    raise TransferError('media_collection_roots_original_selection_required')
                signature=_signature(os.fstat(self._db_fd));thread=threading.get_ident()
                def current():
                    if getattr(self._selection_io,'permit',None) is not permit or threading.get_ident()!=thread:
                        raise TransferError('media_collection_roots_live_selection_lease_required')
                    self._fresh()
                    if _signature(os.fstat(self._db_fd))!=signature:
                        raise TransferError('media_collection_roots_original_membership_changed')
                    return True
                permit=(selected,current);self._selection_io.permit=permit
                try:current();yield current;current()
                finally:self._selection_io.permit=None

    def open_root(self, selected, native_current):
        if type(selected) is not NativeMediaCollectionRootRecord or not callable(native_current):
            raise TransferError('media_collection_roots_original_selection_required')
        def current():
            if native_current() is False:raise TransferError('media_collection_roots_native_owner_revoked')
            permit=getattr(self._selection_io,'permit',None)
            if permit is not None and permit[0]==selected:permit[1]()
            else:
                snapshot=self.read()
                if selected not in snapshot.roots or self._peer().pairing_epoch!=selected.pairing_epoch:
                    raise TransferError('media_collection_roots_original_selection_required')
        current();root=NativeCollectionRoot(selected.directory.path,current)
        try:
            if (root._directory,root.key,root.birthtime,root.mount_id)!=(selected.directory,selected.key,selected.birthtime,selected.mount_id):
                raise TransferError('media_collection_roots_original_generation_required')
            root._require();return root
        except BaseException:root.close();raise
