"""Protected preparation for local special-folder relocation (#429).

Not exposed to the UI. A local rename requires a live native owner and a
durably spent attempt. This journal never changes a saved mapping.
"""
from dataclasses import dataclass, replace
from contextlib import ExitStack
from hashlib import sha256
import os

from magnolie_file_control import _hex
from magnolie_file_transfer import TransferError
from magnolie_media_relocation_anchor import RelocationAnchor
from magnolie_media_relocation_record import MediaRelocationRecord, bind_relocation_selection
from magnolie_media_retention import NativeMediaRetention
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
class RelocatedReadLocation:
    """Effective local path, never a replacement for the historical mapping."""
    original: NativeSavedPhotoMapping
    relative_path: str
    parent_keys: tuple

    @property
    def destination(self):return self.original.destination

    @property
    def file_key(self):return self.original.file_key


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

    def _complete_member(self,action,expected,index,phase,destination,*,require_original,rename):
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
                    retention=lifetime.enter_context(NativeMediaRetention(self._native_directory()))
                    def require_book():
                        if retention.saved_book_version()!=record.book_sha256:
                            raise TransferError('photo_relocation_original_book_changed')
                        return True
                    lease=lifetime.enter_context(retention.activity(require_book,exclusive=True))
                    if lease is None:raise TransferError('photo_relocation_media_activity_busy')
                    book_check=lease;current()
                    require_media_directory(destination.path+'/'+record.source)
                    require_media_directory(destination.path+'/'+record.target)
                    if record.observe_native(destination,current,require_animation=True)!='at_source':
                        raise TransferError('photo_relocation_original_location_unproven')
                    before=self._append_member(before,'attempt',index,self._attempt(record),current)
                    def spent_current():
                        current();self._anchor.require(before)
                        return True
                    record._rename_prepared_animation(destination,spent_current)
                entry=record.sync_terminal_evidence(destination,current,phase)
                return self._append_member(before,'outcome',index,entry.wire(),current)

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
