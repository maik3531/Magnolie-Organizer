"""Authority-neutral native book save/recovery chain.

Subclasses own their independent consent record, key/domain, selected sources
and filesystem policy. This class grants no DAV/Notes/account authority and
never creates consent. Primary-file recognition is not a saved-writer witness.
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
import re

from magnolie_native_book_json import book_hash
from magnolie_personal_actor_store import NativeProducerBookSnapshot


HEX = re.compile('[0-9a-f]{64}')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _strict_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise PermissionError('contact_approval_store_invalid')
        value[key] = item
    return value


@dataclass(frozen=True)
class NativeContactSourcePrimaryBook:
    """Authenticated primary-file observation, explicitly NOT a saved witness."""
    binding: str = field(repr=False)
    saved_sha256: str = field(repr=False)
    content_sha256: str = field(repr=False)


@dataclass(frozen=True)
class NativeContactApprovalSaveIntent:
    """Native before-save correlation, not a document or renderer capability."""
    store: object = field(repr=False)
    key_fingerprint: str = field(repr=False)
    generation: str = field(repr=False)
    token: str = field(repr=False)
    previous: object = field(repr=False)
    next_content: str = field(repr=False)


class NativeContactBookSaveChain:
    def _save_chain_active(self, payload):
        raise NotImplementedError('Independent native consent selection required')

    def _remove_intent(self, directory):
        try:
            self._private(os.stat('.book-intent.json', dir_fd=directory, follow_symlinks=False))
        except FileNotFoundError:
            return
        os.unlink('.book-intent.json', dir_fd=directory)
        os.fsync(directory)

    def _intent(self, directory, key, payload):
        try:
            raw = self._read(directory, '.book-intent.json', 4096)
        except FileNotFoundError:
            return None
        envelope = json.loads(raw, object_pairs_hook=_strict_pairs)
        if not isinstance(envelope, dict) or set(envelope) != {'payload', 'mac'}:
            raise PermissionError('contact_approval_save_intent_invalid')
        intent, signature = envelope['payload'], envelope['mac']
        if (not isinstance(signature, str) or HEX.fullmatch(signature) is None or
                not hmac.compare_digest(signature, self._tag(key, b'book-save', _json(intent))) or
                not isinstance(intent, dict) or set(intent) != {'version', 'generation', 'book', 'old', 'new', 'token'} or
                type(intent['version']) is not int or intent['version'] != 1 or
                any(not isinstance(intent[name], str) or HEX.fullmatch(intent[name]) is None
                    for name in ('generation', 'book', 'old', 'new', 'token')) or
                intent['generation'] != payload['generation'] or intent['book'] != payload['book'] or
                payload['content'] not in (intent['old'], intent['new']) or not self._save_chain_active(payload)):
            raise PermissionError('contact_approval_save_intent_invalid')
        return intent

    def prepare_save(self, previous, next_text):
        """Before native invalidation/write; proposed hashes cannot create consent."""
        active = self._active_record()
        if active is None:
            return None
        if type(previous) not in (NativeProducerBookSnapshot, NativeContactSourcePrimaryBook) or not isinstance(next_text, str):
            raise TypeError('contact_approval_native_save_required')
        proposed = json.loads(next_text, object_pairs_hook=_strict_pairs)
        if not isinstance(proposed, dict):
            raise ValueError('contact_approval_native_book_required')
        next_content = book_hash(proposed)
        observe = self._primary if type(previous) is NativeContactSourcePrimaryBook else self._saved
        snapshot, binding = observe()
        key, payload = active
        if snapshot != previous or payload['content'] != previous.content_sha256 or not hmac.compare_digest(
                payload['book'], self._tag(key, b'book', binding.encode('utf-8'))):
            raise PermissionError('contact_approval_native_book_changed')
        intent = {'version': 1, 'generation': payload['generation'], 'book': payload['book'],
                  'old': previous.content_sha256, 'new': next_content, 'token': os.urandom(32).hex()}
        with self._locked() as directory:
            actual_key, actual_payload = self._record(directory)
            if actual_key != key or actual_payload != payload:
                raise PermissionError('contact_approval_native_context_changed')
            if self._intent(directory, key, payload) is not None:
                raise PermissionError('contact_approval_save_pending')
            self._write(directory, '.book-intent.json', _json({'payload': intent,
                'mac': self._tag(key, b'book-save', _json(intent))}))
            if self._intent(directory, key, payload) != intent:
                raise PermissionError('contact_approval_save_unconfirmed')
        if observe() != (snapshot, binding):
            raise PermissionError('contact_approval_native_book_changed')
        return NativeContactApprovalSaveIntent(self, hashlib.sha256(key).hexdigest(), payload['generation'],
                                              intent['token'], previous, next_content)

    def _advance_saved(self, confirmed, expected=None, *, primary=False):
        # All native callbacks stay outside the private file lock. No account or
        # keyring IO is allowed in ordinary autosave's content chain.
        observe = self._primary if primary else self._saved
        snapshot, binding = observe()
        if snapshot != confirmed:
            raise PermissionError('contact_approval_native_saved_book_required')
        with self._locked() as directory:
            key, payload = self._record(directory)
            intent = self._intent(directory, key, payload)
            if intent is None:
                if expected is None:
                    return None
                raise PermissionError('contact_approval_save_intent_missing')
            if not hmac.compare_digest(payload['book'], self._tag(key, b'book', binding.encode('utf-8'))):
                raise PermissionError('contact_approval_native_book_changed')
            if expected is not None and (expected.store is not self or
                    expected.key_fingerprint != hashlib.sha256(key).hexdigest() or
                    expected.generation != intent['generation'] or expected.token != intent['token'] or
                    expected.next_content != intent['new'] or expected.previous.content_sha256 != intent['old'] or
                    expected.previous == snapshot or snapshot.content_sha256 != intent['new']):
                raise PermissionError('contact_approval_native_save_changed')
            if (snapshot.content_sha256 not in (intent['old'], intent['new']) or
                    payload['content'] == intent['new'] and snapshot.content_sha256 != intent['new']):
                raise PermissionError('contact_approval_save_outcome_unknown')
            if payload['content'] != snapshot.content_sha256:
                payload = dict(payload, content=snapshot.content_sha256)
                # Store-specific sealing; retain the intent until the advanced
                # record is read back, preserving known old/new crash recovery.
                self._write_chain_record(directory, key, payload)
                actual_key, actual_payload = self._record(directory)
                if actual_key != key or actual_payload != payload:
                    raise PermissionError('contact_approval_save_unconfirmed')
            self._remove_intent(directory)
        if observe() != (snapshot, binding):
            raise PermissionError('contact_approval_native_book_changed')
        return snapshot.content_sha256

    def confirm_save(self, intent, confirmed):
        """Only after actual writer success AND all repair checks."""
        if type(intent) is not NativeContactApprovalSaveIntent or intent.store is not self:
            raise TypeError('contact_approval_native_save_intent_required')
        return self._advance_saved(confirmed, intent)

    def recover_saved(self, confirmed):
        if self._active_record() is None:
            return None
        return self._advance_saved(confirmed)

    def recover_primary(self, observed):
        """Known old/new disk recovery only; never issues a saved witness/grant."""
        if self._active_record() is None:
            return None
        if type(observed) is not NativeContactSourcePrimaryBook:
            raise TypeError('contact_approval_native_primary_required')
        return self._advance_saved(observed, primary=True)

    def _primary(self):
        if self._capture_primary is None:
            raise PermissionError('contact_approval_native_primary_required')
        observed, binding = self._capture_primary(), self._binding()
        if (type(observed) is not NativeContactSourcePrimaryBook or
                not isinstance(binding, str) or not 1 <= len(binding) <= 8192 or observed.binding != binding or
                any(not isinstance(value, str) or HEX.fullmatch(value) is None
                    for value in (observed.saved_sha256, observed.content_sha256))):
            raise PermissionError('contact_approval_native_primary_required')
        return observed, binding

    def _saved(self):
        snapshot, binding = self._capture(), self._binding()
        if (type(snapshot) is not NativeProducerBookSnapshot or
                not isinstance(binding, str) or not 1 <= len(binding) <= 8192 or
                hashlib.sha256(snapshot.text.encode('utf-8')).hexdigest() != snapshot.content_sha256 or
                book_hash(snapshot.book()) != snapshot.content_sha256):
            raise PermissionError('contact_approval_native_saved_book_required')
        return snapshot, binding
