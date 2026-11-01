"""Native explicit-choice draft contract only; no enabled action/transport path."""
import copy
import uuid
import json
from pathlib import Path

import pytest
import magnolie_content_scope as scope
import magnolie_personal_actor as actor
import magnolie_telefon as phone
from magnolie_personal_actor_target_review import NativeIncomingTargetChoiceReview
from test_personal_actor_incoming_target_evidence import live_fixture
from test_personal_actor_producer import RUN, native

VECTORS = json.loads((Path(__file__).resolve().parents[2] / 'contracts/notes-actor-target-choice-draft-v1-vectors.json').read_text())


def fixture(kind='note', mutate_observation=None):
    create, state, book, target, key, read = live_fixture(kind)
    proposal = dict(copy.deepcopy(target), deleted_ms=0, label='PRIVATE LABEL MUST NOT ESCAPE')
    body = {'format': 1, 'run_id': RUN, 'proposal_batch_id': str(uuid.uuid4()), 'sequence': 0, 'last': True, 'proposals': [proposal]}
    frames = [actor.wire_message(phone.PhoneService._actor_control_message('personal_sync.deletion_proposals', body), RUN)]
    calls = []
    def observe(targets):
        calls.append(True)
        result = create().observe_many(RUN, targets)
        if mutate_observation is not None: mutate_observation(result, state)
        return result
    def review():
        return NativeIncomingTargetChoiceReview(RUN, current_frames=lambda: copy.deepcopy(frames), current_observations=observe,
            current_authority=lambda: state['source'] if state['owner'] else None,
            current_scope=lambda: copy.deepcopy(state['scope']), current_saved_book=lambda: state['snapshot'].saved_book)
    choice = dict(proposal_id=target['proposal_id'], decision='delete', expected_clock=copy.deepcopy(target['clock']), confirm_conflict=True)
    return review, state, book, frames, target, choice, calls


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
@pytest.mark.parametrize('decision', ['delete', 'restore'])
def test_explicit_conflict_choice_is_stable_private_and_keeps_original_data_scope(kind, decision):
    create, state, book, frames, target, choice, calls = fixture(kind)
    before_book, before_scope = copy.deepcopy(book), copy.deepcopy(state['scope'])
    review = create(); view = review.review(); choice['decision'] = decision
    draft = review.draft_choices(view['revision'], [choice])
    assert draft == review.draft_choices(view['revision'], [choice]) and len(calls) == 3
    assert draft['content_scope'] == before_scope and draft['action_authorized'] is False and view['action_authorized'] is False
    assert draft['conflicts_explicitly_confirmed'] is True
    assert draft['decisions'] == [{key: choice[key] for key in ('proposal_id', 'decision', 'expected_clock')}]
    assert 'PRIVATE' not in str(view) + str(draft)
    assert book == before_book and state['scope'] == before_scope
    draft['decisions'][0]['decision'] = 'forged'
    assert review.draft_choices(view['revision'], [choice])['decisions'][0]['decision'] == decision
    if decision == 'delete':
        with pytest.raises(ValueError): actor.completion_members(RUN, before_scope, [target], [{key: choice[key] for key in ('proposal_id', 'decision', 'expected_clock')}])


@pytest.mark.parametrize('fault', ['missing-confirmation', 'false', 'numeric-true', 'string-true', 'clock',
    'foreign-proposal', 'unknown-decision', 'missing-choice', 'duplicate-choice', 'extra-field', 'revision'])
