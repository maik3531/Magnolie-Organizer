"""Native persistent contact consent core; no renderer deserializer or scheduler.

The private signature attests an actual native user decision for one recognized
book/account. It never stores passwords or a password-derived offline verifier.
Current credentials and their process-local revision are observed afresh.
Ordinary-save advancement/recovery and application hydration are separate callers;
this core alone must not be advertised as completed persistent automation.
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


class NativeContactSourceApprovalStore:
    """Dedicated private native files, not document/profile-import permissions.

    Callbacks observe the actual native saved book and stable native book binding.
    Do not hold this store's file lock while invoking book/account callbacks.
    Missing/default reads create nothing. Unknown transactions always hold.
    """
    def __init__(self, root, account_store, capture_current, current_book_binding):
        if (not isinstance(root, str) or not os.path.isabs(root) or
                not isinstance(account_store, NextcloudSettingsStore) or
                not callable(capture_current) or not callable(current_book_binding)):
            raise TypeError('contact_approval_native_context_required')
        self.root = os.path.abspath(root)
        self._account_store = account_store
        self._capture, self._binding = capture_current, current_book_binding

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
        try:
            self._private(os.lstat(self.root), directory=True)
        except FileNotFoundError:
            return None
        if not any(os.path.lexists(os.path.join(self.root, name)) for name in ('.key', '.transaction', 'approval.json')):
            return None
        with self._locked() as directory:
            key, payload = self._record(directory)
        if not payload['sources']:
            return None
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
        if after_key != key or after != payload:
            raise PermissionError('contact_approval_native_context_changed')
        return NativeStoredContactApproval(self, hashlib.sha256(key).hexdigest(), payload['generation'],
            revision, snapshot, tuple((item['source'], item['href']) for item in payload['sources']))
