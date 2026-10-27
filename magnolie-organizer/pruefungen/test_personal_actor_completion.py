"""Closed data owners and separately bound, encrypted control metadata only."""
import copy
import sqlite3
import uuid

import pytest
from test_personal_actor_registry import fixture, RUN, MESSAGE
import magnolie_personal_actor as actor
import magnolie_personal_actor_store as registry


def completion_fixture(tmp_path):
    service, peer, events, source, clock, store, handle, data, current = fixture(tmp_path)
    store.put(handle, data)
    expected = '77777777-7777-4777-8777-777777777777'
    state = {'ready':True, 'lost':False, 'saved':False, 'put_calls':0, 'lose_on_post':False}
    def guard(operation, wire):
        if state['lost']: return False
        if not state['ready']: return None
        if operation == 'finish' and not state['saved']: return None
        if operation == 'put':
            state['put_calls'] += 1
            if state['lose_on_post'] and state['put_calls'] % 2 == 0: return False
            if wire['kind'] == actor.ACK_KIND and wire['body']['message_id'] != expected:
                raise ValueError('unexpected native completion control')
        return True
    control = {'type':'message', 'v':1, 'message_id':str(uuid.uuid4()), 'kind':actor.ACK_KIND,
        'created_ms':clock['now'], 'expires_ms':clock['now']+60000, 'body':actor.ack(RUN,expected)}
    return service, peer, events, source, clock, store, handle, data, current, state, guard, control


def test_completion_is_encrypted_metadata_and_never_reopens_data(tmp_path):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    with pytest.raises(PermissionError): store.read_completion_controls(handle)
    assert store.read(handle, MESSAGE) == data
    assert store.begin_completion(handle, guard)['phase'] == 'completion'
    assert store.begin_completion(handle, guard)['phase'] == 'completion'
    for action in (lambda:store.read(handle,MESSAGE),lambda:store.put(handle,data),lambda:store.require_current(handle)):
        with pytest.raises(PermissionError): action()
    assert store.read_completion_controls(handle) == []
    source['revision'] = 'b'*64
    assert store.put_completion_control(handle,control) is True
    assert store.put_completion_control(handle,control) is False
    assert store.read_completion_controls(handle) == [control]
    with sqlite3.connect(service.store.database_path) as db:
        sealed = db.execute('SELECT payload FROM personal_actor_completion_wire WHERE actor_id=?', (RUN,)).fetchone()[0]
    assert control['body']['message_id'].encode() not in sealed
    assert store.status(handle)['packets'] == 2
    # The packet was validated while fresh. Inspecting its recorded metadata
    # later does not revive an expired network frame or extend the owner lease.
    clock['now'] += 61000
    assert store.read_completion_controls(handle) == [control]
    with pytest.raises(ValueError): store.put_completion_control(handle,control)
    with pytest.raises(PermissionError): store.finish_completion(handle)
    state['saved'] = True
    assert store.finish_completion(handle)['phase'] == 'completed'
    assert store.finish_completion(handle)['phase'] == 'completed'
    with pytest.raises(PermissionError): store.read(handle,MESSAGE)
    assert not events and service.server is None


def test_completion_rejects_data_even_with_native_metadata_validator(tmp_path):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    store.begin_completion(handle,guard)
    with pytest.raises(ValueError): store.put_completion_control(handle,data)
    assert store.read_completion_controls(handle) == [] and store.status(handle)['phase'] == 'completion'
    changed = copy.deepcopy(control); changed['body']['message_id'] = str(uuid.uuid4())
    with pytest.raises(ValueError): store.put_completion_control(handle,changed)
    assert store.put_completion_control(handle,control)
    replacement = copy.deepcopy(control); replacement['body']['status'] = 'duplicate'
    with pytest.raises(ValueError): store.put_completion_control(handle,replacement)
    assert store.read_completion_controls(handle) == [control] and not events


