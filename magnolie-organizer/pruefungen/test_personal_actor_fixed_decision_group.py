"""Atomic native fixed controls; no transport/GUI/Mixed activation proof."""
import copy
import json
import sqlite3
import uuid
import pytest
import magnolie_personal_actor as actor
import magnolie_telefon as phone
from magnolie_personal_actor_store import NativeBookOwnerScope
from test_mcp_phone import owned_service


def fixture(tmp_path, count=33):
    service, peer, events = owned_service(tmp_path)
    run = str(uuid.uuid4()); private = actor.storage_peer(run)
    proposals = [{'proposal_id': str(uuid.uuid4()), 'kind': 'task', 'id': 'native-task-%03d' % index, 'parent_id': '',
        'prior_hash': 'a' * 64, 'clock': [{'actor_id': peer['device_id'], 'counter': 1}], 'deleted_ms': 2, 'label': 'Synthetic native target'} for index in range(count)]
    proposals.sort(key=lambda value: value['proposal_id'])
    for start in range(0, count, 32):
        service.store.remember_personal_proposal_kinds(private, {'format': 1, 'run_id': run, 'proposal_batch_id': run,
            'sequence': start // 32, 'last': start + 32 >= count, 'proposals': proposals[start:start + 32]}, False)
    choices = [{'proposal_id': value['proposal_id'], 'decision': 'delete', 'expected_clock': value['clock']} for value in proposals]
    owner = NativeBookOwnerScope(); owner.set_ready(True); owner.record_saved('native-fixed-group-fixture', True, 'b' * 64)
    read = lambda: owner.save_state('native-fixed-group-fixture', True)
    state = {'source': 'c' * 64}
    def prepare(values=None, **fields):
        args = dict(expected_source='c' * 64, saved_claim=read(), current_source=lambda: state['source'], current_confirmed_claim=read)
        args.update(fields)
        return service.store.queue_actor_fixed_decisions(peer['device_id'], run, choices if values is None else values, **args)
    return service, peer, run, private, choices, owner, read, state, prepare


def test_atomic_native_fixed_decisions_keep_original_identity_after_peer_ack_without_requeue(tmp_path):
    service, peer, run, private, choices, owner, read, state, prepare = fixture(tmp_path)
    before = read()
    frames = prepare()
    assert len(frames) == 2 and [len(actor.unwrap(wire['body'])[1]['decisions']) for wire in frames] == [32, 1]
    assert [value for wire in frames for value in actor.unwrap(wire['body'])[1]['decisions']] == choices
    assert prepare() == frames and read() == before
    for wire in frames:
        assert service.store.outbox_message(peer['device_id'], wire['message_id']) == wire
        service.store.acknowledge(peer['device_id'], wire['message_id'])
    assert prepare() == frames
    assert not service.store.pending(peer['device_id']) and read() == before and service.server is None


def test_fixed_control_group_sql_fault_rolls_back_every_frame_and_protected_success_record(tmp_path):
    service, peer, run, private, choices, owner, read, state, prepare = fixture(tmp_path)
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("CREATE TRIGGER fixed_group_fault BEFORE INSERT ON outbox WHEN (SELECT COUNT(*) FROM outbox WHERE kind='personal_sync.deletion_decision')>=1 BEGIN SELECT RAISE(ABORT,'synthetic partial fixed control fault'); END")
    with pytest.raises(sqlite3.DatabaseError): prepare()
    assert not service.store.pending(peer['device_id'])
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_actor_fixed:%'").fetchone()[0] == 0
        db.execute('DROP TRIGGER fixed_group_fault')
    assert len(prepare()) == 2


@pytest.mark.parametrize('fault', ['missing', 'clock', 'duplicate', 'unsorted', 'empty', 'extra-field', 'foreign-source', 'missing-claim'])
def test_fixed_group_rejects_unbound_choices_or_missing_current_native_witnesses(tmp_path, fault):
    service, peer, run, private, choices, owner, read, state, prepare = fixture(tmp_path)
    changed = copy.deepcopy(choices); fields = {}
    if fault == 'missing': changed[0]['proposal_id'] = str(uuid.uuid4()); changed.sort(key=lambda value: value['proposal_id'])
    elif fault == 'clock': changed[0]['expected_clock'][0]['counter'] += 1
    elif fault == 'duplicate': changed[-1] = copy.deepcopy(changed[0]); changed.sort(key=lambda value: value['proposal_id'])
    elif fault == 'unsorted': changed.reverse()
    elif fault == 'empty': changed = []
    elif fault == 'extra-field': changed[0]['allow_conflict'] = True
    elif fault == 'foreign-source': state['source'] = 'd' * 64
    else: fields['current_confirmed_claim'] = lambda: None
    with pytest.raises((ValueError, PermissionError)): prepare(changed, **fields)
    assert not service.store.pending(peer['device_id'])


@pytest.mark.parametrize('fault', ['source', 'claim'])
def test_fixed_group_native_source_or_saved_claim_race_rolls_back_sql(tmp_path, fault):
    service, peer, run, private, choices, owner, read, state, prepare = fixture(tmp_path)
    calls = [0]
    def source():
        calls[0] += 1
        if calls[0] == 2:
            if fault == 'source': state['source'] = 'd' * 64
            else: owner.record_saved('native-fixed-group-fixture', True, 'e' * 64)
        return state['source']
    with pytest.raises(PermissionError): prepare(current_source=source)
    assert not service.store.pending(peer['device_id'])
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_actor_fixed:%'").fetchone()[0] == 0


@pytest.mark.parametrize('fault', ['decision', 'source', 'new-claim', 'kind-only-proof'])
def test_protected_fixed_success_identity_cannot_rebind_later_native_choices_or_claims(tmp_path, fault):
    service, peer, run, private, choices, owner, read, state, prepare = fixture(tmp_path, 1)
    original = prepare()
    for wire in original: service.store.acknowledge(peer['device_id'], wire['message_id'])
    changed = copy.deepcopy(choices); fields = {}
    if fault == 'decision': changed[0]['decision'] = 'restore'
    elif fault == 'source': state['source'] = 'd' * 64; fields['expected_source'] = 'd' * 64
    elif fault == 'new-claim': owner.record_saved('native-fixed-group-fixture', True, 'b' * 64)
    else:
        key = 'personal_proposal_kind:%s:in:%s' % (private, choices[0]['proposal_id'])
        with sqlite3.connect(service.store.database_path) as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            proof = json.loads(service.store._decrypt(row[0], 'personal_proposal_kind', key)); proof.pop('target')
            db.execute('UPDATE meta SET value=? WHERE key=?', (service.store._encrypt(phone.canonical(proof), 'personal_proposal_kind', key), key))
    with pytest.raises(PermissionError): prepare(changed, **fields)
    assert not service.store.pending(peer['device_id'])


@pytest.mark.parametrize('field,value', [('created_ms', 1), ('type', 'caller-message'), ('v', True)])
def test_protected_group_replay_rejects_changed_original_header_shape(tmp_path, field, value):
    service, peer, run, private, choices, owner, read, state, prepare = fixture(tmp_path, 1)
    prepare()
    key = 'personal_actor_fixed:%s:%s' % (private, run)
    with sqlite3.connect(service.store.database_path) as db:
        row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        recorded = json.loads(service.store._decrypt(row[0], 'personal_actor_fixed', key))
        recorded['frames'][0][field] = value
        db.execute('UPDATE meta SET value=? WHERE key=?', (service.store._encrypt(phone.canonical(recorded), 'personal_actor_fixed', key), key))
    with pytest.raises(ValueError): prepare()


def test_private_group_cleanup_removes_only_exact_own_frames_not_another_run_or_peer_data(tmp_path):
    service, peer, run, private, choices, owner, read, state, prepare = fixture(tmp_path, 1)
    frames = prepare()
    other_run = str(uuid.uuid4()); other_private = actor.storage_peer(other_run)
    proof = service.store.personal_decision_targets(private, {'format': 1, 'run_id': run, 'decision_id': run, 'decisions': choices}, True)[0]
    service.store.remember_personal_proposal_kinds(other_private, {'format': 1, 'run_id': other_run, 'proposal_batch_id': other_run,
        'sequence': 0, 'last': True, 'proposals': [dict(proof, deleted_ms=2, label='Other private run')]}, False)
    other_frames = service.store.queue_actor_fixed_decisions(peer['device_id'], other_run, choices, expected_source='c' * 64,
        saved_claim=read(), current_source=lambda: state['source'], current_confirmed_claim=read)
    unrelated = service.store.queue(peer['device_id'], 'personal_sync.request', {'format': 3, 'run_id': str(uuid.uuid4()),
        'trigger': 'manual', 'modules': ['tasks']}, 60000)
    service.store.purge_personal(private)
    assert all(service.store.outbox_message(peer['device_id'], wire['message_id']) is None for wire in frames)
    assert all(service.store.outbox_message(peer['device_id'], wire['message_id']) == wire for wire in other_frames)
    assert service.store.outbox_message(peer['device_id'], unrelated['message_id']) == unrelated
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute('SELECT COUNT(*) FROM meta WHERE key=?', ('personal_actor_fixed:%s:%s' % (private, run),)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM meta WHERE key=?', ('personal_actor_fixed:%s:%s' % (other_private, other_run),)).fetchone()[0] == 1
