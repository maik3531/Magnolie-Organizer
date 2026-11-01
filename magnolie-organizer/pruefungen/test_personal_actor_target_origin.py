"""Authenticated native incoming origin, separate from data/save/ACK authority."""
import copy
import uuid

import pytest
import magnolie_personal_actor as actor
from magnolie_personal_actor_store import ActorHandle
from test_personal_actor_transport import owned_transport, frame
from test_personal_actor_target_observer_runtime import observation_runtime


def incoming(tmp_path, monkeypatch, kind='note'):
    service, peer, channel, registry, handle, events = owned_transport(
        tmp_path, monkeypatch, deletions=True, skip_deletions=False)
    service.start_personal_actor(registry, handle)
    request = {'format': 3, 'run_id': handle.actor_id, 'trigger': 'manual', 'modules': ['notes', 'tasks']}
    service._payload(peer, channel, actor.wire_message(frame('personal_sync.request', request), handle.actor_id))
    channel.sent.clear()
    proposal = {'proposal_id': str(uuid.uuid4()), 'kind': kind, 'id': 'outside-native-target',
        'parent_id': 'outside-native-parent' if kind == 'attachment' else '',
        'prior_hash': 'a' * 64, 'clock': [{'actor_id': peer['device_id'], 'counter': 1}],
        'deleted_ms': 1, 'label': 'Synthetic target'}
    body = {'format': 1, 'run_id': handle.actor_id, 'proposal_batch_id': str(uuid.uuid4()),
        'sequence': 0, 'last': True, 'proposals': [proposal]}
    wire = actor.wire_message(frame('personal_sync.deletion_proposals', body), handle.actor_id)
    return service, peer, channel, registry, handle, events, wire


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
def test_authenticated_offscope_frame_has_private_origin_but_no_data_save_or_ack_right(tmp_path, monkeypatch, kind):
    service, peer, channel, registry, handle, events, wire = incoming(tmp_path, monkeypatch, kind)
    before = registry.status(handle)
    queue = service.store.pending(peer['device_id'])
    service._payload(peer, channel, wire)
    received = service.read_personal_actor_incoming_target_frames(registry, handle)
    assert received == [wire]
    received[0]['body']['body']['proposals'][0]['label'] = 'Changed caller copy'
    assert service.read_personal_actor_incoming_target_frames(registry, handle) == [wire]
    assert registry.status(handle) == before
    assert service.store.pending(peer['device_id']) == queue
    assert not channel.sent and not events
    with pytest.raises(KeyError): registry.read(handle, wire['message_id'])
    assert not service.personal_actor_admissions[handle.actor_id].get('commit_plan')


