"""Real native owner/source gates; observations never admit data or wire actions."""
import copy
import json

import pytest
import magnolie_content_scope as scope
import magnolie_personal_actor as actor
import magnolie_shared_sync as shared
import magnolie_personal_sync as personal
from magnolie_personal_actor_store import ActorHandle
from test_personal_actor_source import actor_source_fixture
from test_personal_actor_producer import native
from test_personal_actor_incoming_target_evidence import live_fixture
from test_shared_sync_transport import message


def observation_runtime(tmp_path, monkeypatch, kind, pending=False, source_fixture=None):
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    for side in ('local_grants', 'grants'):
        peer[side]['grants']['personal_deletions_sync'] = True
    service.note_controls[channel]['grants.update'] = copy.deepcopy(peer['grants'])
    setting = service.store.change_shared_setting(peer['device_id'], peer['static_public'], 'skip_deletions', False)
    service._payload(peer, channel, message(shared.merge(shared.create(peer['device_id']), setting,
        peer['device_id'], service.store.identity['device_id'])))
    if source_fixture is None:
        _, _, book, target, key, _ = live_fixture(kind)
    else:
        book, target = copy.deepcopy(source_fixture['book']), copy.deepcopy(source_fixture['target'])
        key = kind + '\0' + target['id']
        meta = book['personalSync']['entities'][key]
        meta['proposal_id'] = personal.deletion_proposal_id(peer['device_id'], kind, target['id'], '', meta['clock'], meta['prior_hash'])
    book['personalSync']['peer_device_id'] = peer['device_id']
    book['personalSync']['entities'][key]['peer_device_id'] = peer['device_id']
    if pending:
        meta = book['personalSync']['entities'][key]
        meta.update(state='deleted', status='local_pending', hash='', prior_hash=target['prior_hash'], deleted_ms=2, label='Synthetic native pending')
        meta['proposal_id'] = personal.deletion_proposal_id(peer['device_id'], kind, target['id'], target['parent_id'], meta['clock'], target['prior_hash'])
        if kind == 'note': book['notizen'] = []
        elif kind == 'task': book['aufgaben'] = []
        else: book['notizen'][0]['anhaenge'] = []
    owner, read, snapshot = native(book)
    service.native_actor_book_source = lambda: owner.current('native-producer-fixture', True)
    service.native_actor_saved_book = read
    service.native_actor_producer_book = lambda: snapshot
    registry = service.personal_actor_registry()
    handle = registry.create(peer['device_id'], fingerprint, service.current_actor_source(peer['device_id'], fingerprint))
    return service, peer, channel, manifest, book, target, owner, read, snapshot, registry, handle


@pytest.mark.parametrize('kind', ['note', 'task', 'attachment'])
def test_native_controller_observes_exact_offscope_live_target_without_admitting_it(tmp_path, monkeypatch, kind):
    service, peer, channel, manifest, book, target, owner, read, snapshot, registry, handle = observation_runtime(tmp_path, monkeypatch, kind)
    before_book, before_saved = copy.deepcopy(book), read()
    before_wire, before_queue = copy.deepcopy(channel.sent), service.store.pending(peer['device_id'])
    captures = []
    service.native_actor_producer_book = lambda: (captures.append(True), snapshot)[1]
    result = service.observe_personal_actor_incoming_targets(registry, handle, [target])
    assert len(result) == 1 and result[0]['target'] == target
    assert result[0]['requires_conflict_choice'] is True
    assert len(captures) == 1, 'A bounded native observation must capture the whole book only once'
    assert 'PRIVATE' not in json.dumps(result)
    assert book == before_book and read() == before_saved
    assert channel.sent == before_wire and service.store.pending(peer['device_id']) == before_queue
    assert service.current_content_scope(peer['device_id'], peer['static_public'], scope.reference(manifest)) == manifest
    assert not service.personal_actor_admissions[handle.actor_id].get('producer_bodies')
    decision = {'format': 1, 'run_id': handle.actor_id, 'decision_id': handle.actor_id,
        'decisions': [{'proposal_id': target['proposal_id'], 'decision': 'delete', 'expected_clock': target['clock']}]}
    assert service.store.personal_decision_targets(actor.storage_peer(handle.actor_id), decision, True) is None
    result[0]['target']['prior_hash'] = 'f' * 64
    assert service.observe_personal_actor_incoming_targets(registry, handle, [target])[0]['target'] == target


