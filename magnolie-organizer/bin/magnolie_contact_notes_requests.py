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
    NativeNotesExportChoice, NativeNotesFsOrigin, NativeNotesProtocolNegotiation,
    _frame_bytes, _digest, _request_uuid, notes_content_hash, _saved_mutable_projection)


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


@dataclass(frozen=True)
class _RequestHistory:
    store: object
    key: str
    physical: str
    ciphertext_hash: bytes


@dataclass(frozen=True)
class _UnconfirmedQueryProof:
    history: _RequestHistory
    consent: object


class NativeNotesUnconfirmedQuery:
    """Read-only inquiry from genuine unconfirmed history, not replay/ACK rights."""
    def __init__(self, proof):
        self._proof = proof

    def request(self):
        from magnolie_contact_notes_consent import NativeNotesChoiceStore
        proof = self._proof
        if (type(proof) is not _UnconfirmedQueryProof or type(proof.consent) is not NativeNotesChoiceStore or
                type(proof.history) is not _RequestHistory or type(proof.history.store) is not NativeNotesRequestIntents):
            raise PermissionError('notes_request_private_query_required')
        history = proof.history.store._read_query_proof(proof.history)
        proof.consent._verify_history_context(proof.history, (tuple(history['peer']), tuple(history['own'])))
        return {'art': 'kontakt_original_statusanfrage', 'fassung': 1,
            **{name: history['request'][name] for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')},
            'request_sha256': history['request_sha256']}

    def _for_negotiated_protocol(self, protocol):
        if type(protocol) is not NativeNotesProtocolNegotiation:
            raise PermissionError('notes_request_negotiated_query_required')
        pins = protocol.require_current()
        body = self.request()
        self._proof.consent._verify_history_context(self._proof.history, pins)
        protocol.require_current()
        return body


class NativeNotesRecoveryNeedsSave(PermissionError):
    """Known primary is readable, but no real current native save exists yet."""
    def __init__(self, context):
        super().__init__('notes_request_real_native_save_required')
        self.context = context


@dataclass
class _RecoveredRequestContext:
    history: _RequestHistory
    consent: object
    result_text: bytes
    origin: NativeNotesFsOrigin
    transport: str
    pending: object = None

    def require_current(self):
        from magnolie_contact_notes_consent import NativeNotesChoiceStore
        if (type(self.history) is not _RequestHistory or type(self.history.store) is not NativeNotesRequestIntents or
                type(self.consent) is not NativeNotesChoiceStore or type(self.origin) is not NativeNotesFsOrigin):
            raise PermissionError('notes_request_private_recovery_required')
        body = json.loads(self.result_text)
        pins = self.origin.require_current(body, self.transport)
        record = self.history.store._read_query_proof(self.history)
        request = record['request']
        fields = {'art', 'fassung', 'request_id', 'request_sha256', 'share_id', 'before_basis',
            'target_sha256', 'receipt_id', 'native_revision', 'next_basis'}
        if (set(body) != fields or body['art'] != 'kontakt_original_ergebnis' or type(body['fassung']) is not int or body['fassung'] != 1 or
                any(_frame_bytes(body[name]) != _frame_bytes(request[name]) for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')) or
                body['request_sha256'] != record['request_sha256'] or not _request_uuid(body['receipt_id']) or
                type(body['native_revision']) is not int or not record['export']['native_revision'] < body['native_revision'] <= 2**63 - 1 or
                not _digest(body['next_basis']) or body['next_basis'] == request['before_basis']):
            raise PermissionError('notes_request_fresh_verified_result_required')
        self.consent._verify_history_context(self.history, pins)
        data = json.loads(_frame_bytes(self.consent._native_data()))
        contacts = [item for item in data.get('kontakte', []) if isinstance(item, dict) and item.get('id') == record['local_id']]
        if (len(contacts) != 1 or contacts[0].get('uid') != record['local_uid'] or
                _frame_bytes(_saved_mutable_projection(contacts[0], record['export']['kontakt'])) != _frame_bytes(request['ziel'])):
            raise PermissionError('notes_request_saved_target_changed')
        self.consent._verify_history_context(self.history, pins)
        self.origin.require_current(body, self.transport)
        return record


    def ack_source(self, pending):
        if self.pending is not pending:
            raise PermissionError('notes_request_owned_recovered_pending_required')
        record = self.require_current()
        if (_frame_bytes(record['request']) != pending._request_text or
                pending._result_text != self.result_text or record['peer'] != list(pending._peer) or
                record['own'] != list(pending._own) or record['local_id'] != pending._local_id or record['local_uid'] != pending._local_uid):
            raise PermissionError('notes_request_recovered_correlation_changed')
        return record


class NativeNotesBootstrapSave:
    """Exact known current model -> real ordinary writer, never a primary witness."""
    def __init__(self, context, guard):
        from magnolie_contact_notes_consent import _NotesExportBootstrapContext
        if type(context) not in (_RecoveredRequestContext, _NotesExportBootstrapContext) or not callable(guard):
            raise PermissionError('notes_request_native_bootstrap_required')
        self._context, self._guard = context, guard
        guard(); context.require_current()
        self._primary = context.consent._primary()
        self._text = json.dumps(context.consent._native_data(), ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False)
        from magnolie_native_book_json import book_hash
        self._content = book_hash(json.loads(self.text))
        self._hash = hashlib.sha256(self.text.encode('utf-8')).hexdigest()
        self._lock, self.done = threading.RLock(), threading.Event()
        self._used, self._written, self._result = False, False, None
        self._require_before()

    @property
    def text(self):
        return self._text

    @property
    def result(self):
        with self._lock:
            return dict(self._result) if self._result is not None else None

    def _require_before(self):
        self._guard(); self._context.require_current()
        from magnolie_native_book_json import book_hash
        if (self._context.consent._primary() != self._primary or
                self._primary[0].content_sha256 != self._content or
                book_hash(self._context.consent._native_data()) != self._content):
            raise PermissionError('notes_request_bootstrap_model_changed')
        self._guard()

    def write(self, payload, native_write):
        with self._lock:
            if (self._used or payload != self.text or not callable(native_write) or
                    hashlib.sha256(payload.encode('utf-8')).hexdigest() != self._hash):
                raise PermissionError('notes_request_bootstrap_consumed_or_changed')
            self._used = True
            self._require_before()
            native_write(payload)
            self._written = True

    def complete(self, acknowledgment):
        from magnolie_personal_actor_store import NativeProducerBookSnapshot
        with self._lock:
            if self.done.is_set():
                return
            self._used = True
            confirmed = False
            try:
                self._guard(); self._context.require_current()
                saved = self._context.consent._capture()
                confirmed = (self._written and acknowledgment.get('ok') is True and
                    acknowledgment.get('committed') is True and acknowledgment.get('repairPending') is False and
                    acknowledgment.get('standSha256') == self._hash and type(saved) is NativeProducerBookSnapshot and
                    saved.saved_sha256 == self._hash and saved.content_sha256 == self._content and saved.text == self.text)
            except Exception:
                pass
            self._result = {'confirmed': bool(confirmed)}
            self.done.set()

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

    def _physical_id(self, binding, local_id):
        key = self._existing_key()
        if type(key) is not bytes or len(key) != 32:
            raise PermissionError('notes_request_journal_key_unavailable')
        return hmac.new(key, self._DOMAIN + b'physical\0' + _frame_bytes([binding, local_id]), hashlib.sha256).hexdigest()

    def _discover_slot(self, binding, source):
        # Exactly one known private source -> exactly one descriptor-relative
        # physical slot. Never enumerate request archives or unrelated paths.
        physical = self._physical_id(binding, source['local_id'])
        try:
            with self._locked(create=False) as directory:
                self._identity(directory)
                try:
                    key, _, record = self._physical(directory, physical)
                except FileNotFoundError:
                    return None
        except FileNotFoundError:
            return None
        if (any(record[name] != source[name] for name in ('peer', 'own', 'local_id', 'local_uid')) or
                record['export']['share_id'] != source['share_id'] or record['export']['setup_id'] != source['setup_id']):
            raise PermissionError('notes_request_discovery_source_changed')
        return key, physical, record

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
        physical = self._physical_id(binding, pending._local_id)
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

    def _read_query_proof(self, proof):
        if type(proof) is not _RequestHistory or proof.store is not self or not _digest(proof.key) or not _digest(proof.physical):
            raise PermissionError('notes_request_private_query_required')
        with self._locked() as directory:
            self._identity(directory)
            key, blob, record = self._physical(directory, proof.physical)
            if (key != proof.key or record['state'] != 'request_pending' or
                    hashlib.sha256(blob).digest() != proof.ciphertext_hash):
                raise PermissionError('notes_request_query_history_changed')
            try:
                archive = self._read(directory, 'r-' + key + '.bin', self._LIMIT)
            except FileNotFoundError:
                archive = None  # Physical-first crash: query only, never recreate send authority.
            if archive is not None and archive != blob:
                raise PermissionError('notes_request_query_history_changed')
        return record

    def readonly_query(self, key, consent, *, physical=None):
        from magnolie_contact_notes_consent import NativeNotesChoiceStore
        if type(consent) is not NativeNotesChoiceStore or not _digest(key) or physical is not None and not _digest(physical):
            raise PermissionError('notes_request_private_query_required')
        with self._locked() as directory:
            self._identity(directory)
            if physical is None:
                blob = self._read(directory, 'r-' + key + '.bin', self._LIMIT)
                physical = self._decode(key, blob)['physical']
            actual_key, blob, _ = self._physical(directory, physical)
            if actual_key != key:
                raise PermissionError('notes_request_query_history_changed')
        history = _RequestHistory(self, key, physical, hashlib.sha256(blob).digest())
        result = NativeNotesUnconfirmedQuery(_UnconfirmedQueryProof(history, consent))
        result.request()
        return result

    def resume_verified(self, query, body, origin, transport):
        """Local metadata commit only, NEVER a fresh provider request or ACK."""
        if (type(query) is not NativeNotesUnconfirmedQuery or query._proof.history.store is not self or
                type(origin) is not NativeNotesFsOrigin):
            raise PermissionError('notes_request_private_recovery_required')
        context = _RecoveredRequestContext(query._proof.history, query._proof.consent, _frame_bytes(body), origin, transport)
        record = context.require_current()
        snapshot = context.consent._capture()
        if snapshot is None:
            raise NativeNotesRecoveryNeedsSave(context)
        snapshot, binding = context.consent._saved()
        primary, actual_binding = context.consent._primary()
        if binding != actual_binding or snapshot.content_sha256 != primary.content_sha256:
            raise PermissionError('notes_request_actual_primary_changed')
        # Physical-first crash recovery copies only the already authenticated
        # request ciphertext. It issues no fresh mutation stamp or saved witness.
        with self._locked() as directory:
            self._identity(directory)
            key, blob, _ = self._physical(directory, context.history.physical)
            if key != context.history.key or hashlib.sha256(blob).digest() != context.history.ciphertext_hash:
                raise PermissionError('notes_request_query_history_changed')
            try:
                archive = self._read(directory, 'r-' + key + '.bin', self._LIMIT)
            except FileNotFoundError:
                self._write(directory, 'r-' + key + '.bin', blob)
                archive = self._read(directory, 'r-' + key + '.bin', self._LIMIT)
            if archive != blob:
                raise PermissionError('notes_request_query_history_changed')
        context.require_current()
        pending = NativeNotesPendingResult(snapshot, record['request'], record['local_id'], record['local_uid'],
            tuple(record['peer']), tuple(record['own']), context.consent._capture, context.require_current,
            before_revision=record['export']['native_revision'])
        context.pending = pending
        pending._recovered_request_context = context
        pending.stage_result(body, origin, transport)
        return pending

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
