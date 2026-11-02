"""Actual native prepare closes data before any writer; no SaveACK yet."""
import copy
import hashlib
import json
import sqlite3
import uuid

import pytest
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
import magnolie_content_scope as scope
from test_personal_actor_restore_candidate import gui_candidates
from test_personal_actor_target_observer_runtime import observation_runtime
from test_personal_actor_transport import frame


def prepared(tmp_path, monkeypatch, raw, *, changed_candidate=False):
    fixture = copy.deepcopy(raw)
    service, peer, channel, manifest, book, target, owner, read, snapshot, registry, handle = observation_runtime(
        tmp_path, monkeypatch, fixture['target']['kind'], source_fixture=fixture, full_live_scope=True)
    candidate = json.loads(fixture['candidate_text'])
    candidate['personalSync']['peer_device_id'] = peer['device_id']
    key = target['kind'] + '\0' + target['id']
    candidate['personalSync']['entities'][key]['peer_device_id'] = peer['device_id']
    if changed_candidate:
        candidate['einstellungen']['unrelated_synthetic_change'] = True
    candidate_text = json.dumps(candidate, ensure_ascii=False, separators=(',', ':'))
    service.start_personal_actor(registry, handle)
    request = {'format': fixture['format'], 'run_id': handle.actor_id, 'trigger': 'manual', 'modules': ['notes', 'tasks']}
    service._payload(peer, channel, actor.wire_message(frame('personal_sync.request', request), handle.actor_id))
    body = {'format': 1, 'run_id': handle.actor_id, 'proposal_batch_id': str(uuid.uuid4()), 'sequence': 0, 'last': True,
        'proposals': [dict(target, deleted_ms=2, label='Synthetic historical target')]}
    service._payload(peer, channel, actor.wire_message(frame('personal_sync.deletion_proposals', body), handle.actor_id))
    channel.sent.clear()
    view = service.review_personal_actor_incoming_targets(registry, handle)
    choices = [fixture['choice']]
    return service, peer, channel, book, owner, read, registry, handle, view, choices, candidate_text


def durable_queue(service):
    with sqlite3.connect(service.store.database_path) as db:
        return db.execute('SELECT peer_id,message_id,kind,payload FROM outbox ORDER BY peer_id,message_id').fetchall()


def test_native_historical_prepare_uses_exact_candidate_and_irreversibly_closes_data_without_saving_or_acknowledging(tmp_path, monkeypatch, gui_candidates):
    for index, fixture in enumerate(gui_candidates):
        service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path / str(index), monkeypatch, fixture)
        retained, saved, queue = copy.deepcopy(book), read(), durable_queue(service)
        claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
        assert claim['data_closed'] is True and claim['book_persisted'] is False and claim['phone_persisted'] is False
        assert claim['after_sha256'] == hashlib.sha256(text.encode()).hexdigest()
        assert len(claim['claim_token']) == 64 and registry.status(handle)['phase'] == 'completion'
        with pytest.raises(PermissionError): registry.require_current(handle)
        with pytest.raises(PermissionError): registry.read_completion_controls(handle)
        service.check_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text)
        with pytest.raises(PermissionError, match='already_used'):
            service.check_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text)
        with pytest.raises(PermissionError): service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
        assert book == retained and read() == saved and durable_queue(service) == queue and not channel.sent
        service.cancel_personal_actor(registry, handle, notify=False)


def test_unrelated_candidate_mutation_cannot_issue_a_native_prepare_or_retire_the_original_data_owner(tmp_path, monkeypatch, gui_candidates):
    for index, fixture in enumerate(gui_candidates):
        service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path / str(index), monkeypatch, fixture, changed_candidate=True)
        before, saved, queue = registry.status(handle), read(), durable_queue(service)
        with pytest.raises(PermissionError): service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
        registry.require_current(handle)
        assert registry.status(handle) == before and read() == saved and durable_queue(service) == queue and not channel.sent