@pytest.mark.parametrize('race', ['saved-after-capture', 'source-after-capture', 'duplicate-group'])
def test_operation_local_observation_has_no_partial_admission_after_a_race(tmp_path, monkeypatch, race):
    service, peer, channel, manifest, book, target, owner, read, snapshot, registry, handle = observation_runtime(tmp_path, monkeypatch, 'note')
    def capture():
        if race == 'saved-after-capture': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
        elif race == 'source-after-capture': service.connections.clear()
        return snapshot
    service.native_actor_producer_book = capture
    before_wire, before_queue = copy.deepcopy(channel.sent), service.store.pending(peer['device_id'])
    targets = [target, target] if race == 'duplicate-group' else [target]
    with pytest.raises((PermissionError, ValueError)):
        service.observe_personal_actor_incoming_targets(registry, handle, targets)
    assert channel.sent == before_wire and service.store.pending(peer['device_id']) == before_queue


@pytest.mark.parametrize('gate', ['foreign-owner', 'cancelled', 'wall-ttl', 'monotonic-ttl', 'local-grant',
    'remote-grant', 'skip-deletions', 'controls', 'channel', 'missing-snapshot', 'saved-mismatch', 'source-mismatch'])
def test_observation_requires_current_native_run_and_deletion_consent(tmp_path, monkeypatch, gate):
    service, peer, channel, manifest, book, target, owner, read, snapshot, registry, handle = observation_runtime(tmp_path, monkeypatch, 'note')
    if gate == 'foreign-owner': handle = ActorHandle(handle.actor_id, 'f' * 64)
    elif gate == 'cancelled': service.cancel_personal_actor(registry, handle)
    elif gate == 'wall-ttl': registry.clock = lambda: 10 ** 18
    elif gate == 'monotonic-ttl': registry.monotonic_clock = lambda: 10 ** 18
    elif gate == 'local-grant': peer['local_grants']['grants']['personal_deletions_sync'] = False
    elif gate == 'remote-grant': peer['grants']['grants']['personal_deletions_sync'] = False
    elif gate == 'skip-deletions': service.store.change_shared_setting(peer['device_id'], peer['static_public'], 'skip_deletions', True)
    elif gate == 'controls': service.note_controls[channel].pop('grants.update')
    elif gate == 'channel': service.connections.clear()
    elif gate == 'missing-snapshot': service.native_actor_producer_book = None
    elif gate == 'saved-mismatch': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
    elif gate == 'source-mismatch': service.native_actor_book_source = lambda: 'c' * 64
    before_wire, before_queue = copy.deepcopy(channel.sent), service.store.pending(peer['device_id'])
    with pytest.raises(PermissionError):
        service.observe_personal_actor_incoming_targets(registry, handle, [target])
    assert channel.sent == before_wire and service.store.pending(peer['device_id']) == before_queue


@pytest.mark.parametrize('count', [0, 257])
def test_invalid_group_capacity_is_rejected_before_native_book_capture(tmp_path, monkeypatch, count):
    service, peer, channel, manifest, book, target, owner, read, snapshot, registry, handle = observation_runtime(tmp_path, monkeypatch, 'note')
    captures = []
    service.native_actor_producer_book = lambda: (captures.append(True), snapshot)[1]
    with pytest.raises(ValueError, match='actor_target_capacity'):
        service.observe_personal_actor_incoming_targets(registry, handle, [target] * count)
    assert not captures
