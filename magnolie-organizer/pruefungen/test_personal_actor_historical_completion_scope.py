"""Separate historical action targets never become content/read membership.

This is terminal metadata math, NOT native save/origin or mutation authority.
"""
import copy
import uuid

import pytest
import magnolie_content_scope as scope
import magnolie_personal_actor as actor
from magnolie_personal_actor_completion import DecisionAckCompletion
from test_personal_actor_transport import frame

RUN = '44444444-4444-4444-8444-444444444444'
ACTOR = '11111111-1111-4111-8111-111111111111'


def target(kind='note', identifier='historical-target', parent=''):
    return {'proposal_id': str(uuid.uuid4()), 'kind': kind, 'id': identifier, 'parent_id': parent,
        'prior_hash': 'a' * 64, 'clock': [{'actor_id': ACTOR, 'counter': 1}]}


def choice(value, decision):
    return {'proposal_id': value['proposal_id'], 'decision': decision, 'expected_clock': copy.deepcopy(value['clock'])}


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
@pytest.mark.parametrize('decision', ['delete', 'restore'])
def test_historical_action_never_adds_its_object_or_parent_to_the_original_content_scope(kind, decision):
    before = scope.create(['data-note'], ['data-task'])
    historical = target(kind, parent='historical-parent' if kind == 'attachment' else '')
    result = actor.historical_completion_members(RUN, before, [historical], [choice(historical, decision)], [historical])
    assert result == before['members']
    assert actor.require_historical_completion_scope(RUN, before, [historical], [choice(historical, decision)], [historical], before) == scope.reference(before)
    advanced = scope.advance(before, ['data-note', historical['parent_id'] or historical['id']], ['data-task'])
    with pytest.raises(ValueError): actor.require_historical_completion_scope(RUN, before, [historical], [choice(historical, decision)], [historical], advanced)


@pytest.mark.parametrize('fault', ['data-target', 'changed-proof', 'foreign-proof', 'duplicate-proof', 'missing-decision', 'changed-clock', 'duplicate-target'])
def test_a_historical_classification_cannot_relabel_data_targets_or_substitute_an_unproved_identity(fault):
    before = scope.create(['data-note'], ['data-task']); historical = target()
    targets, historicals, choices = [historical], [historical], [choice(historical, 'restore')]
    if fault == 'data-target': historical['id'] = 'data-note'
    elif fault == 'changed-proof': historicals = [dict(historical, prior_hash='b' * 64)]
    elif fault == 'foreign-proof': historicals = [target()]
    elif fault == 'duplicate-proof': historicals = [historical, historical]
    elif fault == 'missing-decision': choices = []
    elif fault == 'changed-clock': choices[0]['expected_clock'][0]['counter'] = 2
    else: targets = [historical, dict(historical, proposal_id=str(uuid.uuid4()))]; choices += [choice(targets[1], 'restore')]
    with pytest.raises(ValueError): actor.historical_completion_members(RUN, before, targets, choices, historicals)


def test_normal_data_delta_and_historical_targets_have_disjoint_result_and_receipt_membership():
    before = scope.create(['data-note'], ['data-task']); data = target(identifier='data-note'); historical = target('task')
    targets = [data, historical]; choices = [choice(data, 'delete'), choice(historical, 'restore')]
    members = actor.historical_completion_members(RUN, before, targets, choices, [historical])
    assert members == scope.create([], ['data-task'])['members']
    after = scope.advance(before, [], ['data-task'])
    actor.require_historical_completion_scope(RUN, before, targets, choices, [historical], after)
    saved = {'book_source': 'b' * 64, 'sequence': 2, 'sha256': 'c' * 64}; retained = []
    wires = [actor.wire_message(frame('personal_sync.deletion_decision', {'format': 1, 'run_id': RUN,
        'decision_id': str(uuid.uuid4()), 'decisions': [value]}), RUN) for value in choices]
    acknowledgments = [frame(actor.ACK_KIND, actor.ack(RUN, wire['message_id'])) for wire in wires]
    completion = DecisionAckCompletion(RUN, targets, wires, native_historical_targets=[historical],
        current_authority=lambda: 'd' * 64, current_scope=lambda: after, current_saved_book=lambda: saved,
        persisted_controls=lambda: copy.deepcopy(retained), before_scope=before, native_sent_acknowledgments=[acknowledgments[1]])
    assert completion.validate('begin', None) is True
    retained.append(acknowledgments[0]); completion.record_persisted(acknowledgments[0])
    assert completion.summary() == {'expected': 2, 'received': 1, 'saved': 1, 'rejected': 0}
    assert completion.validate('finish', None) is not True
    retained.append(acknowledgments[1])
    with pytest.raises(PermissionError): completion.record_persisted(acknowledgments[1])
    assert completion.validate('finish', None) is not True
    completion.record_successful_acknowledgment_send(acknowledgments[1])
    completion.record_persisted(acknowledgments[1])
    assert completion.validate('finish', None) is True
    assert after['members'] == members and 'historical-target' not in str(after)


def test_historical_child_restore_never_outlives_an_explicit_parent_delete():
    before = scope.create(['data-note'], []); parent = target(identifier='historical-parent')
    child = target('attachment', 'historical-child', parent['id'])
    targets = [parent, child]
    with pytest.raises(ValueError): actor.historical_completion_members(RUN, before, targets,
        [choice(parent, 'delete'), choice(child, 'restore')], targets)