@pytest.mark.parametrize('fault', ['token', 'candidate', 'save', 'frame', 'grant', 'cancel'])
def test_native_writer_gate_rechecks_the_prepared_claim_before_any_actual_write(tmp_path, monkeypatch, gui_candidates, fault):
    service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path, monkeypatch, gui_candidates[0])
    claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
    token = claim['claim_token']
    if fault == 'token': token = 'f' * 64
    elif fault == 'candidate': text += ' '
    elif fault == 'save': owner.record_saved('native-producer-fixture', True, read()['sha256'])
    elif fault == 'frame':
        origin = service.personal_actor_admissions[handle.actor_id]['incoming_target_origin']
        wire_id = next(iter(origin['frames']))
        changed = json.loads(origin['frames'][wire_id]); changed['expires_ms'] -= 1
        origin['frames'][wire_id] = json.dumps(changed).encode()
    elif fault == 'grant': peer['local_grants']['grants']['personal_deletions_sync'] = False
    else: service.cancel_personal_actor(registry, handle, notify=False)
    retained, saved, queue = copy.deepcopy(book), read(), durable_queue(service)
    with pytest.raises(PermissionError): service.check_personal_actor_historical_restore_save(registry, handle, token, text)
    assert book == retained and read() == saved and durable_queue(service) == queue and not channel.sent
    with pytest.raises(PermissionError): registry.require_current(handle)


@pytest.mark.parametrize('last', [False, True])
def test_a_partial_or_ready_ordinary_data_group_cannot_be_silently_skipped_by_historical_prepare(tmp_path, monkeypatch, gui_candidates, last):
    fixture = gui_candidates[0]
    service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path, monkeypatch, fixture)
    records = [fixture['live_records'][0]]
    batch = {'format': fixture['format'], 'run_id': handle.actor_id, 'batch_id': str(uuid.uuid4()), 'reply': False, 'sequence': 0, 'last': last,
        'records_hash': personal.records_hash(records), 'records': records}
    wire = actor.wire_message(frame('personal_sync.batch', batch), handle.actor_id)
    service._payload(peer, channel, wire)
    assert registry.read(handle, wire['message_id']) == wire
    channel.sent.clear()
    before, saved, queue, retained = registry.status(handle), read(), durable_queue(service), copy.deepcopy(book)
    with pytest.raises(PermissionError, match='mixed_data'):
        service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
    registry.require_current(handle)
    assert registry.status(handle) == before and read() == saved and book == retained and durable_queue(service) == queue and not channel.sent


@pytest.mark.parametrize('foreign_scope', [False, True])
def test_idle_data_check_recognizes_only_the_original_scoped_request_wrapper_without_granting_data_rights(tmp_path, monkeypatch, gui_candidates, foreign_scope):
    service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path, monkeypatch, gui_candidates[0])
    admission = service.personal_actor_admissions[handle.actor_id]
    manifest = service.current_content_scope(peer['device_id'], peer['static_public'], admission['scope'])
    used = scope.create(['foreign'], []) if foreign_scope else manifest
    request = service.store.personal_run(actor.storage_peer(handle.actor_id), handle.actor_id)
    wire = actor.wire_message(frame(scope.DATA_KIND, scope.wrap('personal_sync.request', request, used)), handle.actor_id)
    registry.put(handle, wire)  # Raw storage is not authenticated origin or action authority.
    before = registry.status(handle); saved = read(); queue = durable_queue(service)
    if foreign_scope:
        with pytest.raises(ValueError): registry.require_historical_data_idle(handle, manifest)
    else:
        registry.require_historical_data_idle(handle, manifest)
    registry.require_current(handle)
    assert registry.status(handle) == before and read() == saved and durable_queue(service) == queue and not channel.sent


def test_prepared_native_writer_does_not_reopen_data_or_count_delayed_network_controls_as_save_receipts(tmp_path, monkeypatch, gui_candidates):
    fixture = gui_candidates[0]
    service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path, monkeypatch, fixture)
    claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
    before, retained, saved, queue = registry.status(handle), copy.deepcopy(book), read(), durable_queue(service)
    records = [fixture['live_records'][0]]
    batch = {'format': fixture['format'], 'run_id': handle.actor_id, 'batch_id': str(uuid.uuid4()), 'reply': False, 'sequence': 0, 'last': True,
        'records_hash': personal.records_hash(records), 'records': records}
    incoming = actor.wire_message(frame('personal_sync.batch', batch), handle.actor_id)
    service._payload(peer, channel, incoming)
    service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, str(uuid.uuid4()))))
    assert registry.status(handle) == before and book == retained and read() == saved and durable_queue(service) == queue and not channel.sent
    with pytest.raises(PermissionError): registry.read(handle, incoming['message_id'])
    assert service.personal_actor_status(registry, handle)['book_persisted'] is False
    service.check_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text)
    service.cancel_personal_actor(registry, handle, notify=False)
