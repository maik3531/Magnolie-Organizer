"""Pre-report native handoff primitive and actual sealed metadata boundary."""
import copy
import uuid
import pytest
import magnolie_personal_actor as actor
from magnolie_personal_actor_report_owner import PostDataReportOwner
from magnolie_personal_actor_store import ActorStore
from test_personal_actor_post_data_review import review_fixture
from test_personal_actor_transport import frame
from test_mcp_phone import owned_service
import magnolie_telefon as phone


def report_fixture():
    review, state, owner, read, snapshot, _, _ = review_fixture(1)
    zero = {'notes': 0, 'tasks': 0, 'notebooks': 0}
    report = {'format': 3, 'run_id': review.run_id, 'state': 'complete', 'trigger': 'manual', 'transport': 'wifi',
        'sent': copy.deepcopy(zero), 'received': copy.deepcopy(zero), 'conflicts': 0, 'attachments_omitted': 0, 'oversized_skipped': 0,
        'started_ms': 1, 'finished_ms': 2, 'error': 'none',
        'attachments': dict.fromkeys(('declared', 'requested', 'sent', 'received', 'reused', 'preserved', 'failed', 'bytes'), 0),
        'deletions': dict(dict.fromkeys(('pending', 'deleted', 'restored', 'conflicts', 'blocked'), 0), trash=dict(zero, attachments=0))}
    wire = actor.wire_message(frame('personal_sync.report', report), review.run_id)
    controls = []
    waiting = PostDataReportOwner(review.run_id, review.targets, review.before, wire, read(),
        current_authority=lambda: state['authority'], persisted_controls=lambda: copy.deepcopy(controls))
    return waiting, review, state, owner, read, wire, controls


def test_report_owner_closes_data_before_report_send_and_survives_result_scope_change(tmp_path):
    waiting, template, state, owner, read, report, controls = report_fixture()
    service, peer, events = owned_service(tmp_path)
    original_source = {'revision': 'a' * 64}
    store = ActorStore(service.store, lambda *_: original_source['revision'])
    handle = store.create(peer['device_id'], phone.fingerprint(phone.unb64(peer['static_public'], 32)), original_source['revision'], run_id=waiting.run_id)
    waiting.persisted_controls = lambda: store.read_completion_controls(handle)
    store.begin_decision_review(handle, waiting.validator)
    store.check_decision_report_send(handle, report)
    original_source['revision'] = 'b' * 64
    with pytest.raises(PermissionError): store.require_current(handle)
    with pytest.raises(PermissionError): waiting.begin_review(current_scope=lambda: state['scope'], current_saved_book=read)
    ack = frame(actor.ACK_KIND, actor.ack(waiting.run_id, report['message_id']))
    store.put_completion_control(handle, ack)
    for decision in state['controls']: store.put_completion_control(handle, decision)
    review = waiting.begin_review(current_scope=lambda: state['scope'], current_saved_book=read)
    assert review is waiting.begin_review(current_scope=lambda: None, current_saved_book=lambda: None)
    claim = review.prepare_save(review.review()['revision'], 'b' * 64)
    owner.record_saved('native-producer-fixture', True, 'b' * 64)
    review.confirm_saved(claim['claim_token'])
    assert waiting.validator('handoff', None) is True
    assert not events and service.server is None


@pytest.mark.parametrize('fault', ['foreign-report', 'changed-report', 'ordinary-data', 'unknown-decision', 'wrong-clock', 'source', 'handoff', 'send'])
def test_report_owner_does_not_create_general_data_send_or_adoption_rights(fault):
    waiting, review, state, owner, read, report, controls = report_fixture()
    if fault == 'foreign-report':
        wire = frame(actor.ACK_KIND, actor.ack(waiting.run_id, str(uuid.uuid4())))
    elif fault == 'changed-report':
        wire = copy.deepcopy(report); wire['message_id'] = str(uuid.uuid4())
        with pytest.raises(ValueError): waiting.validate('send_report', wire)
        return
    elif fault == 'ordinary-data':
        wire = actor.wire_message(frame('personal_sync.request', {'format': 3, 'run_id': waiting.run_id, 'trigger': 'manual', 'modules': ['notes']}), waiting.run_id)
    elif fault in ('unknown-decision', 'wrong-clock'):
        wire = copy.deepcopy(state['controls'][0]); value = wire['body']['body']['decisions'][0]
        if fault == 'unknown-decision': value['proposal_id'] = str(uuid.uuid4())
        else: value['expected_clock'][0]['counter'] += 1
    elif fault == 'source':
        state['authority'] = 'b' * 64
        assert waiting.validate('begin', None) is False
        return
    elif fault == 'handoff':
        assert waiting.validate('handoff', None) is None
        return
    else:
        with pytest.raises(ValueError): waiting.validate('send', report)
        return
    with pytest.raises(ValueError): waiting.validate('put', wire)


def test_rejected_report_receipt_and_unpersisted_success_do_not_unlock_review():
    waiting, review, state, owner, read, report, controls = report_fixture()
    success = frame(actor.ACK_KIND, actor.ack(waiting.run_id, report['message_id']))
    assert waiting.validate('put', success) is True
    with pytest.raises(PermissionError): waiting.begin_review(current_scope=lambda: state['scope'], current_saved_book=read)
    rejected = copy.deepcopy(success); rejected['body'].update(status='rejected', error='temporary_failure'); controls.append(rejected)
    with pytest.raises(PermissionError): waiting.begin_review(current_scope=lambda: state['scope'], current_saved_book=read)
    controls.append(success)
    assert waiting.begin_review(current_scope=lambda: state['scope'], current_saved_book=read) is not None


def test_known_producer_ack_is_only_metadata_and_requires_exact_native_frame_target_binding():
    from test_personal_actor_producer import fixture, prepare
    waiting, review, state, owner, read, report, controls = report_fixture()
    book, manifest = fixture(1)
    producer = actor.wire_message(frame('personal_sync.deletion_proposals', prepare(book, manifest)[0]), waiting.run_id)
    bound = PostDataReportOwner(waiting.run_id, review.targets, review.before, report, read(),
        current_authority=lambda: state['authority'], persisted_controls=lambda: controls, producer_frames=[producer])
    ack = frame(actor.ACK_KIND, actor.ack(waiting.run_id, producer['message_id']))
    assert bound.validate('put', ack) is True
    controls.append(ack)
    with pytest.raises(PermissionError): bound.begin_review(current_scope=lambda: state['scope'], current_saved_book=read)
    changed = copy.deepcopy(producer); changed['body']['body']['proposals'][0]['prior_hash'] = 'f' * 64
    with pytest.raises(ValueError):
        PostDataReportOwner(waiting.run_id, review.targets, review.before, report, read(),
            current_authority=lambda: state['authority'], persisted_controls=lambda: controls, producer_frames=[changed])


def test_report_receipt_cannot_rebind_a_new_unrelated_saved_book_as_review_baseline():
    waiting, review, state, owner, read, report, controls = report_fixture()
    controls.append(frame(actor.ACK_KIND, actor.ack(waiting.run_id, report['message_id'])))
    owner.record_saved('native-producer-fixture', True, read()['sha256'])
    with pytest.raises(PermissionError): waiting.begin_review(current_scope=lambda: state['scope'], current_saved_book=read)
    assert waiting.review is None
