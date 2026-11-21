"""Protected preparation for local special-folder relocation (#429).

Not exposed to the UI. A local rename requires a live native owner and a
durably spent attempt. This journal never changes a saved mapping.
"""
from dataclasses import dataclass, replace
from contextlib import ExitStack
from hashlib import sha256
import os

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_control import _hex
from magnolie_file_transfer import TransferError
from magnolie_media_relocation_anchor import RelocationAnchor
from magnolie_media_relocation_owner import relocation_destination_digest
from magnolie_media_relocation_record import MediaRelocationRecord, bind_relocation_selection
from magnolie_media_retention import NativeMediaActivity, NativeMediaRetention
from magnolie_photo_destination import NativePhotoDestinationAction, require_media_directory
from magnolie_photo_mappings import NativeSavedPhotoMapping
from magnolie_photo_preferences import ProtectedPhotoPreferences


@dataclass(frozen=True)
class RelocationJournalSnapshot:
    version: str
    associated: bool
    records: tuple
    outcome_version: str | None = None
    outcomes: tuple = ()
    attempts: tuple = ()


@dataclass(frozen=True)
class RelocationOwnerCheckpoint:
    """Bounded metadata for an independent owner store; parsing is not authority."""
    selection_sha256: str
    book_sha256: str
    destination_sha256: str
    prepared_version: str
    outcome_version: str

    def __post_init__(self):
        if not all(_hex(value) for value in vars(self).values()):
            raise TransferError('photo_relocation_invalid_owner_checkpoint')

    def wire(self):return dict(format=1,**vars(self))

    @classmethod
    def parse(cls,value):
        if (type(value) is not dict or set(value)!=(set(cls.__annotations__)|{'format'})
                or type(value['format']) is not int or value['format']!=1):
            raise TransferError('photo_relocation_invalid_owner_checkpoint')
        return cls(**{key:value[key] for key in cls.__annotations__})

    @classmethod
    def from_snapshot(cls,snapshot,destination):
        if (type(snapshot) is not RelocationJournalSnapshot or not snapshot.associated or not snapshot.records
                or type(destination) is not NativeAcceptedDestination
                or snapshot.records[0].root_key!=destination.ancestor_keys[0]):
            raise TransferError('photo_relocation_original_checkpoint_required')
        original=snapshot.records[0]
        # The selection digest commits to operation ID, preferences, members,
        # endpoint chains and bytes. The destination also pins its full path.
        address=relocation_destination_digest(destination)
        return cls(original.selection_sha256,original.book_sha256,address,snapshot.version,snapshot.outcome_version)


@dataclass(frozen=True)
class RelocatedReadLocation:
    """Effective local path, never a replacement for the historical mapping."""
    original: NativeSavedPhotoMapping
    relative_path: str
    parent_keys: tuple

    @property
    def destination(self):return self.original.destination

    @property
    def file_key(self):return self.original.file_key


@dataclass(frozen=True)
class RelocationRecoveryObservation:
    ordinal: int
    state: str

    @property
    def grants_write_authority(self):return False


