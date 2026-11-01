"""Native mixed pre-report metadata capability, not controller/E2E acceptance."""
import copy
import uuid
import pytest
import magnolie_personal_actor as actor
import magnolie_content_scope as scope
import magnolie_telefon as phone
from magnolie_personal_actor_report_owner import PostDataReportOwner
from magnolie_personal_actor_store import ActorStore
from test_mcp_phone import owned_service
from test_personal_actor_report_owner import report_fixture
from test_personal_actor_transport import frame


def mixed_report_fixture():
    original, template, state, owner, read, report, controls = report_fixture()
    fixed = {'proposal_id': str(uuid.uuid4()), 'kind': 'task', 'id': 'selected-task', 'parent_id': '',
        'prior_hash': 'f' * 64, 'clock': [{'actor_id': '22222222-2222-4222-8222-222222222222', 'counter': 7}]}
    fixed_frame = actor.wire_message(frame('personal_sync.deletion_decision', {'format': 1, 'run_id': original.run_id,
        'decision_id': str(uuid.uuid4()), 'decisions': [{'proposal_id': fixed['proposal_id'], 'decision': 'delete', 'expected_clock': fixed['clock']}]}), original.run_id)
    def create(targets=None, frames=None):
        return PostDataReportOwner(original.run_id, original.targets, original.before, report, read(),
            current_authority=lambda: state['authority'], persisted_controls=lambda: copy.deepcopy(controls),
            native_fixed_targets=[fixed] if targets is None else targets, fixed_decision_frames=[fixed_frame] if frames is None else frames)
    return create, state, owner, read, report, controls, fixed, fixed_frame


def test_mixed_pre_report_owner_has_only_exact_initial_control_send_not_general_data_or_success(tmp_path):
    create, state, owner, read, report, controls, fixed, fixed_frame = mixed_report_fixture()
    waiting = create()
    service, peer, events = owned_service(tmp_path)
    store = ActorStore(service.store, lambda *_: 'a' * 64)
    handle = store.create(peer['device_id'], phone.fingerprint(phone.unb64(peer['static_public'], 32)), 'a' * 64, run_id=waiting.run_id)
    waiting.persisted_controls = lambda: store.read_completion_controls(handle)
    before_saved = read()
    store.begin_decision_review(handle, waiting.validator)
    store.check_decision_control_send(handle, fixed_frame)
    store.check_decision_report_send(handle, report)
    with pytest.raises(ValueError): store.check_decision_control_send(handle, report)
    with pytest.raises(ValueError): store.check_decision_report_send(handle, fixed_frame)
    for changed in [dict(copy.deepcopy(fixed_frame), message_id=str(uuid.uuid4())), copy.deepcopy(fixed_frame)]:
        changed['body']['body']['decisions'][0]['decision'] = 'restore'
        with pytest.raises(ValueError): store.check_decision_control_send(handle, changed)
    assert read() == before_saved
    with pytest.raises(PermissionError): store.require_current(handle)
    assert waiting.validate('handoff', None) is None
    # Report is not gated on decision success: Notes needs that report before it
    # can save/ack the initial decisions. Only exact metadata persistence is allowed.
    fixed_ack = frame(actor.ACK_KIND, actor.ack(waiting.run_id, fixed_frame['message_id']))
    store.put_completion_control(handle, fixed_ack)
    with pytest.raises(PermissionError): waiting.begin_review(current_scope=lambda: state['scope'], current_saved_book=read)
    store.put_completion_control(handle, frame(actor.ACK_KIND, actor.ack(waiting.run_id, report['message_id'])))
    for late in state['controls']: store.put_completion_control(handle, late)
    state['scope'] = scope.advance(waiting.before, waiting.before['members']['notes'], [])
    review = waiting.begin_review(current_scope=lambda: state['scope'], current_saved_book=read)
    view = review.review()
    assert len(view['decisions']) == 1 and view['decisions'][0]['proposal_id'] != fixed['proposal_id']
    assert view['fixed_decisions'][0]['proposal_id'] == fixed['proposal_id']
    claim = review.prepare_save(view['revision'], 'b' * 64)
    owner.record_saved('native-producer-fixture', True, 'b' * 64)
    review.confirm_saved(claim['claim_token'])
    assert waiting.validate('handoff', None) is True
    assert fixed_ack in store.read_completion_controls(handle)
    assert not events and service.server is None


@pytest.mark.parametrize('fault', ['missing-frame', 'missing-target', 'duplicate-frame', 'foreign-clock', 'report-collision', 'late-target-collision'])
def test_mixed_report_owner_rejects_unbound_fixed_native_evidence(fault):
    create, state, owner, read, report, controls, fixed, fixed_frame = mixed_report_fixture()
    targets, frames = [copy.deepcopy(fixed)], [copy.deepcopy(fixed_frame)]
    if fault == 'missing-frame': frames = []
    elif fault == 'missing-target': targets = []
    elif fault == 'duplicate-frame': frames.append(copy.deepcopy(frames[0]))
    elif fault == 'foreign-clock': frames[0]['body']['body']['decisions'][0]['expected_clock'][0]['counter'] += 1
    elif fault == 'report-collision': frames[0]['message_id'] = report['message_id']
    else: targets[0]['proposal_id'] = state['controls'][0]['body']['body']['decisions'][0]['proposal_id']
    with pytest.raises(ValueError): create(targets, frames)