def test_unready_scope_waits_but_lost_authority_cannot_reopen(tmp_path):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    store.begin_completion(handle,guard)
    state['ready'] = False
    with pytest.raises(PermissionError,match='not_ready'): store.put_completion_control(handle,control)
    assert store.status(handle)['phase'] == 'completion'
    state['ready'] = True
    assert store.put_completion_control(handle,control)
    state['lost'] = True
    with pytest.raises(PermissionError): store.read_completion_controls(handle)
    assert store.status(handle)['phase'] == 'cancelled'
    state['lost'] = False
    with pytest.raises(PermissionError): store.read_completion_controls(handle)
    with pytest.raises(PermissionError): store.read(handle,MESSAGE)
    assert not events


def test_metadata_postcheck_rolls_back_packet_and_irrevocably_retires(tmp_path):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    store.begin_completion(handle,guard); state['lose_on_post'] = True
    with pytest.raises(PermissionError): store.put_completion_control(handle,control)
    assert store.status(handle)['phase'] == 'cancelled'
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute('SELECT COUNT(*) FROM personal_actor_completion_wire').fetchone()[0] == 0
    state['lose_on_post'] = False
    with pytest.raises(PermissionError): store.put_completion_control(handle,control)
    assert not events


def test_wrong_owner_or_callback_cannot_steal_metadata_context(tmp_path):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    store.begin_completion(handle,guard)
    wrong = registry.ActorHandle(handle.actor_id,'0'*64)
    for action in (lambda:store.cancel(wrong),lambda:store.put_completion_control(wrong,control),lambda:store.read_completion_controls(wrong)):
        with pytest.raises(PermissionError): action()
    with pytest.raises(PermissionError): store.begin_completion(handle,lambda *_:True)
    assert store.put_completion_control(handle,control)
    assert store.read_completion_controls(handle) == [control] and not events


@pytest.mark.parametrize('field,delta', (('now',registry.LIFETIME_MS+1),('monotonic',registry.LIFETIME_MS+1),('now',-1),('monotonic',-1)))
def test_completion_lease_expiry_or_clock_rollback_never_authorizes_metadata(tmp_path,field,delta):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    store.begin_completion(handle,guard); clock[field] += delta
    with pytest.raises(PermissionError): store.read_completion_controls(handle)
    assert store.status(handle)['phase'] == 'cancelled' and not events


def test_completion_owner_counts_toward_active_capacity_and_cancel_releases_it(tmp_path):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    store.begin_completion(handle,guard)
    fingerprint = store.status(handle)['fingerprint']
    for _ in range(registry.MAX_ACTIVE-1): store.create(peer['device_id'],fingerprint,source['revision'])
    with pytest.raises(RuntimeError): store.create(peer['device_id'],fingerprint,source['revision'])
    assert store.cancel(handle)['phase'] == 'cancelled'
    store.create(peer['device_id'],fingerprint,source['revision'])
    assert not events


def test_restore_of_old_binding_does_not_revive_closed_data_owner(tmp_path):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    with sqlite3.connect(service.store.database_path) as db:
        original = db.execute('SELECT payload FROM personal_actor_context WHERE actor_id=?',(RUN,)).fetchone()[0]
    store.begin_completion(handle,guard)
    with sqlite3.connect(service.store.database_path) as db:
        db.execute('UPDATE personal_actor_context SET payload=? WHERE actor_id=?',(original,RUN))
    with pytest.raises(PermissionError): store.read(handle,MESSAGE)
    assert store.reap() == 1 and store.status(handle)['phase'] == 'cancelled'
    assert not events


def test_metadata_capability_does_not_survive_native_registry_replacement(tmp_path):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    store.begin_completion(handle,guard)
    reopened = registry.ActorStore(service.store,current,epoch=store.epoch,clock=lambda:clock['now'],monotonic_clock=lambda:clock['monotonic'])
    with pytest.raises(PermissionError): reopened.read_completion_controls(handle)
    assert reopened.status(handle)['phase'] == 'cancelled'
    with pytest.raises(PermissionError): store.put_completion_control(handle,control)
    assert not events
