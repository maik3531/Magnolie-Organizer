"""Private Notes choices and known native book-save chain; no enabled setup UI.

Only an authenticated export plus a genuine native contact choice can publish
consent. Restart restoration requires recognized primary/saved-book observations
and a fresh authenticated export. Portable IDs/basis fields are not permissions.
ACK outcomes keep their independent journal key and are not stored here.
"""
import hashlib
import hmac
import json
import os
import threading
from dataclasses import dataclass

from magnolie_contact_book_save_chain import NativeContactBookSaveChain
from magnolie_contact_source_authority import NativeContactSourceApprovalStore as _PrivateFiles
from magnolie_contact_notes_return import NativeNotesExportChoice, NativeNotesFsOrigin, _AckHistoryProof, _digest, _request_uuid, _frame_bytes
from magnolie_native_book_json import book_hash


@dataclass(frozen=True)
class _NotesChoiceSeal:
    store: object
    key_fingerprint: bytes
    generation: str
    book: str
    source_text: bytes

    def record(self):
        if type(self.store) is not NativeNotesChoiceStore:
            raise PermissionError('notes_choice_private_seal_required')
        self.store._require_seal(self)
        return {'key_sha256': self.key_fingerprint.hex(), 'generation': self.generation,
            'book': self.book, 'source_sha256': hashlib.sha256(self.source_text).hexdigest()}


@dataclass(frozen=True)
class _RecognizedNotesAckContext:
    store: object
    history: _AckHistoryProof
    result_text: bytes
    origin: NativeNotesFsOrigin
    transport: str

    def require_current(self):
        if type(self.store) is not NativeNotesChoiceStore:
            raise PermissionError('notes_choice_native_ack_context_required')
        self.store._verify_saved_ack(self)


@dataclass(frozen=True)
class _NotesExportBootstrapContext:
    consent: object
    body_text: bytes
    origin: NativeNotesFsOrigin
    transport: str

    def require_current(self):
        if type(self.consent) is not NativeNotesChoiceStore or type(self.origin) is not NativeNotesFsOrigin:
            raise PermissionError('notes_choice_native_export_bootstrap_required')
        body = json.loads(self.body_text)
        pins = self.origin.require_current(body, self.transport)
        self.consent._verify_history_context(self, pins)
        self.origin.require_current(body, self.transport)


@dataclass
class _NotesSetupProof:
    store: object
    stamp: bytes
    saved: object
    primary: object
    binding: str
    addition: bool
    version: int
    used: bool = False


class NativeNotesSetupDecision:
    """Opaque one-use BEFORE-dialog native context, never serialized permission."""
    def __init__(self, proof):
        self.__proof = proof

    def _native(self):
        proof = self.__proof
        if type(proof) is not _NotesSetupProof or type(proof.store) is not NativeNotesChoiceStore:
            raise PermissionError('notes_setup_native_decision_required')
        return proof

    @property
    def snapshot(self):
        return self._native().saved

    @property
    def is_addition(self):
        return self._native().addition

    def commit(self, choice):
        proof = self._native()
        with proof.store._setup_lock:
            if proof.used:
                raise PermissionError('notes_setup_decision_already_used')
            proof.used = True
        proof.store._commit_setup(proof, choice)


