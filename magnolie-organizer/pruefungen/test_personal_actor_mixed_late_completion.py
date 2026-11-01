"""Actual late-confirm union, with injected reviewed owner/writer, not Mixed E2E."""
import copy
import base64
import json
import sqlite3
import pytest
import magnolie_personal_actor as actor
import magnolie_content_scope as scope
import magnolie_telefon as phone
from magnolie_personal_actor_store import ActorStore
from test_mcp_phone import owned_service
from test_personal_actor_mixed_report_owner import mixed_report_fixture
from test_personal_actor_transport import frame


@pytest.mark.parametrize('early_ack', [True, False])
@pytest.mark.parametrize('fault', ['none', 'promotion', 'fixed-proof'])
def test_late_confirm_unions_both_receipt_directions_without_requeue_or_initial_mutation(tmp_path, monkeypatch, early_ack, fault):
    create, state, owner, read, report, controls, fixed_target, fixed_frame = mixed_report_fixture()
    waiting = create()
    service, peer, events = owned_service(tmp_path)
    registry = ActorStore(service.store, lambda *_: 'a' * 64)
    handle = registry.create(peer['device_id'], phone.fingerprint(phone.unb64(peer['static_public'], 32)), 'a' * 64, run_id=waiting.run_id)
    private = actor.storage_peer(handle.actor_id)
    late_frames = copy.deepcopy(state['controls'])
    for targets, outgoing in [(waiting.targets, True), ([fixed_target], False)]:
        service.store.remember_personal_proposal_kinds(private, {'format': 1, 'run_id': handle.actor_id,
            'proposal_batch_id': handle.actor_id, 'sequence': 0, 'last': True,
            'proposals': [dict(target, deleted_ms=2, label='Synthetic original proof') for target in targets]}, outgoing)
    waiting.persisted_controls = lambda: registry.read_completion_controls(handle)
    registry.begin_decision_review(handle, waiting.validator)
    registry.put_completion_control(handle, frame(actor.ACK_KIND, actor.ack(handle.actor_id, report['message_id'])))
    for wire in late_frames: registry.put_completion_control(handle, wire)
    fixed_ack = frame(actor.ACK_KIND, actor.ack(handle.actor_id, fixed_frame['message_id']))
    if early_ack: registry.put_completion_control(handle, fixed_ack)
    state['scope'] = scope.advance(waiting.before, waiting.before['members']['notes'], [])
    review = waiting.begin_review(current_scope=lambda: state['scope'], current_saved_book=read)
    claim = review.prepare_save(review.review()['revision'], 'b' * 64)
    channel = object()
    admission = dict(peer=peer['device_id'], key=peer['static_public'], channel=channel, registry=registry, handle=handle,
        report_owner=waiting, late_claim_token=claim['claim_token'], phone_data_persisted=True, outbound=set(), producer_bodies=[])
    service.connections[peer['device_id']] = channel
    service.personal_actor_admissions[handle.actor_id] = admission
    projection = service.read_personal_actor_late_review(registry, handle, native_saved_book=read)
    projected = json.loads(base64.b64decode(projection['data_base64']))
    assert projected['fixed_targets'] == [fixed_target]
    assert projected['fixed_decisions'][0]['proposal_id'] == fixed_target['proposal_id']
    assert projected['fixed_decision_message_ids'] == [fixed_frame['message_id']]
    assert projected['decisions'] == review.review()['decisions']
    assert all(value['proposal_id'] != fixed_target['proposal_id'] for value in projected['decisions'])
    owner.record_saved('native-producer-fixture', True, 'b' * 64)
    saved = read()
    # Paging/ordinary Mixed preparation is deliberately not part of this probe.
    # The original native review and protected receipts above are actual.
    monkeypatch.setattr(service, 'read_personal_actor_late_review', lambda *args, **kwargs: None)
    if fault == 'promotion':
        with sqlite3.connect(service.store.database_path) as db:
            db.execute("CREATE TRIGGER mixed_handoff_fault BEFORE INSERT ON personal_actor_context BEGIN SELECT RAISE(ABORT,'synthetic union handoff fault'); END")
        with pytest.raises(sqlite3.DatabaseError):
            service.confirm_personal_actor_late_save(registry, handle, claim['claim_token'], native_saved_book=read)
        with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER mixed_handoff_fault')
        assert admission.get('completion') is None and review.saved == saved and read() == saved
    if fault == 'fixed-proof':
        key = 'personal_proposal_kind:%s:in:%s' % (private, fixed_target['proposal_id'])
        with sqlite3.connect(service.store.database_path) as db: db.execute('DELETE FROM meta WHERE key=?', (key,))
        with pytest.raises(PermissionError, match='actor_completion_target_proof_missing'):
            service.confirm_personal_actor_late_save(registry, handle, claim['claim_token'], native_saved_book=read)
        assert admission.get('completion') is None and read() == saved
        return
    receipt = service.confirm_personal_actor_late_save(registry, handle, claim['claim_token'], native_saved_book=read)
    completion = admission['completion']
    assert receipt['deletion_book_persisted'] and not receipt['phone_persisted']
    assert completion.summary() == dict(expected=2, received=int(early_ack), saved=int(early_ack), rejected=0)
    assert admission['completion_ids'] == {fixed_frame['message_id']}
    assert not service.store.pending(peer['device_id']) and read() == saved
    assert service.confirm_personal_actor_late_save(registry, handle, claim['claim_token'], native_saved_book=read) == receipt
    own_ack = next(iter(admission['completion_native_acks'].values()))
    # Native own-send marker fixture; actual network guard tested separately.
    completion.record_successful_acknowledgment_send(own_ack)
    registry.put_completion_control(handle, own_ack); completion.record_persisted(own_ack)
    if not early_ack:
        assert completion.summary()['saved'] == 1 and completion.validate('finish', None) is None
        assert service._receive_personal_actor(peer, channel, fixed_ack) is True
    else:
        assert registry.finish_completion(handle)['phase'] == 'completed'
    assert completion.summary() == dict(expected=2, received=2, saved=2, rejected=0)
    assert read() == saved and not events and not service.store.pending(peer['device_id'])
