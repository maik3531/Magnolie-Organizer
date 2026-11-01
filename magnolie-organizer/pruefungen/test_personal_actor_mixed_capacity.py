"""Maximum native review/receipt union; no GUI responsiveness or phone claim."""
import copy
import json
import time
import uuid

import pytest
import magnolie_content_scope as scope
import magnolie_personal_actor as actor
from magnolie_personal_actor_completion import DecisionAckCompletion
from magnolie_personal_actor_decision_review import PostDataDecisionReview
from test_personal_actor_post_data_review import review_fixture
from test_personal_actor_transport import frame


@pytest.mark.parametrize('fixed_count', [1, 128, 255])
def test_maximum_mixed_union_keeps_separate_mutations_and_exact_both_direction_receipts(fixed_count):
    late_count = 256 - fixed_count
    original, state, owner, read, snapshot, report_id, report_ack = review_fixture(late_count)
    fixed = [{'proposal_id': str(uuid.uuid4()), 'kind': 'task', 'id': 'capacity-task-%03d' % index,
        'parent_id': '', 'prior_hash': 'f' * 64,
        'clock': [{'actor_id': '22222222-2222-4222-8222-222222222222', 'counter': index + 1}]}
        for index in range(fixed_count)]
    fixed.sort(key=lambda value: value['proposal_id'])
    before = scope.create(original.before['members']['notes'], [value['id'] for value in fixed])
    state['scope'] = scope.advance(before, before['members']['notes'], [])
    fixed_frames = []
    for start in range(0, fixed_count, 32):
        fixed_frames.append(actor.wire_message(frame('personal_sync.deletion_decision', {'format': 1,
            'run_id': original.run_id, 'decision_id': str(uuid.uuid4()),
            'decisions': [{'proposal_id': value['proposal_id'], 'decision': 'delete', 'expected_clock': value['clock']}
                for value in fixed[start:start + 32]]}), original.run_id))
    started = time.monotonic()
    review = PostDataDecisionReview(original.run_id, original.targets, before, report_id, report_ack,
        current_authority=lambda: state['authority'], current_scope=lambda: state['scope'], current_saved_book=read,
        persisted_controls=lambda: copy.deepcopy(state['controls']), native_fixed_targets=fixed,
        fixed_decision_frames=fixed_frames)
    view = review.review()
    assert len(view['decisions']) == late_count and len(view['fixed_decisions']) == fixed_count
    assert len(view['frame_hashes']) == (late_count + 31) // 32
    assert len(view['fixed_frame_hashes']) == (fixed_count + 31) // 32
    assert len(json.dumps(view).encode()) < 4 * 1024 * 1024
    baseline = read()
    claim = review.prepare_save(view['revision'], 'b' * 64)
    assert review.prepare_save(view['revision'], 'b' * 64) == claim and read() == baseline
    owner.record_saved('native-producer-fixture', True, 'b' * 64)
    receipt = review.confirm_saved(claim['claim_token'])
    assert review.confirm_saved(claim['claim_token']) == receipt
    late_frames = copy.deepcopy(state['controls'])
    own = [frame(actor.ACK_KIND, actor.ack(original.run_id, value['message_id'])) for value in late_frames]
    persisted = []
    completion = DecisionAckCompletion(original.run_id, original.targets + fixed, late_frames + fixed_frames,
        current_authority=lambda: state['authority'], current_scope=lambda: state['scope'], current_saved_book=read,
        persisted_controls=lambda: copy.deepcopy(persisted), native_sent_acknowledgments=own, before_scope=before)
    expected = len(late_frames) + len(fixed_frames)
    assert completion.summary()['expected'] == expected
    for wire in own:
        completion.record_successful_acknowledgment_send(wire)
        persisted.append(copy.deepcopy(wire))
        completion.record_persisted(wire)
    assert completion.summary()['saved'] == len(late_frames)
    assert completion.validate('finish', None) is None, 'Own sends substituted for fixed peer receipts'
    for wire in fixed_frames:
        ack = frame(actor.ACK_KIND, actor.ack(original.run_id, wire['message_id']))
        persisted.append(copy.deepcopy(ack))
        completion.record_persisted(ack)
    assert completion.summary() == dict(expected=expected, received=expected, saved=expected, rejected=0)
    assert completion.validate('finish', None) is True
    assert read()['sequence'] == baseline['sequence'] + 1
    # Bounded native primitive budget, deliberately not an event-loop/UI claim.
    elapsed = time.monotonic() - started
    assert elapsed < 10, 'Bounded native primitive exceeded its 10s test budget: %.3fs' % elapsed


def test_combined_257_native_targets_rejected_without_any_writer_or_save_claim():
    original, state, owner, read, snapshot, report_id, report_ack = review_fixture(256)
    baseline = read()
    fixed = {'proposal_id': str(uuid.uuid4()), 'kind': 'task', 'id': 'extra-task', 'parent_id': '',
        'prior_hash': 'f' * 64, 'clock': [{'actor_id': '22222222-2222-4222-8222-222222222222', 'counter': 1}]}
    wire = actor.wire_message(frame('personal_sync.deletion_decision', {'format': 1, 'run_id': original.run_id,
        'decision_id': str(uuid.uuid4()), 'decisions': [{'proposal_id': fixed['proposal_id'], 'decision': 'restore',
            'expected_clock': fixed['clock']}]}), original.run_id)
    with pytest.raises(ValueError):
        PostDataDecisionReview(original.run_id, original.targets, original.before, report_id, report_ack,
            current_authority=lambda: state['authority'], current_scope=lambda: state['scope'], current_saved_book=read,
            persisted_controls=lambda: state['controls'], native_fixed_targets=[fixed], fixed_decision_frames=[wire])
    assert read() == baseline
