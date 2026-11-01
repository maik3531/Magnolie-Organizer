"""Native saved-book proposal preparation, not queue/controller/physical acceptance."""
import copy
import hashlib
import json
import sqlite3
import pytest

import magnolie_content_scope as scope
import magnolie_personal_sync as personal
from magnolie_personal_actor_producer import prepare_deletion_proposals
from magnolie_personal_actor_store import NativeBookOwnerScope, NativeProducerBookSnapshot
import magnolie_personal_actor as actor
import magnolie_telefon as phone
from test_mcp_phone import owned_service

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


@pytest.mark.parametrize('fault', ('none', 'second-frame', 'last-target', 'ledger', 'source-before', 'source-after',
    'saved-before', 'saved-after', 'missing-last', 'changed-batch', 'duplicate-target', 'incomplete-first'))
def test_native_prepared_group_commits_all_frames_and_targets_or_rolls_back(tmp_path, fault):
    service, _, events = owned_service(tmp_path); store = service.store
    book, manifest = fixture(); owner, read, snapshot = native(book)
    bodies = prepare_deletion_proposals(snapshot, manifest, PEER, RUN, current_saved_book=read, current_source=lambda: 'a' * 64)
    private = actor.storage_peer(RUN)
    if fault == 'missing-last': bodies[-1]['last'] = False
    if fault == 'changed-batch': bodies[-1]['proposal_batch_id'] = PEER
    if fault == 'duplicate-target': bodies[-1]['proposals'][0]['id'] = bodies[0]['proposals'][0]['id']
    if fault == 'incomplete-first': bodies[0]['proposals'].pop()
    if fault in ('second-frame', 'last-target', 'ledger'):
        with sqlite3.connect(store.database_path) as db:
            trigger = ("BEFORE INSERT ON outbox WHEN (SELECT COUNT(*) FROM outbox)>=1" if fault == 'second-frame' else
                "BEFORE INSERT ON meta WHEN NEW.key LIKE 'personal_actor_producer:%'" if fault == 'ledger' else
                "BEFORE INSERT ON meta WHEN NEW.key='personal_proposal_kind:" + private + ":out:" + bodies[-1]['proposals'][0]['proposal_id'] + "'")
            db.execute("CREATE TRIGGER group_atomic_failure " + trigger + " BEGIN SELECT RAISE(ABORT,'synthetic group transaction failure'); END")
    sources = [0]; saved_reads = [0]
    def source():
        sources[0] += 1
        return ('b' if fault == 'source-before' or fault == 'source-after' and sources[0] == 2 else 'a') * 64
    def saved():
        saved_reads[0] += 1
        if fault == 'saved-after' and saved_reads[0] == 2: owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
        return read()
    if fault == 'saved-before': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
    def commit():
        return store.queue_actor_deletion_proposals(PEER, RUN, bodies, expected_source='a' * 64,
            saved_book=snapshot.saved_book, current_source=source, current_saved_book=saved)
    if fault != 'none':
        with pytest.raises((ValueError, PermissionError, sqlite3.DatabaseError)):
            commit()
        with sqlite3.connect(store.database_path) as db:
            assert db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_proposal_kind:%'").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_actor_producer:%'").fetchone()[0] == 0
        assert not events and service.server is None
        return
    wire = commit()
    assert len(wire) == 2 and all(frame['kind'] == actor.DATA_KIND for frame in wire)
    assert [actor.unwrap(frame['body'])[1] for frame in wire] == bodies
    reopened = phone.PhoneStore(str(tmp_path / 'phone'), 'Owned desktop')
    assert {frame['message_id'] for frame in reopened.pending(PEER)} == {frame['message_id'] for frame in wire}
    for body in bodies:
        decision = {'format': 1, 'run_id': RUN, 'decision_id': RUN, 'decisions': [
            {'proposal_id': proposal['proposal_id'], 'decision': 'restore', 'expected_clock': proposal['clock']} for proposal in body['proposals']]}
        assert len(reopened.personal_decision_targets(private, decision, False)) == len(body['proposals'])
        assert reopened.personal_decision_targets(PEER, decision, False) is None
    assert snapshot.book() == book and read() == snapshot.saved_book and not events and service.server is None


@pytest.mark.parametrize('scenario', ('same', 'changed-body', 'new-batch', 'source', 'new-save', 'expired', 'after-ack', 'retired-owner'))
def test_successful_native_group_replay_keeps_original_frames_and_never_requeues(tmp_path, monkeypatch, scenario):
    service, _, events = owned_service(tmp_path); store = service.store
    book, manifest = fixture(); owner, read, snapshot = native(book)
    bodies = prepare_deletion_proposals(snapshot, manifest, PEER, RUN, current_saved_book=read, current_source=lambda: 'a' * 64)
    current = ['a' * 64]
    def commit(target):
        return target.queue_actor_deletion_proposals(PEER, RUN, bodies, expected_source='a' * 64,
            saved_book=snapshot.saved_book, current_source=lambda: current[0], current_saved_book=read)
    original = commit(store)
    private = actor.storage_peer(RUN)
    def rows(target):
        with sqlite3.connect(target.database_path) as db:
            return (db.execute('SELECT * FROM outbox ORDER BY message_id').fetchall(),
                db.execute("SELECT key,value FROM meta WHERE key LIKE 'personal_proposal_kind:%' OR key LIKE 'personal_actor_producer:%' ORDER BY key").fetchall())
    if scenario == 'changed-body': bodies[0]['proposals'][0]['label'] = 'Changed retry content'
    if scenario == 'new-batch':
        for body in bodies: body['proposal_batch_id'] = PEER
    if scenario == 'source': current[0] = 'b' * 64
    if scenario == 'new-save': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
    if scenario == 'expired': monkeypatch.setattr(phone, 'now_ms', lambda: original[0]['expires_ms'] + 1)
    if scenario == 'after-ack':
        for wire in original: store.acknowledge(PEER, wire['message_id'])
    if scenario == 'retired-owner':
        current[0] = None
        for wire in original: store.acknowledge(PEER, wire['message_id'])
        store.purge_personal(private)
        assert rows(store) == ([], [])
    reopened = phone.PhoneStore(str(tmp_path / 'phone'), 'Owned desktop')
    before = rows(reopened)  # Reopen may perform its normal expired-outbox cleanup.
    if scenario not in ('same', 'after-ack'):
        with pytest.raises(PermissionError): commit(reopened)
    else:
        assert commit(reopened) == original
        assert len(reopened.pending(PEER)) == (0 if scenario == 'after-ack' else 2)
        returned = commit(reopened); returned[0]['message_id'] = RUN
        assert commit(reopened) == original
    assert rows(reopened) == before, 'Successful replay/failed identity check rewrote protected metadata or outbox'
    assert not events and service.server is None
