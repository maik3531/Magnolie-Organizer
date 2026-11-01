"""Native registry capability transition only, not controller/save/E2E acceptance."""
import copy
import sqlite3
import pytest
import magnolie_personal_actor as actor
from magnolie_personal_actor_store import ActorHandle, ActorStore
from test_personal_actor_registry import fixture


def review_fixture(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    state = {'review': True, 'complete': True, 'handoff': None}
    def review(operation, value):
        if operation == 'handoff': return state['handoff']
        return state['review']
    def complete(operation, value): return state['complete']
    control = copy.deepcopy(wire)
    control['kind'] = actor.ACK_KIND
    control['body'] = actor.ack(handle.actor_id, wire['message_id'])
    control['message_id'] = '33333333-3333-4333-8333-333333333333'
    return service, source, clock, store, handle, wire, control, state, review, complete, current


def test_post_data_review_irrevocably_closes_data_but_accepts_only_guarded_metadata(tmp_path):
    service, source, clock, store, handle, wire, control, state, review, complete, current = review_fixture(tmp_path)
    assert store.begin_decision_review(handle, review)['phase'] == 'decision_review'
    source['revision'] = 'b' * 64  # Resultscope may legitimately replace original data source.
    for operation in (lambda: store.require_current(handle), lambda: store.put(handle, wire), lambda: store.read(handle, wire['message_id']),
                      lambda: store.begin_completion(handle, complete), lambda: store.finish_completion(handle),
                      lambda: store.check_completion(handle, 'send', control)):
        with pytest.raises(PermissionError): operation()
    assert store.put_completion_control(handle, control)
    assert not store.put_completion_control(handle, control)
    assert store.read_completion_controls(handle) == [control]
    with pytest.raises(ValueError): store.put_completion_control(handle, wire)
    store.reap()
    assert store.status(handle)['phase'] == 'decision_review'
    assert not service.server


def test_exact_native_handoff_waits_for_separate_saved_claim_and_retries_without_reopening_data(tmp_path):
    _, source, clock, store, handle, wire, control, state, review, complete, _ = review_fixture(tmp_path)
    store.begin_decision_review(handle, review)
    with pytest.raises(PermissionError): store.promote_decision_review(handle, review, complete)
    assert store.status(handle)['phase'] == 'decision_review'
    state['handoff'] = True
    assert store.promote_decision_review(handle, review, complete)['phase'] == 'completion'
    assert store.promote_decision_review(handle, review, complete)['phase'] == 'completion'
    with pytest.raises(PermissionError): store.promote_decision_review(handle, lambda *_: True, complete)
    assert store.promote_decision_review(handle, review, complete)['phase'] == 'completion'
    with pytest.raises(PermissionError): store.require_current(handle)


@pytest.mark.parametrize('fault', ['foreign', 'review-lost', 'new-owner-lost', 'sql', 'restart', 'wall', 'monotonic'])
def test_review_handoff_failures_never_restore_data_or_replace_legitimate_owner(tmp_path, fault):
    service, source, clock, store, handle, wire, control, state, review, complete, current = review_fixture(tmp_path)
    store.begin_decision_review(handle, review); state['handoff'] = True
    if fault == 'foreign':
        with pytest.raises(PermissionError): store.promote_decision_review(ActorHandle(handle.actor_id, 'f' * 64), review, complete)
        assert store.status(handle)['phase'] == 'decision_review'
    elif fault == 'restart':
        restarted = ActorStore(service.store, current, clock=lambda: clock['now'], monotonic_clock=lambda: clock['monotonic'])
        with pytest.raises(PermissionError): restarted.promote_decision_review(handle, review, complete)
    elif fault == 'sql':
        with sqlite3.connect(service.store.database_path) as db:
            db.execute("CREATE TRIGGER review_handoff_fault BEFORE INSERT ON personal_actor_context BEGIN SELECT RAISE(ABORT,'synthetic handoff SQL fault'); END")
        with pytest.raises(sqlite3.DatabaseError): store.promote_decision_review(handle, review, complete)
        with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER review_handoff_fault')
        assert store.status(handle)['phase'] == 'decision_review'
        assert store.completion_guards[handle.actor_id] is review
        assert store.promote_decision_review(handle, review, complete)['phase'] == 'completion'
    else:
        if fault == 'review-lost': state['handoff'] = False
        if fault == 'new-owner-lost': state['complete'] = False
        if fault == 'wall': clock['now'] += 10 ** 8
        if fault == 'monotonic': clock['monotonic'] += 10 ** 8
        with pytest.raises(PermissionError): store.promote_decision_review(handle, review, complete)
        assert store.status(handle)['phase'].startswith('cancelled')
    with pytest.raises(PermissionError): store.require_current(handle)


def test_review_owner_loss_during_new_validator_permanently_retires_the_run(tmp_path):
    _, source, clock, store, handle, wire, control, state, review, complete, _ = review_fixture(tmp_path)
    store.begin_decision_review(handle, review); state['handoff'] = True
    def changed(operation, value):
        state['handoff'] = False
        return True
    with pytest.raises(PermissionError): store.promote_decision_review(handle, review, changed)
    assert store.status(handle)['phase'].startswith('cancelled')
    with pytest.raises(PermissionError): store.require_current(handle)