def test_no_implicit_or_changed_conflict_choice_can_become_a_native_draft(fault):
    create, state, book, frames, target, choice, calls = fixture()
    review = create(); view = review.review(); choices = [choice]
    if fault == 'missing-confirmation': choice.pop('confirm_conflict')
    elif fault == 'false': choice['confirm_conflict'] = False
    elif fault == 'numeric-true': choice['confirm_conflict'] = 1
    elif fault == 'string-true': choice['confirm_conflict'] = 'true'
    elif fault == 'clock': choice['expected_clock'][0]['counter'] += 1
    elif fault == 'foreign-proposal': choice['proposal_id'] = str(uuid.uuid4())
    elif fault == 'unknown-decision': choice['decision'] = 'accept'
    elif fault == 'missing-choice': choices = []
    elif fault == 'duplicate-choice': choices *= 2
    elif fault == 'extra-field': choice['action_authorized'] = True
    with pytest.raises((ValueError, PermissionError)):
        review.draft_choices('f' * 64 if fault == 'revision' else view['revision'], choices)


@pytest.mark.parametrize('fault', ['owner', 'source', 'scope', 'save', 'frame-body', 'frame-id', 'missing-frame'])
def test_original_native_frame_source_saved_book_and_scope_are_rechecked(fault):
    create, state, book, frames, target, choice, calls = fixture()
    review = create(); view = review.review()
    if fault == 'owner': state['owner'] = False
    elif fault == 'source': state['source'] = 'c' * 64
    elif fault == 'scope': state['scope'] = scope.create(['different'], [])
    elif fault == 'save': state['snapshot'] = native(book)[2]
    elif fault == 'frame-body': frames[0]['body']['body']['proposals'][0]['label'] = 'Changed original protected bytes'
    elif fault == 'frame-id': frames[0]['message_id'] = str(uuid.uuid4())
    elif fault == 'missing-frame': frames.clear()
    with pytest.raises((ValueError, PermissionError)): review.draft_choices(view['revision'], [choice])


@pytest.mark.parametrize('fault', ['optimistic-conflict', 'saved-book', 'local-hash', 'metadata-claim', 'extra-content', 'duplicate-result', 'source-race'])
def test_native_observation_contract_cannot_be_weakened_or_replaced_with_caller_content(fault):
    def mutate(result, state):
        if fault == 'optimistic-conflict': result[0]['requires_conflict_choice'] = False
        elif fault == 'saved-book': result[0]['native_saved_book']['sequence'] += 1
        elif fault == 'local-hash': result[0]['local_hash'] = 'invalid'
        elif fault == 'metadata-claim': result[0]['metadata_matches'] = False
        elif fault == 'extra-content': result[0]['content'] = 'PRIVATE'
        elif fault == 'duplicate-result': result.append(copy.deepcopy(result[0]))
        elif fault == 'source-race': state['source'] = 'f' * 64
    create, *_ = fixture(mutate_observation=mutate)
    with pytest.raises((ValueError, PermissionError)): create().review()


@pytest.mark.parametrize('fault', ['missing-last', 'first-sequence', 'duplicate-identity', 'content-target', 'wrong-run'])
def test_incomplete_ambiguous_or_content_scope_groups_are_not_historical_choice_reviews(fault):
    create, state, book, frames, target, choice, calls = fixture()
    body = frames[0]['body']['body']
    if fault == 'missing-last': body['last'] = False
    elif fault == 'first-sequence': body['sequence'] = 1
    elif fault == 'duplicate-identity': body['proposals'].append(dict(copy.deepcopy(body['proposals'][0]), proposal_id=str(uuid.uuid4())))
    elif fault == 'content-target': state['scope'] = scope.create(['own-note'], [])
    elif fault == 'wrong-run': body['run_id'] = str(uuid.uuid4())
    with pytest.raises((ValueError, PermissionError)): create()


def test_original_proposal_frames_are_rechecked_after_the_native_observation_callback():
    held = []
    def mutate(result, state):
        held[0][0]['body']['body']['proposals'][0]['label'] = 'Changed during native observation'
    create, state, book, frames, target, choice, calls = fixture(mutate_observation=mutate)
    held.append(frames)
    with pytest.raises(PermissionError): create().review()


