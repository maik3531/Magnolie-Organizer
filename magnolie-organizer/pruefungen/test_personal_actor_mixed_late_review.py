"""Native mixed-review primitive only. Controllers/frontend remain blocked."""
import copy
import uuid
import pytest
import magnolie_personal_actor as actor
import magnolie_content_scope as scope
from magnolie_personal_actor_decision_review import PostDataDecisionReview
from test_personal_actor_post_data_review import review_fixture
from test_personal_actor_transport import frame


def mixed_fixture(late_choice='restore', fixed_choice='delete'):
    original, state, owner, read, snapshot, report_id, ack = review_fixture(1)
    target = copy.deepcopy(original.targets[0])
    target.update(kind='note', id='canonical-parent', parent_id='')
    # These are native proof fixtures, never inferred from incoming JSON.
    fixed = {'proposal_id': str(uuid.uuid4()), 'kind': 'task', 'id': 'selected-task', 'parent_id': '',
        'clock': [{'actor_id': '22222222-2222-4222-8222-222222222222', 'counter': 7}], 'prior_hash': 'f' * 64}
    late_decision = {'proposal_id': target['proposal_id'], 'decision': late_choice, 'expected_clock': target['clock']}
    fixed_decision = {'proposal_id': fixed['proposal_id'], 'decision': fixed_choice, 'expected_clock': fixed['clock']}
    def decision_wire(value):
        return actor.wire_message(frame('personal_sync.deletion_decision', {'format': 1, 'run_id': original.run_id,
            'decision_id': str(uuid.uuid4()), 'decisions': [value]}), original.run_id)
    before = scope.create(['canonical-parent'], ['selected-task'])
    state['controls'] = [decision_wire(late_decision)]
    fixed_frame = decision_wire(fixed_decision)
    def create(targets=None, frames=None):
        return PostDataDecisionReview(original.run_id, [target], before, report_id, ack,
            current_authority=lambda: state['authority'], current_scope=lambda: state['scope'], current_saved_book=read,
            persisted_controls=lambda: copy.deepcopy(state['controls']),
            native_fixed_targets=[fixed] if targets is None else targets, fixed_decision_frames=[fixed_frame] if frames is None else frames)
    notes = [] if late_choice == 'delete' else ['canonical-parent']
    tasks = [] if fixed_choice == 'delete' else ['selected-task']
    state['scope'] = scope.advance(before, notes, tasks) if notes != before['members']['notes'] or tasks != before['members']['tasks'] else before
    return create, state, owner, read, fixed, fixed_frame, target, before


@pytest.mark.parametrize('late_choice', ['delete', 'restore'])
@pytest.mark.parametrize('fixed_choice', ['delete', 'restore'])
def test_mixed_review_derives_union_but_exposes_only_late_mutations(late_choice, fixed_choice):
    create, state, owner, read, fixed, fixed_frame, target, before = mixed_fixture(late_choice, fixed_choice)
    review = create(); baseline = read()
    result = review.review()
    assert result['decisions'] == [{'proposal_id': target['proposal_id'], 'decision': late_choice, 'expected_clock': target['clock']}]
    assert result['fixed_decisions'][0]['proposal_id'] == fixed['proposal_id']
    assert list(result['fixed_frame_hashes']) == [fixed_frame['message_id']]
    assert list(result['frame_hashes']) == [state['controls'][0]['message_id']]
    claim = review.prepare_save(result['revision'], 'b' * 64)
    assert read() == baseline and not claim['book_persisted']
    owner.record_saved('native-producer-fixture', True, 'b' * 64)
    receipt = review.confirm_saved(claim['claim_token'])
    assert receipt['book_persisted'] and not receipt['phone_persisted'] and review.validate('handoff', None) is True
    assert review.confirm_saved(claim['claim_token']) == receipt


@pytest.mark.parametrize('fault', ['missing-frame', 'missing-target', 'foreign-frame', 'clock', 'duplicate-frame', 'duplicate-proposal', 'duplicate-entity', 'wrong-run', 'direction-collision'])
def test_mixed_review_rejects_ambiguous_or_unbound_native_fixed_evidence(fault):
    create, state, owner, read, fixed, fixed_frame, target, before = mixed_fixture()
    targets, frames = [copy.deepcopy(fixed)], [copy.deepcopy(fixed_frame)]
    if fault == 'missing-frame': frames = []
    elif fault == 'missing-target': targets = []
    elif fault == 'foreign-frame': frames[0]['body']['body']['decisions'][0]['proposal_id'] = str(uuid.uuid4())
    elif fault == 'clock': frames[0]['body']['body']['decisions'][0]['expected_clock'][0]['counter'] += 1
    elif fault == 'duplicate-frame': frames.append(copy.deepcopy(frames[0]))
    elif fault == 'duplicate-proposal': targets[0] = copy.deepcopy(target)
    elif fault == 'duplicate-entity':
        targets[0].update(kind='note', id=target['id'])
    elif fault == 'wrong-run': frames[0]['body']['body']['run_id'] = str(uuid.uuid4())
    else: frames[0]['message_id'] = state['controls'][0]['message_id']
    with pytest.raises(ValueError): create(targets, frames).review()


def test_fixed_original_frames_are_deep_pinned_and_change_review_revision_without_reapplying_them():
    create, state, owner, read, fixed, fixed_frame, target, before = mixed_fixture()
    targets, frames = [copy.deepcopy(fixed)], [copy.deepcopy(fixed_frame)]
    review = create(targets, frames); revision = review.review()['revision']
    frames[0]['body']['body']['decisions'][0]['decision'] = 'restore'
    targets[0]['prior_hash'] = 'e' * 64
    assert review.review()['revision'] == revision
    # The same effective choice in a different protected original frame still
    # cannot substitute for the original bound direction/receipt identity.
    changed = copy.deepcopy(fixed_frame); changed['message_id'] = str(uuid.uuid4())
    assert create([fixed], [changed]).review()['revision'] != revision
    assert read()['sequence'] == review.before_saved['sequence']


@pytest.mark.parametrize('scope_case', ['only-late', 'only-fixed', 'unrelated'])
def test_mixed_review_requires_both_result_scope_directions(scope_case):
    create, state, owner, read, fixed, fixed_frame, target, before = mixed_fixture('delete', 'delete')
    members = {'only-late': ([], ['selected-task']), 'only-fixed': (['canonical-parent'], []), 'unrelated': (['unrelated'], [])}[scope_case]
    state['scope'] = scope.advance(before, *members)
    with pytest.raises(ValueError): create().review()
