"""Native saved-book proposal preparation, not queue/controller/physical acceptance."""
import copy
import hashlib
import json
import pytest

import magnolie_content_scope as scope
import magnolie_personal_sync as personal
from magnolie_personal_actor_producer import prepare_deletion_proposals
from magnolie_personal_actor_store import NativeBookOwnerScope, NativeProducerBookSnapshot

PEER = '22222222-2222-4222-8222-222222222222'
RUN = '44444444-4444-4444-8444-444444444444'
ACTOR = '11111111-1111-4111-8111-111111111111'


def tombstone(kind, identifier, parent='', counter=1):
    clock = [{'actor_id': ACTOR, 'counter': counter}]
    return {'state': 'deleted', 'status': 'local_pending', 'peer_device_id': PEER, 'parent_id': parent,
        'hash': '', 'prior_hash': 'a' * 64, 'clock': clock, 'deleted_ms': 2, 'label': 'Synthetic native target',
        'proposal_id': personal.deletion_proposal_id(PEER, kind, identifier, parent, clock, 'a' * 64)}


def fixture(count=33):
    book = {'notizen': [{'id': 'local-parent', 'text': 'Synthetic Grüße 🌸', 'anhaenge': []}], 'aufgaben': [],
        'personalSync': {'actor_id': ACTOR, 'peer_device_id': PEER, 'counter': count,
            'note_ids': {'local-parent': 'wire-parent'}, 'note_aliases': {'wire-parent': 'canonical-parent'},
            'entities': {'attachment\0canonical-parent\0file-%03d' % i: tombstone('attachment', 'file-%03d' % i, 'canonical-parent', i + 1) for i in range(count)}}}
    manifest = scope.create(['canonical-parent'], ['selected-task'])
    return book, manifest


def native(book):
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    text = json.dumps(book, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    saved = owner.record_saved('native-producer-fixture', True, fingerprint)
    read = lambda: owner.save_state('native-producer-fixture', True)
    snapshot = NativeProducerBookSnapshot.capture(read, lambda: book, lambda: (saved['book_source'], saved['sequence'], fingerprint))
    return owner, read, snapshot


def prepare(book, manifest):
    owner, read, snapshot = native(book)
    before = snapshot.text
    result = prepare_deletion_proposals(snapshot, manifest, PEER, RUN, current_saved_book=read, current_source=lambda: 'a' * 64)
    assert snapshot.text == before and snapshot.book() == book
    return result


def test_native_saved_tombstones_produce_complete_32_plus_1_group_without_mutating_book():
    book, manifest = fixture(); before = copy.deepcopy(book)
    bodies = prepare(book, manifest)
    assert [len(body['proposals']) for body in bodies] == [32, 1]
    assert [body['sequence'] for body in bodies] == [0, 1] and [body['last'] for body in bodies] == [False, True]
    assert len({body['proposal_batch_id'] for body in bodies}) == 1
    proposals = [proposal for body in bodies for proposal in body['proposals']]
    assert [p['proposal_id'] for p in proposals] == sorted(p['proposal_id'] for p in proposals)
    assert all(p['parent_id'] == 'canonical-parent' and p['kind'] == 'attachment' for p in proposals)
    assert {p['id'] for p in proposals} == {'file-%03d' % i for i in range(33)}
    assert book == before


def test_current_scope_only_excludes_historical_targets_and_keeps_selected_absent_note_task():
    book, manifest = fixture(0); state = book['personalSync']
    state['entities'] = {'note\0historical-note': tombstone('note', 'historical-note'),
        'task\0historical-task': tombstone('task', 'historical-task'),
        'note\0selected-absent': tombstone('note', 'selected-absent'),
        'task\0selected-task': tombstone('task', 'selected-task')}
    state['entities']['note\0historical-note']['acknowledged_by_peer'] = True
    manifest = scope.create(['canonical-parent', 'selected-absent'], ['selected-task'])
    proposals = [p for body in prepare(book, manifest) for p in body['proposals']]
    assert {(p['kind'], p['id']) for p in proposals} == {('note', 'selected-absent'), ('task', 'selected-task')}


def test_live_attachment_alias_cannot_be_proposed_as_removed():
    book, manifest = fixture()
    book['notizen'][0]['anhaenge'] = [{'id': 'local-file'}]
    book['personalSync']['attachment_aliases'] = {'wire-parent\0local-file': 'file-000'}
    proposals = [p for body in prepare(book, manifest) for p in body['proposals']]
    assert len(proposals) == 32 and all(p['id'] != 'file-000' for p in proposals)


@pytest.mark.parametrize('gate', ('parent-absent', 'parent-unselected', 'tree-parent', 'other-peer', 'other-state-peer', 'resolved', 'live-note', 'live-task'))
def test_unowned_unselected_or_not_removed_targets_do_not_enter_native_plan(gate):
    book, manifest = fixture(1); state = book['personalSync']; meta = next(iter(state['entities'].values()))
    if gate == 'parent-absent': book['notizen'] = []
    if gate == 'parent-unselected': manifest = scope.create([], ['selected-task'])
    if gate == 'tree-parent': book['notizen'][0]['baumQuelle'] = 'unlinked-tree-source'
    if gate == 'other-peer': meta['peer_device_id'] = RUN
    if gate == 'other-state-peer': state['peer_device_id'] = RUN
    if gate == 'resolved': meta['status'] = 'resolved'
    if gate == 'live-note': state['entities'] = {'note\0canonical-parent': tombstone('note', 'canonical-parent')}
    if gate == 'live-task':
        book['aufgaben'] = [{'id': 'selected-task'}]
        state['entities'] = {'task\0selected-task': tombstone('task', 'selected-task')}
    assert prepare(book, manifest) == []


@pytest.mark.parametrize('field,value', [('parent_id', 'another-parent'), ('prior_hash', 'b' * 64),
    ('proposal_id', RUN), ('clock', [{'actor_id': ACTOR, 'counter': 99}]), ('conflict', True), ('hash', 'a' * 64)])
def test_tampered_native_tombstone_identity_denies_complete_preparation(field, value):
    book, manifest = fixture(2); next(iter(book['personalSync']['entities'].values()))[field] = value
    with pytest.raises((ValueError, TypeError)): prepare(book, manifest)


@pytest.mark.parametrize('gate', ('stale-save', 'new-save-during-prepare', 'source-changed', 'missing-source', 'alias-cycle', 'over-capacity'))
def test_native_preparation_fences_writer_source_identity_and_capacity(gate):
    book, manifest = fixture(257 if gate == 'over-capacity' else 1)
    if gate == 'alias-cycle': book['personalSync']['note_aliases']['canonical-parent'] = 'wire-parent'
    owner, read, snapshot = native(book)
    if gate == 'stale-save': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
    calls = [0]
    def source():
        calls[0] += 1
        if gate == 'new-save-during-prepare' and calls[0] == 2: owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
        return None if gate == 'missing-source' else ('b' if gate == 'source-changed' and calls[0] == 2 else 'a') * 64
    with pytest.raises((PermissionError, ValueError)):
        prepare_deletion_proposals(snapshot, manifest, PEER, RUN, current_saved_book=read, current_source=source)
