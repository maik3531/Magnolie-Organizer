"""Private native proposal preparation from a fresh saved GUI book.

No peer-supplied targets, data mutations, queue writes or transport. The native
caller must supply its current accepted scope and source/writer observations;
this plan does not itself authorize staging or replace later fresh gates.
"""
import copy
import re
import uuid

import magnolie_content_scope as scope
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
from magnolie_personal_actor_store import NativeProducerBookSnapshot

HEX = re.compile(r"^[0-9a-f]{64}$")


def _identifier(value):
    return (isinstance(value, str) and bool(value) and value == value.strip() and '\0' not in value and
            len(value.encode('utf-8')) <= 160)


def _note_id(value, state):
    seen = set()
    aliases = state.get('note_aliases', {})
    if not isinstance(aliases, dict) or not _identifier(value):
        raise ValueError('invalid_native_note_identity')
    while value in aliases:
        target = aliases[value]
        if value in seen or not _identifier(target) or target.encode('utf-8') >= value.encode('utf-8'):
            raise ValueError('invalid_native_note_alias')
        seen.add(value); value = target
    return value


def _note_wire_id(value, state):
    ids = state.get('note_ids', {})
    if not isinstance(ids, dict):
        raise ValueError('invalid_native_note_identity')
    return _note_id(ids.get(value, value), state)


def _attachment_id(parent, value, state):
    aliases = state.get('attachment_aliases', {})
    if not isinstance(aliases, dict) or not _identifier(value):
        raise ValueError('invalid_native_attachment_identity')
    parent = _note_id(parent, state); seen = set()
    while True:
        targets = []
        for key, target in aliases.items():
            parts = key.split('\0')
            if len(parts) == 2 and parts[1] == value and _note_id(parts[0], state) == parent:
                if not _identifier(target) or target.encode('utf-8') >= value.encode('utf-8'):
                    raise ValueError('invalid_native_attachment_alias')
                targets.append(target)
        if not targets:
            return value
        if value in seen:
            raise ValueError('invalid_native_attachment_alias')
        seen.add(value); value = min(targets, key=lambda item: item.encode('utf-8'))


def prepare_deletion_proposals(snapshot, manifest, peer_id, run_id, *, current_saved_book, current_source):
    """Prepare the entire bounded group, or fail before returning any frame.

    Historical targets outside the CURRENT accepted scope remain excluded even
    if a book contains old peer acknowledgments or local-pending tombstones.
    """
    actor.start(run_id)
    if not isinstance(peer_id, str) or personal.UUID4.fullmatch(peer_id) is None:
        raise ValueError('invalid_native_peer')
    if not isinstance(snapshot, NativeProducerBookSnapshot) or not callable(current_saved_book) or not callable(current_source):
        raise TypeError('Native producer snapshot and observations are required')
    source = current_source()
    if not isinstance(source, str) or HEX.fullmatch(source) is None or current_saved_book() != snapshot.saved_book:
        raise PermissionError('actor_producer_source_changed')
    manifest = copy.deepcopy(manifest); scope.validate(manifest)
    notes, tasks = set(manifest['members']['notes']), set(manifest['members']['tasks'])
    book = snapshot.book(); state = book.get('personalSync', {})
    if not isinstance(state, dict) or not isinstance(state.get('entities', {}), dict):
        raise ValueError('invalid_native_personal_state')
    live_notes = {}
    for note in book.get('notizen', []):
        canonical = _note_wire_id(note['id'], state)
        if canonical in live_notes:
            raise ValueError('ambiguous_native_note_identity')
        live_notes[canonical] = note
    live_tasks = {task['id'] for task in book.get('aufgaben', [])}
    proposals = []
    if state.get('peer_device_id') == peer_id:
        for key, meta in state.get('entities', {}).items():
            if not isinstance(meta, dict) or meta.get('state') != 'deleted' or meta.get('status') != 'local_pending' or meta.get('peer_device_id') != peer_id:
                continue
            parts = key.split('\0'); kind = parts[0]
            if kind == 'note' and len(parts) == 2:
                identifier, parent = parts[1], ''
                if identifier not in notes or identifier in live_notes:
                    continue
            elif kind == 'task' and len(parts) == 2:
                identifier, parent = parts[1], ''
                if identifier not in tasks or identifier in live_tasks:
                    continue
            elif kind == 'attachment' and len(parts) == 3:
                parent, identifier = parts[1:]
                note = live_notes.get(parent)
                if parent not in notes or note is None or note.get('baumQuelle') and note.get('persoenlichVerknuepft') is not True:
                    continue
                if any(_attachment_id(parent, attachment['id'], state) == identifier for attachment in note.get('anhaenge', [])):
                    continue
            else:
                continue
            if meta.get('parent_id', '') != parent or meta.get('conflict') is True or meta.get('hash', '') != '':
                raise ValueError('invalid_native_tombstone')
            clock = personal.normalize_clock(meta.get('clock'))
            proposal = {'proposal_id': meta.get('proposal_id'), 'kind': kind, 'id': identifier, 'parent_id': parent,
                'clock': clock, 'prior_hash': meta.get('prior_hash'), 'deleted_ms': meta.get('deleted_ms'), 'label': meta.get('label', '')}
            if proposal['proposal_id'] != personal.deletion_proposal_id(peer_id, kind, identifier, parent, clock, proposal['prior_hash']):
                raise ValueError('native_tombstone_proposal_identity_changed')
            proposals.append(proposal)
            if len(proposals) > 256:
                raise ValueError('actor_producer_target_capacity')
    proposals.sort(key=lambda value: value['proposal_id'].encode('utf-8'))
    if len({value['proposal_id'] for value in proposals}) != len(proposals):
        raise ValueError('ambiguous_native_proposal_identity')
    batch_id = str(uuid.uuid4()); bodies = []
    for start in range(0, len(proposals), 32):
        body = {'format': 1, 'run_id': run_id, 'proposal_batch_id': batch_id, 'sequence': start // 32,
            'last': start + 32 >= len(proposals), 'proposals': proposals[start:start + 32]}
        personal.validate_body('personal_sync.deletion_proposals', body)
        bodies.append(body)
    if current_source() != source or current_saved_book() != snapshot.saved_book:
        raise PermissionError('actor_producer_source_changed')
    return bodies
