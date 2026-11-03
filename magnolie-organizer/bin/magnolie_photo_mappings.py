"""Protected historical source→saved-target mappings, never current write grants.

Reuse the existing native descriptor/SQLite/AEAD lifetime, in a separate store
and protection domain. Original/version records remain immutable; only a separate
authenticated head advances. No delete/move API or implicit reconciliation.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from hashlib import sha256
from pathlib import PurePosixPath
import threading

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_control import MAX_REVISION, _hex
from magnolie_file_media import correlate_media_pages
from magnolie_file_media_history import NativeMediaHistory
from magnolie_file_receive import NativeFileReceiveOperation
from magnolie_file_transfer import MAX_FILE_BYTES, TransferError, _portable_path
from magnolie_photo_destination import NativePhotoDestinationAction
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_photo_mapping_witness import PhotoMappingStoreWitness,NativePhotoMappingStoreChoice,PhotoMappingStoreCheckpoint
from magnolie_telefon import canonical


def photo_version_path(association, file):
    """Visible, deterministic no-replace target; never a replacement pathname."""
    if type(association) is not PhotoMappingAssociation or not _hex(file.sha256):
        raise TransferError('photo_mapping_invalid_version_target')
    suffix=PurePosixPath(file.path).suffix.lower()
    if suffix not in ('.jpg','.jpeg','.png','.gif','.webp','.heic','.heif','.avif','.bmp','.tif','.tiff','.dng','.mp4','.mov','.mkv','.webm'):suffix=''
    return 'Versionen/'+association.photo_id+'/'+file.sha256+suffix


@dataclass(frozen=True)
class PhotoMappingAssociation:
    source_epoch: str
    photo_id: str
    media_type: str

    def __post_init__(self):
        if not _hex(self.source_epoch) or not _hex(self.photo_id) or self.media_type not in ('images','video'):
            raise TransferError('photo_mapping_invalid_association')

    def wire(self):
        return dict(source_epoch=self.source_epoch,photo_id=self.photo_id,media_type=self.media_type)

    @property
    def key(self):
        return sha256(canonical(self.wire())).hexdigest()


@dataclass(frozen=True)
class PhotoMappingsSnapshot:
    version: str
    revision: int
    count: int
    associated: bool


@dataclass(frozen=True)
class NativeSavedPhotoMapping:
    association: PhotoMappingAssociation
    destination: NativeAcceptedDestination
    relative_path: str
    file_key: tuple
    parent_keys: tuple
    saved_size: int
    saved_sha256: str
    receipt_sha256: str
    manifest_sha256: str
    accepted_sha256: str
    source_file_id: str
    job_owner: str
    protected_record_sha256: str

    @property
    def grants_write_authority(self):return False

    @property
    def is_saved_receipt(self):return False # The referenced receipt is historical, not current file presence.

    def wire(self):
        return dict(format=1,association=self.association.wire(),destination=self.destination.wire(),relative_path=self.relative_path,
            file_key=list(self.file_key),parent_keys=[list(key) for key in self.parent_keys],saved_size=self.saved_size,
            saved_sha256=self.saved_sha256,receipt_sha256=self.receipt_sha256,manifest_sha256=self.manifest_sha256,
            accepted_sha256=self.accepted_sha256,source_file_id=self.source_file_id,job_owner=self.job_owner)

    @classmethod
    def parse(cls,value,association,record_hash):
        if (type(value) is not dict or set(value)!={'format','association','destination','relative_path','file_key','parent_keys',
                'saved_size','saved_sha256','receipt_sha256','manifest_sha256','accepted_sha256','source_file_id','job_owner'}
                or type(value['format']) is not int or value['format']!=1 or value['association']!=association.wire()
                or type(value['saved_size']) is not int or not 0<=value['saved_size']<=MAX_FILE_BYTES
                or any(not _hex(value[name]) for name in ('saved_sha256','receipt_sha256','manifest_sha256','accepted_sha256'))
                or not _hex(record_hash)):
            raise TransferError('photo_mapping_invalid_record')
        for name in ('source_file_id','job_owner'):
            if type(value[name]) is not str or len(value[name])!=32 or not _hex(value[name]*2):
                raise TransferError('photo_mapping_invalid_native_owner')
        _portable_path(value['relative_path'])
        destination=NativeAcceptedDestination.parse(value['destination'])
        parents=value['parent_keys']
        if type(parents) is not list or len(parents)!=len(value['relative_path'].split('/')):
            raise TransferError('photo_mapping_invalid_target_witness')
        for key in [value['file_key'],*parents]:
            if (type(key) is not list or len(key)!=2 or any(type(number) is not int or not 0<=number<2**64 for number in key) or key[1]==0):
                raise TransferError('photo_mapping_invalid_target_witness')
        if tuple(parents[0])!=destination.ancestor_keys[0] or value['file_key'][0]!=parents[-1][0]:
            raise TransferError('photo_mapping_original_target_changed')
        return cls(association,destination,value['relative_path'],tuple(value['file_key']),tuple(tuple(key) for key in parents),
            value['saved_size'],value['saved_sha256'],value['receipt_sha256'],value['manifest_sha256'],value['accepted_sha256'],
            value['source_file_id'],value['job_owner'],record_hash)


class ProtectedPhotoMappings(ProtectedPhotoPreferences):
    MAX_DATABASE_BYTES=64*1024*1024
    MAX_MAPPINGS=10_000
    _SCHEMA={
        'owner':'CREATE TABLE owner (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)',
        'mappings':'CREATE TABLE mappings (association TEXT PRIMARY KEY,payload BLOB NOT NULL)'}

    def __init__(self,authority,**kwargs):
        super().__init__(authority,**kwargs)
        self._name='photo-mappings-v1-'+self._scope
        self._domain='magnolie-photo-mappings-v1/'+self._scope+'/'
        self._absent=sha256((self._domain+'absent').encode()).hexdigest()
        self._validation_lease=None

    def _initial_owner(self):
        return dict(revision=1,count=0,mappings_sha256=sha256(b'').hexdigest(),pairing_epoch=self._peer().pairing_epoch)

    def _store_witness(self):
        self._fresh()
        return PhotoMappingStoreWitness(self._scope,self._root_key,self._db_key,self._lock_key)

    def bootstrap(self,action,expected):
        """Explicit native bootstrap only; never called from absent lookup."""
        if type(action) is not NativePhotoDestinationAction:raise TransferError('photo_mappings_native_action_required')
        action.consume(self)
        if type(expected) is not PhotoMappingsSnapshot:raise TransferError('photo_mappings_native_snapshot_required')
        with self._operation():
            self._open(create=True,validate=lambda:action.validate(self))
            with self._locked():
                self._schema();current=self._snapshot()
                if current.version!=expected.version:raise TransferError('photo_mappings_cas_conflict')
                if not current.associated:raise TransferError('photo_mappings_reassociation_required')
                action.validate(self);self._sync();witness=self._store_witness();action.validate(self)
                return NativePhotoMappingStoreChoice(witness,self)

    def verify_witness(self,witness):
        return self.checkpoint(witness).witness

    def checkpoint(self,witness):
        if type(witness) is not PhotoMappingStoreWitness:raise TransferError('photo_mapping_store_native_witness_required')
        PhotoMappingStoreWitness.parse(witness.wire())
        try:
            with self._operation():
                if not self._open():raise TransferError('photo_mapping_store_expected_missing')
                with self._locked():
                    self._schema();snapshot=self._snapshot()
                    if witness!=self._store_witness():raise TransferError('photo_mapping_store_original_changed')
                    if not snapshot.associated:raise TransferError('photo_mappings_reassociation_required')
                    self._sync();return PhotoMappingStoreCheckpoint(witness,self._last[1],snapshot.revision,snapshot.count)
        except Exception as error:
            if not isinstance(error,TransferError) or str(error) not in ('photo_preferences_busy','photo_preferences_closed_or_pending','photo_preferences_authority_changed'):
                self._uncertain=True
            raise

    def _require_checkpoint(self,minimum,current):
        if type(minimum) is not PhotoMappingStoreCheckpoint:raise TransferError('photo_mapping_store_native_checkpoint_required')
        PhotoMappingStoreCheckpoint.parse(minimum.wire())
        if (minimum.witness!=self._store_witness() or not current.associated or current.revision<minimum.revision
                or current.count<minimum.count or current.revision==minimum.revision and (self._last[1],current.count)!=(minimum.version,minimum.count)):
            self._uncertain=True
            raise TransferError('photo_mapping_store_checkpoint_changed')

    def verify_checkpoint(self,minimum):
        if type(minimum) is not PhotoMappingStoreCheckpoint:raise TransferError('photo_mapping_store_native_checkpoint_required')
        PhotoMappingStoreCheckpoint.parse(minimum.wire())
        current=self.checkpoint(minimum.witness)
        if (current.revision<minimum.revision or current.count<minimum.count
                or current.revision==minimum.revision and (current.version,current.count)!=(minimum.version,minimum.count)):
            self._uncertain=True;raise TransferError('photo_mapping_store_checkpoint_changed')
        return current

    def verify_choice(self,choice):
        if type(choice) is not NativePhotoMappingStoreChoice or choice.owner is not self:
            raise TransferError('photo_mapping_store_foreign_choice')
        return self.verify_witness(choice.witness)

    @contextmanager
    def _validated_metadata_io(self,action):
        """Exact held native metadata transaction, not a cached availability bit.
        Only its current thread may revalidate a receiver binding while this
        object's non-reentrant metadata gate is held. Other callers stay busy.
        """
        self._schema();snapshot=self._snapshot()
        if self._validation_lease is not None or not snapshot.associated:
            raise TransferError('photo_mappings_native_validation_busy')
        action.validate(self)
        lease=(threading.get_ident(),self._store_witness(),action)
        self._validation_lease=lease
        try:yield
        finally:self._validation_lease=None

    def validate_availability(self,witness):
        lease=self._validation_lease
        if lease is not None and lease[0]==threading.get_ident():
            if type(witness) is not PhotoMappingStoreWitness or witness!=lease[1]:
                raise TransferError('photo_mapping_store_original_changed')
            lease[2].validate(self);self._fresh()
            return True
        self.verify_witness(witness)
        return True

    def _rows_digest(self):
        digest=sha256();count=0
        for key,blob in self._db.execute('SELECT association,payload FROM mappings ORDER BY association'):
            if not _hex(key) or type(blob) is not bytes or not 28<=len(blob)<=self.MAX_RECORD_BYTES+28 or count>=self.MAX_MAPPINGS:
                raise TransferError('photo_mappings_invalid_member')
            digest.update(key.encode('ascii'));digest.update(sha256(blob).digest());count+=1
            if count%64==0:self._fresh()
        self._fresh()
        return count,digest.hexdigest()

    def _snapshot(self):
        rows=self._db.execute('SELECT id,payload FROM owner').fetchall()
        if len(rows)!=1 or rows[0][0]!=1:raise TransferError('photo_mappings_owner_required')
        blob=rows[0][1];owner=self._unprotect(blob,'owner')
        if (type(owner) is not dict or set(owner)!={'revision','count','mappings_sha256','pairing_epoch'}
                or type(owner['revision']) is not int or not 1<=owner['revision']<=MAX_REVISION
                or type(owner['count']) is not int or not 0<=owner['count']<=self.MAX_MAPPINGS
                or not _hex(owner['mappings_sha256']) or not _hex(owner['pairing_epoch'])):
            raise TransferError('photo_mappings_invalid_owner')
        if self._rows_digest()!=(owner['count'],owner['mappings_sha256']):
            raise TransferError('photo_mappings_members_changed')
        protected=sha256(blob).hexdigest()
        if self._last is not None and (owner['revision']<self._last[0] or owner['revision']==self._last[0] and protected!=self._last[1]):
            raise TransferError('photo_mappings_owner_rollback')
        self._last=(owner['revision'],protected)
        associated=owner['pairing_epoch']==self._peer().pairing_epoch
        version=self._absent if owner['revision']==1 and owner['count']==0 and associated else protected
        return PhotoMappingsSnapshot(version,owner['revision'],owner['count'],associated)

    def read(self):
        try:
            with self._operation():
                if not self._open():return PhotoMappingsSnapshot(self._absent,0,0,False)
                with self._locked():
                    self._schema();snapshot=self._snapshot();self._sync();return snapshot
        except Exception as error:
            if not isinstance(error,TransferError) or str(error) not in ('photo_preferences_busy','photo_preferences_closed_or_pending','photo_preferences_authority_changed'):
                self._uncertain=True
            raise

    @staticmethod
    def _head_key(association):
        return sha256(('magnolie-photo-version-head-v1\0'+association.key).encode('ascii')).hexdigest()

    @staticmethod
    def _version_key(association,receipt):
        return sha256(('magnolie-photo-version-record-v1\0'+association.key+'\0'+receipt).encode('ascii')).hexdigest()

    def _mapping_records(self,association):
        """Newest first, with every immutable predecessor authenticated.

        The original v1 row and its ciphertext never change. Extra rows use
        separate protection domains; the mutable head is not a save receipt.
        The existing aggregate owner covers all rows without a schema migration.
        """
        row=self._db.execute('SELECT payload FROM mappings WHERE association=?',(association.key,)).fetchone()
        head_key=self._head_key(association)
        head_row=self._db.execute('SELECT payload FROM mappings WHERE association=?',(head_key,)).fetchone()
        if row is None:
            if head_row is not None:raise TransferError('photo_mapping_version_original_required')
            return ()
        root=NativeSavedPhotoMapping.parse(self._unprotect(row[0],'mapping/'+association.key),association,sha256(row[0]).hexdigest())
        if head_row is None:return ((association.key,root),)
        head=self._unprotect(head_row[0],'head/'+head_key)
        if (type(head) is not dict or set(head)!={'format','association','record_key','record_sha256'}
                or type(head['format']) is not int or head['format']!=1 or head['association']!=association.wire()
                or not _hex(head['record_key']) or not _hex(head['record_sha256']) or head['record_key']==association.key):
            raise TransferError('photo_mapping_invalid_version_head')
        key=head['record_key'];expected=head['record_sha256'];seen=set();records=[]
        while key!=association.key:
            if key in seen or len(seen)>=self.MAX_MAPPINGS:raise TransferError('photo_mapping_version_chain_changed')
            seen.add(key)
            item=self._db.execute('SELECT payload FROM mappings WHERE association=?',(key,)).fetchone()
            if item is None or sha256(item[0]).hexdigest()!=expected:raise TransferError('photo_mapping_version_chain_changed')
            value=self._unprotect(item[0],'version/'+key)
            if (type(value) is not dict or set(value)!={'format','mapping','previous_key','previous_sha256'}
                    or type(value['format']) is not int or value['format']!=2
                    or not _hex(value['previous_key']) or not _hex(value['previous_sha256'])):
                raise TransferError('photo_mapping_invalid_version_record')
            record=NativeSavedPhotoMapping.parse(value['mapping'],association,expected)
            if (key!=self._version_key(association,record.receipt_sha256) or record.destination!=root.destination):
                raise TransferError('photo_mapping_version_chain_changed')
            records.append((key,record));key=value['previous_key'];expected=value['previous_sha256']
            self._fresh()
        if expected!=root.protected_record_sha256:raise TransferError('photo_mapping_version_chain_changed')
        return tuple(records)+((association.key,root),)

    def _mapping(self,association):
        records=self._mapping_records(association)
        return records[0][1] if records else None

    def _saved_mapping(self,association,receipt):
        return next((record for _,record in self._mapping_records(association) if record.receipt_sha256==receipt),None)

    def lookup_saved(self,associations,receipts):
        if (type(associations) is not tuple or type(receipts) is not tuple or len(receipts)!=len(associations)
                or any(not _hex(receipt) for receipt in receipts)):
            raise TransferError('photo_mappings_native_receipts_required')
        return self.lookup(associations,saved_receipts=receipts)

    def lookup(self,associations,*,contents=None,saved_receipts=None):
        if (type(associations) is not tuple or len(associations)>128 or any(type(item) is not PhotoMappingAssociation for item in associations)
                or contents is not None and (type(contents) is not tuple or len(contents)!=len(associations)
                    or any(type(item) is not tuple or len(item)!=2 or not _hex(item[0]) or type(item[1]) is not int
                        or not 0<=item[1]<=MAX_FILE_BYTES for item in contents))
                or saved_receipts is not None and (type(saved_receipts) is not tuple or len(saved_receipts)!=len(associations)
                    or any(not _hex(item) for item in saved_receipts))):
            raise TransferError('photo_mappings_native_associations_required')
        try:
            with self._operation():
                if not self._open():return PhotoMappingsSnapshot(self._absent,0,0,False),tuple(None for _ in associations)
                with self._locked():
                    self._schema();before=self._snapshot()
                    if saved_receipts is not None:
                        result=tuple(self._saved_mapping(association,receipt) for association,receipt in zip(associations,saved_receipts))
                    elif contents is not None:
                        chosen=[]
                        for association,content in zip(associations,contents):
                            records=self._mapping_records(association)
                            chosen.append(next((record for _,record in records
                                if (record.saved_sha256,record.saved_size)==content),records[0][1] if records else None))
                        result=tuple(chosen)
                    else:result=tuple(self._mapping(association) for association in associations)
                    if self._snapshot()!=before:raise TransferError('photo_mappings_lookup_changed')
                    self._sync();return before,result
        except Exception as error:
            if not isinstance(error,TransferError) or str(error) not in ('photo_preferences_busy','photo_preferences_closed_or_pending','photo_preferences_authority_changed'):
                self._uncertain=True
            raise

    def commit_received(self,action,expected,receiver,pages):
        return self._commit_received(action,expected,receiver,pages)

    def commit_saved_history(self,action,expected,receiver):
        """Only the owned native index supplies the original historical IDs."""
        return self._commit_received(action,expected,receiver,None)

    def _commit_received(self,action,expected,receiver,pages):
        if type(action) is not NativePhotoDestinationAction:raise TransferError('photo_mappings_native_action_required')
        action.consume(self)
        if type(expected) is not PhotoMappingsSnapshot or type(receiver) is not NativeFileReceiveOperation:
            raise TransferError('photo_mappings_native_saved_receiver_required')
        # Historical mapping only. Never treat a receipt as current presence.
        with receiver._gate:
            receiver._require()
            accepted=receiver._accepted
            history=receiver._index.media_history
            if pages is None:
                if type(history) is not NativeMediaHistory:raise TransferError('photo_mappings_persisted_media_history_required')
                NativeMediaHistory.parse(history.wire(),accepted)
                entries=history.entries;source_epoch=history.source_epoch;media_type=history.media_type
            else:
                entries=correlate_media_pages(pages,accepted.manifest)
                if history is not None and NativeMediaHistory.capture(accepted,pages,mapping_store=history.mapping_store,
                        version_parents=history.version_parents)!=history:
                    raise TransferError('photo_mappings_media_history_changed')
                source_epoch=pages[0].source_epoch;media_type=pages[0].media_type
            peer=self._peer()
            if (accepted.binding.sender_id!=peer.peer_id or accepted.binding.sender_identity_sha256!=peer.identity_sha256
                    or accepted.binding.receiver_id!=self._authority.identity.receiver_id
                    or accepted.binding.receiver_identity_sha256!=self._authority.identity.receiver_identity_sha256):
                raise TransferError('photo_mappings_foreign_saved_receiver')
            receipts=receiver._index.saved_receipts()
            by_file={receipt.file_id:receipt for receipt in receipts}
            if set(by_file)!={file.id for file in accepted.manifest.files}:raise TransferError('photo_mappings_complete_saved_receipts_required')
            wanted=[]
            for entry in entries:
                receipt=by_file[entry.file_id]
                association=PhotoMappingAssociation(source_epoch,entry.photo_id,media_type)
                proposed=NativeSavedPhotoMapping(association,accepted.destination,receipt.relative_path,receipt.file_key,receipt.parent_keys,
                    receipt.size,receipt.sha256,receipt.protected_record_sha256,receipt.manifest_sha256,receipt.accepted_sha256,
                    receipt.file_id,receipt.owner,'0'*64)
                wanted.append(proposed)
            with self._operation():
                self._open(create=True,validate=lambda:action.validate(self))
                with self._locked(),self._validated_metadata_io(action):
                    self._schema();current=self._snapshot()
                    if history is not None and history.mapping_store is not None:self._require_checkpoint(history.mapping_store,current)
                    if current.version!=expected.version:raise TransferError('photo_mappings_cas_conflict')
                    if not current.associated:raise TransferError('photo_mappings_reassociation_required')
                    pending=[];parents=dict(history.version_parents) if history is not None else {}
                    for proposed in wanted:
                        existing=self._mapping(proposed.association)
                        saved=self._saved_mapping(proposed.association,proposed.receipt_sha256)
                        parent=parents.get(proposed.association.photo_id)
                        if saved is not None:
                            if saved.wire()!=proposed.wire():raise TransferError('photo_mapping_existing_requires_reconcile')
                        elif parent is not None:
                            file=next(file for file in accepted.manifest.files if file.id==proposed.source_file_id)
                            if (existing is None or existing.protected_record_sha256!=parent
                                    or existing.destination!=proposed.destination
                                    or proposed.relative_path!=photo_version_path(proposed.association,file)
                                    or (existing.saved_sha256,existing.saved_size)==(proposed.saved_sha256,proposed.saved_size)):
                                raise TransferError('photo_mapping_version_parent_changed')
                            pending.append((proposed,self._mapping_records(proposed.association)[0]))
                        elif existing is not None:raise TransferError('photo_mapping_existing_requires_reconcile')
                        else:pending.append((proposed,None))
                    added=sum(1 if parent is None else 1+int(self._db.execute('SELECT 1 FROM mappings WHERE association=?',
                        (self._head_key(item.association),)).fetchone() is None) for item,parent in pending)
                    if current.count+added>self.MAX_MAPPINGS or current.revision>=MAX_REVISION:raise TransferError('photo_mappings_limit')
                    def fresh():
                        receiver._require();self._fresh();action.validate(self)
                        if self._peer().pairing_epoch!=peer.pairing_epoch:raise TransferError('photo_mappings_pairing_changed')
                        if receiver._index.saved_receipts()!=receipts:raise TransferError('photo_mappings_saved_receipts_changed')
                        if receiver._index.media_history!=history:raise TransferError('photo_mappings_media_history_changed')
                    fresh()
                    if not pending:return current,tuple(self._saved_mapping(item.association,item.receipt_sha256) for item in wanted)
                    mutated=False
                    try:
                        protected=[];heads=[]
                        for item,parent in pending:
                            if parent is None:protected.append((item.association.key,self._protect(item.wire(),'mapping/'+item.association.key)))
                            else:
                                key=self._version_key(item.association,item.receipt_sha256);head_key=self._head_key(item.association)
                                blob=self._protect(dict(format=2,mapping=item.wire(),previous_key=parent[0],
                                    previous_sha256=parent[1].protected_record_sha256),'version/'+key)
                                protected.append((key,blob))
                                head=self._protect(dict(format=1,association=item.association.wire(),record_key=key,
                                    record_sha256=sha256(blob).hexdigest()),'head/'+head_key)
                                heads.append((head_key,head))
                        fresh()
                        self._db.execute('BEGIN IMMEDIATE')
                        mutated=True
                        self._db.executemany('INSERT INTO mappings VALUES(?,?)',protected)
                        self._db.executemany('INSERT INTO mappings VALUES(?,?) ON CONFLICT(association) DO UPDATE SET payload=excluded.payload',heads)
                        count,digest=self._rows_digest()
                        owner=self._protect(dict(revision=current.revision+1,count=count,mappings_sha256=digest,pairing_epoch=peer.pairing_epoch),'owner')
                        self._db.execute('UPDATE owner SET payload=? WHERE id=1',(owner,))
                        fresh()
                        self._db.commit();self._sync()
                        after=self._snapshot();result=tuple(self._saved_mapping(item.association,item.receipt_sha256) for item in wanted)
                        fresh()
                        return after,result
                    except BaseException:
                        if self._db.in_transaction:self._db.rollback()
                        if mutated:self._uncertain=True
                        raise

    def configure(self,*args,**kwargs):raise TransferError('photo_mappings_are_not_preferences')
    def local_grant(self,*args,**kwargs):raise TransferError('photo_mappings_are_not_grants')