@pytest.mark.parametrize('parent_choice,child_choice', [('delete', 'restore'), ('restore', 'restore'), ('delete', 'delete')])
def test_explicit_parent_child_choices_cannot_restore_a_child_under_a_deleted_parent(parent_choice, child_choice):
    create, state, book, frames, target, choice, calls = fixture()
    child = dict(copy.deepcopy(target), proposal_id=str(uuid.uuid4()), kind='attachment', id='own-file', parent_id='own-note')
    meta = copy.deepcopy(book['personalSync']['entities']['note\0own-note']); meta['parent_id'] = 'own-note'
    book['personalSync']['entities']['attachment\0own-note\0own-file'] = meta
    state['snapshot'] = native(book)[2]
    frames[0]['body']['body']['proposals'].append(dict(child, deleted_ms=0, label=''))
    frames[0]['body']['body']['proposals'].sort(key=lambda value: value['proposal_id'])
    review = create(); view = review.review()
    choices = [dict(choice, decision=parent_choice), dict(choice, proposal_id=child['proposal_id'], decision=child_choice)]
    if parent_choice == 'delete' and child_choice == 'restore':
        with pytest.raises(ValueError): review.draft_choices(view['revision'], choices)
    else:
        assert review.draft_choices(view['revision'], choices)['action_authorized'] is False


@pytest.mark.parametrize('case', VECTORS['cases'], ids=lambda case: case['kind'])
@pytest.mark.parametrize('decision', ['delete', 'restore'])
def test_shared_private_choice_draft_revision_vectors(case, decision):
    value = VECTORS['fixture']; run = value['run_id']; kind = case['kind']
    clock = [{'actor_id': value['actor_id'], 'counter': 1}]
    target = {'proposal_id': value['proposal_id'], 'kind': kind, 'id': {'note': 'own-note', 'task': 'own-task', 'attachment': 'own-file'}[kind],
        'parent_id': 'own-note' if kind == 'attachment' else '', 'prior_hash': value['prior_hash'], 'clock': clock}
    body = {'format': 1, 'run_id': run, 'proposal_batch_id': run, 'sequence': 0, 'last': True,
        'proposals': [dict(target, deleted_ms=0, label=value['label'])]}
    frame = actor.wire_message({'type': 'message', 'v': 1, 'message_id': value['frame_id'], 'kind': 'personal_sync.deletion_proposals',
        'created_ms': value['created_ms'], 'expires_ms': value['expires_ms'], 'body': body}, run)
    before = scope.create([], [], epoch=run)
    def observe(targets):
        return [{'target': copy.deepcopy(targets[0]), 'local_state': 'live', 'local_hash': value['prior_hash'], 'local_clock': clock,
            'native_saved_book': value['saved_book'], 'metadata_matches': True, 'requires_conflict_choice': True}]
    review = NativeIncomingTargetChoiceReview(run, current_frames=lambda: [frame], current_observations=observe,
        current_authority=lambda: value['source'], current_scope=lambda: before, current_saved_book=lambda: value['saved_book'])
    view = review.review()
    assert view['revision'] == case['review_revision']
    choice = dict(proposal_id=target['proposal_id'], decision=decision, expected_clock=clock, confirm_conflict=True)
    assert review.draft_choices(view['revision'], [choice])['choice_revision'] == case[decision + '_choice_revision']


def test_native_observation_callback_cannot_replace_original_targets_through_its_input():
    create, state, book, frames, target, choice, calls = fixture()
    def observe(targets):
        targets[0]['id'] = 'changed-native-input'
        return [{'target': copy.deepcopy(targets[0]), 'local_state': 'live', 'local_hash': 'a' * 64,
            'local_clock': copy.deepcopy(target['clock']), 'native_saved_book': state['snapshot'].saved_book,
            'metadata_matches': True, 'requires_conflict_choice': True}]
    review = NativeIncomingTargetChoiceReview(RUN, current_frames=lambda: copy.deepcopy(frames), current_observations=observe,
        current_authority=lambda: state['source'], current_scope=lambda: state['scope'], current_saved_book=lambda: state['snapshot'].saved_book)
    with pytest.raises(ValueError): review.review()