class NativeNotesChoiceStore(NativeContactBookSaveChain):
    _private = staticmethod(_PrivateFiles._private)
    _locked = _PrivateFiles._locked
    _read = _PrivateFiles._read
    _write = _PrivateFiles._write
    _DOMAIN = b'Magnolie/native-notes-contact-choice/v1\0'

    def __init__(self, root, capture_current, current_book_binding, capture_primary, *, current_native_data=None):
        if (not isinstance(root, str) or not os.path.isabs(root) or
                not all(callable(value) for value in (capture_current, current_book_binding, capture_primary))):
            raise TypeError('notes_choice_native_book_callbacks_required')
        if current_native_data is not None and not callable(current_native_data):
            raise TypeError('notes_choice_native_book_callbacks_required')
        self.root, self._capture, self._binding, self._capture_primary = root, capture_current, current_book_binding, capture_primary
        self._native_data = current_native_data
        self._setup_lock, self._setup_version = threading.RLock(), 0

    def _tag(self, key, label, value):
        return hmac.new(key, self._DOMAIN + label + b'\0' + value, hashlib.sha256).hexdigest()

    def _save_chain_active(self, payload):
        return bool(payload['choices'])

    @staticmethod
    def _source(choice):
        if type(choice) is not NativeNotesExportChoice:
            raise PermissionError('notes_choice_native_selection_required')
        choice.require_current()
        body = json.loads(choice._body_text)
        return {'peer': list(choice._peer), 'own': list(choice._own), 'share_id': body['share_id'],
            'setup_id': body['setup_id'], 'local_id': choice._id, 'local_uid': choice._uid}

    def _record(self, directory):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if self._read(directory, '.transaction', 32) != b'clean\n':
            raise PermissionError('notes_choice_store_pending')
        key = self._read(directory, '.key', 32)
        if len(key) != 32:
            raise PermissionError('notes_choice_store_invalid')
        blob = self._read(directory, 'choices.aes', 512 * 1024)
        if len(blob) < 29 or blob[:1] != b'\x01':
            raise PermissionError('notes_choice_store_invalid')
        clear = AESGCM(key).decrypt(blob[1:13], blob[13:], self._DOMAIN)
        payload = json.loads(clear)
        if (not isinstance(payload, dict) or set(payload) != {'version', 'generation', 'book', 'content', 'choices'} or
                type(payload['version']) is not int or payload['version'] != 1 or
                not _digest(payload['generation']) or not _digest(payload['book']) or
                not isinstance(payload['choices'], list) or len(payload['choices']) > 256 or _frame_bytes(payload) != clear):
            raise PermissionError('notes_choice_store_invalid')
        if bool(payload['choices']) != (payload['content'] is not None) or payload['content'] is not None and not _digest(payload['content']):
            raise PermissionError('notes_choice_store_invalid')
        for source in payload['choices']:
            if (not isinstance(source, dict) or set(source) != {'peer', 'own', 'share_id', 'setup_id', 'local_id', 'local_uid'} or
                    any(not isinstance(source[name], str) or not source[name] for name in ('share_id', 'local_id', 'local_uid')) or
                    not _request_uuid(source['setup_id']) or
                    any(not isinstance(source[name], list) or len(source[name]) != 2 or
                        any(not isinstance(value, str) or not value for value in source[name]) for name in ('peer', 'own'))):
                raise PermissionError('notes_choice_store_invalid')
        self._unique(payload['choices'])
        return key, payload

    @staticmethod
    def _unique(sources):
        if (len({(tuple(item['peer']), tuple(item['own']), item['share_id']) for item in sources}) != len(sources) or
                len({item['local_id'] for item in sources}) != len(sources)):
            raise PermissionError('notes_choice_ambiguous_selection')

    def _write_chain_record(self, directory, key, payload):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        clear = _frame_bytes(payload)
        if len(clear) > 500 * 1024:
            raise ValueError('notes_choice_store_budget')
        nonce = os.urandom(12)
        self._write(directory, 'choices.aes', b'\x01' + nonce + AESGCM(key).encrypt(nonce, clear, self._DOMAIN))

    def _active_record(self):
        try:
            self._private(os.lstat(self.root), directory=True)
        except FileNotFoundError:
            return None
        if not any(os.path.lexists(os.path.join(self.root, name)) for name in ('.key', '.transaction', 'choices.aes', '.book-intent.json')):
            return None
        with self._locked() as directory:
            key, payload = self._record(directory)
        return (key, payload) if payload['choices'] else None

    def has_desired_consent(self):
        return self._active_record() is not None

    def _discovery_sources(self, pins):
        """Bounded private selection for slot lookup, not mutation authority."""
        active = self._active_record()
        if active is None:
            return None
        key, payload = active
        primary, binding = self._primary()
        if (self._native_data is None or payload['content'] != primary.content_sha256 or
                payload['book'] != self._tag(key, b'book', binding.encode('utf-8')) or
                book_hash(self._native_data()) != primary.content_sha256):
            raise PermissionError('notes_choice_recognized_primary_required')
        with self._locked() as directory:
            if self._record(directory) != active or self._intent(directory, key, payload) is not None:
                raise PermissionError('notes_choice_native_context_changed')
        if self._primary() != (primary, binding):
            raise PermissionError('notes_choice_native_primary_changed')
        return binding, [dict(source) for source in payload['choices']
            if pins is None or (tuple(source['peer']), tuple(source['own'])) == pins]

    def _publish(self, directory, key, payload):
        try:
            self._write(directory, '.transaction', b'pending\n')
            self._remove_intent(directory)
            self._write(directory, '.key', key)
            self._write_chain_record(directory, key, payload)
            self._write(directory, '.transaction', b'clean\n')
            if self._record(directory) != (key, payload):
                raise PermissionError('notes_choice_write_unconfirmed')
        except Exception:
            try:
                self._write(directory, '.transaction', b'pending\n')
            except Exception:
                pass
            raise

    def configure(self, choices):
        with self._setup_lock:
            self._setup_version += 1
        return self._configure(choices)

    def _configure(self, choices, setup=None):
        selected = tuple(choices)
        if not selected:
            self.revoke()
            return
        if len(selected) > 256:
            raise ValueError('notes_choice_selection_budget')
        sources = [self._source(choice) for choice in selected]
        self._unique(sources)
        saved, binding = self._saved()
        primary, primary_binding = self._primary()
        # Primary hashes the encrypted envelope; SaveACK hashes its clear writer
        # payload. Compare their exact content fingerprint, not different domains.
        if primary_binding != binding or primary.content_sha256 != saved.content_sha256:
            raise PermissionError('notes_choice_native_primary_changed')
        if any(choice._book_source != saved.book_source for choice in selected):
            raise PermissionError('notes_choice_native_book_changed')
        key = os.urandom(32)  # Dedicated nonportable consent key, ONLY explicit native configuration.
        payload = {'version': 1, 'generation': os.urandom(32).hex(),
            'book': self._tag(key, b'book', binding.encode('utf-8')), 'content': saved.content_sha256, 'choices': sources}
        # Publish the in-process dependency first: a failed durable setup must
        # not leave the newly selected ephemeral object usable without it.
        for choice, source in zip(selected, sources):
            self._attach(choice, key, payload, source)
        if setup is not None:
            self._require_setup_context(setup)
        with self._locked(create=True) as directory:
            if setup is not None and self._setup_stamp(directory) != setup.stamp:
                raise PermissionError('notes_setup_newer_private_decision')
            self._publish(directory, key, payload)
        try:
            if setup is not None:
                self._require_setup_context(setup)
            if self._saved() != (saved, binding) or self._primary() != (primary, primary_binding):
                raise PermissionError('notes_choice_native_book_changed')
            for choice in selected:
                choice.require_current()
        except Exception:
            if setup is not None:
                with self._locked() as directory:
                    if self._record(directory) == (key, payload):
                        self._write(directory, '.transaction', b'pending\n')
            raise

    def add_sources(self, choices):
        return self._add_sources(choices)

    def _add_sources(self, choices, setup=None):
        """Strict monotone native addition; configure/revoke still rotate epochs.

        Caller holds the native book lock, as with configure. Private record CAS
        also rejects concurrent decisions by another store instance/process.
        """
        selected = tuple(choices)
        if not selected or len(selected) > 256:
            raise ValueError('notes_choice_addition_budget')
        active = self._active_record()
        if active is None or not self.recognizes_saved():
            raise PermissionError('notes_choice_existing_decision_required')
        key, previous = active
        saved, binding = self._saved()
        primary, primary_binding = self._primary()
        if (primary_binding != binding or primary.content_sha256 != saved.content_sha256 or
                previous['content'] != saved.content_sha256 or
                previous['book'] != self._tag(key, b'book', binding.encode('utf-8')) or
                any(type(choice) is not NativeNotesExportChoice or choice._book_source != saved.book_source for choice in selected)):
            raise PermissionError('notes_choice_native_book_changed')
        sources = [self._source(choice) for choice in selected]
        merged = list(previous['choices'])
        for source in sources:
            if source not in merged:
                merged.append(source)
        self._unique(merged)
        if len(merged) > 256:
            raise ValueError('notes_choice_selection_budget')
        payload = dict(previous, choices=merged)
        changed = payload != previous
        for choice in selected:
            choice.require_current()
        if self._saved() != (saved, binding) or self._primary() != (primary, primary_binding):
            raise PermissionError('notes_choice_native_book_changed')
        for choice, source in zip(selected, sources):
            self._attach(choice, key, payload, source)
        if setup is not None:
            self._require_setup_context(setup)
        with self._locked() as directory:
            if (self._record(directory) != active or self._intent(directory, key, previous) is not None or
                    setup is not None and self._setup_stamp(directory) != setup.stamp):
                raise PermissionError('notes_choice_newer_private_decision')
            if changed:
                try:
                    self._write(directory, '.transaction', b'pending\n')
                    # Preserve key, generation, book and content. Never remove a
                    # pending native save intent or mint a new consent epoch.
                    self._write_chain_record(directory, key, payload)
                    self._write(directory, '.transaction', b'clean\n')
                    if self._record(directory) != (key, payload):
                        raise PermissionError('notes_choice_write_unconfirmed')
                except Exception:
                    self._write(directory, '.transaction', b'pending\n')
                    raise
        try:
            if setup is not None:
                self._require_setup_context(setup)
            if self._saved() != (saved, binding) or self._primary() != (primary, primary_binding):
                raise PermissionError('notes_choice_native_book_changed')
            for choice in selected:
                choice.require_current()
        except Exception:
            if changed:
                with self._locked() as directory:
                    if self._record(directory) == (key, payload):
                        self._write(directory, '.transaction', b'pending\n')
            raise

    def _setup_stamp(self, directory):
        digest = hashlib.sha256(b'Magnolie/notes/setup/private-state/v1\0')
        for name, limit in (('.transaction', 32), ('.key', 32), ('choices.aes', 512 * 1024), ('.book-intent.json', 4096)):
            try:
                value = self._read(directory, name, limit) if directory is not None else None
            except FileNotFoundError:
                value = None
            digest.update(name.encode('ascii') + b'\0')
            digest.update(b'\0' if value is None else b'\1' + len(value).to_bytes(8, 'big') + value)
        return digest.digest()  # No raw consent secret is retained by a dialog token.

    def _setup_observe(self):
        try:
            self._private(os.lstat(self.root), directory=True)
        except FileNotFoundError:
            return self._setup_stamp(None), False
        with self._locked() as directory:
            stamp = self._setup_stamp(directory)
            if stamp == self._setup_stamp(None):
                return stamp, False
            key, payload = self._record(directory)
            if self._intent(directory, key, payload) is not None:
                raise PermissionError('notes_setup_pending_book_intent')
            return stamp, bool(payload['choices'])

    def begin_setup_decision(self):
        """Native book lock required; authenticate before opening any dialog."""
        with self._setup_lock:
            version = self._setup_version
        stamp, addition = self._setup_observe()
        saved, binding = self._saved()
        primary, primary_binding = self._primary()
        if primary_binding != binding or primary.content_sha256 != saved.content_sha256 or addition and not self.recognizes_saved():
            raise PermissionError('notes_setup_recognized_native_book_required')
        proof = _NotesSetupProof(self, stamp, saved, primary, binding, addition, version)
        self._require_setup_context(proof)
        if self._setup_observe() != (stamp, addition):
            raise PermissionError('notes_setup_context_changed')
        return NativeNotesSetupDecision(proof)

    def _require_setup_context(self, proof):
        with self._setup_lock:
            if proof.store is not self or self._setup_version != proof.version:
                raise PermissionError('notes_setup_context_changed')
        if self._saved() != (proof.saved, proof.binding) or self._primary() != (proof.primary, proof.binding):
            raise PermissionError('notes_setup_context_changed')

    def _commit_setup(self, proof, choice):
        if type(choice) is not NativeNotesExportChoice or self._setup_observe() != (proof.stamp, proof.addition):
            raise PermissionError('notes_setup_context_changed')
        self._require_setup_context(proof)
        if proof.addition:
            self._add_sources([choice], setup=proof)
        else:
            self._configure([choice], setup=proof)

    def recognizes_saved(self):
        active = self._active_record()
        if active is None:
            return False
        key, payload = active
        saved, binding = self._saved()
        if payload['content'] != saved.content_sha256 or payload['book'] != self._tag(key, b'book', binding.encode('utf-8')):
            return False
        with self._locked() as directory:
            actual_key, actual_payload = self._record(directory)
            intent = self._intent(directory, actual_key, actual_payload)
        return actual_key == key and actual_payload == payload and intent is None

    def _attach(self, choice, key, payload, source):
        fingerprint, generation = hashlib.sha256(key).digest(), payload['generation']
        def current():
            active = self._active_record()
            if (active is None or not hmac.compare_digest(hashlib.sha256(active[0]).digest(), fingerprint) or
                    active[1]['generation'] != generation or source not in active[1]['choices'] or not self.recognizes_saved()):
                raise PermissionError('notes_choice_withdrawn_or_changed')
        choice._persistent_guard = current
        choice._private_seal = _NotesChoiceSeal(self, fingerprint, generation, payload['book'], _frame_bytes(source))

    def _require_seal(self, seal):
        active = self._active_record()
        if (type(seal) is not _NotesChoiceSeal or seal.store is not self or active is None or
                not hmac.compare_digest(hashlib.sha256(active[0]).digest(), seal.key_fingerprint) or
                active[1]['generation'] != seal.generation or active[1]['book'] != seal.book or
                json.loads(seal.source_text) not in active[1]['choices'] or not self.recognizes_saved()):
            raise PermissionError('notes_choice_private_seal_changed')

    def _recognize_saved_ack(self, history, body, origin, transport):
        if type(history) is not _AckHistoryProof or type(origin) is not NativeNotesFsOrigin:
            raise PermissionError('notes_choice_private_ack_history_required')
        proof = _RecognizedNotesAckContext(self, history, _frame_bytes(body), origin, transport)
        proof.require_current()
        return proof

    def _verify_saved_ack(self, proof):
        if type(proof) is not _RecognizedNotesAckContext or proof.store is not self:
            raise PermissionError('notes_choice_native_ack_context_required')
        body = json.loads(proof.result_text)
        peer, own = proof.origin.require_current(body, proof.transport)
        history = proof.history.store._read_history_proof(proof.history)
        result_bytes = _frame_bytes(history['result'])
        status_bytes = [_frame_bytes(dict(history['result'], art='kontakt_original_abschlussstatus', phase=phase,
            desktop_sha256=history['saved_book'][2])) for phase in ('prepared', 'settled')]
        if (_frame_bytes(body) not in [result_bytes, *status_bytes] or
                list(peer) != history['peer'] or list(own) != history['own']):
            raise PermissionError('notes_choice_repeated_result_changed')
        self._verify_history_context(proof.history, (peer, own))
        proof.origin.require_current(body, proof.transport)

    def _verify_history_context(self, history_proof, pins):
        # Independent private observation permits a read-only inquiry, NOT an
        # ACK. A fresh native result/status remains mandatory for ACK recovery.
        from magnolie_contact_notes_return import NativeNotesAckIntents
        from magnolie_contact_notes_requests import _RequestHistory, NativeNotesRequestIntents
        if type(history_proof) is _AckHistoryProof and type(history_proof.store) is NativeNotesAckIntents:
            history = history_proof.store._read_history_proof(history_proof)
        elif type(history_proof) is _RequestHistory and type(history_proof.store) is NativeNotesRequestIntents:
            unconfirmed = history_proof.store._read_query_proof(history_proof)
            history = {name: unconfirmed[name] for name in ('peer', 'own', 'choice_seal', 'local_id', 'local_uid')}
            history.update(source_setup_id=unconfirmed['export']['setup_id'], result={'share_id': unconfirmed['request']['share_id']})
        elif type(history_proof) is _NotesExportBootstrapContext and history_proof.consent is self:
            from magnolie_contact_notes_return import _validate_notes_export
            body = json.loads(history_proof.body_text)
            _validate_notes_export(body)
            if history_proof.origin.require_current(body, history_proof.transport) != pins:
                raise PermissionError('notes_choice_authenticated_export_changed')
            selected = self._active_record()
            if selected is None:
                raise PermissionError('notes_choice_source_not_granted')
            selected_key, selected_payload = selected
            sources = [source for source in selected_payload['choices'] if source['peer'] == list(pins[0]) and source['own'] == list(pins[1]) and
                source['share_id'] == body['share_id'] and source['setup_id'] == body['setup_id']]
            if len(sources) != 1:
                raise PermissionError('notes_choice_source_changed')
            source = sources[0]
            history = {name: source[name] for name in ('peer', 'own', 'local_id', 'local_uid')}
            history.update(source_setup_id=source['setup_id'], result={'share_id': source['share_id']},
                choice_seal={'key_sha256': hashlib.sha256(selected_key).hexdigest(), 'generation': selected_payload['generation'],
                    'book': selected_payload['book'], 'source_sha256': hashlib.sha256(_frame_bytes(source)).hexdigest()})
        else:
            raise PermissionError('notes_choice_private_ack_history_required')
        if pins != (tuple(history['peer']), tuple(history['own'])):
            raise PermissionError('notes_choice_repeated_result_changed')
        active = self._active_record()
        if active is None or self._native_data is None:
            raise PermissionError('notes_choice_recognized_primary_required')
        key, payload = active
        claim = history['choice_seal']
        matches = [source for source in payload['choices'] if source['peer'] == history['peer'] and source['own'] == history['own'] and
            source['setup_id'] == history['source_setup_id'] and source['share_id'] == history['result']['share_id'] and
            source['local_id'] == history['local_id'] and source['local_uid'] == history['local_uid']]
        if (len(matches) != 1 or claim != {'key_sha256': hashlib.sha256(key).hexdigest(), 'generation': payload['generation'],
                'book': payload['book'], 'source_sha256': hashlib.sha256(_frame_bytes(matches[0])).hexdigest()}):
            raise PermissionError('notes_choice_ack_binding_changed')
        primary, binding = self._primary()
        if payload['book'] != self._tag(key, b'book', binding.encode('utf-8')) or payload['content'] != primary.content_sha256:
            raise PermissionError('notes_choice_recognized_primary_required')
        data = json.loads(_frame_bytes(self._native_data()))
        if not isinstance(data, dict) or book_hash(data) != primary.content_sha256:
            raise PermissionError('notes_choice_native_primary_changed')
        contacts = [contact for contact in data.get('kontakte', []) if isinstance(contact, dict) and contact.get('id') == history['local_id']]
        if len(contacts) != 1 or contacts[0].get('uid') != history['local_uid']:
            raise PermissionError('notes_choice_ack_contact_changed')
        with self._locked() as directory:
            current_key, current = self._record(directory)
            if current_key != key or current != payload or self._intent(directory, key, payload) is not None:
                raise PermissionError('notes_choice_ack_context_changed')
        if self._primary() != (primary, binding):
            raise PermissionError('notes_choice_native_primary_changed')
        return history

    def bootstrap_export(self, body, origin, transport, guard):
        from magnolie_contact_notes_requests import NativeNotesBootstrapSave
        if type(origin) is not NativeNotesFsOrigin:
            raise PermissionError('notes_choice_authenticated_export_required')
        context = _NotesExportBootstrapContext(self, _frame_bytes(body), origin, transport)
        context.require_current()
        return NativeNotesBootstrapSave(context, guard)

    def restore(self, body, origin, transport_id):
        if type(origin) is not NativeNotesFsOrigin:
            raise PermissionError('notes_choice_authenticated_export_required')
        peer, own = origin.require_current(body, transport_id)
        active = self._active_record()
        if active is None or not self.recognizes_saved():
            raise PermissionError('notes_choice_recognized_saved_book_required')
        key, payload = active
        saved, _ = self._saved()
        primary, binding = self._primary()
        if primary.content_sha256 != saved.content_sha256:
            raise PermissionError('notes_choice_native_primary_changed')
        matches = [item for item in payload['choices'] if item['peer'] == list(peer) and item['own'] == list(own) and
            item['share_id'] == body.get('share_id') and item['setup_id'] == body.get('setup_id')]
        if len(matches) != 1:
            raise PermissionError('notes_choice_source_changed')
        source = matches[0]
        # Only this sealed private choice chooses an existing saved ID here;
        # no user prompt, portable tag lookup or name/default-book fallback.
        choice = NativeNotesExportChoice(body, origin, transport_id, saved, self._capture, lambda _: source['local_id'])
        if choice._uid != source['local_uid']:
            raise PermissionError('notes_choice_contact_changed')
        self._attach(choice, key, payload, source)
        choice.require_current()
        if self._primary() != (primary, binding):
            raise PermissionError('notes_choice_native_primary_changed')
        return choice

    def prepare_current_save(self, text):
        if self._active_record() is None:
            return None
        current = self._capture()
        if current is None:
            current, _ = self._primary()
            self.recover_primary(current)
        else:
            self.recover_saved(current)
        return self.prepare_save(current, text)

    def revoke(self):
        with self._setup_lock:
            self._setup_version += 1  # Invalidate same-owner open FIRST setup even when no key exists.
        active = self._active_record()
        if active is None:
            return
        key, payload = active
        disabled = dict(payload, generation=os.urandom(32).hex(), content=None, choices=[])
        with self._locked() as directory:
            if self._record(directory) != (key, payload):
                raise PermissionError('notes_choice_native_context_changed')
            self._publish(directory, key, disabled)
