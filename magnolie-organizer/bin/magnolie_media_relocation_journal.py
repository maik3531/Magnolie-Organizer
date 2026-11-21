"""Protected preparation for local special-folder relocation (#429).

Not exposed to the UI. A durable intent alone neither permits a rename nor
changes a saved mapping. No replay, resume or terminal write is provided here.
"""
from dataclasses import dataclass
from hashlib import sha256

from magnolie_file_control import _hex
from magnolie_file_transfer import TransferError
from magnolie_media_relocation_record import MediaRelocationRecord, bind_relocation_selection
from magnolie_photo_destination import NativePhotoDestinationAction
from magnolie_photo_preferences import ProtectedPhotoPreferences


@dataclass(frozen=True)
class RelocationJournalSnapshot:
    version: str
    associated: bool
    records: tuple


class ProtectedMediaRelocationJournal(ProtectedPhotoPreferences):
    _SCHEMA={
        'owner':'CREATE TABLE owner (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)',
        'selection':'CREATE TABLE selection (ordinal INTEGER PRIMARY KEY, payload BLOB NOT NULL)'}
    MAX_DATABASE_BYTES=2*1024*1024
    MAX_MEMBERS=128

    def __init__(self,authority,**kwargs):
        super().__init__(authority,**kwargs)
        self._name='media-relocation-v1-'+self._scope
        self._domain='magnolie-media-relocation-v1/'+self._scope+'/'
        self._absent=sha256((self._domain+'absent').encode()).hexdigest()

    def _initial_owner(self):
        return dict(pairing_epoch=self._peer().pairing_epoch,count=0,rows_sha256=sha256(b'').hexdigest())

    def _snapshot(self):
        head=self._db.execute('SELECT id,payload FROM owner').fetchall()
        if len(head)!=1 or head[0][0]!=1:raise TransferError('photo_relocation_original_journal_required')
        blob=head[0][1];owner=self._unprotect(blob,'owner')
        if (type(owner) is not dict or set(owner)!={'pairing_epoch','count','rows_sha256'}
                or not _hex(owner['pairing_epoch']) or not _hex(owner['rows_sha256'])
                or type(owner['count']) is not int or not 0<=owner['count']<=self.MAX_MEMBERS):
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
        version=sha256(blob).hexdigest();mark=(1 if records else 0,version)
        if self._last is not None and (mark[0]<self._last[0] or mark[0]==self._last[0] and mark!=self._last):
            raise TransferError('photo_relocation_journal_rollback')
        self._last=mark
        return RelocationJournalSnapshot(version if records else self._absent,
            owner['pairing_epoch']==self._peer().pairing_epoch,records)

    def read(self):
        with self._operation():
            if not self._open():return RelocationJournalSnapshot(self._absent,False,())
            with self._locked():
                self._schema();return self._snapshot()

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
                self._schema();before=self._snapshot();current()
                if not before.associated or before.version!=expected.version or before.records:
                    raise TransferError('photo_relocation_original_journal_changed')
                try:
                    self._db.execute('BEGIN IMMEDIATE');rows=sha256()
                    for index,record in enumerate(records):
                        current();cipher=self._protect(record.wire(),'member/'+str(index))
                        self._db.execute('INSERT INTO selection VALUES(?,?)',(index,cipher))
                        rows.update(sha256(cipher).digest())
                    owner=dict(self._initial_owner(),count=len(records),rows_sha256=rows.hexdigest())
                    self._db.execute('UPDATE owner SET payload=? WHERE id=1',(self._protect(owner,'owner'),))
                    current();self._db.commit();self._sync();current()
                    return self._snapshot()
                except BaseException:
                    if self._db.in_transaction:self._db.rollback()
                    self._uncertain=True
                    raise
