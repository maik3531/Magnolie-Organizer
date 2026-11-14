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

from magnolie_contact_book_save_chain import NativeContactBookSaveChain
from magnolie_contact_source_authority import NativeContactSourceApprovalStore as _PrivateFiles
from magnolie_contact_notes_return import NativeNotesExportChoice, NativeNotesFsOrigin, _digest, _request_uuid, _frame_bytes


class NativeNotesChoiceStore(NativeContactBookSaveChain):
    _private = staticmethod(_PrivateFiles._private)
    _locked = _PrivateFiles._locked
    _read = _PrivateFiles._read
    _write = _PrivateFiles._write
    _DOMAIN = b'Magnolie/native-notes-contact-choice/v1\0'

    def __init__(self, root, capture_current, current_book_binding, capture_primary):
        if (not isinstance(root, str) or not os.path.isabs(root) or
                not all(callable(value) for value in (capture_current, current_book_binding, capture_primary))):
            raise TypeError('notes_choice_native_book_callbacks_required')
        self.root, self._capture, self._binding, self._capture_primary = root, capture_current, current_book_binding, capture_primary

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
        with self._locked(create=True) as directory:
            self._publish(directory, key, payload)
        if self._saved() != (saved, binding) or self._primary() != (primary, primary_binding):
            raise PermissionError('notes_choice_native_book_changed')
        for choice in selected:
            choice.require_current()

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
        active = self._active_record()
        if active is None:
            return
        key, payload = active
        disabled = dict(payload, generation=os.urandom(32).hex(), content=None, choices=[])
        with self._locked() as directory:
            if self._record(directory) != (key, payload):
                raise PermissionError('notes_choice_native_context_changed')
            self._publish(directory, key, disabled)
