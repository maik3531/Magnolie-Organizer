"""Notes full-return interoperability; no enabled source/transport capability.

The native Notes target hash is NOT a sorted document/renderer hash. Match its
existing KontaktSync projection/normalization before correlating a real pending
desktop request. This module alone cannot grant sources or issue a SaveACK.
"""
import hashlib
import hmac
import json
import os
import re
import unicodedata
from dataclasses import dataclass
import threading
import uuid

from magnolie_contact_source_book import NativeContactSourceResultCommit
from magnolie_contact_source_authority import NativeContactSourceApprovalStore as _PrivateFiles
from magnolie_personal_actor_store import NativeProducerBookSnapshot


def _frame_bytes(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


@dataclass(frozen=True)
class _FsOriginProof:
    peer: tuple
    own: tuple
    body_hash: bytes
    transport_id: str
    current: object


class NativeNotesFsOrigin:
    """Process-local actual FS1 origin, never a JSON source grant or save ACK."""
    def __init__(self, proof):
        self._proof = proof

    def _native(self):
        if type(self._proof) is not _FsOriginProof:
            raise PermissionError('notes_original_authenticated_origin_required')
        return self._proof

    def require_current(self, body, transport_id):
        proof = self._native()
        if (proof.current() is not True or transport_id != proof.transport_id or
                not hmac.compare_digest(hashlib.sha256(_frame_bytes(body)).digest(), proof.body_hash)):
            raise PermissionError('notes_original_authenticated_origin_changed')
        return proof.peer, proof.own


def _issue_notes_fs_origin(peer, own, body, transport_id, current):
    """Native issuer used only immediately after actual FS1 authenticated open.

    No bridge/deserializer calls this factory. The receive service supplies its
    pinned handshake identities and native stop/expiry/current-state callback.
    """
    result = NativeNotesFsOrigin(_FsOriginProof(tuple(peer), tuple(own),
        hashlib.sha256(_frame_bytes(body)).digest(), transport_id, current))
    result.require_current(body, transport_id)
    return result


class NativeNotesPendingResult:
    """Native pending request -> authenticated result -> actual book invocation.

    No bridge registration or production factory exists yet. The native caller
    must supply its private mapping/setup authority, not imported contact tags.
    Receiving only stages work: prepare_commit/confirmed_save run later under
    the existing book mutation gate, never inside the tree receive lock.
    This joins the actual writer but does not yet issue/send a wire SaveACK.
    """
    def __init__(self, snapshot, request, local_id, local_uid, peer, own, capture_current, require_mapping, *, before_revision=0, source_choice=None):
        if (type(snapshot) is not NativeProducerBookSnapshot or not callable(capture_current) or
                not callable(require_mapping) or not isinstance(request, dict)):
            raise TypeError('notes_original_native_pending_required')
        if type(before_revision) is not int or not 0 <= before_revision <= 2**63 - 1:
            raise ValueError('notes_original_pending_revision_required')
        self._before_revision = before_revision
        if source_choice is not None and type(source_choice) is not NativeNotesExportChoice:
            raise PermissionError('notes_original_native_export_choice_required')
        self._source_choice = source_choice
        self._lock = threading.RLock()
        self._work_lock = threading.RLock()
        self._snapshot, self._capture, self._mapping = snapshot, capture_current, require_mapping
        self._peer, self._own = tuple(peer), tuple(own)
        self._request_text = _frame_bytes(request)
        self._request_hash = hashlib.sha256(self._request_text).hexdigest()
        owned = json.loads(self._request_text)
        fields = {'art', 'fassung', 'request_id', 'share_id', 'before_basis', 'target_sha256', 'ziel'}
        patch_fields = {'vorname', 'nachname', 'anzeigename', 'vcardName', 'firma', 'notiz', 'geburtstag', 'jubilaeum', 'anschriften'}
        if (set(owned) != fields or owned['art'] != 'kontakt_original_anfrage' or
                type(owned['fassung']) is not int or owned['fassung'] != 1 or
                not _request_uuid(owned['request_id']) or not _digest(owned['before_basis']) or
                not _digest(owned['target_sha256']) or not isinstance(owned['share_id'], str) or
                not owned['share_id'] or not isinstance(owned['ziel'], dict) or set(owned['ziel']) != patch_fields):
            raise ValueError('notes_original_pending_request_schema')
        contacts = snapshot.book().get('kontakte', [])
        selected = [index for index, contact in enumerate(contacts) if contact.get('id') == local_id]
        if len(selected) != 1 or contacts[selected[0]].get('uid') != local_uid or not local_id or not local_uid:
            raise PermissionError('notes_original_pending_contact_required')
        self._index, self._local_id, self._local_uid = selected[0], local_id, local_uid
        if source_choice is not None:
            source_choice.require_current()
            exported = json.loads(source_choice._body_text)
            patch = _saved_mutable_projection(contacts[self._index], exported['kontakt'])
            if (source_choice._id != local_id or source_choice._uid != local_uid or source_choice._peer != self._peer or
                    source_choice._own != self._own or source_choice._book_source != snapshot.book_source or
                    owned['share_id'] != exported['share_id'] or owned['before_basis'] != exported['before_basis'] or
                    owned['ziel'] != patch or owned['target_sha256'] != notes_content_hash(dict(exported['kontakt'], **patch)) or
                    before_revision != exported['native_revision']):
                raise PermissionError('notes_original_native_choice_retargeted')
        self._result_text, self._origin, self._transport, self._commit = None, None, None, None
        self._require_before()

    def request(self):
        with self._work_lock:
            self._require_before()
            return json.loads(self._request_text)

    def _require_before(self):
        # The callback must check the genuine native source/mapping/setup grant.
        # Returning document flags or accepting renderer fields is not a caller.
        self._mapping()
        if self._capture() != self._snapshot:
            raise PermissionError('notes_original_pending_book_changed')
        self._mapping()

    def stage_result(self, body, origin, transport_id):
        """Actual receive callback may call this without acquiring the book lock.

        No book access, private mapping callback, writer wait or ACK occurs here.
        Exact repeats retain the same invocation; conflicts cannot replace it.
        """
        if type(origin) is not NativeNotesFsOrigin:
            raise PermissionError('notes_original_authenticated_origin_required')
        # Never call the origin (tree gate) while holding the pending-state
        # lock: a book worker may be running concurrently with this callback.
        identities = origin.require_current(body, transport_id)
        if identities != (self._peer, self._own):
            raise PermissionError('notes_original_pending_peer_changed')
        owned = json.loads(_frame_bytes(body))
        request = json.loads(self._request_text)
        fields = {'art', 'fassung', 'request_id', 'request_sha256', 'share_id', 'before_basis',
                  'target_sha256', 'receipt_id', 'native_revision', 'next_basis'}
        if (set(owned) != fields or owned['art'] != 'kontakt_original_ergebnis' or
                type(owned['fassung']) is not int or owned['fassung'] != 1 or
                any(owned[name] != request[name] for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')) or
                owned['request_sha256'] != self._request_hash or not _request_uuid(owned['receipt_id']) or
                type(owned['native_revision']) is not int or not self._before_revision < owned['native_revision'] <= 2**63 - 1 or
                not _digest(owned['next_basis']) or owned['next_basis'] == request['before_basis']):
            raise ValueError('notes_original_pending_result_changed')
        text = _frame_bytes(owned)
        origin.require_current(body, transport_id)
        with self._lock:
            if self._result_text is not None and self._result_text != text:
                raise PermissionError('notes_original_pending_result_held')
            if self._result_text is None:
                self._result_text, self._origin, self._transport = text, origin, transport_id

    def _require_origin(self):
        self._mapping()
        with self._lock:
            text, origin, transport = self._result_text, self._origin, self._transport
        if text is None:
            raise PermissionError('notes_original_pending_result_required')
        origin.require_current(json.loads(text), transport)
        self._mapping()

    def prepare_commit(self):
        """Called under the actual native book gate, outside receive dispatch."""
        with self._work_lock:
            self._require_origin()
            if self._commit is None:
                self._require_before()
                proposal = self._snapshot.book()
                contact = proposal['kontakte'][self._index]
                # Evidence only: never a portable source grant. The common UI
                # must preserve this metadata before production can be enabled.
                result = json.loads(self._result_text)
                contact['notesOriginalBasis'] = {
                    'fassung': 1, 'share_id': result['share_id'], 'basis': result['next_basis'],
                    'native_revision': str(result['native_revision']),
                    'request_id': result['request_id'], 'request_sha256': result['request_sha256'],
                    'target_sha256': result['target_sha256'], 'receipt_id': result['receipt_id']}
                self._commit = NativeContactSourceResultCommit(self._snapshot, proposal, self._capture, self._require_origin)
            return self._commit

    def confirmed_save(self):
        """Actual confirmed-save correlation, NOT a wire ACK or release token.

        Durable private ACK intent, restart restoration and negotiated sending
        must be connected before this can become an enabled SaveACK producer.
        """
        with self._work_lock:
            self._require_origin()
            if self._commit is None:
                raise PermissionError('notes_original_save_unconfirmed')
            witness = self._commit.saved_witness()
            saved = witness.require_current()
            self._require_origin()
            if witness.require_current() != saved:
                raise PermissionError('notes_original_saved_frame_changed')
            return {'result': json.loads(self._result_text), 'saved_book': saved}


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(char in '0123456789abcdef' for char in value)


def _request_uuid(value):
    try:
        parsed = uuid.UUID(value)
        return isinstance(value, str) and parsed.version == 4 and str(parsed) == value
    except (ValueError, TypeError, AttributeError):
        return False


class NativeNotesExportChoice:
    """Process-local native choice from an actual authenticated Notes export.

    Invoke later under the native book gate, NOT from the tree receive callback.
    This is not a portable tag loader or durable setup implementation. No UI or
    production controller registers this factory until restart authority exists.
    """
    def __init__(self, body, origin, transport_id, snapshot, capture_current, choose_native):
        if (type(origin) is not NativeNotesFsOrigin or type(snapshot) is not NativeProducerBookSnapshot or
                not callable(capture_current) or not callable(choose_native)):
            raise PermissionError('notes_original_native_export_choice_required')
        self._body_text = _frame_bytes(body)
        owned = json.loads(self._body_text)
        self._origin, self._transport, self._capture = origin, transport_id, capture_current
        self._peer, self._own = origin.require_current(owned, transport_id)
        if (set(owned) != {'art', 'fassung', 'share_id', 'before_basis', 'setup_id', 'native_revision', 'content_sha256', 'kontakt'} or
                owned['art'] != 'kontakt_original_export' or type(owned['fassung']) is not int or owned['fassung'] != 1 or
                not isinstance(owned['share_id'], str) or not 0 < len(owned['share_id']) <= 128 or
                any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in owned['share_id']) or
                not _digest(owned['before_basis']) or not _request_uuid(owned['setup_id']) or type(owned['native_revision']) is not int or
                not 0 <= owned['native_revision'] <= 2**63 - 1 or not _digest(owned['content_sha256']) or
                notes_content_hash(owned['kontakt']) != owned['content_sha256']):
            raise ValueError('notes_original_export_schema')
        if capture_current() != snapshot:
            raise PermissionError('notes_original_export_book_changed')
        contacts = snapshot.book().get('kontakte', [])
        # Explicit native choice among actual saved contacts, never a lookup by
        # imported share/source tags, matching display names or default book.
        selected = choose_native(tuple(json.loads(json.dumps(contact, ensure_ascii=False)) for contact in contacts))
        matches = [contact for contact in contacts if contact.get('id') == selected]
        if (len(matches) != 1 or not isinstance(selected, str) or not selected or
                not isinstance(matches[0].get('uid'), str) or not matches[0]['uid']):
            raise PermissionError('notes_original_export_native_choice_required')
        self._id, self._uid, self._book_source = selected, matches[0]['uid'], snapshot.book_source
        self._active = True
        if capture_current() != snapshot:
            raise PermissionError('notes_original_export_book_changed')
        self.require_current()

    def require_current(self):
        if not self._active:
            raise PermissionError('notes_original_native_choice_revoked')
        body = json.loads(self._body_text)
        self._origin.require_current(body, self._transport)

        current = self._capture()
        if type(current) is not NativeProducerBookSnapshot or current.book_source != self._book_source:
            raise PermissionError('notes_original_export_book_changed')
        matches = [contact for contact in current.book().get('kontakte', []) if contact.get('id') == self._id]
        if len(matches) != 1 or matches[0].get('uid') != self._uid:
            raise PermissionError('notes_original_export_contact_changed')
        self._origin.require_current(body, self._transport)

    def revoke(self):
        """Native choice-owner cancellation; no renderer/document restore path."""
        self._active = False

    def pending(self):
        self.require_current()
        snapshot = self._capture()
        local = next(contact for contact in snapshot.book()['kontakte'] if contact.get('id') == self._id)
        exported = json.loads(self._body_text)
        before = exported['kontakt']
        patch = _saved_mutable_projection(local, before)
        target = dict(before, **patch)
        if target == before:
            raise ValueError('notes_original_no_mutation_required')
        request = {'art': 'kontakt_original_anfrage', 'fassung': 1, 'request_id': str(uuid.uuid4()),
            'share_id': exported['share_id'], 'before_basis': exported['before_basis'],
            'target_sha256': notes_content_hash(target), 'ziel': patch}
        return NativeNotesPendingResult(snapshot, request, self._id, self._uid, self._peer, self._own,
            self._capture, self.require_current, before_revision=exported['native_revision'], source_choice=self)


def _saved_mutable_projection(contact, before):
    """Bounded native saved-book projection; no renderer-supplied target DTO.

    Retain all excluded native phone/email/photo/group fields via the exported
    before model. Unsupported local postal columns/changed custom labels hold
    rather than pretending that the Android model represents them losslessly.
    """
    patch = {name: _native_text(contact.get(name, '')) for name in
             ('vorname', 'nachname', 'firma', 'notiz', 'geburtstag', 'jubilaeum', 'anzeigename')}
    if contact.get('geburtstagJahrUnbekannt') is True and re.fullmatch(r'\d{4}-\d{2}-\d{2}', patch['geburtstag']):
        patch['geburtstag'] = '--' + patch['geburtstag'][5:]
    raw_names = contact.get('vcardRoundtrip', [])
    if not isinstance(raw_names, list):
        raise ValueError('notes_original_saved_name_projection')
    patch['vcardName'] = [line for line in map(_native_text, raw_names) if re.match(r'^(?:[A-Za-z0-9-]+\.)?(?:N|FN)[;:]', line, re.I)]
    rows = contact.get('anschriften', [])
    if not isinstance(rows, list):
        raise ValueError('notes_original_saved_postal_projection')
    if not rows and any(contact.get(name) for name in ('strasse', 'plz', 'ort')):
        rows = [{name: contact.get(name, '') for name in ('strasse', 'plz', 'ort')}]
    postal = []
    for row in rows:
        if not isinstance(row, dict) or any(row.get(name) for name in ('postfach', 'zusatz')):
            raise ValueError('notes_original_saved_postal_projection')
        fields = {name: _native_text(row.get(name, '')) for name in ('strasse', 'plz', 'ort', 'region', 'land')}
        types, label = row.get('typen', []), _native_text(row.get('label', ''))
        if not isinstance(types, list) or any(type(value) is not str for value in types):
            raise ValueError('notes_original_saved_postal_projection')
        if label:
            same = [value for value in before.get('anschriften', []) if value['art'] == label and
                    all(value[name] == fields[name] for name in fields)]
            if len(same) != 1:
                raise ValueError('notes_original_saved_postal_label_not_supported')
            kind = same[0]['art']
        elif types == ['HOME']:
            kind = 'privat'
        elif types == ['WORK']:
            kind = 'arbeit'
        elif types in ([], ['OTHER']):
            kind = 'sonstige'
        else:
            raise ValueError('notes_original_saved_postal_kind_not_supported')
        postal.append(dict(art=kind, **fields))
    patch['anschriften'] = postal
    return patch


@dataclass(frozen=True)
class _SavedAckProof:
    store: object
    key: str
    ciphertext_hash: bytes
    pending: NativeNotesPendingResult
    record_text: bytes


class NativeNotesSavedAckIntent:
    """Fresh native-only durable intent. There is no JSON deserializer/factory."""
    def __init__(self, proof):
        self._proof = proof

    def body(self):
        proof = self._proof
        if type(proof) is not _SavedAckProof:
            raise PermissionError('notes_original_native_saved_ack_required')
        return proof.store._ack_body(proof)


class NativeNotesAckIntents:
    """Encrypted durable post-save intentions, independent of source consent.

    The native caller supplies ONLY its existing journal-key accessor. This
    store neither creates a replacement key nor reads a key/permission from a
    document. Readback after restart is history, not a fresh send grant.
    No production sender or restoration authority is wired by adding this store.
    """
    # Reuse the existing descriptor-relative private filesystem primitives only;
    # no consent records, consent key creation or source-authority API is reused.
    _private = staticmethod(_PrivateFiles._private)
    _locked = _PrivateFiles._locked
    _read = _PrivateFiles._read
    _write = _PrivateFiles._write
    _DOMAIN = b'Magnolie/notes-original-saved-ack-intent/v1\0'

    def __init__(self, root, existing_journal_key, *, stage=lambda _: None):
        if not callable(existing_journal_key) or not callable(stage):
            raise TypeError('notes_original_existing_journal_key_required')
        self.root, self._existing_key, self._stage = os.path.abspath(root), existing_journal_key, stage

    def _cipher(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = self._existing_key()
        if type(key) is not bytes or len(key) != 32:
            raise PermissionError('notes_original_journal_key_unavailable')
        return AESGCM(key)

    @staticmethod
    def _key(record):
        request = record['request']
        # Same UUID on the same chosen source cannot bypass a conflicting
        # earlier saved result merely by changing its body or receipt.
        return hashlib.sha256(_frame_bytes({'peer': record['peer'], 'own': record['own'],
            'share_id': request['share_id'], 'request_id': request['request_id']})).hexdigest()

    @staticmethod
    def _capture(pending):
        if type(pending) is not NativeNotesPendingResult:
            raise PermissionError('notes_original_native_pending_required')
        confirmed = pending.confirmed_save()
        choice = pending._source_choice
        if type(choice) is not NativeNotesExportChoice:
            raise PermissionError('notes_original_native_export_choice_required')
        choice.require_current()
        request = json.loads(pending._request_text)
        return {'format': 1, 'state': 'saved_ack_intent', 'peer': list(pending._peer), 'own': list(pending._own),
            'local_id': pending._local_id, 'local_uid': pending._local_uid, 'request': request,
            'result': confirmed['result'], 'saved_book': list(confirmed['saved_book']),
            'source_setup_id': json.loads(choice._body_text)['setup_id']}

    def _decode(self, key, blob):
        if len(blob) > 512 * 1024 or len(blob) < 29 or blob[:1] != b'\x01':
            raise ValueError('notes_original_saved_intent_schema')
        clear = self._cipher().decrypt(blob[1:13], blob[13:], self._DOMAIN + key.encode('ascii'))
        record = json.loads(clear)
        fields = {'format', 'state', 'peer', 'own', 'local_id', 'local_uid', 'request', 'result', 'saved_book'}
        if (not isinstance(record, dict) or set(record) not in (fields, fields | {'source_setup_id'}) or
                record['format'] != 1 or type(record['format']) is not int or record['state'] != 'saved_ack_intent' or
                _frame_bytes(record) != clear or self._key(record) != key):
            raise ValueError('notes_original_saved_intent_schema')
        if 'source_setup_id' in record and not _request_uuid(record['source_setup_id']):
            raise ValueError('notes_original_saved_intent_setup_required')
        return record

    def seal_after_save(self, pending):
        # All book/origin/mapping callbacks stay outside the private file lock.
        record = self._capture(pending)
        clear, key = _frame_bytes(record), self._key(record)
        if len(clear) > 500 * 1024:
            raise ValueError('notes_original_saved_intent_budget')
        cipher = self._cipher()  # No empty state if the existing key is missing.
        self._stage('before_write')
        with self._locked(create=True) as directory:
            name = key + '.bin'
            try:
                blob = self._read(directory, name, 512 * 1024)
            except FileNotFoundError:
                nonce = os.urandom(12)
                blob = b'\x01' + nonce + cipher.encrypt(nonce, clear, self._DOMAIN + key.encode('ascii'))
                self._write(directory, name, blob)
            if self._decode(key, blob) != record:
                raise PermissionError('notes_original_saved_intent_held')
            # Exact readback and file+directory durability are required also for
            # an existing identical intent after an interrupted previous call.
            if self._read(directory, name, 512 * 1024) != blob:
                raise PermissionError('notes_original_saved_intent_changed')
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                self._private(os.fstat(descriptor)); os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(directory)
        self._stage('after_durable_write')
        if _frame_bytes(self._capture(pending)) != clear:
            raise PermissionError('notes_original_saved_frame_changed')
        return NativeNotesSavedAckIntent(_SavedAckProof(self, key, hashlib.sha256(blob).digest(), pending, clear))

    def load_held(self, key):
        """Read-only history, deliberately no send proof or provider replay API."""
        if not _digest(key):
            raise ValueError('notes_original_saved_intent_key')
        try:
            with self._locked(create=False) as directory:
                blob = self._read(directory, key + '.bin', 512 * 1024)
                return self._decode(key, blob)
        except FileNotFoundError:
            return None

    def _ack_body(self, proof):
        if proof.store is not self:
            raise PermissionError('notes_original_native_saved_ack_required')
        with self._locked(create=False) as directory:
            blob = self._read(directory, proof.key + '.bin', 512 * 1024)
            record = self._decode(proof.key, blob)
        if (not hmac.compare_digest(hashlib.sha256(blob).digest(), proof.ciphertext_hash) or
                _frame_bytes(record) != proof.record_text or _frame_bytes(self._capture(proof.pending)) != proof.record_text):
            raise PermissionError('notes_original_saved_intent_changed')
        # Dedicated draft data only. The generic outbox must not send a copied
        # dict; future reserved send admission must retain this native intent.
        result = record['result']
        return {'art': 'kontakt_original_saveack', 'fassung': 1,
            **{name: result[name] for name in ('request_id', 'request_sha256', 'share_id', 'before_basis',
                'target_sha256', 'receipt_id', 'native_revision', 'next_basis')},
            'desktop_sha256': record['saved_book'][2]}


def _native_text(value):
    if not isinstance(value, str) or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError('notes_original_text_required')
    return value


def _blank_char(char):
    # Kotlin Char.isWhitespace = Java isWhitespace OR isSpaceChar.
    return char in '\t\n\v\f\r\x1c\x1d\x1e\x1f' or unicodedata.category(char) in ('Zs', 'Zl', 'Zp')


def _trim(value):
    start, end = 0, len(value)
    while start < end and _blank_char(value[start]):
        start += 1
    while end > start and _blank_char(value[end - 1]):
        end -= 1
    return value[start:end]


def _distinct(values, key):
    seen, result = set(), []
    for value in values:
        identity = key(value)
        if identity not in seen:
            seen.add(identity)
            result.append(value)
    return result


def _escape_name(text):
    return text.replace('\\', '\\\\').replace('\r\n', '\\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def _root_lower(value):
    # Notes runs Java String ROOT casing, whose final-sigma context uses ROOT
    # word boundaries and its cased categories, not Python's Unicode lower().
    if 'Σ' not in value:
        return value.lower()
    def cased(char):
        number = ord(char)
        return unicodedata.category(char) in ('Ll', 'Lu', 'Lt') or number in (0x345, 0x37A) or any(
            start <= number <= end for start, end in ((0x2B0, 0x2B8), (0x2C0, 0x2C1), (0x2E0, 0x2E4),
                (0x1D2C, 0x1D61), (0x2160, 0x217F), (0x24B6, 0x24E9)))
    def kind(char):
        number = ord(char); category = unicodedata.category(char)
        cjk = number in (0x3005, 0x309D, 0x309E, 0x30FD, 0x30FE) or any(start <= number <= end
            for start, end in ((0x4E00, 0x9FA5), (0xF900, 0xFA2D), (0x3041, 0x3094), (0x30A1, 0x30FC), (0x3099, 0x309C)))
        return 'L' if (category.startswith('L') or category == 'Mc') and not cjk else 'N' if category.startswith('N') else ''
    def middle(char, previous, following):
        return previous == following and (previous == 'L' and (unicodedata.category(char) in ('Pd', 'Pc') or char in '\u00ad\u2027\"\'.') or
            previous == 'N' and char in '\"\',\u066b.')
    positions = [(index, char) for index, char in enumerate(value) if unicodedata.category(char) != 'Cf']
    chars = [char for _, char in positions]
    finals, index = set(), 0
    def unit_end(start):
        end = start + 1
        while end < len(chars) and unicodedata.category(chars[end]) in ('Mn', 'Me'):
            end += 1
        return end
    while index < len(chars):
        previous = kind(chars[index])
        if not previous:
            index += 1; continue
        start, end = index, unit_end(index)
        while end < len(chars):
            following = kind(chars[end])
            if following:
                previous = following; end = unit_end(end)
            elif end + 1 < len(chars) and middle(chars[end], previous, kind(chars[end + 1])):
                previous = kind(chars[end + 1]); end = unit_end(end + 1)
            else:
                break
        remaining = sum(cased(char) for char in chars[start:end]); before = 0
        for offset in range(start, end):
            is_cased = cased(chars[offset]); remaining -= is_cased
            if chars[offset] == 'Σ' and before and not remaining:
                finals.add(positions[offset][0])
            before += is_cased
        index = end
    return ''.join(('ς' if index in finals else 'σ') if char == 'Σ' else char.lower() for index, char in enumerate(value))


def notes_content_hash(content):
    """Hash an actual validated Notes contact projection, not source authority.

    Validation/admission must still reject invalid DTOs and unsupported edits;
    this reproduces the native content fingerprint, including legacy projection.
    """
    scalar = ('vorname', 'nachname', 'firma', 'notiz', 'geburtstag', 'jubilaeum', 'anzeigename', 'foto')
    allowed = set(scalar) | {'vcardName', 'telefone', 'emailEintraege', 'anschriften', 'gruppen'}
    if not isinstance(content, dict) or set(content) - allowed:
        raise ValueError('notes_original_projection_required')
    text = {name: _native_text(content.get(name, '')) for name in scalar}
    def text_list(name):
        values = content.get(name, [])
        if not isinstance(values, list):
            raise ValueError('notes_original_list_required')
        return [_native_text(value) for value in values]
    names = text_list('vcardName')
    def rows(name, fields):
        values = content.get(name, [])
        if not isinstance(values, list):
            raise ValueError('notes_original_list_required')
        if any(not isinstance(value, dict) or set(value) != set(fields) for value in values):
            raise ValueError('notes_original_row_required')
        return [{field: _native_text(value[field]) for field in fields} for value in values]
    phones = rows('telefone', ('art', 'wert'))
    emails = rows('emailEintraege', ('art', 'wert'))
    postal = rows('anschriften', ('art', 'strasse', 'plz', 'ort', 'region', 'land'))
    # Kotlin filters UTF-16 Char values: astral digits/superscripts are not BMP Nd.
    def phone_key(value):
        return ''.join(char for char in value['wert'] if char == '+' or ord(char) <= 0xFFFF and unicodedata.category(char) == 'Nd').lstrip('+')
    phones = _distinct([value for value in phones if _trim(value['wert'])], phone_key)
    emails = _distinct([value for value in emails if _trim(value['wert'])], lambda value: _root_lower(_trim(value['wert'])))
    def postal_key(value):
        return '|'.join(_root_lower(_trim(value[field])) for field in ('strasse', 'plz', 'ort', 'region', 'land'))
    postal = _distinct([value for value in postal if _trim(postal_key(value))], postal_key)
    groups = None
    if content.get('gruppen') is not None:
        groups = _distinct([unicodedata.normalize('NFC', _trim(value)) for value in text_list('gruppen') if _trim(value)], _root_lower)
        groups.sort(key=lambda value: value.encode('utf-16-be'))
    fn = ' '.join(value for value in (text['vorname'], text['nachname']) if value)
    n = 'N:' + _escape_name(text['nachname']) + ';' + _escape_name(text['vorname']) + ';;;'
    legacy = not text['jubilaeum'] and text['anzeigename'] in ('', fn) and all(value in (n, 'FN:' + _escape_name(fn)) for value in names)
    result = {name: text[name] for name in ('vorname', 'nachname', 'firma', 'notiz', 'geburtstag')}
    if groups is not None or not legacy:
        result.update(jubilaeum=text['jubilaeum'], anzeigename=text['anzeigename'], vcardName=names)
    if text['foto']:
        result['foto'] = text['foto']
    if groups is not None:
        result['gruppen'] = groups
    result.update(telefone=phones, emailEintraege=emails, anschriften=postal)
    return hashlib.sha256(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
