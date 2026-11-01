"""Outgoing native evidence primitive only; NOT a controller/wire/data grant."""
import copy
import uuid

import pytest
import magnolie_content_scope as scope
from magnolie_personal_actor_producer import prepare_deletion_proposals
from magnolie_personal_actor_target_evidence import NativeOutgoingTargetEvidence
from test_personal_actor_producer import fixture, native, tombstone, PEER, RUN


def evidence_fixture():
    book, _ = fixture(1)
    book['personalSync']['entities'].update({'note\0removed-note': tombstone('note', 'removed-note'),
        'task\0removed-task': tombstone('task', 'removed-task')})
    owner, read, snapshot = native(book)
    state = {'owner': True, 'source': 'b' * 64, 'snapshot': snapshot, 'scope': scope.create([], [])}
    def create():
        return NativeOutgoingTargetEvidence(PEER, RUN, current_owner=lambda: state['owner'], current_source=lambda: state['source'],
            current_snapshot=lambda: state['snapshot'], current_scope=lambda: copy.deepcopy(state['scope']))
    return create, state, book, owner, read


def test_fresh_exact_pending_targets_are_separate_from_content_scope_and_have_no_side_effect():
    create, state, book, owner, read = evidence_fixture()
    before, saved = copy.deepcopy(book), read()
    proof = create(); targets = proof.targets()
    assert {(value['kind'], value['id']) for value in targets} == {('note', 'removed-note'), ('task', 'removed-task'), ('attachment', 'file-000')}
    assert state['scope']['members'] == {'notes': [], 'tasks': []}
    assert book == before and read() == saved
    assert prepare_deletion_proposals(state['snapshot'], state['scope'], PEER, RUN,
        current_saved_book=read, current_source=lambda: state['source']) == [], 'Evidence widened the ordinary scoped producer'
    assert all(set(value) == {'proposal_id', 'kind', 'id', 'parent_id', 'prior_hash', 'clock'} for value in targets)
    for target in targets: assert proof.require_exact(RUN, target) is True
    targets[0]['prior_hash'] = 'f' * 64
    with pytest.raises(PermissionError): proof.require_exact(RUN, targets[0])
    assert proof.targets()[0]['prior_hash'] == 'a' * 64
    with pytest.raises(PermissionError): proof.require_exact(str(uuid.uuid4()), proof.targets()[0])


@pytest.mark.parametrize('fault', ['owner', 'source', 'scope', 'book', 'native-book-missing'])
def test_every_native_observation_is_fresh_for_each_target_lookup(fault):
    create, state, book, owner, read = evidence_fixture(); proof = create(); target = proof.targets()[0]
    if fault == 'owner': state['owner'] = False
    elif fault == 'source': state['source'] = 'c' * 64
    elif fault == 'scope': state['scope'] = scope.create(['different'], [])
    elif fault == 'book':
        book['notizen'][0]['text'] += ' actual newer book'
        state['snapshot'] = native(book)[2]
    else: state['snapshot'] = None
    with pytest.raises(PermissionError): proof.targets()
    with pytest.raises(PermissionError): proof.require_exact(RUN, target)


@pytest.mark.parametrize('fault', ['historical-ack-only', 'live', 'resolved', 'other-peer', 'parent-absent', 'tree-parent', 'active-alias'])
def test_old_ack_or_nonpending_or_invalid_parent_cannot_become_target_evidence(fault):
    create, state, book, owner, read = evidence_fixture()
    if fault == 'historical-ack-only':
        book['personalSync']['entities'] = {'note\0historical': {'acknowledged_by_peer': True}}
    elif fault == 'live':
        for value in book['personalSync']['entities'].values(): value.update(state='live', acknowledged_by_peer=True)
    elif fault == 'resolved':
        for value in book['personalSync']['entities'].values(): value.update(status='resolved', acknowledged_by_peer=True)
    elif fault == 'other-peer': book['personalSync']['peer_device_id'] = str(uuid.uuid4())
    elif fault == 'parent-absent': book['notizen'] = []
    elif fault == 'tree-parent': book['notizen'][0]['baumQuelle'] = 'unowned'
    elif fault == 'active-alias':
        book['notizen'][0]['anhaenge'] = [{'id': 'local-alias'}]
        book['personalSync']['attachment_aliases'] = {'canonical-parent\0local-alias': 'file-000'}
    state['snapshot'] = native(book)[2]
    targets = create().targets()
    if fault in ('parent-absent', 'tree-parent', 'active-alias'): assert all(value['kind'] != 'attachment' for value in targets)
    else: assert targets == []


def test_current_content_targets_are_not_mislabeled_as_offscope_evidence():
    create, state, book, owner, read = evidence_fixture()
    state['scope'] = scope.create(['canonical-parent', 'removed-note'], ['removed-task'])
    assert create().targets() == []


def test_missing_native_book_or_owner_denies_even_construction():
    create, state, book, owner, read = evidence_fixture()
    state['snapshot'] = None
    with pytest.raises(PermissionError): create()
    state['snapshot'] = native(book)[2]; state['owner'] = False
    with pytest.raises(PermissionError): create()


@pytest.mark.parametrize('field,value', [('proposal_id', RUN), ('prior_hash', 'f' * 64), ('hash', 'a' * 64),
    ('parent_id', 'different'), ('clock', [{'actor_id': PEER, 'counter': 99}]), ('conflict', True)])
def test_changed_current_tombstone_identity_cannot_be_attested(field, value):
    create, state, book, owner, read = evidence_fixture()
    book['personalSync']['entities']['attachment\0canonical-parent\0file-000'][field] = value
    state['snapshot'] = native(book)[2]
    with pytest.raises(ValueError): create()
