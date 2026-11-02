"""Native volatile data retirement is required; no document write/restore here."""
import pytest
from magnolie_personal_actor_store import ActorStore
from test_personal_actor_completion import completion_fixture


def test_historical_writer_gate_requires_real_current_volatile_retirement(tmp_path):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    with pytest.raises(PermissionError, match='not_retired'): store.check_historical_save(handle)
    store.require_current(handle)
    store.begin_completion(handle, guard)
    before = store.status(handle)
    store.check_historical_save(handle)
    assert store.status(handle) == before
    with pytest.raises(PermissionError): store.require_current(handle)
    # Even reinstalling a callback in a reopened registry cannot manufacture the
    # original live owner's volatile retirement evidence from sealed phase alone.
    reopened = ActorStore(service.store, current, epoch=store.epoch, clock=store.clock, monotonic_clock=store.monotonic_clock)
    reopened.completion_guards[handle.actor_id] = guard
    with pytest.raises(PermissionError, match='not_retired'): reopened.check_historical_save(handle)
    state['saved'] = True; store.finish_completion(handle)
    with pytest.raises(PermissionError, match='not_retired'): store.check_historical_save(handle)
    assert store.status(handle)['phase'] == 'completed' and not events


@pytest.mark.parametrize('fault', ['unready', 'lost-before', 'lost-after', 'wall', 'mono', 'cancelled'])
def test_historical_writer_gate_rechecks_fresh_native_save_guard_and_lifecycle(tmp_path, fault):
    service, peer, events, source, clock, store, handle, data, current, state, guard, control = completion_fixture(tmp_path)
    calls = []
    def native(operation, wire):
        if operation == 'save':
            calls.append(operation)
            if fault == 'lost-after' and len(calls) == 2: return False
        return guard(operation, wire)
    store.begin_completion(handle, native)
    if fault == 'unready': state['ready'] = False
    elif fault == 'lost-before': state['lost'] = True
    elif fault == 'wall': store.clock = lambda: 10 ** 18
    elif fault == 'mono': store.monotonic_clock = lambda: 10 ** 18
    elif fault == 'cancelled': store.cancel(handle)
    with pytest.raises(PermissionError): store.check_historical_save(handle)
    assert store.status(handle)['phase'] == ('completion' if fault == 'unready' else 'cancelled')
    if fault == 'lost-after': assert len(calls) == 2
    with pytest.raises(PermissionError): store.require_current(handle)
    assert not events
