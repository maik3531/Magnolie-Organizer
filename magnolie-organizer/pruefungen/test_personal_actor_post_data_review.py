"""Native late-decision/save-claim primitive, not frontend/controller or phone E2E."""
import copy
import uuid
import pytest
import magnolie_personal_actor as actor
import magnolie_content_scope as scope
from magnolie_personal_actor_decision_review import PostDataDecisionReview
from test_personal_actor_producer import fixture, prepare, native, tombstone, RUN, PEER, ACTOR
from test_personal_actor_transport import frame


def review_fixture(count=33):
    book, manifest = fixture(count)
    prepared = prepare(book, manifest)
    targets = [{key: copy.deepcopy(value[key]) for key in ('proposal_id', 'kind', 'id', 'parent_id', 'prior_hash', 'clock')}
        for body in prepared for value in body['proposals']]
    owner, read, snapshot = native(book)
    report_id = str(uuid.uuid4())
    report_ack = frame(actor.ACK_KIND, actor.ack(RUN, report_id))
    controls = []
    for body in prepared:
        decisions = [{'proposal_id': value['proposal_id'], 'decision': 'delete', 'expected_clock': copy.deepcopy(value['clock'])}
            for value in body['proposals']]
        controls.append(actor.wire_message(frame('personal_sync.deletion_decision', {
            'format': 1, 'run_id': RUN, 'decision_id': str(uuid.uuid4()), 'decisions': decisions}), RUN))
    state = {'authority': 'a' * 64, 'scope': manifest, 'controls': controls}
    review = PostDataDecisionReview(RUN, targets, manifest, report_id, report_ack,
        current_authority=lambda: state['authority'], current_scope=lambda: state['scope'], current_saved_book=read,
        persisted_controls=lambda: copy.deepcopy(state['controls']))
    return review, state, owner, read, snapshot, report_id, report_ack


def test_complete_native_review_has_separate_explicit_save_claim_and_no_ack_or_document_side_effect():
    review, state, owner, read, snapshot, _, _ = review_fixture()
    before = read()
    assert review.validate('handoff', None) is None
    reviewed = review.review()
    assert len(reviewed['decisions']) == 33 and not reviewed['book_persisted']
    claim = review.prepare_save(reviewed['revision'], 'b' * 64)
    assert read() == before and not claim['book_persisted']
    assert review.prepare_save(reviewed['revision'], 'b' * 64) == claim
    with pytest.raises(PermissionError): review.confirm_saved(claim['claim_token'])
    owner.record_saved('native-producer-fixture', True, 'b' * 64)
    assert review.validate('maintain', None) is None, 'In-flight matching SaveACK was falsely completed or retired'
    receipt = review.confirm_saved(claim['claim_token'])
    assert receipt['book_persisted'] and not receipt['phone_persisted']
    assert review.validate('handoff', None) is True
    assert review.confirm_saved(claim['claim_token']) == receipt
    with pytest.raises(ValueError): review.validate('send', state['controls'][0])


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'foreign', 'clock', 'frame-conflict', 'ordinary-data', 'scope', 'authority', 'writer'])
def test_full_review_rejects_partial_changed_or_unauthorized_evidence(fault):
    review, state, owner, read, snapshot, _, _ = review_fixture()
    if fault == 'missing': state['controls'].pop()
    elif fault == 'duplicate':
        duplicate = copy.deepcopy(state['controls'][0]); duplicate['message_id'] = str(uuid.uuid4()); state['controls'].append(duplicate)
    elif fault in ('foreign', 'clock'):
        body = state['controls'][0]['body']['body']
        if fault == 'foreign': body['decisions'][0]['proposal_id'] = str(uuid.uuid4())
        else: body['decisions'][0]['expected_clock'][0]['counter'] += 1
    elif fault == 'frame-conflict':
        changed = copy.deepcopy(state['controls'][0]); changed['body']['body']['decisions'][0]['decision'] = 'restore'; state['controls'].append(changed)
    elif fault == 'ordinary-data': state['controls'] = [actor.wire_message(frame('personal_sync.request', {'format': 3, 'run_id': RUN, 'trigger': 'manual', 'modules': ['notes']}), RUN)]
    elif fault == 'scope': state['scope'] = scope.create(['unexpected-parent'], [])
    elif fault == 'authority': state['authority'] = 'c' * 64
    else: owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
    with pytest.raises((PermissionError, ValueError)): review.review()
    assert review.saved is None and review.claim is None


@pytest.mark.parametrize('fault', ['token', 'revision', 'claim-hash', 'wrong-save', 'newer-writer', 'source-change'])
def test_save_claim_cannot_rebind_another_candidate_or_saved_observation(fault):
    review, state, owner, read, snapshot, _, _ = review_fixture()
    revision = review.review()['revision']
    claim = review.prepare_save(revision, 'b' * 64)
    if fault == 'revision':
        with pytest.raises(PermissionError): review.prepare_save('f' * 64, 'b' * 64)
    elif fault == 'claim-hash':
        with pytest.raises(PermissionError): review.prepare_save(revision, 'c' * 64)
    else:
        owner.record_saved('native-producer-fixture', True, 'c' * 64 if fault == 'wrong-save' else 'b' * 64)
        if fault == 'newer-writer':
            review.confirm_saved(claim['claim_token'])
            owner.record_saved('native-producer-fixture', True, 'b' * 64)
        if fault == 'source-change': state['authority'] = 'c' * 64
        with pytest.raises(PermissionError): review.confirm_saved('f' * 64 if fault == 'token' else claim['claim_token'])


