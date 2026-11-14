"""Distinct encrypted pre-save request intentions, never saved-ACK records.

Only successful fresh durable sealing mints a process-local send proof. Reload
returns held history, not permission to repeat a provider mutation. Existing
independent journal key only; no key generation or portable source authority.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import threading

from magnolie_contact_notes_return import (NativeNotesAckIntents, NativeNotesPendingResult,
    NativeNotesExportChoice, _frame_bytes, _digest, _request_uuid, notes_content_hash)


@dataclass(frozen=True)
class _FreshRequestIntention:
    store: object
    key: str
    physical: str
    ciphertext_hash: bytes
    pending: NativeNotesPendingResult
    stamp: object

    def link(self, pending):
        if type(self.store) is not NativeNotesRequestIntents:
            raise PermissionError('notes_request_native_intention_store_required')
        return self.store._require_fresh(self, pending)


class NativeNotesRequestIntents:
    _private = staticmethod(NativeNotesAckIntents._private)
    _locked = NativeNotesAckIntents._locked
    _read = NativeNotesAckIntents._read
    _write = NativeNotesAckIntents._write
    _cipher = NativeNotesAckIntents._cipher
    _DOMAIN = b'Magnolie/notes-original-unconfirmed-request/v1\0'
    _LIMIT = 1024 * 1024

    def __init__(self, root, existing_journal_key, *, stage=lambda _: None):
        if not callable(existing_journal_key) or not callable(stage):
            raise TypeError('notes_request_existing_journal_key_required')
        self.root, self._existing_key, self._stage = os.path.abspath(root), existing_journal_key, stage
        self._memory_lock, self._fresh = threading.RLock(), {}

    @staticmethod
    def _key(record):
        return hashlib.sha256(_frame_bytes([record['physical'], record['request']['request_id']])).hexdigest()

    @staticmethod
    def target_unchanged(patch, before):
        # Planning only, never source authority. Legacy semantic fingerprints
        # can omit literal display-name/vCard differences.
        return all(_frame_bytes(value) == _frame_bytes(before.get(name,
            [] if name in ('vcardName', 'anschriften') else '')) for name, value in patch.items())

    def _key_id(self):
        key = self._existing_key()
        if type(key) is not bytes or len(key) != 32:
            raise PermissionError('notes_request_journal_key_unavailable')
        return hashlib.sha256(key).hexdigest()

    def _identity(self, directory, create=False):
        expected = self._key_id().encode('ascii')
        try:
            actual = self._read(directory, '.journal-key', 64)
        except FileNotFoundError:
            if not create:
                raise PermissionError('notes_request_journal_identity_missing')
            with os.scandir(directory) as entries:
                if any(entry.name != '.lock' for entry in entries):
                    raise PermissionError('notes_request_unknown_store_held')
            self._write(directory, '.journal-key', expected)
            actual = self._read(directory, '.journal-key', 64)
        if not hmac.compare_digest(actual, expected):
            raise PermissionError('notes_request_journal_key_changed')

    def _capture(self, pending):
        from magnolie_contact_notes_consent import _NotesChoiceSeal
        if type(pending) is not NativeNotesPendingResult or type(pending._source_choice) is not NativeNotesExportChoice:
            raise PermissionError('notes_request_genuine_native_choice_required')
        pending._require_before()
        with pending._lock:
            if pending._result_text is not None:
                raise PermissionError('notes_request_result_already_received')
        choice = pending._source_choice
        seal = getattr(choice, '_private_seal', None)
        if type(seal) is not _NotesChoiceSeal:
            raise PermissionError('notes_request_private_choice_seal_required')
        source = seal.record()
        export, request = json.loads(choice._body_text), json.loads(pending._request_text)
        if self.target_unchanged(request['ziel'], export['kontakt']):
            raise ValueError('notes_request_no_target_change')
        key = self._existing_key()
        if type(key) is not bytes or len(key) != 32:
            raise PermissionError('notes_request_journal_key_unavailable')
        primary, binding = seal.store._primary()
        if primary.content_sha256 != pending._snapshot.content_sha256:
            raise PermissionError('notes_request_actual_primary_changed')
        physical = hmac.new(key, self._DOMAIN + b'physical\0' + _frame_bytes([binding, pending._local_id]), hashlib.sha256).hexdigest()
        return {'format': 1, 'state': 'request_pending', 'physical': physical, 'journal_key_sha256': hashlib.sha256(key).hexdigest(),
            'peer': list(pending._peer), 'own': list(pending._own), 'local_id': pending._local_id,
            'local_uid': pending._local_uid, 'choice_seal': source, 'export': export,
            'request': request, 'request_sha256': pending._request_hash,
            'book_before': [pending._snapshot.saved_sha256, pending._snapshot.content_sha256]}

    def _decode(self, key, blob):
        if not _digest(key) or len(blob) < 29 or len(blob) > self._LIMIT or blob[:1] != b'\x01':
            raise PermissionError('notes_request_intention_invalid')
        clear = self._cipher().decrypt(blob[1:13], blob[13:], self._DOMAIN + key.encode('ascii'))
        record = json.loads(clear)
        fields = {'format', 'state', 'physical', 'journal_key_sha256', 'peer', 'own', 'local_id', 'local_uid', 'choice_seal',
            'export', 'request', 'request_sha256', 'book_before'}
        if (not isinstance(record, dict) or set(record) not in (fields, fields | {'previous_sha256', 'native_terminal_sha256'}) or
                type(record['format']) is not int or record['format'] != 1 or
                record['state'] not in ('request_pending', 'request_settled') or not _digest(record['physical']) or
                record['journal_key_sha256'] != self._key_id() or
                (record['state'] == 'request_settled') != ('previous_sha256' in record) or
                any(not _digest(record[name]) for name in ('previous_sha256', 'native_terminal_sha256') if name in record) or
                _frame_bytes(record) != clear or self._key(record) != key):
            raise PermissionError('notes_request_intention_invalid')
        export, request, seal = record['export'], record['request'], record['choice_seal']
        if (not isinstance(export, dict) or set(export) != {'art', 'fassung', 'share_id', 'setup_id', 'before_basis', 'native_revision', 'content_sha256', 'kontakt'} or
                export['art'] != 'kontakt_original_export' or type(export['fassung']) is not int or export['fassung'] != 1 or
                not _request_uuid(export['setup_id']) or type(export['native_revision']) is not int or not 0 <= export['native_revision'] <= 2**63 - 1 or
                not _digest(export['before_basis']) or notes_content_hash(export['kontakt']) != export['content_sha256'] or
                not isinstance(request, dict) or set(request) != {'art', 'fassung', 'request_id', 'share_id', 'before_basis', 'target_sha256', 'ziel'} or
                request['art'] != 'kontakt_original_anfrage' or type(request['fassung']) is not int or request['fassung'] != 1 or
                not _request_uuid(request['request_id']) or not isinstance(request['share_id'], str) or not request['share_id'] or
                request['share_id'] != export['share_id'] or request['before_basis'] != export['before_basis'] or
                not isinstance(request['ziel'], dict) or set(request['ziel']) !=
                    {'vorname', 'nachname', 'anzeigename', 'vcardName', 'firma', 'notiz', 'geburtstag', 'jubilaeum', 'anschriften'} or
                notes_content_hash(dict(export['kontakt'], **request['ziel'])) != request['target_sha256'] or
                record['request_sha256'] != hashlib.sha256(_frame_bytes(request)).hexdigest() or
                not isinstance(seal, dict) or set(seal) != {'key_sha256', 'generation', 'book', 'source_sha256'} or
                not all(_digest(value) for value in seal.values()) or
                any(not isinstance(record[name], str) or not record[name] for name in ('local_id', 'local_uid')) or
                any(not isinstance(record[name], list) or len(record[name]) != 2 or
                    any(not isinstance(value, str) or not value for value in record[name]) for name in ('peer', 'own')) or
                not isinstance(record['book_before'], list) or len(record['book_before']) != 2 or
                not all(_digest(value) for value in record['book_before'])):
            raise PermissionError('notes_request_intention_invalid')
        return record

    def _encode(self, key, record):
        clear = _frame_bytes(record)
        if len(clear) > self._LIMIT - 29:
            raise PermissionError('notes_request_intention_budget')
        nonce = os.urandom(12)
        return b'\x01' + nonce + self._cipher().encrypt(nonce, clear, self._DOMAIN + key.encode('ascii'))

    def _physical(self, directory, physical):
        blob = self._read(directory, 'p-' + physical + '.bin', self._LIMIT + 33)
        if len(blob) < 62 or blob[:1] != b'\x02':
            raise PermissionError('notes_request_physical_hold_invalid')
        key = blob[1:33].hex(); secret = blob[33:]
        record = self._decode(key, secret)
        if record['physical'] != physical:
            raise PermissionError('notes_request_physical_hold_invalid')
        return key, secret, record

    def seal(self, pending):
        old = getattr(pending, '_request_intention', None)
        if old is not None:
            if type(old) is not _FreshRequestIntention or old.store is not self:
                raise PermissionError('notes_request_foreign_intention')
            old.link(pending)
            return old
        record = self._capture(pending); key = self._key(record)
        encrypted = self._encode(key, record)
        with self._locked(create=True) as directory:
            self._identity(directory, create=True)
            try:
                previous_key, previous_blob, previous = self._physical(directory, record['physical'])
            except FileNotFoundError:
                previous = None
            if previous is not None:
                if previous['state'] != 'request_settled' or self._read(directory, 'r-' + previous_key + '.bin', self._LIMIT) != previous_blob:
                    raise PermissionError('notes_request_physical_held')
            try:
                self._read(directory, 'r-' + key + '.bin', self._LIMIT)
            except FileNotFoundError:
                pass
            else:
                raise PermissionError('notes_request_reloaded_intention_held')
            # Reserve the physical desktop slot first. A crash before the
            # independent archive must still block another UUID/source choice.
            self._write(directory, 'p-' + record['physical'] + '.bin', b'\x02' + bytes.fromhex(key) + encrypted)
            self._stage('physical_written')
            self._write(directory, 'r-' + key + '.bin', encrypted); self._stage('archive_written')
            if (self._read(directory, 'r-' + key + '.bin', self._LIMIT) != encrypted or
                    self._physical(directory, record['physical'])[:2] != (key, encrypted)):
                raise PermissionError('notes_request_durability_unconfirmed')
        self._stage('after_readback')
        if self._capture(pending) != record:
            raise PermissionError('notes_request_native_frame_changed')
        stamp = object()
        proof = _FreshRequestIntention(self, key, record['physical'], hashlib.sha256(encrypted).digest(), pending, stamp)
        with self._memory_lock:
            self._fresh[key] = (pending, stamp)
        pending._request_intention = proof
        proof.link(pending)
        return proof

    def _require_fresh(self, proof, pending):
        if type(proof) is not _FreshRequestIntention or proof.store is not self or proof.pending is not pending:
            raise PermissionError('notes_request_fresh_intention_required')
        with self._memory_lock:
            if self._fresh.get(proof.key) != (pending, proof.stamp):
                raise PermissionError('notes_request_reloaded_intention_held')
        with self._locked() as directory:
            self._identity(directory)
            blob = self._read(directory, 'r-' + proof.key + '.bin', self._LIMIT)
            record = self._decode(proof.key, blob)
            if (hashlib.sha256(blob).digest() != proof.ciphertext_hash or record['state'] != 'request_pending' or
                    self._physical(directory, proof.physical)[:2] != (proof.key, blob)):
                raise PermissionError('notes_request_intention_changed')
        choice = pending._source_choice
        from magnolie_contact_notes_consent import _NotesChoiceSeal
        seal = getattr(choice, '_private_seal', None)
        if (type(choice) is not NativeNotesExportChoice or
                type(seal) is not _NotesChoiceSeal or record['choice_seal'] != seal.record() or
                record['peer'] != list(pending._peer) or record['own'] != list(pending._own) or
                record['local_id'] != pending._local_id or record['local_uid'] != pending._local_uid or
                _frame_bytes(record['request']) != pending._request_text or
                _frame_bytes(record['export']) != choice._body_text):
            raise PermissionError('notes_request_private_source_changed')
        saved, binding = seal.store._saved()
        primary, primary_binding = seal.store._primary()
        if binding != primary_binding or saved.content_sha256 != primary.content_sha256:
            raise PermissionError('notes_request_actual_primary_changed')
        with self._memory_lock:
            if self._fresh.get(proof.key) != (pending, proof.stamp):
                raise PermissionError('notes_request_reloaded_intention_held')
        return proof.key

    def load_held(self, key):
        if not _digest(key):
            raise PermissionError('notes_request_intention_key_required')
        with self._locked() as directory:
            self._identity(directory)
            return self._decode(key, self._read(directory, 'r-' + key + '.bin', self._LIMIT))

    def forget_process_proofs(self):
        with self._memory_lock:
            self._fresh.clear()  # Disk holds/history are intentionally untouched.

    def retire_from_terminal(self, intent):
        from magnolie_contact_notes_return import NativeNotesSavedAckIntent, _RestoredAckProof
        if (type(intent) is not NativeNotesSavedAckIntent or type(intent._proof) is not _RestoredAckProof or
                not intent.terminal_confirmed()):
            raise PermissionError('notes_request_real_terminal_history_required')
        ack = intent._proof.store._read_history_proof(intent._proof.history)
        terminal = hashlib.sha256(intent._proof.context.result_text).hexdigest()
        if ack.get('native_terminal_sha256') != terminal:
            raise PermissionError('notes_request_durable_terminal_history_required')
        key = ack.get('request_intention')
        if key is None:
            return None  # Genuine older ACKs have no local pre-save lease to release.
        if not _digest(key):
            raise PermissionError('notes_request_intention_key_required')
        with self._locked() as directory:
            self._identity(directory)
            old = self._read(directory, 'r-' + key + '.bin', self._LIMIT); record = self._decode(key, old)
            if (record['request'] != ack['request'] or record['choice_seal'] != ack['choice_seal'] or
                    record['export']['setup_id'] != ack['source_setup_id'] or
                    any(record[name] != ack[name] for name in ('peer', 'own', 'local_id', 'local_uid'))):
                raise PermissionError('notes_request_terminal_correlation_changed')
            if record['state'] == 'request_settled':
                if record['native_terminal_sha256'] != terminal:
                    raise PermissionError('notes_request_terminal_history_changed')
                physical_key, physical_blob, _ = self._physical(directory, record['physical'])
                if physical_key != key or physical_blob == old:
                    with self._memory_lock:
                        self._fresh.pop(key, None)
                    return record  # Old terminal history must never release a newer hold.
                if hashlib.sha256(physical_blob).hexdigest() != record['previous_sha256']:
                    raise PermissionError('notes_request_physical_held')
                complete = record; encrypted = old
            else:
                if self._physical(directory, record['physical'])[:2] != (key, old):
                    raise PermissionError('notes_request_physical_held')
                complete = dict(record, state='request_settled', previous_sha256=hashlib.sha256(old).hexdigest(), native_terminal_sha256=terminal)
                encrypted = self._encode(key, complete)
                self._write(directory, 'r-' + key + '.bin', encrypted); self._stage('terminal_archive_written')
            self._write(directory, 'p-' + record['physical'] + '.bin', b'\x02' + bytes.fromhex(key) + encrypted)
            self._stage('terminal_physical_written')
            if (self._read(directory, 'r-' + key + '.bin', self._LIMIT) != encrypted or
                    self._physical(directory, record['physical'])[:2] != (key, encrypted)):
                raise PermissionError('notes_request_terminal_history_changed')
        intent.terminal_confirmed()
        with self._memory_lock:
            self._fresh.pop(key, None)
        return complete
