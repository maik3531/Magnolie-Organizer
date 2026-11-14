"""Native persistent contact consent core; no renderer deserializer or scheduler.

The private signature attests an actual native user decision for one recognized
book/account. It never stores passwords or a password-derived offline verifier.
Current credentials and their process-local revision are observed afresh.
The actual writer can advance signed save intents; application setup/hydration
remain separate. This core alone is not completed persistent automation.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat

from magnolie_contact_source_dav import NativeDavSourceApproval, _account, _source_matches
from magnolie_native_book_json import book_hash
from magnolie_nextcloud import NextcloudSettingsStore
from magnolie_personal_actor_store import NativeProducerBookSnapshot


HEX = re.compile('[0-9a-f]{64}')
DOMAIN = b'Magnolie/native-original-contact-consent/v1\0'


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
class NativeStoredContactApproval:
    """Native operation-local witness, never accepted as serialized permission."""
    store: object = field(repr=False)
    key_fingerprint: str = field(repr=False)
    generation: str = field(repr=False)
    account_revision: str = field(repr=False)
    snapshot: NativeProducerBookSnapshot = field(repr=False)
    sources: tuple = field(repr=False)

    def require_current(self):
        current = self.store.load_current()
        if (type(current) is not NativeStoredContactApproval or
                current.key_fingerprint != self.key_fingerprint or
                current.generation != self.generation or current.account_revision != self.account_revision or
                current.snapshot != self.snapshot or current.sources != self.sources):
            raise PermissionError('contact_approval_withdrawn_or_changed')


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


class NativeContactSourceApprovalStore:
    """Dedicated private native files, not document/profile-import permissions.

    Callbacks observe the actual native saved book and stable native book binding.
    Do not hold this store's file lock while invoking book/account callbacks.
    Missing/default reads create nothing. Unknown transactions always hold.
    """
    def __init__(self, root, account_store, capture_current, current_book_binding, *, capture_primary=None):
        if (not isinstance(root, str) or not os.path.isabs(root) or
                not isinstance(account_store, NextcloudSettingsStore) or
                not callable(capture_current) or not callable(current_book_binding) or
                capture_primary is not None and not callable(capture_primary)):
            raise TypeError('contact_approval_native_context_required')
        self.root = os.path.abspath(root)
        self._account_store = account_store
        self._capture, self._binding = capture_current, current_book_binding
        self._capture_primary = capture_primary

    @staticmethod
    def _private(status, directory=False):
        if ((not stat.S_ISDIR(status.st_mode) if directory else not stat.S_ISREG(status.st_mode)) or
                status.st_uid != os.geteuid() or status.st_mode & 0o077 or
                not directory and status.st_nlink != 1):
            raise PermissionError('contact_approval_store_insecure')

    @contextmanager
    def _locked(self, create=False):
        if create:
            os.makedirs(self.root, mode=0o700, exist_ok=True)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self._private(os.fstat(directory), directory=True)
            descriptor = os.open('.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            try:
                self._private(os.fstat(descriptor))
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield directory
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)

    def _read(self, directory, name, limit):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as source:
            self._private(os.fstat(source.fileno()))
            value = source.read(limit + 1)
        if len(value) > limit:
            raise PermissionError('contact_approval_store_invalid')
        return value

    def _write(self, directory, name, value):
        # Descriptor-relative replacement cannot follow a substituted key/state
        # symlink. Refuse existing insecure destinations rather than repairing it.
        try:
            self._private(os.stat(name, dir_fd=directory, follow_symlinks=False))
        except FileNotFoundError:
            pass
        temporary = '.' + name + '-' + os.urandom(12).hex()
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        try:
            with os.fdopen(descriptor, 'wb') as target:
                target.write(value); target.flush(); os.fsync(target.fileno())
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass

    @staticmethod
    def _tag(key, label, value):
        return hmac.new(key, DOMAIN + label + b'\0' + value, hashlib.sha256).hexdigest()

    def _record(self, directory):
        if self._read(directory, '.transaction', 32) != b'clean\n':
            raise PermissionError('contact_approval_store_pending')
        key = self._read(directory, '.key', 32)
        if len(key) != 32:
            raise PermissionError('contact_approval_store_invalid')
        envelope = json.loads(self._read(directory, 'approval.json', 128 * 1024), object_pairs_hook=_strict_pairs)
        if not isinstance(envelope, dict) or set(envelope) != {'payload', 'mac'}:
            raise PermissionError('contact_approval_store_invalid')
        payload, signature = envelope['payload'], envelope['mac']
        if (not isinstance(signature, str) or HEX.fullmatch(signature) is None or
                not hmac.compare_digest(signature, self._tag(key, b'record', _json(payload)))):
            raise PermissionError('contact_approval_store_invalid')
        if (not isinstance(payload, dict) or set(payload) != {'version', 'generation', 'book', 'content', 'account', 'sources'} or
                type(payload['version']) is not int or payload['version'] != 1 or
                any(not isinstance(payload[name], str) or HEX.fullmatch(payload[name]) is None for name in ('generation', 'book')) or
                not isinstance(payload['sources'], list) or len(payload['sources']) > 256):
            raise PermissionError('contact_approval_store_invalid')
        sources = payload['sources']
        if any(not isinstance(item, dict) or set(item) != {'source', 'href'} or
               any(not isinstance(item[name], str) or not 1 <= len(item[name]) <= 8192 for name in ('source', 'href'))
               for item in sources):
            raise PermissionError('contact_approval_store_invalid')
        if len({item['source'] for item in sources}) != len(sources) or len({item['href'] for item in sources}) != len(sources):
            raise PermissionError('contact_approval_store_invalid')
        if sources:
            if any(not isinstance(payload[name], str) or HEX.fullmatch(payload[name]) is None for name in ('content', 'account')):
                raise PermissionError('contact_approval_store_invalid')
        elif payload['content'] is not None or payload['account'] is not None:
            raise PermissionError('contact_approval_store_invalid')
        return key, payload

    def _publish(self, directory, key, payload):
        # A crash or uncertain fsync cannot release an old/new partial grant.
        try:
            self._write(directory, '.transaction', b'pending\n')
            self._remove_intent(directory)
            self._write(directory, '.key', key)
            self._write(directory, 'approval.json', _json({'payload': payload,
                'mac': self._tag(key, b'record', _json(payload))}))
            self._write(directory, '.transaction', b'clean\n')
            actual_key, actual_payload = self._record(directory)
            if actual_key != key or actual_payload != payload:
                raise PermissionError('contact_approval_store_write_unconfirmed')
        except Exception:
            # In particular, clean-marker replacement may have happened before
            # its directory fsync failed. Quarantine that uncertain outcome too.
            try:
                self._write(directory, '.transaction', b'pending\n')
            except Exception:
                pass  # Never turn an unconfirmed operation into success.
            raise

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
                payload['content'] not in (intent['old'], intent['new']) or not payload['sources']):
            raise PermissionError('contact_approval_save_intent_invalid')
        return intent

    def _active_record(self):
        """Read without creating even a lock file when no consent exists."""
        try:
            self._private(os.lstat(self.root), directory=True)
        except FileNotFoundError:
            return None
        if not any(os.path.lexists(os.path.join(self.root, name))
                   for name in ('.key', '.transaction', 'approval.json', '.book-intent.json')):
            return None
        with self._locked() as directory:
            key, payload = self._record(directory)
        return (key, payload) if payload['sources'] else None

    def prepare_save(self, previous, next_text):
        """Native writer BEFORE invalidation/write; never observes credentials.

        Only advance existing intent for the recognized saved book or an actual
        authenticated primary observation. Proposed hashes cannot create consent.
        """
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
        # These callbacks are deliberately outside the file lock and do not
        # consult the account/keyring: autosave must not wait on credential IO.
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
            # Recovery accepts only a known old/new outcome. Never roll back an
            # already advanced record to old content, or adopt an unrelated edit.
            if (snapshot.content_sha256 not in (intent['old'], intent['new']) or
                    payload['content'] == intent['new'] and snapshot.content_sha256 != intent['new']):
                raise PermissionError('contact_approval_save_outcome_unknown')
            if payload['content'] != snapshot.content_sha256:
                payload = dict(payload, content=snapshot.content_sha256)
                # Keep the signed intent until the new sealed record is read
                # back. Either old or new remains recoverable after a crash.
                self._write(directory, 'approval.json', _json({'payload': payload,
                    'mac': self._tag(key, b'record', _json(payload))}))
                actual_key, actual_payload = self._record(directory)
                if actual_key != key or actual_payload != payload:
                    raise PermissionError('contact_approval_save_unconfirmed')
            self._remove_intent(directory)
        if observe() != (snapshot, binding):
            raise PermissionError('contact_approval_native_book_changed')
        return snapshot.content_sha256

    def confirm_save(self, intent, confirmed):
        """After actual native writer success AND all repair checks only."""
        if type(intent) is not NativeContactApprovalSaveIntent or intent.store is not self:
            raise TypeError('contact_approval_native_save_intent_required')
        return self._advance_saved(confirmed, intent)

    def recover_saved(self, confirmed):
        """Recover only after a real current saved witness, never loaded JSON.

        Primary-file recovery is a separate typed path. This method does not
        bless startup data as a native saved-book observation.
        """
        if self._active_record() is None:
            return None
        return self._advance_saved(confirmed)

    def recover_primary(self, observed):
        """Known old/new authenticated disk recovery, NEVER issues permission.

        Loading a usable lease still requires a separate actual saved witness.
        Native startup may recover the chain before that first real SaveACK.
        """
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

    def _account(self):
        settings, revision = _account(self._account_store)
        # Persist ONLY native nonsecret identity/credential-slot metadata. The
        # actual credential-bound revision stays operation-local and fresh.
        identity = _json({'store': os.path.realpath(self._account_store.path),
            'provider': settings['kontoArt'], 'server': settings['server'], 'user': settings['benutzer'],
            'slot': self._account_store.account(settings['server'], settings['benutzer'], settings['kontoArt'])})
        return settings, revision, identity

    def approve(self, snapshot, approvals):
        approvals = tuple(approvals)
        if not approvals:
            self.revoke(); return None
        if any(type(item) is not NativeDavSourceApproval for item in approvals):
            raise TypeError('contact_approval_native_decision_required')
        current_snapshot, binding = self._saved()
        if current_snapshot != snapshot:
            raise PermissionError('contact_approval_native_book_changed')
        settings, revision, identity = self._account()
        for item in approvals:
            item.require_current()
            if item.account_revision != revision or not _source_matches(settings, item.source, item.href):
                raise PermissionError('contact_approval_native_decision_changed')
        sources = sorted(({'source': item.source, 'href': item.href} for item in approvals), key=lambda item: item['source'])
        if len(sources) > 256 or len({item['source'] for item in sources}) != len(sources) or len({item['href'] for item in sources}) != len(sources):
            raise ValueError('contact_approval_native_decision_ambiguous')
        key, generation = os.urandom(32), os.urandom(32).hex()
        payload = {'version': 1, 'generation': generation, 'book': self._tag(key, b'book', binding.encode('utf-8')),
                   'content': snapshot.content_sha256, 'account': self._tag(key, b'account', identity), 'sources': sources}
        with self._locked(create=True) as directory:
            self._publish(directory, key, payload)
        try:
            if self._saved() != (snapshot, binding) or self._account()[1] != revision:
                raise PermissionError('contact_approval_native_context_changed')
            for item in approvals: item.require_current()
        except Exception:
            self.revoke_if_generation(generation)
            raise
        result = self.load_current()
        if result is None or result.generation != generation or result.key_fingerprint != hashlib.sha256(key).hexdigest():
            raise PermissionError('contact_approval_native_context_changed')
        return result

    def _revoke_locked(self, directory):
        key = os.urandom(32)
        self._publish(directory, key, {'version': 1, 'generation': os.urandom(32).hex(),
            'book': '0' * 64, 'content': None, 'account': None, 'sources': []})

    def revoke(self):
        with self._locked(create=True) as directory:
            self._revoke_locked(directory)

    def revoke_if_generation(self, generation):
        with self._locked() as directory:
            _, payload = self._record(directory)
            if payload['generation'] == generation:
                self._revoke_locked(directory)

    def load_current(self):
        active = self._active_record()
        if active is None:
            return None
        key, payload = active
        with self._locked() as directory:
            if self._intent(directory, key, payload) is not None:
                raise PermissionError('contact_approval_save_pending')
        snapshot, binding = self._saved()
        if payload['content'] != snapshot.content_sha256 or not hmac.compare_digest(
                payload['book'], self._tag(key, b'book', binding.encode('utf-8'))):
            return None
        settings, revision, identity = self._account()
        if not hmac.compare_digest(payload['account'], self._tag(key, b'account', identity)):
            return None
        if any(not _source_matches(settings, item['source'], item['href']) for item in payload['sources']):
            raise PermissionError('contact_approval_account_or_source_changed')
        if self._saved() != (snapshot, binding) or self._account()[1] != revision:
            raise PermissionError('contact_approval_native_context_changed')
        with self._locked() as directory:
            after_key, after = self._record(directory)
            after_intent = self._intent(directory, after_key, after)
        if after_key != key or after != payload or after_intent is not None:
            raise PermissionError('contact_approval_native_context_changed')
        return NativeStoredContactApproval(self, hashlib.sha256(key).hexdigest(), payload['generation'],
            revision, snapshot, tuple((item['source'], item['href']) for item in payload['sources']))
