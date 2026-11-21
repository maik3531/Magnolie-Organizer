"""Independent native relocation intent in the existing phone DB (#429).

No file moves, journal bootstrap, recovery or app bridge. A durable intent
is a hold, not permission to resume a move after restart.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
import time

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_control import _hex
from magnolie_file_native_authority import NativeDesktopFileAuthority
from magnolie_file_transfer import TransferError
from magnolie_media_relocation_record import bind_relocation_selection
from magnolie_media_retention import NativeMediaRetention
from magnolie_photo_destination import NativePhotoDestinationAction, require_media_directory
from magnolie_telefon import canonical, strict_json


def relocation_destination_digest(destination):
    if type(destination) is not NativeAcceptedDestination:
        raise TransferError('photo_relocation_original_destination_required')
    return sha256(b'magnolie-relocation-owner-destination-v1\0'+canonical(destination.wire())).hexdigest()


@dataclass(frozen=True)
class RelocationOwnerIntent:
    operation: str
    selection_sha256: str
    book_sha256: str
    destination_sha256: str
    mappings: tuple

    def __post_init__(self):
        if (type(self.operation) is not str or len(self.operation)!=32 or not _hex(self.operation*2)
                or not all(_hex(value) for value in (self.selection_sha256,self.book_sha256,self.destination_sha256))
                or type(self.mappings) is not tuple or not 1<=len(self.mappings)<=128
                or not all(_hex(value) for value in self.mappings)
                or tuple(sorted(set(self.mappings)))!=self.mappings):
            raise TransferError('photo_relocation_invalid_owner_intent')

    def wire(self):
        return dict(format=1,operation=self.operation,selection_sha256=self.selection_sha256,
            book_sha256=self.book_sha256,destination_sha256=self.destination_sha256,mappings=list(self.mappings))

    @classmethod
    def parse(cls,body):
        if (type(body) is not dict or set(body)!=(set(cls.__annotations__)|{'format'})
                or type(body['format']) is not int or body['format']!=1 or type(body['mappings']) is not list):
            raise TransferError('photo_relocation_invalid_owner_intent')
        return cls(body['operation'],body['selection_sha256'],body['book_sha256'],body['destination_sha256'],tuple(body['mappings']))

    @classmethod
    def for_selection(cls,records,destination):
        address=relocation_destination_digest(destination)
        if bind_relocation_selection(records,occupied=())!=records or records[0].root_key!=destination.ancestor_keys[0]:
            raise TransferError('photo_relocation_confirmation_changed')
        first=records[0]
        return cls(first.operation,first.selection_sha256,first.book_sha256,address,
            tuple(sorted(record.original_mapping_sha256 for record in records)))


class ProtectedRelocationOwner(NativeMediaRetention):
    # Do not override the base retention KEY/DOMAIN: this is a separate row.
    _INTENT_KEY='media_relocation_owner:local:v1'
    _INTENT_DOMAIN='media-relocation-owner-v1/local'
    _PREPARED_KEY='media_relocation_prepared:local:v1'
    _PREPARED_DOMAIN='media-relocation-prepared-v1/local'
    _MAX_CIPHER_BYTES=16384

    def __init__(self,authority,*,monotonic_ms=lambda:time.monotonic_ns()//1_000_000):
        if type(authority) is not NativeDesktopFileAuthority or not callable(monotonic_ms):
            raise TransferError('photo_relocation_original_owner_required')
        self._authority=authority;self._clock=monotonic_ms;self._observed=None;self._held=False
        super().__init__(authority.binding.native_directory)

    def _subject(self):
        self._fresh()
        peer=self._authority.current_peer()
        if peer is None:raise TransferError('photo_relocation_original_owner_ended')
        identity=self._authority.identity
        return [identity.receiver_id,identity.receiver_identity_sha256,peer.peer_id,peer.identity_sha256,peer.pairing_epoch]

    def _read_intent(self):
        if self._held:raise TransferError('photo_relocation_owner_held')
        subject=self._subject()
        actual=self._db.execute('SELECT value FROM meta WHERE key=?',(self._INTENT_KEY,)).fetchone()
        intent=None
        if actual is not None:
            blob,=actual
            if type(blob) is not bytes or not 28<=len(blob)<=self._MAX_CIPHER_BYTES:
                raise TransferError('photo_relocation_invalid_owner_intent')
            plain=self._protection.unseal(blob,self._INTENT_DOMAIN);body=strict_json(plain)
            if (type(body) is not dict or set(body)!={'db','subject','intent'} or body['db']!=list(self._identity)
                    or body['subject']!=subject or canonical(body)!=plain):
                raise TransferError('photo_relocation_original_owner_changed')
            intent=RelocationOwnerIntent.parse(body['intent'])
        elif self._db.execute('SELECT 1 FROM meta WHERE key=?',(self._PREPARED_KEY,)).fetchone() is not None:
            self._held=True
            raise TransferError('photo_relocation_original_owner_changed')
        if self._observed is not None and intent!=self._observed or self._subject()!=subject:
            self._held=True
            raise TransferError('photo_relocation_original_owner_changed')
        self._observed=intent
        return intent

    def read_intent(self):
        """Read without bootstrapping; absence alone must not authorize a path."""
        return self._read_intent()

    def require_intent(self,expected):
        if type(expected) is not RelocationOwnerIntent or self._read_intent()!=expected:
            raise TransferError('photo_relocation_original_owner_changed')
        return True

    def _issue_confirmed_action(self,native_current):
        """Private entry for a native confirmation owner, never an IPC action."""
        if not callable(native_current):raise TransferError('photo_relocation_original_owner_required')
        return NativePhotoDestinationAction(self,self._clock,native_current=lambda:native_current() is True)

    def record_confirmed_intent(self,action,records,destination,confirmed_sha256):
        with self._confirming_intent(action,records,destination,confirmed_sha256) as (intent,_):
            return intent

    @contextmanager
    def _confirming_intent(self,action,records,destination,confirmed_sha256):
        if type(action) is not NativePhotoDestinationAction:
            raise TransferError('photo_relocation_original_owner_required')
        action.consume(self)
        intent=RelocationOwnerIntent.for_selection(records,destination)
        if intent.selection_sha256!=confirmed_sha256:raise TransferError('photo_relocation_confirmation_changed')
        subject=self._subject()

        def current():
            action.validate(self)
            if self.saved_book_version()!=intent.book_sha256:
                raise TransferError('photo_relocation_original_book_changed')
            if self._subject()!=subject:raise TransferError('photo_relocation_original_owner_changed')
            destination.verify()
            return True

        with self.activity(current,exclusive=True) as lease:
            if lease is None:raise TransferError('photo_relocation_activity_busy')
            for record in records:
                require_media_directory(destination.path+'/'+record.source)
                require_media_directory(destination.path+'/'+record.target)
            # No journal lock while the independent database transaction is open.
            with self._transaction():
                lease()
                if self._read_intent() is not None:raise TransferError('photo_relocation_owner_already_recorded')
                blob=self._protection.seal(canonical(dict(db=list(self._identity),subject=subject,intent=intent.wire())),self._INTENT_DOMAIN)
                self._db.execute('INSERT INTO meta(key,value) VALUES(?,?)',(self._INTENT_KEY,blob))
                lease()
            self.require_intent(intent);lease()
            yield intent,lease

    def prepare_original(self,action,journal,records,destination,confirmed_sha256):
        """Prepare and bind the exact readback while the original action lives.

        No public setter for a checkpoint loaded after a restart. The intent
        survives any split between independent commits and prevents a retry.
        No media file is moved by this operation.
        """
        with self._prepared_original(action,journal,records,destination,confirmed_sha256) as (intent,snapshot,checkpoint,_):
            return intent,checkpoint

    @contextmanager
    def _prepared_original(self,action,journal,records,destination,confirmed_sha256):
        from magnolie_media_relocation_journal import ProtectedMediaRelocationJournal, RelocationOwnerCheckpoint
        if type(journal) is not ProtectedMediaRelocationJournal or journal._authority is not self._authority:
            raise TransferError('photo_relocation_original_owner_required')
        with self._confirming_intent(action,records,destination,confirmed_sha256) as (intent,lease):
            def current():
                lease();return self.require_intent(intent)
            initial=journal.read();current()
            snapshot=journal.prepare(journal.issue_action(_native_current=current),initial,records,confirmed_sha256,
                destination,require_original=current)
            if snapshot.records!=records or snapshot.attempts or snapshot.outcomes:
                raise TransferError('photo_relocation_original_journal_changed')
            checkpoint=RelocationOwnerCheckpoint.from_snapshot(snapshot,destination)
            if journal.require_prepared(checkpoint.prepared_version,intent.selection_sha256)!=snapshot:
                raise TransferError('photo_relocation_original_journal_changed')
            subject=self._subject()
            body=dict(db=list(self._identity),subject=subject,intent=intent.wire(),checkpoint=checkpoint.wire())
            with self._transaction():
                current()
                if self._db.execute('SELECT 1 FROM meta WHERE key=?',(self._PREPARED_KEY,)).fetchone() is not None:
                    raise TransferError('photo_relocation_preparation_already_recorded')
                cipher=self._protection.seal(canonical(body),self._PREPARED_DOMAIN)
                self._db.execute('INSERT INTO meta(key,value) VALUES(?,?)',(self._PREPARED_KEY,cipher))
                current()
            if self.require_checkpoint(intent)!=checkpoint:
                raise TransferError('photo_relocation_original_checkpoint_changed')
            if journal.require_prepared(checkpoint.prepared_version,intent.selection_sha256)!=snapshot:
                raise TransferError('photo_relocation_original_journal_changed')
            current();yield intent,snapshot,checkpoint,current

    def _move_original_animation_selection(self,action,journal,records,destination,confirmed_sha256):
        """Private end-to-end primitive; no restart or standalone execution API."""
        from magnolie_media_relocation_journal import RelocationOwnerCheckpoint
        with self._prepared_original(action,journal,records,destination,confirmed_sha256) as (intent,snapshot,witness,live):
            owner=self
            class Binding:
                def require_active(self,source,before):
                    if (source is not journal or RelocationOwnerCheckpoint.from_snapshot(before,destination)!=witness
                            or not current()):
                        raise TransferError('photo_relocation_original_checkpoint_changed')

                def advance(self,source,before,after,ordinal,kind):
                    nonlocal witness
                    self.require_active(source,before)
                    if kind=='attempt':
                        expected=replace(before,attempts=tuple(sorted((*before.attempts,ordinal))))
                    elif kind=='outcome':
                        moved=replace(before.records[ordinal],phase='moved')
                        expected=replace(before,outcomes=tuple(sorted((*before.outcomes,(ordinal,moved)))))
                    else:
                        raise TransferError('photo_relocation_original_checkpoint_changed')
                    if replace(after,outcome_version=before.outcome_version)!=expected:
                        raise TransferError('photo_relocation_original_checkpoint_changed')
                    next_witness=RelocationOwnerCheckpoint.from_snapshot(after,destination)
                    if next_witness.outcome_version==witness.outcome_version:
                        raise TransferError('photo_relocation_original_checkpoint_changed')
                    owner._advance_checkpoint(intent,witness,next_witness,live)
                    witness=next_witness
                    self.require_active(source,after)

            def current():
                live()
                if self.require_checkpoint(intent)!=witness:
                    raise TransferError('photo_relocation_original_checkpoint_changed')
                return True

            binding=Binding()
            for ordinal in range(len(records)):
                snapshot=journal._complete_member(journal.issue_action(_native_current=current),snapshot,ordinal,'moved',
                    destination,require_original=current,rename=True,owner_checkpoint=binding)
            if journal.require_prepared(witness.prepared_version,intent.selection_sha256)!=snapshot:
                raise TransferError('photo_relocation_original_journal_changed')
            current();return intent,witness

    def _advance_checkpoint(self,intent,before,after,live):
        # Called only by the live journal transition, after its durable readback.
        # Never acquire the journal lock while holding the phone DB transaction.
        subject=self._subject()
        body=dict(db=list(self._identity),subject=subject,intent=intent.wire(),checkpoint=after.wire())
        with self._transaction():
            live()
            if self.require_checkpoint(intent)!=before:
                raise TransferError('photo_relocation_original_checkpoint_changed')
            cipher=self._protection.seal(canonical(body),self._PREPARED_DOMAIN)
            changed=self._db.execute('UPDATE meta SET value=? WHERE key=?',(cipher,self._PREPARED_KEY))
            if changed.rowcount!=1:raise TransferError('photo_relocation_original_checkpoint_changed')
            live()
        if self.require_checkpoint(intent)!=after:
            raise TransferError('photo_relocation_original_checkpoint_changed')
        live()

    def require_checkpoint(self,intent):
        """Read the original outer checkpoint, not the journal's current head."""
        from magnolie_media_relocation_journal import RelocationOwnerCheckpoint
        self.require_intent(intent);subject=self._subject()
        row=self._db.execute('SELECT value FROM meta WHERE key=?',(self._PREPARED_KEY,)).fetchone()
        if row is None:raise TransferError('photo_relocation_original_checkpoint_required')
        cipher,=row
        if type(cipher) is not bytes or not 28<=len(cipher)<=self._MAX_CIPHER_BYTES:
            raise TransferError('photo_relocation_invalid_owner_checkpoint')
        plain=self._protection.unseal(cipher,self._PREPARED_DOMAIN);body=strict_json(plain)
        if (type(body) is not dict or set(body)!={'db','subject','intent','checkpoint'} or canonical(body)!=plain
                or body['db']!=list(self._identity) or body['subject']!=subject or body['intent']!=intent.wire()):
            raise TransferError('photo_relocation_original_checkpoint_changed')
        witness=RelocationOwnerCheckpoint.parse(body['checkpoint'])
        if ((witness.selection_sha256,witness.book_sha256,witness.destination_sha256)!=
                (intent.selection_sha256,intent.book_sha256,intent.destination_sha256) or self._subject()!=subject):
            raise TransferError('photo_relocation_original_checkpoint_changed')
        self.require_intent(intent)
        if self._db.execute('SELECT value FROM meta WHERE key=?',(self._PREPARED_KEY,)).fetchone()!=row:
            raise TransferError('photo_relocation_original_checkpoint_changed')
        return witness
