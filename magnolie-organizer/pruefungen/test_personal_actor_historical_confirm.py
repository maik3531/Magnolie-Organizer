"""Native SaveACK/terminal integration; writer ACK is synthetic, no GUI/E2E claim."""
import copy
import hashlib
import json
import uuid

import pytest
import magnolie_personal_actor as actor
import magnolie_content_scope as scope
from magnolie_personal_actor_store import NativeProducerBookSnapshot
from test_personal_actor_restore_candidate import gui_candidates
from test_personal_actor_historical_prepare import prepared, durable_queue
from test_personal_actor_transport import frame


def native_saved_candidate(service, owner, read, text, extra_sequence=False):
    candidate = json.loads(text); digest = hashlib.sha256(text.encode()).hexdigest()
    owner.record_saved('native-producer-fixture', True, digest)
    if extra_sequence: owner.record_saved('native-producer-fixture', True, digest)
    saved = read()
    fingerprint = hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    captured = NativeProducerBookSnapshot.capture(read, lambda: candidate,
        lambda: (saved['book_source'], saved['sequence'], fingerprint))
    assert captured is not None
    service.native_actor_producer_book = lambda: captured
    return candidate, captured


def test_confirm_binds_native_save_ack_then_only_exact_historical_decision_receipt_completes(tmp_path, monkeypatch, gui_candidates):
    for index, fixture in enumerate(gui_candidates):
        service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path / str(index), monkeypatch, fixture)
        admission = service.personal_actor_admissions[handle.actor_id]
        manifest = service.current_content_scope(peer['device_id'], peer['static_public'], admission['scope'])
        claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
        with pytest.raises(PermissionError, match='not_invoked'):
            service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'])
        service.check_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text)
        with pytest.raises(PermissionError, match='actual_save_proof'):
            service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'])
        candidate, after = native_saved_candidate(service, owner, read, text)
        result = service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'])
        assert result['historical_book_persisted'] is True and result['book_persisted'] is False and result['phone_data_persisted'] is False
        assert result['phase'] == 'completion' and result['phone_persisted'] is False
        assert result['deletion_completion'] == {'expected': 1, 'received': 0, 'saved': 0, 'rejected': 0}
        assert service.current_content_scope(peer['device_id'], peer['static_public'], admission['scope']) == manifest
        before_queue, saved = durable_queue(service), read()
        assert service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token']) == result
        assert durable_queue(service) == before_queue and read() == saved
        with pytest.raises(PermissionError): registry.require_current(handle)
        service.advance_personal_actor_completion(registry, handle)
        sent = channel.sent.pop()
        assert not channel.sent and sent['kind'] == actor.DATA_KIND
        kind, body = actor.unwrap(sent['body'])
        assert kind == 'personal_sync.deletion_decision' and body['decisions'] == [{key: choices[0][key] for key in ('proposal_id', 'decision', 'expected_clock')}]
        acknowledgment = frame(actor.ACK_KIND, actor.ack(handle.actor_id, sent['message_id']))
        service._payload(peer, channel, acknowledgment)
        done = service.personal_actor_status(registry, handle)
        assert done['phase'] == 'completed' and done['phone_persisted'] is True and done['phone_data_persisted'] is False
        assert done['deletion_completion'] == {'expected': 1, 'received': 1, 'saved': 1, 'rejected': 0}
        assert read() == saved and service.native_actor_producer_book().book() == candidate and not channel.sent
        with pytest.raises(PermissionError): registry.require_current(handle)
        assert service.current_content_scope(peer['device_id'], peer['static_public'], admission['scope']) == manifest


@pytest.mark.parametrize('fault', ['extra-sequence', 'wrong-bytes', 'scope', 'grant', 'token'])
def test_a_saved_but_mismatched_historical_claim_cannot_queue_decisions_or_claim_peer_persistence(tmp_path, monkeypatch, gui_candidates, fault):
    service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path, monkeypatch, gui_candidates[0])
    claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
    service.check_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text)
    if fault == 'wrong-bytes':
        changed = json.loads(text); changed['einstellungen']['unrelated_synthetic_change'] = True
        text = json.dumps(changed, ensure_ascii=False)
    candidate, after = native_saved_candidate(service, owner, read, text, extra_sequence=fault == 'extra-sequence')
    if fault == 'scope':
        binding = (peer['device_id'], peer['static_public'], id(channel)); session = scope.ScopeSession(binding)
        for part in scope.chunks(scope.create(['foreign'], [])): session.receive(binding, part)
        service.content_scope_sessions[channel] = session
    elif fault == 'grant': peer['local_grants']['grants']['personal_deletions_sync'] = False
    queue, saved = durable_queue(service), read()
    with pytest.raises(PermissionError):
        service.confirm_personal_actor_historical_restore_save(registry, handle, 'f' * 64 if fault == 'token' else claim['claim_token'])
    result = service.personal_actor_status(registry, handle)
    assert result['phase'] != 'completed' and result['phone_persisted'] is False and result['historical_book_persisted'] is False
    assert durable_queue(service) == queue and read() == saved and service.native_actor_producer_book().book() == candidate and not channel.sent
    with pytest.raises(PermissionError): registry.require_current(handle)


def test_prepared_outgoing_request_waits_without_cancelling_writer_and_is_not_a_terminal_receipt_frame(tmp_path, monkeypatch, gui_candidates):
    service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path, monkeypatch, gui_candidates[0])
    request = service.store.personal_run(actor.storage_peer(handle.actor_id), handle.actor_id)
    old = service.store.queue(peer['device_id'], 'personal_sync.request', request, 60000, actor_run_id=handle.actor_id)
    service.personal_actor_admissions[handle.actor_id]['outbound'].add(old['message_id'])
    claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
    assert service._send_personal_actor_queued(channel, peer['device_id'], old) is False
    assert registry.status(handle)['phase'] == 'completion' and service.store.outbox_message(peer['device_id'], old['message_id']) == old
    service.check_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text)
    candidate, after = native_saved_candidate(service, owner, read, text)
    result = service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'])
    assert service.store.outbox_message(peer['device_id'], old['message_id']) is None
    assert result['deletion_completion']['expected'] == 1 and not channel.sent


@pytest.mark.parametrize('fault', ['save', 'book-source-provider'])
def test_independent_native_save_after_confirm_blocks_the_old_decision_ack_without_rolling_back_local_data(tmp_path, monkeypatch, gui_candidates, fault):
    service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path, monkeypatch, gui_candidates[0])
    claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
    service.check_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text)
    candidate, after = native_saved_candidate(service, owner, read, text)
    service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'])
    service.advance_personal_actor_completion(registry, handle)
    sent = channel.sent.pop(); assert not channel.sent
    if fault == 'save': owner.record_saved('native-producer-fixture', True, read()['sha256'])
    else: service.native_actor_book_source = lambda: '0' * 64
    saved = read()
    service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, sent['message_id'])))
    result = service.personal_actor_status(registry, handle)
    assert result['phase'] == 'cancelled' and result['phone_persisted'] is False
    assert read() == saved and service.native_actor_producer_book().book() == candidate and not channel.sent