def test_note_delete_review_accepts_only_derived_advanced_scope_not_original_or_unrelated_membership():
    manifest = scope.create(['gone'], [])
    book = {'notizen': [], 'aufgaben': [], 'personalSync': {'actor_id': ACTOR, 'counter': 1, 'peer_device_id': PEER,
        'entities': {'note\0gone': tombstone('note', 'gone')}}}
    target = {key: value for key, value in prepare(book, manifest)[0]['proposals'][0].items() if key not in ('deleted_ms', 'label')}
    owner, read, snapshot = native(book)
    report = str(uuid.uuid4())
    controls = [actor.wire_message(frame('personal_sync.deletion_decision', {'format': 1, 'run_id': RUN, 'decision_id': str(uuid.uuid4()),
        'decisions': [{'proposal_id': target['proposal_id'], 'decision': 'delete', 'expected_clock': target['clock']}]}), RUN)]
    state = {'scope': manifest}
    review = PostDataDecisionReview(RUN, [target], manifest, report, frame(actor.ACK_KIND, actor.ack(RUN, report)),
        current_authority=lambda: 'a' * 64, current_scope=lambda: state['scope'], current_saved_book=read, persisted_controls=lambda: controls)
    with pytest.raises(ValueError): review.review()
    state['scope'] = scope.create([], [], epoch=str(uuid.uuid4()), revision=review.before['revision'] + 1)
    assert review.review()['scope'] == state['scope']


@pytest.mark.parametrize('receipt', ['missing', 'wrong-report', 'wrong-run', 'rejected'])
def test_review_requires_exact_successful_ordinary_report_receipt(receipt):
    review, state, owner, read, snapshot, report_id, ack = review_fixture(1)
    if receipt == 'missing': ack = None
    elif receipt == 'wrong-report': ack['body']['message_id'] = str(uuid.uuid4())
    elif receipt == 'wrong-run': ack['body']['run_id'] = str(uuid.uuid4())
    else: ack['body'].update(status='rejected', error='temporary_failure')
    with pytest.raises(PermissionError):
        PostDataDecisionReview(RUN, review.targets, review.before, report_id, ack,
            current_authority=lambda: state['authority'], current_scope=lambda: state['scope'], current_saved_book=read,
            persisted_controls=lambda: state['controls'])


def test_review_save_and_handoff_use_actual_protected_registry_without_recursive_sql_reads(tmp_path):
    from test_mcp_phone import owned_service
    import magnolie_telefon as phone
    from magnolie_personal_actor_store import ActorStore
    review, state, owner, read, snapshot, _, _ = review_fixture()
    service, peer, events = owned_service(tmp_path)
    source = {'revision': 'a' * 64}
    store = ActorStore(service.store, lambda *_: source['revision'])
    handle = store.create(peer['device_id'], phone.fingerprint(phone.unb64(peer['static_public'], 32)), source['revision'], run_id=RUN)
    review.persisted_controls = lambda: store.read_completion_controls(handle)
    store.begin_decision_review(handle, review.validator)
    source['revision'] = 'b' * 64
    for control in state['controls']: assert store.put_completion_control(handle, control)
    claim = review.prepare_save(review.review()['revision'], 'b' * 64)
    owner.record_saved('native-producer-fixture', True, 'b' * 64)
    store.reap()  # Matching unconfirmed save waits rather than restoring data.
    assert store.status(handle)['phase'] == 'decision_review'
    review.confirm_saved(claim['claim_token'])
    changed = copy.deepcopy(state['controls'][0]); changed['message_id'] = str(uuid.uuid4())
    with pytest.raises(ValueError): store.put_completion_control(handle, changed)
    assert not store.put_completion_control(handle, state['controls'][0])
    def completion(operation, wire): return True  # Registry handoff only, not receipt acceptance.
    assert store.promote_decision_review(handle, review.validator, completion)['phase'] == 'completion'
    assert store.promote_decision_review(handle, review.validator, completion)['phase'] == 'completion'
    with pytest.raises(PermissionError): store.require_current(handle)
    assert not events and service.server is None


def test_native_source_change_while_reading_protected_controls_cannot_create_a_save_claim():
    review, state, owner, read, snapshot, _, _ = review_fixture(1)
    def changed():
        state['authority'] = 'b' * 64
        return copy.deepcopy(state['controls'])
    review.persisted_controls = changed
    with pytest.raises(PermissionError): review.review()
    assert review.claim is None and review.saved is None


def test_new_writer_observation_during_save_confirmation_cannot_rebind_the_claim():
    review, state, owner, read, snapshot, _, _ = review_fixture(1)
    claim = review.prepare_save(review.review()['revision'], 'b' * 64)
    owner.record_saved('native-producer-fixture', True, 'b' * 64)
    calls = [0]
    def changed():
        calls[0] += 1
        if calls[0] == 2: owner.record_saved('native-producer-fixture', True, 'b' * 64)
        return read()
    review.current_saved_book = changed
    with pytest.raises(PermissionError): review.confirm_saved(claim['claim_token'])
    assert review.saved is None
