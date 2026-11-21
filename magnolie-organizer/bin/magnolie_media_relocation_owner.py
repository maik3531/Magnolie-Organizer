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
from magnolie_file_transfer import TransferError, _portable_path
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
    _FOLDER_KEY='media_relocation_folder_plan:local:v1'
    _FOLDER_DOMAIN='media-relocation-folder-plan-v1/local'
    _FOLDER_ATTEMPT_KEY='media_relocation_folder_attempt:local:v1'
    _FOLDER_ATTEMPT_DOMAIN='media-relocation-folder-attempt-v1/local'
    _FOLDER_RESULT_KEY='media_relocation_folder_result:local:v1'
    _FOLDER_RESULT_DOMAIN='media-relocation-folder-result-v1/local'
    _FOLDER_PREPARED_KEY='media_relocation_folder_prepared:local:v1'
    _FOLDER_PREPARED_DOMAIN='media-relocation-folder-prepared-v1/local'
    _MAX_CIPHER_BYTES=16384

    def __init__(self,authority,*,monotonic_ms=lambda:time.monotonic_ns()//1_000_000):
        if type(authority) is not NativeDesktopFileAuthority or not callable(monotonic_ms):
            raise TransferError('photo_relocation_original_owner_required')
        self._authority=authority;self._clock=monotonic_ms;self._observed=None;self._folder_observed=None;self._held=False
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
        if self._folder_observed is not None or self._db.execute(
                'SELECT 1 FROM meta WHERE key IN (?,?,?,?) OR key GLOB ? OR key GLOB ? LIMIT 1',
                (self._FOLDER_KEY,self._FOLDER_ATTEMPT_KEY,self._FOLDER_RESULT_KEY,self._FOLDER_PREPARED_KEY,
                 self._FOLDER_ATTEMPT_KEY+':*',self._FOLDER_RESULT_KEY+':*')).fetchone():
            raise TransferError('photo_relocation_folder_plan_held')
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

    def read_folder_intent(self):
        """Read the independently sealed plan witness, never a mkdir grant."""
        if self._held:raise TransferError('photo_relocation_owner_held')
        subject=self._subject()
        row=self._db.execute('SELECT value FROM meta WHERE key=?',(self._FOLDER_KEY,)).fetchone()
        intent=None
        if row is not None:
            blob,=row
            if type(blob) is not bytes or not 28<=len(blob)<=self._MAX_CIPHER_BYTES:
                raise TransferError('photo_relocation_invalid_owner_intent')
            plain=self._protection.unseal(blob,self._FOLDER_DOMAIN);body=strict_json(plain)
            if (type(body) is not dict or set(body)!={'db','subject','intent'} or body['db']!=list(self._identity)
                    or body['subject']!=subject or canonical(body)!=plain):
                raise TransferError('photo_relocation_original_owner_changed')
            intent=RelocationOwnerIntent.parse(body['intent'])
        if (self._folder_observed is not None and intent!=self._folder_observed or self._subject()!=subject
                or self._db.execute('SELECT value FROM meta WHERE key=?',(self._FOLDER_KEY,)).fetchone()!=row):
            self._held=True
            raise TransferError('photo_relocation_original_owner_changed')
        self._folder_observed=intent
        return intent

    def _record_confirmed_folder_plan(self,action,journal,plan,destination):
        """Commit the last confirmed plan before any possible namespace write."""
        with self._confirming_folder_plan(action,journal,plan,destination) as (intent,_):return intent

    @contextmanager
    def _confirming_folder_plan(self,action,journal,plan,destination):
        from magnolie_media_relocation_journal import ProtectedMediaRelocationJournal
        from magnolie_media_relocation_record import (GifRelocationFolderPlan, bind_gif_relocation_folder_plan,
            inspect_relocation_target_parents)
        if (type(action) is not NativePhotoDestinationAction or type(journal) is not ProtectedMediaRelocationJournal
                or journal._authority is not self._authority or type(plan) is not GifRelocationFolderPlan
                or bind_gif_relocation_folder_plan(plan.members,destination)!=plan
                or not any(member.target_parents.missing for member in plan.members)):
            raise TransferError('photo_relocation_native_confirmation_required')
        action.consume(self);subject=self._subject();first=plan.members[0]
        intent=RelocationOwnerIntent(first.operation,plan.selection_sha256,first.book_sha256,
            relocation_destination_digest(destination),tuple(sorted(member.original_mapping_sha256 for member in plan.members)))
        def current():
            action.validate(self)
            if self.saved_book_version()!=intent.book_sha256 or self._subject()!=subject:
                raise TransferError('photo_relocation_original_owner_changed')
            destination.verify();return True
        with self.activity(current,exclusive=True) as lease:
            if lease is None:raise TransferError('photo_relocation_activity_busy')
            empty=journal.read()
            if empty.associated or empty.records or empty.outcome_version is not None or self._read_intent() is not None:
                raise TransferError('photo_relocation_owner_already_recorded')
            for member in plan.members:
                if inspect_relocation_target_parents(destination,member.target,lease)!=member.target_parents:
                    raise TransferError('photo_relocation_confirmation_changed')
            with self._transaction():
                lease()
                if self._read_intent() is not None:raise TransferError('photo_relocation_owner_already_recorded')
                blob=self._protection.seal(canonical(dict(db=list(self._identity),subject=subject,intent=intent.wire())),self._FOLDER_DOMAIN)
                self._db.execute('INSERT INTO meta(key,value) VALUES(?,?)',(self._FOLDER_KEY,blob))
                lease()
            if self.read_folder_intent()!=intent or journal.read()!=empty:
                raise TransferError('photo_relocation_original_owner_changed')
            lease();yield intent,lease

    def _spend_first_folder_attempt(self,action,journal,plan,destination):
        """Private cut point before the first mkdir; the result grants nothing."""
        with self._first_folder_attempt(action,journal,plan,destination) as (intent,_,__):return intent

    @contextmanager
    def _first_folder_attempt(self,action,journal,plan,destination):
        with self._confirming_folder_plan(action,journal,plan,destination) as (intent,lease):
            path=plan.missing_parents()[0]
            member=next(item for item in plan.members if item.target.startswith(path+'/'))
            body,spent=self._bind_folder_attempt(intent,destination,path,member.target_parents.existing,0,lease,{})
            yield intent,body,spent

    def _bind_folder_attempt(self,intent,destination,path,parent_keys,ordinal,lease,committed):
        from magnolie_media_relocation_record import inspect_relocation_target_parents
        suffix=':'+str(ordinal) if ordinal else ''
        key=self._FOLDER_ATTEMPT_KEY+suffix
        body=dict(format=1,db=list(self._identity),subject=self._subject(),intent=intent.wire(),
            path=path,parents=[list(value) for value in parent_keys])
        def current():
            lease()
            if (self.read_folder_intent()!=intent or any(
                    self._db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()!=(cipher,)
                    for name,cipher in committed.items())):
                raise TransferError('photo_relocation_folder_attempt_held')
            return lease()
        observed=inspect_relocation_target_parents(destination,path+'/probe',current)
        if observed.existing!=parent_keys or observed.missing!=(path.rsplit('/',1)[-1],):
            raise TransferError('photo_relocation_confirmation_changed')
        expected=canonical(body)
        with self._transaction():
            current()
            if self._db.execute('SELECT 1 FROM meta WHERE key=?',(key,)).fetchone():
                raise TransferError('photo_relocation_folder_attempt_held')
            blob=self._protection.seal(expected,self._FOLDER_ATTEMPT_DOMAIN)
            self._db.execute('INSERT INTO meta(key,value) VALUES(?,?)',(key,blob))
            current()
        if (self._db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()!=(blob,)
                or self._protection.unseal(blob,self._FOLDER_ATTEMPT_DOMAIN)!=expected):
            raise TransferError('photo_relocation_folder_attempt_held')
        committed[key]=blob;current();return body,current

    def _create_first_confirmed_folder(self,action,journal,plan,destination):
        """Create only the first planned parent and bind its verified native inode."""
        intent,created=self._create_confirmed_folders(action,journal,plan,destination,first_only=True)
        return intent,created[0][1]

    def _create_confirmed_folders(self,action,journal,plan,destination,*,first_only=False):
        with self._creating_confirmed_folders(action,journal,plan,destination,first_only=first_only) as (intent,created,_):
            return intent,created

    @contextmanager
    def _creating_confirmed_folders(self,action,journal,plan,destination,*,first_only=False):
        from magnolie_media_relocation_record import _install_spent_folder, inspect_relocation_target_parents
        with self._confirming_folder_plan(action,journal,plan,destination) as (intent,lease):
            planned=plan.missing_parents();committed={};created=[];known={'':destination.ancestor_keys[0]}
            for member in plan.members:
                parts=member.target.split('/')
                for index,identity in enumerate(member.target_parents.existing):
                    known['/'.join(parts[:index])]=identity
            def chain(path):
                parts=path.split('/')
                return tuple(known['/'.join(parts[:index])] for index in range(len(parts)))
            def require_result(path,keys,current):
                observed=inspect_relocation_target_parents(destination,path+'/probe',current)
                if observed.missing or observed.existing!=keys:
                    raise TransferError('photo_relocation_parent_changed')
            for ordinal,path in enumerate(planned[:1] if first_only else planned):
                parent_keys=chain(path)
                attempt,spent=self._bind_folder_attempt(intent,destination,path,parent_keys,ordinal,lease,committed)
                identity=_install_spent_folder(destination,path,parent_keys,intent.operation,spent)
                require_result(path,parent_keys+(identity,),spent)
                expected=canonical(dict(attempt=attempt,created=list(identity)))
                key=self._FOLDER_RESULT_KEY+(':'+str(ordinal) if ordinal else '')
                with self._transaction():
                    spent()
                    blob=self._protection.seal(expected,self._FOLDER_RESULT_DOMAIN)
                    self._db.execute('INSERT INTO meta(key,value) VALUES(?,?)',(key,blob))
                    spent()
                if (self._db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()!=(blob,)
                        or self._protection.unseal(blob,self._FOLDER_RESULT_DOMAIN)!=expected):
                    raise TransferError('photo_relocation_folder_attempt_held')
                committed[key]=blob;require_result(path,parent_keys+(identity,),spent)
                known[path]=identity;created.append((path,identity))
            for path,identity in created:require_result(path,chain(path)+(identity,),spent)
            yield intent,tuple(created),spent

    def _materialize_confirmed_folder_selection(self,action,journal,plan,destination):
        """Build rename candidates during the original action, not from a later restart."""
        with self._materializing_folder_selection(action,journal,plan,destination) as (intent,records,_):
            return intent,records

    @contextmanager
    def _materializing_folder_selection(self,action,journal,plan,destination):
        from magnolie_media_relocation_record import _materialize_gif_folder_plan
        with self._creating_confirmed_folders(action,journal,plan,destination) as (intent,created,spent):
            records=_materialize_gif_folder_plan(plan,destination,created,spent)
            spent();yield intent,records,spent

    def _prepare_after_gif_folder_creation(self,action,journal,plan,destination):
        """Prepare the exact journal under the same live approval; never rename."""
        from magnolie_media_relocation_journal import RelocationOwnerCheckpoint
        with self._materializing_folder_selection(action,journal,plan,destination) as (folder_intent,records,current):
            intent=RelocationOwnerIntent.for_selection(records,destination)
            if ((intent.operation,intent.book_sha256,intent.destination_sha256,intent.mappings)!=
                    (folder_intent.operation,folder_intent.book_sha256,folder_intent.destination_sha256,folder_intent.mappings)):
                raise TransferError('photo_relocation_confirmation_changed')
            initial=journal.read();current()
            snapshot=journal.prepare(journal.issue_action(_native_current=current),initial,records,intent.selection_sha256,
                destination,require_original=current)
            if snapshot.records!=records or snapshot.attempts or snapshot.outcomes:
                raise TransferError('photo_relocation_original_journal_changed')
            checkpoint=RelocationOwnerCheckpoint.from_snapshot(snapshot,destination)
            def require_journal():
                if journal.require_prepared(checkpoint.prepared_version,intent.selection_sha256)!=snapshot:
                    raise TransferError('photo_relocation_original_journal_changed')
                current()
            require_journal()
            expected=canonical(dict(db=list(self._identity),subject=self._subject(),folder=folder_intent.wire(),
                intent=intent.wire(),checkpoint=checkpoint.wire()))
            with self._transaction():
                current()
                if self._db.execute('SELECT 1 FROM meta WHERE key=?',(self._FOLDER_PREPARED_KEY,)).fetchone():
                    raise TransferError('photo_relocation_preparation_already_recorded')
                blob=self._protection.seal(expected,self._FOLDER_PREPARED_DOMAIN)
                self._db.execute('INSERT INTO meta(key,value) VALUES(?,?)',(self._FOLDER_PREPARED_KEY,blob))
                current()
            if (self._db.execute('SELECT value FROM meta WHERE key=?',(self._FOLDER_PREPARED_KEY,)).fetchone()!=(blob,)
                    or self._protection.unseal(blob,self._FOLDER_PREPARED_DOMAIN)!=expected):
                raise TransferError('photo_relocation_original_checkpoint_changed')
            require_journal();return folder_intent,checkpoint

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

    def inspect_bound_recovery(self,journal,destination,*,require_original):
        """Observe a restarted operation from its sealed owner, never its journal head."""
        from magnolie_media_relocation_journal import ProtectedMediaRelocationJournal
        if (type(journal) is not ProtectedMediaRelocationJournal or journal._authority is not self._authority
                or not callable(require_original) or require_original() is not True):
            raise TransferError('photo_relocation_original_owner_required')
        intent=self.read_intent()
        if intent is None:raise TransferError('photo_relocation_original_owner_required')
        if relocation_destination_digest(destination)!=intent.destination_sha256:
            raise TransferError('photo_relocation_original_destination_required')
        witness=self.require_checkpoint(intent)
        def current():
            if require_original() is not True:
                raise TransferError('photo_relocation_original_owner_ended')
            if self.require_checkpoint(intent)!=witness:
                raise TransferError('photo_relocation_original_checkpoint_changed')
            return True
        return journal.inspect_original_recovery(witness,destination,require_original=current)

    def observe_completed_target(self,intent,journal,mapping,accepted,receipt,current_binding,*,require_original):
        """Use the exact terminal selection for readback, never the old name.

        The caller still owns the live protected mapping and Saved receipt.
        Neither a partial operation nor a plain historical journal can opt in.
        """
        from magnolie_media_relocation_journal import ProtectedMediaRelocationJournal, RelocationOwnerCheckpoint
        from magnolie_photo_mappings import NativeSavedPhotoMapping
        if (type(journal) is not ProtectedMediaRelocationJournal or journal._authority is not self._authority
                or type(intent) is not RelocationOwnerIntent or type(mapping) is not NativeSavedPhotoMapping
                or not callable(require_original)):
            raise TransferError('photo_relocation_original_owner_required')
        if mapping.protected_record_sha256 not in intent.mappings or relocation_destination_digest(mapping.destination)!=intent.destination_sha256:
            raise TransferError('photo_relocation_original_receipt_changed')
        witness=self.require_checkpoint(intent)

        def current():
            if require_original() is not True:return False
            if self.saved_book_version()!=intent.book_sha256:
                raise TransferError('photo_relocation_original_book_changed')
            if self.require_checkpoint(intent)!=witness:
                raise TransferError('photo_relocation_original_checkpoint_changed')
            return True

        if not current():raise TransferError('photo_relocation_original_owner_ended')
        snapshot=journal.require_prepared(witness.prepared_version,intent.selection_sha256)
        if (RelocationOwnerCheckpoint.from_snapshot(snapshot,mapping.destination)!=witness
                or RelocationOwnerIntent.for_selection(snapshot.records,mapping.destination)!=intent):
            raise TransferError('photo_relocation_original_journal_changed')
        ordinals=tuple(range(len(snapshot.records)))
        if (snapshot.attempts!=ordinals or tuple(i for i,_ in snapshot.outcomes)!=ordinals
                or any(record.phase!='moved' for _,record in snapshot.outcomes)):
            raise TransferError('photo_relocation_selection_held')
        return journal.observe_moved_saved_target(snapshot,mapping,accepted,receipt,current_binding,require_original=current)


class RelocationComparison:
    """Read-only comparison view inside the caller's existing media lane."""
    def __init__(self,owner,journal,require_activity,mappings):
        self._owner=owner;self._journal=journal;self._activity=require_activity
        self._mappings=mappings;self._roots=None
        require_activity()
        self._intent=owner.read_intent();self._snapshot=journal.read()
        self._witness=None
        if self._intent is None:
            if self._snapshot.records:raise TransferError('photo_relocation_original_owner_required')
        else:
            self._witness=owner.require_checkpoint(self._intent)
            snapshot=self._snapshot;witness=self._witness;intent=self._intent
            if (not snapshot.associated or not snapshot.records
                    or (snapshot.version,snapshot.outcome_version)!=(witness.prepared_version,witness.outcome_version)
                    or any((record.operation,record.selection_sha256,record.book_sha256)!=(intent.operation,intent.selection_sha256,intent.book_sha256)
                        for record in snapshot.records)
                    or tuple(sorted(record.original_mapping_sha256 for record in snapshot.records))!=intent.mappings):
                raise TransferError('photo_relocation_original_journal_changed')
            ordinals=tuple(range(len(snapshot.records)))
            if (snapshot.attempts!=ordinals or tuple(i for i,_ in snapshot.outcomes)!=ordinals
                    or any(record.phase!='moved' for _,record in snapshot.outcomes)):
                raise TransferError('photo_relocation_selection_held')
        self._current()

    def _current(self):
        self._activity()
        if self._owner.read_intent()!=self._intent:
            raise TransferError('photo_relocation_original_owner_changed')
        if self._intent is not None:
            if self._owner.saved_book_version()!=self._intent.book_sha256:
                raise TransferError('photo_relocation_original_book_changed')
            if self._owner.require_checkpoint(self._intent)!=self._witness:
                raise TransferError('photo_relocation_original_checkpoint_changed')
        return True

    def require_current(self):
        self._current()
        if self._journal.read()!=self._snapshot:
            raise TransferError('photo_relocation_original_journal_changed')
        if self._roots is not None and self._mappings.read()!=self._roots[0]:
            raise TransferError('photo_relocation_original_mapping_changed')
        return self._current()

    def _original_mappings(self):
        if self._roots is None:
            snapshot,mappings=self._mappings._lookup_relocation_originals(self._intent.mappings)
            records={item.original_mapping_sha256:item for item in self._snapshot.records}
            for mapping in mappings:
                item=records[mapping.protected_record_sha256]
                if (relocation_destination_digest(mapping.destination)!=self._intent.destination_sha256
                        or (mapping.relative_path,mapping.parent_keys,mapping.file_key)!=(item.source,item.source_parents,item.file.file_key)):
                    raise TransferError('photo_relocation_original_mapping_changed')
            self._roots=snapshot,mappings
        return self._roots[1]

    def require_unmapped(self,association):
        if self._intent is None:return
        self._current()
        if any(mapping.association==association for mapping in self._original_mappings()):
            raise TransferError('photo_relocation_unmapped_target_held')

    def require_unreserved_output(self,destination,relative_path):
        if self._intent is None:return
        self._current()
        original=self._original_mappings()[0].destination;relative=_portable_path(relative_path).casefold()
        if destination!=original:
            # Related roots and aliases cannot be compared just by relative path.
            if (destination.ancestor_keys[0] in original.ancestor_keys
                    or original.ancestor_keys[0] in destination.ancestor_keys):
                raise TransferError('photo_relocation_aliased_target_held')
            return
        def overlap(left,right):
            return left==right or left.startswith(right+'/') or right.startswith(left+'/')
        if any(overlap(relative,path.casefold()) for item in self._snapshot.records for path in (item.source,item.target)):
            raise TransferError('photo_relocation_aliased_target_held')

    def observe(self,mapping,accepted,receipt,current_binding):
        from magnolie_photo_target import observe_saved_target
        self._current()
        if self._intent is not None:
            if mapping.protected_record_sha256 in self._intent.mappings:
                # Construction pinned the entire terminal selection and the
                # external witness. Keep that same witness live, rather than
                # wrapping this guard in a second owner/checkpoint read loop.
                if RelocationOwnerIntent.for_selection(self._snapshot.records,mapping.destination)!=self._intent:
                    raise TransferError('photo_relocation_original_receipt_changed')
                return self._journal.observe_moved_saved_target(self._snapshot,mapping,accepted,receipt,
                    current_binding,require_original=self._current)
            if any(record.file.file_key==mapping.file_key or
                    (record.root_key==mapping.destination.ancestor_keys[0] and mapping.relative_path.casefold() in
                    (record.source.casefold(),record.target.casefold())) for record in self._snapshot.records):
                raise TransferError('photo_relocation_aliased_target_held')
        def binding():
            self._current();return current_binding()
        return observe_saved_target(accepted,receipt,binding)