class ProtectedMediaRelocationJournal(ProtectedPhotoPreferences):
    _SCHEMA={
        'owner':'CREATE TABLE owner (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)',
        'selection':'CREATE TABLE selection (ordinal INTEGER PRIMARY KEY, payload BLOB NOT NULL)',
        'outcomes':'CREATE TABLE outcomes (ordinal INTEGER PRIMARY KEY, payload BLOB NOT NULL)',
        'attempts':'CREATE TABLE attempts (ordinal INTEGER PRIMARY KEY, payload BLOB NOT NULL)'}
    MAX_DATABASE_BYTES=2*1024*1024
    MAX_MEMBERS=128

    def __init__(self,authority,**kwargs):
        super().__init__(authority,**kwargs)
        self._name='media-relocation-v1-'+self._scope
        self._domain='magnolie-media-relocation-v1/'+self._scope+'/'
        self._absent=sha256((self._domain+'absent').encode()).hexdigest()
        self._anchor=RelocationAnchor(self)

    def _open(self,*,create=False,validate=lambda:None):
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
        parent=os.open(self._native_directory(),flags)
        try:
            info=os.fstat(parent);self._private(info,directory=True)
            if self._key(info)!=self._protection().native_directory_identity:
                raise TransferError('photo_relocation_original_root_changed')
            def present(name):
                try:os.stat(name,dir_fd=parent,follow_symlinks=False);return True
                except FileNotFoundError:return False
            exists,anchored=present(self._name),present(self._anchor.name)
            if exists!=anchored or not exists and self._anchor._identity is not None:
                raise TransferError('photo_relocation_original_anchor_required')
            if not exists and not create:return False
            result=super()._open(create=create,validate=validate)
            if not result:raise TransferError('photo_relocation_original_journal_changed')
            if not exists:
                with self._locked():
                    self._schema();initial=self._snapshot();validate()
                    if initial.records or not initial.associated:
                        raise TransferError('photo_relocation_original_journal_changed')
                    self._anchor.create(initial)
            return result
        finally:os.close(parent)

    def _anchored_snapshot(self):
        snapshot=self._snapshot();self._anchor.require(snapshot);return snapshot

    def _commit_anchored(self,before,owner,current):
        blob=self._protect(owner,'owner')
        self._db.execute('UPDATE owner SET payload=? WHERE id=1',(blob,))
        checkpoint=(owner['rows_sha256'],sha256(blob).hexdigest(),owner['count'],owner['attempt_count'],owner['outcome_count'])
        # Deliberate write-ahead ordering: a cut between independent writes is
        # held on restart, not interpreted as an old or successful operation.
        current();self._anchor.append(before,checkpoint)
        current();self._db.commit();self._sync();current()
        return self._anchored_snapshot()

    def _initial_owner(self):
        empty=sha256(b'').hexdigest()
        return dict(pairing_epoch=self._peer().pairing_epoch,count=0,rows_sha256=empty,outcome_count=0,outcomes_sha256=empty,
            attempt_count=0,attempts_sha256=empty)

    @staticmethod
    def _attempt(record):
        return dict(operation=record.operation,selection_sha256=record.selection_sha256,mapping_sha256=record.original_mapping_sha256)

    def _event_digest(self,table):
        if table not in ('outcomes','attempts'):raise TransferError('photo_relocation_invalid_event_table')
        digest=sha256()
        for ordinal,cipher in self._db.execute('SELECT ordinal,payload FROM '+table+' ORDER BY ordinal'):
            digest.update(ordinal.to_bytes(2,'big')+sha256(cipher).digest())
        return digest.hexdigest()

    def _snapshot(self):
        head=self._db.execute('SELECT id,payload FROM owner').fetchall()
        if len(head)!=1 or head[0][0]!=1:raise TransferError('photo_relocation_original_journal_required')
        blob=head[0][1];owner=self._unprotect(blob,'owner')
        if (type(owner) is not dict or set(owner)!={'pairing_epoch','count','rows_sha256','outcome_count','outcomes_sha256','attempt_count','attempts_sha256'}
                or any(not _hex(owner[name]) for name in ('pairing_epoch','rows_sha256','outcomes_sha256','attempts_sha256'))
                or any(type(owner[name]) is not int or not 0<=owner[name]<=self.MAX_MEMBERS for name in ('count','outcome_count','attempt_count'))):
            raise TransferError('photo_relocation_invalid_journal')
        records=[];rows=sha256()
        for index,cipher in self._db.execute('SELECT ordinal,payload FROM selection ORDER BY ordinal'):
            if type(index) is not int or index!=len(records) or index>=self.MAX_MEMBERS:
                raise TransferError('photo_relocation_invalid_journal')
            records.append(MediaRelocationRecord.parse(self._unprotect(cipher,'member/'+str(index))))
            rows.update(sha256(cipher).digest())
        records=tuple(records)
        if (owner['count']!=len(records) or owner['rows_sha256']!=rows.hexdigest()
                or records and bind_relocation_selection(records,occupied=())!=records):
            raise TransferError('photo_relocation_original_journal_changed')
        outcomes=[];outcome_hash=sha256()
        for index,cipher in self._db.execute('SELECT ordinal,payload FROM outcomes ORDER BY ordinal'):
            if type(index) is not int or not 0<=index<len(records):raise TransferError('photo_relocation_invalid_outcome')
            entry=MediaRelocationRecord.parse(self._unprotect(cipher,'outcome/'+str(index)))
            if entry.phase not in ('moved','canceled') or replace(entry,phase='prepared')!=records[index]:
                raise TransferError('photo_relocation_invalid_outcome')
            outcome_hash.update(index.to_bytes(2,'big')+sha256(cipher).digest());outcomes.append((index,entry))
        if owner['outcome_count']!=len(outcomes) or owner['outcomes_sha256']!=outcome_hash.hexdigest():
            raise TransferError('photo_relocation_original_journal_changed')
        attempts=[];attempt_hash=sha256()
        for index,cipher in self._db.execute('SELECT ordinal,payload FROM attempts ORDER BY ordinal'):
            if (type(index) is not int or not 0<=index<len(records)
                    or self._unprotect(cipher,'attempt/'+str(index))!=self._attempt(records[index])):
                raise TransferError('photo_relocation_invalid_attempt')
            attempt_hash.update(index.to_bytes(2,'big')+sha256(cipher).digest());attempts.append(index)
        if owner['attempt_count']!=len(attempts) or owner['attempts_sha256']!=attempt_hash.hexdigest():
            raise TransferError('photo_relocation_original_journal_changed')
        version=sha256(blob).hexdigest();mark=(len(records)+len(outcomes)+len(attempts),version)
        if self._last is not None and (mark[0]<self._last[0] or mark[0]==self._last[0] and mark!=self._last):
            raise TransferError('photo_relocation_journal_rollback')
        self._last=mark
        return RelocationJournalSnapshot(owner['rows_sha256'] if records else self._absent,
            owner['pairing_epoch']==self._peer().pairing_epoch,records,version,tuple(outcomes),tuple(attempts))

    def read(self):
        with self._operation():
            if not self._open():return RelocationJournalSnapshot(self._absent,False,())
            with self._locked():
                self._schema();return self._anchored_snapshot()

    def require_prepared(self,expected_version,confirmed_sha256):
        """Read the exact previous preparation; an absent store cannot be recreated.

        A later native owner must keep these two witnesses outside this store.
        A caller-supplied checkpoint, even if current, is not a rename grant.
        """
        if (not _hex(expected_version) or expected_version==self._absent or not _hex(confirmed_sha256)):
            raise TransferError('photo_relocation_original_checkpoint_required')
        current=self.read()
        if (not current.associated or current.version!=expected_version or not current.records
                or current.records[0].selection_sha256!=confirmed_sha256):
            raise TransferError('photo_relocation_original_journal_changed')
        return current

    def inspect_original_recovery(self,expected,destination,*,require_original):
        """Observe all original members, never repair, adopt, or spend an attempt.

        `expected` must come from the original owner outside this journal. In
        particular, reading a checkpoint after restart is not an owner proof.
        """
        if (type(expected) is not RelocationOwnerCheckpoint or type(destination) is not NativeAcceptedDestination
                or not callable(require_original)):
            raise TransferError('photo_relocation_original_checkpoint_required')
        with NativeMediaRetention(self._native_directory()) as retention:
            def current_book():
                if require_original() is not True:raise TransferError('photo_relocation_original_owner_ended')
                if retention.saved_book_version()!=expected.book_sha256:
                    raise TransferError('photo_relocation_original_book_changed')
                return True
            with retention.activity(current_book) as lease:
                if lease is None:raise TransferError('photo_relocation_activity_busy')
                with self._operation():
                    if not self._open():raise TransferError('photo_relocation_original_journal_changed')
                    with self._locked():
                        def current():
                            lease();self._fresh();return True
                        self._schema();before=self._anchored_snapshot();current()
                        if not before.records or RelocationOwnerCheckpoint.from_snapshot(before,destination)!=expected:
                            raise TransferError('photo_relocation_original_journal_changed')
                        outcomes=dict(before.outcomes);attempts=set(before.attempts);observations=[]
                        for ordinal,record in enumerate(before.records):
                            state='held'
                            try:
                                require_media_directory(destination.path+'/'+record.source)
                                require_media_directory(destination.path+'/'+record.target)
                                outcome=outcomes.get(ordinal)
                                if outcome is not None and outcome.phase=='moved' and ordinal in attempts:
                                    outcome.require_moved_location(destination,current)
                                    state='moved'
                                else:
                                    location=record.observe_native(destination,current)
                                    if outcome is not None:
                                        if outcome.phase=='canceled' and location=='at_source':state='canceled'
                                    elif location=='at_source':
                                        state='held_spent_at_source' if ordinal in attempts else 'prepared_at_source'
                                    elif location=='at_target' and ordinal in attempts:
                                        state='held_spent_at_target'
                            except (OSError,TransferError):
                                # Endpoint uncertainty is not absence. An ended
                                # owner or changed book retires the whole scan.
                                current()
                            observations.append(RelocationRecoveryObservation(ordinal,state))
                        if self._anchored_snapshot()!=before:raise TransferError('photo_relocation_original_journal_changed')
                        current();return tuple(observations)

    def resolve_moved_read_location(self,expected,mapping,*,require_original):
        """Read a moved location under the exact externally bound outcome.

        Only the path and its directory witnesses change. Any reader must still
        open and revalidate the exact file, using the original mapping for byte
        comparison. Never use this projection to grant SEND or resume a move.
        """
        if (type(expected) is not RelocationJournalSnapshot or not expected.associated or not expected.records
                or type(mapping) is not NativeSavedPhotoMapping or not callable(require_original)):
            raise TransferError('photo_relocation_original_checkpoint_required')
        def current():
            if require_original() is not True:raise TransferError('photo_relocation_original_owner_ended')
            self._fresh()
            return True
        with self._operation():
            if not self._open():raise TransferError('photo_relocation_original_journal_changed')
            with self._locked():
                self._schema();before=self._anchored_snapshot();current()
                if before!=expected:raise TransferError('photo_relocation_original_journal_changed')
                moved=next((item for _,item in before.outcomes if item.original_mapping_sha256==mapping.protected_record_sha256),None)
                if (moved is None or moved.phase!='moved' or moved.source!=mapping.relative_path
                        or moved.source_parents!=mapping.parent_keys or moved.file.file_key!=mapping.file_key
                        or moved.root_key!=mapping.destination.ancestor_keys[0]):
                    raise TransferError('photo_relocation_moved_mapping_required')
                require_media_directory(mapping.destination.path+'/'+moved.target)
                moved.require_moved_location(mapping.destination,current)
                if self._anchored_snapshot()!=before:raise TransferError('photo_relocation_original_journal_changed')
                current()
                return RelocatedReadLocation(mapping,moved.target,moved.target_parents)

    def observe_moved_saved_target(self,expected,mapping,accepted,receipt,current_binding,*,require_original):
        """Compare bytes at a proven moved name without rewriting a receipt.

        The native caller must supply and keep current the original book,
        journal checkpoint and protected mapping/receipt. No path fallback.
        """
        from magnolie_photo_target import _observe_target, _require_receipt_context
        _require_receipt_context(accepted,receipt,current_binding)
        if (type(mapping) is not NativeSavedPhotoMapping or not callable(require_original)
                or (mapping.destination,mapping.source_file_id,mapping.relative_path,mapping.parent_keys,mapping.file_key,
                    mapping.saved_size,mapping.saved_sha256,mapping.receipt_sha256,mapping.manifest_sha256,mapping.accepted_sha256)
                != (accepted.destination,receipt.file_id,receipt.relative_path,receipt.parent_keys,receipt.file_key,
                    receipt.size,receipt.sha256,receipt.protected_record_sha256,receipt.manifest_sha256,receipt.accepted_sha256)):
            raise TransferError('photo_relocation_original_receipt_changed')

        def current():
            accepted.verify(current_binding)
            return require_original()

        with NativeMediaActivity(self._native_directory()) as activity:
            with activity.activity(current) as lease:
                if lease is None:raise TransferError('photo_relocation_activity_busy')
                location=self.resolve_moved_read_location(expected,mapping,require_original=lease)
                observed=_observe_target(accepted,receipt,current_binding,location.relative_path,location.parent_keys,
                    require_moved=lease)
                if self.resolve_moved_read_location(expected,mapping,require_original=lease)!=location:
                    raise TransferError('photo_relocation_original_location_unproven')
                return observed

    def prepare(self,action,expected,records,confirmed_sha256,destination,*,require_original):
        """Store the whole exact selection or none. No files are moved here.

        The caller must be the explicit native confirmation owner, with actual
        protected mapping/book validation, not a browser or a reconstructed run.
        """
        if (type(action) is not NativePhotoDestinationAction or type(expected) is not RelocationJournalSnapshot
                or expected.records or expected.version!=self._absent or not callable(require_original)
                or not _hex(confirmed_sha256)):
            raise TransferError('photo_relocation_native_preparation_required')
        action.consume(self)
        if bind_relocation_selection(records,occupied=())!=records or records[0].selection_sha256!=confirmed_sha256:
            raise TransferError('photo_relocation_confirmation_changed')
        def current():
            action.validate(self)
            if require_original() is not True:raise TransferError('photo_relocation_original_owner_ended')
            return True
        with self._operation():
            for record in records:
                if record.observe_native(destination,current)!='at_source':
                    raise TransferError('photo_relocation_original_location_unproven')
            self._open(create=True,validate=current)
            with self._locked():
                self._schema();before=self._anchored_snapshot();current()
                if not before.associated or before.version!=expected.version or before.records:
                    raise TransferError('photo_relocation_original_journal_changed')
                try:
                    self._db.execute('BEGIN IMMEDIATE');rows=sha256()
                    for index,record in enumerate(records):
                        current();cipher=self._protect(record.wire(),'member/'+str(index))
                        self._db.execute('INSERT INTO selection VALUES(?,?)',(index,cipher))
                        rows.update(sha256(cipher).digest())
                    owner=dict(self._initial_owner(),count=len(records),rows_sha256=rows.hexdigest())
                    return self._commit_anchored(before,owner,current)
                except BaseException:
                    if self._db.in_transaction:self._db.rollback()
                    self._uncertain=True
                    raise

    def record_terminal(self,action,expected,index,phase,destination,*,require_original):
        """Append one proven outcome to the exact already prepared selection."""
        return self._complete_member(action,expected,index,phase,destination,require_original=require_original,rename=False)

    def move_prepared_animation(self,action,expected,index,destination,*,require_original):
        """Private native path: spend once before touching an exact animated original."""
        return self._complete_member(action,expected,index,'moved',destination,require_original=require_original,rename=True)

    def _complete_member(self,action,expected,index,phase,destination,*,require_original,rename,
            owner_checkpoint=None):
        if (type(action) is not NativePhotoDestinationAction or type(expected) is not RelocationJournalSnapshot
                or not expected.associated or not expected.records or not _hex(expected.outcome_version)
                or type(index) is not int or not 0<=index<len(expected.records) or not callable(require_original)):
            raise TransferError('photo_relocation_original_checkpoint_required')
        action.consume(self)
        book_check=None
        def current():
            action.validate(self)
            if require_original() is not True:raise TransferError('photo_relocation_original_owner_ended')
            if book_check is not None:book_check()
            return True
        with self._operation():
            if not self._open():raise TransferError('photo_relocation_original_journal_changed')
            with self._locked(), ExitStack() as lifetime:
                self._schema();before=self._anchored_snapshot();current()
                if before!=expected:raise TransferError('photo_relocation_original_journal_changed')
                if index in dict(before.outcomes):raise TransferError('photo_relocation_outcome_already_recorded')
                record=before.records[index]
                if rename:
                    if index in before.attempts:raise TransferError('photo_relocation_attempt_already_spent')
                    if owner_checkpoint is None:
                        retention=lifetime.enter_context(NativeMediaRetention(self._native_directory()))
                        def require_book():
                            if retention.saved_book_version()!=record.book_sha256:
                                raise TransferError('photo_relocation_original_book_changed')
                            return True
                        lease=lifetime.enter_context(retention.activity(require_book,exclusive=True))
                        if lease is None:raise TransferError('photo_relocation_media_activity_busy')
                        book_check=lease
                    else:
                        # The original owner already holds the exclusive lane.
                        # Never try to reenter it through a second DB descriptor.
                        owner_checkpoint.require_active(self,expected)
                    current()
                    require_media_directory(destination.path+'/'+record.source)
                    require_media_directory(destination.path+'/'+record.target)
                    if record.observe_native(destination,current,require_animation=True)!='at_source':
                        raise TransferError('photo_relocation_original_location_unproven')
                    spent=self._append_member(before,'attempt',index,self._attempt(record),current)
                    if owner_checkpoint is not None:owner_checkpoint.advance(self,before,spent,index,'attempt')
                    before=spent
                    def spent_current():
                        current();self._anchor.require(before)
                        return True
                    record._rename_prepared_animation(destination,spent_current)
                entry=record.sync_terminal_evidence(destination,current,phase)
                after=self._append_member(before,'outcome',index,entry.wire(),current)
                if owner_checkpoint is not None:owner_checkpoint.advance(self,before,after,index,'outcome')
                return after

    def _append_member(self,before,kind,index,payload,current):
        if kind not in ('attempt','outcome'):raise TransferError('photo_relocation_invalid_event_table')
        try:
            self._db.execute('BEGIN IMMEDIATE');current()
            cipher=self._protect(payload,kind+'/'+str(index))
            self._db.execute('INSERT INTO '+kind+'s VALUES(?,?)',(index,cipher))
            owner=dict(self._initial_owner(),count=len(before.records),rows_sha256=before.version,
                attempt_count=len(before.attempts)+(kind=='attempt'),attempts_sha256=self._event_digest('attempts'),
                outcome_count=len(before.outcomes)+(kind=='outcome'),outcomes_sha256=self._event_digest('outcomes'))
            return self._commit_anchored(before,owner,current)
        except BaseException:
            if self._db.in_transaction:self._db.rollback()
            self._uncertain=True
            raise
