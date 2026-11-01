"""Current native pending removals, not historical ACKs or restore authority."""
import copy
import json
import uuid

import pytest
from test_personal_actor_incoming_target_evidence import live_fixture
from test_personal_actor_producer import native, tombstone, RUN


def pending_fixture(kind):
    create, state, book, target, key, read = live_fixture(kind)
    book['personalSync']['entities'][key] = tombstone(kind, target['id'], target['parent_id'])
    if kind == 'note': book['notizen'] = []
    elif kind == 'task': book['aufgaben'] = []
    else: book['notizen'][0]['anhaenge'] = []
    state['snapshot'] = native(book)[2]
    return create, state, book, target, key


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
def test_current_native_pending_removal_is_observable_without_restoring_or_widening_scope(kind):
    create, state, book, target, key = pending_fixture(kind)
    before, manifest = copy.deepcopy(book), copy.deepcopy(state['scope'])
    observed = create().observe(RUN, target)
    assert observed['local_state'] == 'deleted' and observed['local_hash'] == target['prior_hash']
    assert observed['requires_conflict_choice'] is True
    assert observed['metadata_matches'] is True
    assert observed['target'] == target and book == before and state['scope'] == manifest
    assert 'PRIVATE' not in json.dumps(observed)
    assert 'restore_available' not in observed and 'action_authorized' not in observed


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
@pytest.mark.parametrize('fault', ['resolved', 'old-ack', 'foreign-peer', 'conflict', 'forged-proposal', 'nonempty-hash', 'present-object'])
def test_deleted_metadata_without_exact_current_native_pending_evidence_is_not_a_target_proof(kind, fault):
    create, state, book, target, key = pending_fixture(kind)
    meta = book['personalSync']['entities'][key]
    if fault == 'resolved': meta['status'] = 'resolved'
    elif fault == 'old-ack': meta.clear(); meta['acknowledged_by_peer'] = True
    elif fault == 'foreign-peer': meta['peer_device_id'] = str(uuid.uuid4())
    elif fault == 'conflict': meta['conflict'] = True
    elif fault == 'forged-proposal': meta['proposal_id'] = str(uuid.uuid4())
    elif fault == 'nonempty-hash': meta['hash'] = 'a' * 64
    elif kind == 'note': book['notizen'] = [{'id': target['id']}]
    elif kind == 'task': book['aufgaben'] = [{'id': target['id']}]
    else: book['notizen'][0]['anhaenge'] = [{'id': target['id']}]
    state['snapshot'] = native(book)[2]
    with pytest.raises((PermissionError, ValueError)): create().observe(RUN, target)


@pytest.mark.parametrize('fault', ['missing-parent', 'foreign-parent', 'duplicate-parent'])
def test_pending_child_still_requires_an_exact_current_own_live_parent_without_exporting_it(fault):
    create, state, book, target, key = pending_fixture('attachment')
    if fault == 'missing-parent': book['notizen'] = []
    elif fault == 'foreign-parent': book['notizen'][0]['baumQuelle'] = 'foreign-owner'
    else: book['notizen'].append(copy.deepcopy(book['notizen'][0]))
    state['snapshot'] = native(book)[2]
    with pytest.raises((PermissionError, ValueError)): create().observe(RUN, target)
