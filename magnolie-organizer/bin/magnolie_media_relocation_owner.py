"""Independent native relocation intent in the existing phone DB (#429).

No file moves, journal bootstrap, recovery or app bridge. A durable intent
is a hold, not permission to resume a move after restart.
"""
from dataclasses import dataclass
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
        return intent
