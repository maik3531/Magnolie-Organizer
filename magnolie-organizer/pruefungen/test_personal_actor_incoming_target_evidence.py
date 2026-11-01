"""Current local LIVE observations only; no incoming admission/action permission."""
import copy
import json
import uuid

import pytest
import magnolie_content_scope as scope
from magnolie_personal_actor_target_evidence import NativeIncomingLiveTargetObservation
from test_personal_actor_producer import native, PEER, RUN, ACTOR


def live_fixture(kind):
    parent = 'own-note'
    identifier = {'note': parent, 'task': 'own-task', 'attachment': 'own-file'}[kind]
    key = kind + '\0' + (parent + '\0' if kind == 'attachment' else '') + identifier
    clock = [{'actor_id': ACTOR, 'counter': 1}]
    book = {'notizen': [{'id': parent, 'text': 'PRIVATE CONTENT MUST NOT BE RETURNED', 'anhaenge': [{'id': 'own-file', 'daten': 'PRIVATE BLOB'}]}],
        'aufgaben': [{'id': 'own-task', 'titel': 'PRIVATE TASK'}], 'personalSync': {'peer_device_id': PEER,
            'entities': {key: {'state': 'live', 'peer_device_id': PEER, 'hash': 'a' * 64, 'clock': clock,
                'parent_id': parent if kind == 'attachment' else ''}}}}
    owner, read, snapshot = native(book)
    state = {'owner': True, 'source': 'b' * 64, 'scope': scope.create([], []), 'snapshot': snapshot}
    target = {'proposal_id': str(uuid.uuid4()), 'kind': kind, 'id': identifier, 'parent_id': parent if kind == 'attachment' else '',
        'prior_hash': 'a' * 64, 'clock': copy.deepcopy(clock)}
    def create():
        return NativeIncomingLiveTargetObservation(PEER, RUN, current_owner=lambda: state['owner'], current_source=lambda: state['source'],
            current_snapshot=lambda: state['snapshot'], current_scope=lambda: copy.deepcopy(state['scope']))
    return create, state, book, target, key, read


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
def test_observation_proves_only_exact_current_local_identity_without_exporting_content(kind):
    create, state, book, target, key, read = live_fixture(kind)
    original, saved, before_scope = copy.deepcopy(book), read(), copy.deepcopy(state['scope'])
    proof = create(); observed = proof.observe(RUN, target)
    assert observed['target'] == target and observed['local_state'] == 'live' and observed['metadata_matches']
    assert observed['requires_conflict_choice'], 'Matching historical entity metadata cannot prove current content is conflict-free'
    assert observed['native_saved_book'] == saved and observed['local_hash'] == 'a' * 64
    assert 'PRIVATE' not in json.dumps(observed)
    observed['target']['prior_hash'] = 'f' * 64
    assert proof.observe(RUN, target)['target'] == target
    assert book == original and read() == saved and state['scope'] == before_scope
    conflict = copy.deepcopy(target); conflict['proposal_id'] = str(uuid.uuid4()); conflict['prior_hash'] = 'f' * 64
    with pytest.raises(PermissionError): proof.observe(RUN, conflict)
    separate = create().observe(RUN, conflict)
    assert separate['requires_conflict_choice'] and not separate['metadata_matches'], 'A current local observation falsely accepted a conflicting remote value as identical'


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
@pytest.mark.parametrize('fault', ['old-ack', 'other-peer', 'missing-live', 'duplicate-live', 'unowned', 'stale-meta'])
def test_historical_or_unowned_or_inconsistent_local_state_is_not_a_live_target_proof(kind, fault):
    create, state, book, target, key, read = live_fixture(kind)
    if fault == 'old-ack': book['personalSync']['entities'][key] = {'acknowledged_by_peer': True}
    elif fault == 'other-peer': book['personalSync']['entities'][key]['peer_device_id'] = str(uuid.uuid4())
    elif fault == 'stale-meta': book['personalSync']['entities'][key]['state'] = 'deleted'
    elif fault == 'missing-live':
        if kind == 'task': book['aufgaben'] = []
        elif kind == 'note': book['notizen'] = []
        else: book['notizen'][0]['anhaenge'] = []
    elif fault == 'duplicate-live':
        if kind == 'task': book['aufgaben'].append(copy.deepcopy(book['aufgaben'][0]))
        elif kind == 'note': book['notizen'].append(copy.deepcopy(book['notizen'][0]))
        else: book['notizen'][0]['anhaenge'].append(copy.deepcopy(book['notizen'][0]['anhaenge'][0]))
    else:
        if kind == 'task': book['aufgaben'][0]['delegiertAn'] = 'someone-else'
        else: book['notizen'][0]['baumQuelle'] = 'unowned-tree'
    state['snapshot'] = native(book)[2]
    with pytest.raises(PermissionError): create().observe(RUN, target)


@pytest.mark.parametrize('fault', ['owner', 'source', 'scope', 'book', 'run', 'target-change', 'content-target'])
def test_every_incoming_observation_remains_under_its_original_native_boundaries(fault):
    create, state, book, target, key, read = live_fixture('note')
    if fault == 'content-target': state['scope'] = scope.create(['own-note'], [])
    proof = create()
    if fault != 'content-target': proof.observe(RUN, target)
    run = RUN
    if fault == 'owner': state['owner'] = False
    elif fault == 'source': state['source'] = 'c' * 64
    elif fault == 'scope': state['scope'] = scope.create(['different'], [])
    elif fault == 'book': book['notizen'][0]['text'] = 'CHANGED'; state['snapshot'] = native(book)[2]
    elif fault == 'run': run = str(uuid.uuid4())
    elif fault == 'target-change': target['clock'][0]['counter'] += 1
    with pytest.raises(PermissionError): proof.observe(run, target)


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
def test_matching_old_entity_metadata_does_not_skip_explicit_conflict_choice_for_current_changed_content(kind):
    create, state, book, target, key, read = live_fixture(kind)
    if kind == 'note': book['notizen'][0]['text'] = 'CURRENT CHANGED PRIVATE NOTE'
    elif kind == 'task': book['aufgaben'][0]['titel'] = 'CURRENT CHANGED PRIVATE TASK'
    else: book['notizen'][0]['anhaenge'][0]['daten'] = 'CURRENT CHANGED PRIVATE BLOB'
    state['snapshot'] = native(book)[2]
    observed = create().observe(RUN, target)
    assert observed['metadata_matches'] and observed['requires_conflict_choice']
    assert 'PRIVATE' not in json.dumps(observed)


def test_incoming_native_observation_cache_is_bounded_at_256_without_data_scope_or_book_side_effect():
    create, state, book, target, key, read = live_fixture('task')
    meta = copy.deepcopy(book['personalSync']['entities'][key])
    book['personalSync']['entities'] = {}; book['aufgaben'] = []
    targets = []
    for index in range(257):
        identifier = 'capacity-task-%03d' % index
        book['aufgaben'].append({'id': identifier, 'titel': 'PRIVATE CAPACITY CONTENT'})
        book['personalSync']['entities']['task\0' + identifier] = copy.deepcopy(meta)
        targets.append(dict(target, id=identifier, proposal_id=str(uuid.uuid4())))
    state['snapshot'] = native(book)[2]
    before = copy.deepcopy(book); proof = create()
    for target in targets[:256]: assert proof.observe(RUN, target)['requires_conflict_choice']
    with pytest.raises(ValueError, match='actor_target_capacity'): proof.observe(RUN, targets[256])
    assert book == before and state['scope']['members'] == {'notes': [], 'tasks': []}