def test_raw_registry_bytes_do_not_establish_authenticated_incoming_origin(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events, wire = incoming(tmp_path, monkeypatch)
    registry.put(handle, wire)
    with pytest.raises(PermissionError): service.read_personal_actor_incoming_target_frames(registry, handle)
    assert not channel.sent and not events


@pytest.mark.parametrize('gate', ['foreign-channel', 'foreign-key', 'foreign-peer', 'expired-frame', 'future-frame', 'no-run'])
def test_unauthenticated_or_invalid_incoming_cannot_create_origin(tmp_path, monkeypatch, gate):
    service, peer, channel, registry, handle, events, wire = incoming(tmp_path, monkeypatch)
    sender, transport = copy.deepcopy(peer), channel
    if gate == 'foreign-channel': transport = object()
    elif gate == 'foreign-key': sender['static_public'] = 'foreign'
    elif gate == 'foreign-peer': sender['device_id'] = str(uuid.uuid4())
    elif gate == 'expired-frame': wire['expires_ms'] = wire['created_ms'] - 1
    elif gate == 'future-frame':
        wire['created_ms'] += 600000; wire['expires_ms'] += 600000
    else:
        service.personal_actor_admissions.clear()
    service._payload(sender, transport, wire)
    if handle is not None:
        with pytest.raises((PermissionError, ValueError)): service.read_personal_actor_incoming_target_frames(registry, handle)
    assert not channel.sent and not events


@pytest.mark.parametrize('gate', ['foreign-owner', 'cancelled', 'channel', 'local-grant', 'remote-grant',
    'skip-deletions', 'wall-ttl', 'monotonic-ttl', 'quarantine-wall-ttl', 'quarantine-monotonic-ttl'])
def test_origin_read_requires_the_same_live_native_owner_and_consent(tmp_path, monkeypatch, gate):
    service, peer, channel, registry, handle, events, wire = incoming(tmp_path, monkeypatch)
    service._payload(peer, channel, wire)
    assert service.read_personal_actor_incoming_target_frames(registry, handle) == [wire]
    if gate == 'foreign-owner': handle = ActorHandle(handle.actor_id, 'f' * 64)
    elif gate == 'cancelled': service.cancel_personal_actor(registry, handle, notify=False)
    elif gate == 'channel': service.connections.clear()
    elif gate == 'local-grant': peer['local_grants']['grants']['personal_deletions_sync'] = False
    elif gate == 'remote-grant': peer['grants']['grants']['personal_deletions_sync'] = False
    elif gate == 'skip-deletions': service.store.change_shared_setting(peer['device_id'], peer['static_public'], 'skip_deletions', True)
    elif gate == 'wall-ttl': registry.clock = lambda: 10 ** 18
    elif gate == 'monotonic-ttl': registry.monotonic_clock = lambda: 10 ** 18
    elif gate == 'quarantine-wall-ttl':
        now = registry.clock(); registry.clock = lambda: now + 30001
    else:
        now = registry.monotonic_clock(); registry.monotonic_clock = lambda: now + 30001
    with pytest.raises((PermissionError, ValueError)): service.read_personal_actor_incoming_target_frames(registry, handle)
    assert not channel.sent and not events


def test_partial_group_is_not_a_review_and_changed_duplicates_cannot_replace_origin(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events, wire = incoming(tmp_path, monkeypatch)
    first = copy.deepcopy(wire); first['body']['body']['last'] = False
    service._payload(peer, channel, first)
    with pytest.raises(PermissionError): service.read_personal_actor_incoming_target_frames(registry, handle)
    second = copy.deepcopy(wire); second['message_id'] = str(uuid.uuid4())
    second['body']['body']['sequence'] = 1
    second['body']['body']['proposals'][0]['proposal_id'] = str(uuid.uuid4())
    second['body']['body']['proposals'][0]['id'] = 'second-outside-target'
    service._payload(peer, channel, second)
    assert service.read_personal_actor_incoming_target_frames(registry, handle) == [first, second]
    service._payload(peer, channel, first)  # exact retransmission is harmless
    assert service.read_personal_actor_incoming_target_frames(registry, handle) == [first, second]
    changed = copy.deepcopy(first); changed['body']['body']['proposals'][0]['prior_hash'] = 'b' * 64
    service._payload(peer, channel, changed)
    with pytest.raises(PermissionError): service.read_personal_actor_incoming_target_frames(registry, handle)
    assert not channel.sent and not events


@pytest.mark.parametrize('state', ['missing', 'expired', 'finished'])
def test_a_retired_native_request_cannot_keep_an_origin_alive(tmp_path, monkeypatch, state):
    service, peer, channel, registry, handle, events, wire = incoming(tmp_path, monkeypatch)
    service._payload(peer, channel, wire)
    assert service.read_personal_actor_incoming_target_frames(registry, handle) == [wire]
    stored = service.store._personal_run_record(actor.storage_peer(handle.actor_id), handle.actor_id)
    if state == 'missing': stored = None
    elif state == 'expired': stored['expires_ms'] = registry.clock() - 1
    else: stored['finished_ms'] = registry.clock()
    monkeypatch.setattr(service.store, '_personal_run_record', lambda *_: stored)
    with pytest.raises(PermissionError): service.read_personal_actor_incoming_target_frames(registry, handle)
    assert not channel.sent and not events


def test_retransmission_does_not_extend_the_original_origin_deadline(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events, wire = incoming(tmp_path, monkeypatch)
    wall, mono = registry.clock(), registry.monotonic_clock()
    registry.clock = lambda: wall; registry.monotonic_clock = lambda: mono
    service._payload(peer, channel, wire)
    registry.clock = lambda: wall + 20000; registry.monotonic_clock = lambda: mono + 20000
    service._payload(peer, channel, wire)
    assert service.read_personal_actor_incoming_target_frames(registry, handle) == [wire]
    registry.clock = lambda: wall + 30000; registry.monotonic_clock = lambda: mono + 30000
    with pytest.raises(PermissionError): service.read_personal_actor_incoming_target_frames(registry, handle)
    assert not channel.sent and not events


def test_257_targets_retire_the_quarantine_instead_of_yielding_a_partial_review(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events, template = incoming(tmp_path, monkeypatch)
    before = registry.status(handle)
    for index in range(9):
        wire = copy.deepcopy(template); wire['message_id'] = str(uuid.uuid4())
        body = wire['body']['body']; body['sequence'] = index; body['last'] = index == 8
        proposals = []
        for offset in range(32 if index < 8 else 1):
            item = copy.deepcopy(template['body']['body']['proposals'][0])
            item['proposal_id'] = str(uuid.uuid4()); item['id'] = f'target-{index}-{offset}'
            proposals.append(item)
        body['proposals'] = sorted(proposals, key=lambda item: item['proposal_id'])
        service._payload(peer, channel, wire)
    with pytest.raises(PermissionError): service.read_personal_actor_incoming_target_frames(registry, handle)
    origin = service.personal_actor_admissions[handle.actor_id]['incoming_target_origin']
    assert origin['invalid'] and origin['targets'] == 256 and len(origin['frames']) == 8
    assert origin['bytes'] <= 1024 * 1024
    assert registry.status(handle) == before and not channel.sent and not events


def test_normal_content_targets_are_not_promoted_to_the_private_historical_origin(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events, wire = incoming(tmp_path, monkeypatch)
    wire['body']['body']['proposals'][0]['id'] = 'note-one'
    service._payload(peer, channel, wire)
    assert registry.read(handle, wire['message_id']) == wire
    with pytest.raises(PermissionError): service.read_personal_actor_incoming_target_frames(registry, handle)
    assert not channel.sent and not events


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
def test_native_review_joins_actual_received_origin_with_fresh_saved_target_observation(tmp_path, monkeypatch, kind):
    service, peer, channel, manifest, book, target, owner, read, snapshot, registry, handle = observation_runtime(tmp_path, monkeypatch, kind)
    service.start_personal_actor(registry, handle)
    request = {'format': 3, 'run_id': handle.actor_id, 'trigger': 'manual', 'modules': ['notes', 'tasks']}
    service._payload(peer, channel, actor.wire_message(frame('personal_sync.request', request), handle.actor_id))
    body = {'format': 1, 'run_id': handle.actor_id, 'proposal_batch_id': str(uuid.uuid4()),
        'sequence': 0, 'last': True, 'proposals': [dict(target, deleted_ms=1, label='Synthetic target')]}
    wire = actor.wire_message(frame('personal_sync.deletion_proposals', body), handle.actor_id)
    service._payload(peer, channel, wire); channel.sent.clear()
    before = registry.status(handle); original_book = copy.deepcopy(book); original_save = read()
    captures = []
    service.native_actor_producer_book = lambda: (captures.append(True), snapshot)[1]
    view = service.review_personal_actor_incoming_targets(registry, handle)
    assert view['targets'] == [target] and view['action_authorized'] is False
    choice = {'proposal_id': target['proposal_id'], 'decision': 'delete', 'expected_clock': target['clock'], 'confirm_conflict': True}
    draft = service.review_personal_actor_incoming_targets(registry, handle,
        expected_revision=view['revision'], choices=[choice])
    assert draft['action_authorized'] is False and draft['conflicts_explicitly_confirmed'] is True
    assert len(captures) == 2, 'Each native review/choice operation needs a fresh actual capture'
    assert registry.status(handle) == before and book == original_book and read() == original_save and not channel.sent
    assert 'incoming_target_review' not in service.personal_actor_admissions[handle.actor_id]
    # A completed review is not a retained book/observation authority.
    owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
    with pytest.raises(PermissionError): service.review_personal_actor_incoming_targets(registry, handle,
        expected_revision=view['revision'], choices=[choice])
