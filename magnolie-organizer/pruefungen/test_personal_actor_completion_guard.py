"""Bound saved/scope/queued-control evidence, using the actual native adapters."""
import copy
import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from test_personal_actor_transport import owned_transport, frame
from magnolie_personal_actor_store import NativeBookOwnerScope
from magnolie_personal_actor_completion import DecisionAckCompletion
import magnolie_personal_actor as actor
import magnolie_content_scope as scope
import magnolie_telefon as phone


def fixture(tmp_path, monkeypatch, decision='delete', own_ack=False, admitted=False):
    book = NativeBookOwnerScope(); book.set_ready(True)
    provider = lambda:book.current('native-completion-profile',True)
    service, peer, channel, registry, handle, events = owned_transport(tmp_path,monkeypatch,
        deletions=True,skip_deletions=False,book_source=provider)
    fingerprint = phone.fingerprint(phone.unb64(peer['static_public'],32))
    private = actor.storage_peer(handle.actor_id)
    proposal = {'proposal_id':str(uuid.uuid4()),'kind':'note','id':'note-one','parent_id':'',
        'clock':[{'actor_id':peer['device_id'],'counter':2}],'prior_hash':'a'*64,'deleted_ms':0,'label':'Synthetic'}
    proposals = {'format':1,'run_id':handle.actor_id,'proposal_batch_id':str(uuid.uuid4()),'sequence':0,'last':True,'proposals':[proposal]}
    service.store.remember_personal_proposal_kinds(private,proposals,False)
    body = {'format':1,'run_id':handle.actor_id,'decision_id':str(uuid.uuid4()),'decisions':[
        {'proposal_id':proposal['proposal_id'],'decision':decision,'expected_clock':proposal['clock']}]}
    wire = service.store.queue(peer['device_id'],'personal_sync.deletion_decision',body,60000,actor_run_id=handle.actor_id)
    targets = service.store.personal_decision_targets(private,body,True)
    if admitted:
        service.start_personal_actor(registry,handle)
        channel.sent.clear()
    book.record_saved('native-completion-profile',True,'a'*64)
    binding = (peer['device_id'],peer['static_public'],id(channel))
    session = service.content_scope_sessions[channel]
    def current_scope():
        reference = session.current_reference(binding)
        return service.current_content_scope(peer['device_id'],peer['static_public'],reference)
    ack = frame(actor.ACK_KIND,actor.ack(handle.actor_id,wire['message_id']))
    completion = DecisionAckCompletion(handle.actor_id,targets,[wire],
        current_authority=lambda:service.current_actor_completion_authority(peer['device_id'],fingerprint),
        current_scope=current_scope,current_saved_book=lambda:book.save_state('native-completion-profile',True),
        persisted_controls=lambda:registry.read_completion_controls(handle),native_sent_acknowledgments=[ack] if own_ack else [])
    registry.begin_completion(handle,completion.validator)
    def advance(notes):
        updated = scope.advance(completion.before,notes,['task-one'])
        for part in scope.chunks(updated): session.receive(binding,part)
    return service,peer,channel,registry,handle,events,book,completion,ack,advance


def test_success_requires_fresh_expected_scope_and_durable_control(tmp_path,monkeypatch):
    service,peer,channel,registry,handle,events,book,completion,ack,advance = fixture(tmp_path,monkeypatch)
    with pytest.raises(PermissionError): registry.put_completion_control(handle,ack)
    with pytest.raises(PermissionError): registry.finish_completion(handle)
    advance([])
    with pytest.raises(PermissionError,match='not_persisted'): completion.record_persisted(ack)
    assert registry.put_completion_control(handle,ack)
    completion.record_persisted(ack)
    assert completion.summary() == {'expected':1,'received':1,'saved':1,'rejected':0}
    assert registry.finish_completion(handle)['phase'] == 'completed'
    with pytest.raises(PermissionError): registry.require_current(handle)
    assert not channel.sent and not events


def test_post_data_completion_pins_original_scope_when_peer_membership_already_advanced(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events, book, original, ack, advance = fixture(tmp_path, monkeypatch)
    advance([])
    book.record_saved('native-completion-profile', True, 'b' * 64)
    arguments = dict(current_authority=original.current_authority, current_scope=original.current_scope,
        current_saved_book=lambda: book.save_state('native-completion-profile', True), persisted_controls=lambda: [])
    # Current membership alone is not the pre-deletion target scope. The exact
    # accepted native before-scope must survive the separate late SaveACK.
    with pytest.raises(ValueError): DecisionAckCompletion(handle.actor_id, original.targets, list(original.queued_frames.values()), **arguments)
    pinned = DecisionAckCompletion(handle.actor_id, original.targets, list(original.queued_frames.values()), before_scope=original.before, **arguments)
    assert pinned.validate('begin', None) is True
    forged = scope.create(['note-one', 'unrelated-member'], ['task-one'])
    invalid = DecisionAckCompletion(handle.actor_id, original.targets, list(original.queued_frames.values()), before_scope=forged, **arguments)
    assert invalid.validate('begin', None) is False
    assert not channel.sent and not events


@pytest.mark.parametrize('gate',('foreign_scope','changed_book','changed_profile','partial_scope'))
def test_unrelated_native_changes_never_complete_a_saved_claim(tmp_path,monkeypatch,gate):
    service,peer,channel,registry,handle,events,book,completion,ack,advance = fixture(tmp_path,monkeypatch)
    if gate == 'foreign_scope': advance(['foreign-note'])
    elif gate == 'changed_book': book.record_saved('native-completion-profile',True,'b'*64)
    elif gate == 'changed_profile': book.invalidate()
    else:
        updated = scope.advance(completion.before,[f'note-{i:02}' for i in range(40)],['task-one'])
        service.content_scope_sessions[channel].receive((peer['device_id'],peer['static_public'],id(channel)),scope.chunks(updated,size=32)[0])
    with pytest.raises(PermissionError): registry.put_completion_control(handle,ack)
    assert completion.summary()['saved'] == 0
    with pytest.raises(PermissionError): registry.require_current(handle)
    assert not channel.sent and not events


def test_restore_that_preserves_membership_still_needs_exact_packet_persistence(tmp_path,monkeypatch):
    service,peer,channel,registry,handle,events,book,completion,ack,advance = fixture(tmp_path,monkeypatch,'restore')
    unrelated = copy.deepcopy(ack); unrelated['body']['message_id'] = str(uuid.uuid4())
    with pytest.raises(ValueError): registry.put_completion_control(handle,unrelated)
    assert registry.put_completion_control(handle,ack)
    completion.record_persisted(ack)
    assert registry.finish_completion(handle)['phase'] == 'completed' and not events


def test_temporary_remote_rejection_is_not_a_saved_receipt(tmp_path,monkeypatch):
    service,peer,channel,registry,handle,events,book,completion,ack,advance = fixture(tmp_path,monkeypatch)
    rejected = frame(actor.ACK_KIND,actor.ack(handle.actor_id,ack['body']['message_id'],'rejected','temporary_failure'))
    assert registry.put_completion_control(handle,rejected)
    completion.record_persisted(rejected)
    assert completion.summary()['saved'] == 0
    with pytest.raises(PermissionError): registry.finish_completion(handle)
    advance([])
    assert registry.put_completion_control(handle,ack)
    completion.record_persisted(ack)
    assert registry.finish_completion(handle)['phase'] == 'completed'
    assert not channel.sent and not events


def test_own_ack_needs_exact_native_send_and_protected_persistence(tmp_path,monkeypatch):
    service,peer,channel,registry,handle,events,book,completion,ack,advance = fixture(tmp_path,monkeypatch,own_ack=True)
    message_id = ack['body']['message_id']
    assert completion.expects_native_acknowledgment(message_id)
    assert not completion.expects_native_acknowledgment(str(uuid.uuid4()))
    with pytest.raises(ValueError): registry.check_completion(handle,'send',completion.queued_frames[message_id])
    with pytest.raises(PermissionError): registry.check_completion(handle,'send',ack)
    advance([])
    registry.check_completion(handle,'send',ack)
    with pytest.raises(PermissionError): registry.put_completion_control(handle,ack)
    with pytest.raises(PermissionError): completion.record_persisted(ack)
    forged = copy.deepcopy(ack); forged['message_id'] = str(uuid.uuid4())
    with pytest.raises(ValueError): completion.record_successful_acknowledgment_send(forged)
    assert completion.summary()['saved'] == 0
    # Marker contract only: this fixture does not perform channel I/O.
    completion.record_successful_acknowledgment_send(ack)
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("CREATE TRIGGER own_ack_failure BEFORE INSERT ON personal_actor_completion_wire BEGIN SELECT RAISE(ABORT,'synthetic own ACK write failure'); END")
    with pytest.raises(sqlite3.DatabaseError): registry.put_completion_control(handle,ack)
    with pytest.raises(PermissionError): completion.record_persisted(ack)
    with pytest.raises(PermissionError): registry.finish_completion(handle)
    with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER own_ack_failure')
    assert registry.put_completion_control(handle,ack)
    completion.record_persisted(ack)
    assert not registry.put_completion_control(handle,ack)
    completion.record_persisted(ack)
    assert completion.summary()['saved'] == 1
    assert registry.finish_completion(handle)['phase'] == 'completed'
    with pytest.raises(PermissionError): registry.require_current(handle)
    assert not channel.sent and not events


@pytest.mark.parametrize('gate',('authority','book','profile','scope'))
def test_changed_native_source_cannot_mark_own_ack_sent(tmp_path,monkeypatch,gate):
    service,peer,channel,registry,handle,events,book,completion,ack,advance = fixture(tmp_path,monkeypatch,own_ack=True)
    if gate != 'scope': advance([])
    if gate == 'authority': completion.current_authority = lambda:'b'*64
    elif gate == 'book': book.record_saved('native-completion-profile',True,'b'*64)
    elif gate == 'profile': book.invalidate()
    else: advance(['foreign-note'])
    with pytest.raises(PermissionError): completion.record_successful_acknowledgment_send(ack)
    assert completion.summary()['saved'] == 0 and not channel.sent and not events


def test_own_ack_restore_preserves_membership_and_direction(tmp_path,monkeypatch):
    service,peer,channel,registry,handle,events,book,completion,ack,advance = fixture(tmp_path,monkeypatch,'restore',own_ack=True)
    registry.check_completion(handle,'send',ack)
    completion.record_successful_acknowledgment_send(ack)
    registry.put_completion_control(handle,ack); completion.record_persisted(ack)
    assert registry.finish_completion(handle)['phase'] == 'completed'
    assert not channel.sent and not events


@pytest.mark.parametrize('own_first',(True,False))
def test_mixed_own_and_peer_receipts_require_both_exact_directions(tmp_path,monkeypatch,own_first):
    book = NativeBookOwnerScope(); book.set_ready(True)
    service,peer,channel,registry,handle,events = owned_transport(tmp_path,monkeypatch,
        deletions=True,skip_deletions=False,book_source=lambda:book.current('mixed-native-profile',True))
    vectors = json.loads((Path(__file__).resolve().parents[2]/'contracts/notes-actor-completion-scope.json').read_text())
    vector = next(value for value in vectors['cases'] if value['name']=='delete-parent-and-attachment')
    observed = {'scope':copy.deepcopy(vector['before'])}
    book.record_saved('mixed-native-profile',True,'a'*64)
    frames = [actor.wire_message(frame('personal_sync.deletion_decision',{
        'format':1,'run_id':handle.actor_id,'decision_id':str(uuid.uuid4()),'decisions':[decision]}),handle.actor_id)
        for decision in vector['decisions']]
    peer_ack = frame(actor.ACK_KIND,actor.ack(handle.actor_id,frames[0]['message_id']))
    own_ack = frame(actor.ACK_KIND,actor.ack(handle.actor_id,frames[1]['message_id']))
    completion = DecisionAckCompletion(handle.actor_id,vector['native_targets'],frames,
        current_authority=lambda:'a'*64,current_scope=lambda:observed['scope'],
        current_saved_book=lambda:book.save_state('mixed-native-profile',True),
        persisted_controls=lambda:registry.read_completion_controls(handle),native_sent_acknowledgments=[own_ack])
    registry.begin_completion(handle,completion.validator)
    with pytest.raises(ValueError): registry.check_completion(handle,'send',frames[1])
    registry.check_completion(handle,'send',frames[0])
    observed['scope'] = copy.deepcopy(vector['actual_after'])
    with pytest.raises(PermissionError): registry.put_completion_control(handle,own_ack)
    for own in (own_first,not own_first):
        wire = own_ack if own else peer_ack
        if own: completion.record_successful_acknowledgment_send(wire)
        assert registry.put_completion_control(handle,wire)
        completion.record_persisted(wire)
        if completion.summary()['saved']==1:
            with pytest.raises(PermissionError): registry.finish_completion(handle)
    assert completion.summary()=={'expected':2,'received':2,'saved':2,'rejected':0}
    assert registry.finish_completion(handle)['phase']=='completed'
    with pytest.raises(PermissionError): registry.require_current(handle)
    assert not channel.sent and not events


@pytest.mark.parametrize('after_native_send',(False,True))
def test_receive_peer_ack_cannot_attest_to_or_abort_native_ack_send(tmp_path,monkeypatch,after_native_send):
    service,peer,channel,registry,handle,events,book,completion,ack,advance = fixture(tmp_path,monkeypatch,own_ack=True,admitted=True)
    # Inject only the already native-bound completion into the real receive
    # lane; this is not a claim that its producer/controller is wired yet.
    service.personal_actor_admissions[handle.actor_id]['completion'] = completion
    advance([])
    if after_native_send: completion.record_successful_acknowledgment_send(ack)
    for status,error in [('accepted','none'),('duplicate','none'),('rejected','temporary_failure')]:
        peer_claim = frame(actor.ACK_KIND,actor.ack(handle.actor_id,ack['body']['message_id'],status,error))
        assert service._receive_personal_actor(peer,channel,peer_claim) is True
        assert completion.summary()['saved']==0 and registry.read_completion_controls(handle)==[]
        assert registry.status(handle)['phase']=='completion'
    if not after_native_send: completion.record_successful_acknowledgment_send(ack)
    assert registry.put_completion_control(handle,ack)
    completion.record_persisted(ack)
    assert registry.finish_completion(handle)['phase']=='completed'
    assert not channel.sent and not events


@pytest.mark.parametrize('fault', ['insert', 'proof_read', 'outbox'])
def test_actual_peer_ack_receive_sql_failure_retries_only_bounded_metadata_not_the_original_decision(tmp_path, monkeypatch, fault):
    service, peer, channel, registry, handle, events, book, completion, ack, advance = fixture(tmp_path, monkeypatch, admitted=True)
    admission = service.personal_actor_admissions[handle.actor_id]
    admission.update(completion=completion, save_receipt=copy.deepcopy(completion.saved_book), phone_data_persisted=True,
        completion_ids=set(), completion_native_acks={}, completion_deferred_controls={})
    advance([])
    sequence = book.save_state('native-completion-profile', True)['sequence']
    if fault == 'insert':
        with sqlite3.connect(service.store.database_path) as db:
            db.execute("CREATE TRIGGER peer_ack_receive_fault BEFORE INSERT ON personal_actor_completion_wire BEGIN SELECT RAISE(ABORT,'synthetic peer ACK receive ledger fault'); END")
    else:
        target, name = (completion, 'persisted_controls') if fault == 'proof_read' else (service.store, 'acknowledge')
        original = getattr(target, name); failed = [False]
        def fail_once(*args, **kwargs):
            if not failed[0]:
                failed[0] = True
                raise sqlite3.OperationalError('Synthetic peer ACK post-insert metadata failure')
            return original(*args, **kwargs)
        monkeypatch.setattr(target, name, fail_once)
    service._receive_personal_actor(peer, channel, ack)
    assert completion.summary()['saved'] == (1 if fault == 'outbox' else 0)
    assert registry.read_completion_controls(handle) == ([] if fault == 'insert' else [ack])
    assert not admission.get('phone_persisted')
    if fault == 'insert':
        with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER peer_ack_receive_fault')
    # The peer may already have durably completed its own ACK send. Requiring a
    # replay of the original decision is neither a native send proof nor safe
    # progress after the peer has closed its data lane.
    assert admission['completion_deferred_controls'].get(ack['message_id']) == ack
    state = service.advance_personal_actor_completion(registry, handle)
    assert state['phase'] == 'completed' and state['phone_persisted']
    assert state['deletion_completion'] == {'expected': 1, 'received': 1, 'saved': 1, 'rejected': 0}
    assert not admission['completion_deferred_controls'] and book.save_state('native-completion-profile', True)['sequence'] == sequence
    assert not channel.sent and not events


def test_peer_ack_sql_deferral_keeps_exact_identity_and_bounded_untrusted_metadata(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events, book, completion, ack, advance = fixture(tmp_path, monkeypatch, admitted=True)
    admission = service.personal_actor_admissions[handle.actor_id]
    admission.update(completion=completion, save_receipt=copy.deepcopy(completion.saved_book), phone_data_persisted=True,
        completion_ids=set(), completion_native_acks={})
    advance([])
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("CREATE TRIGGER peer_ack_bounded_fault BEFORE INSERT ON personal_actor_completion_wire BEGIN SELECT RAISE(ABORT,'synthetic bounded metadata fault'); END")
    for index in range(257):
        candidate = copy.deepcopy(ack); candidate['message_id'] = str(uuid.uuid4())
        service._receive_personal_actor(peer, channel, candidate)
    deferred = admission['completion_deferred_controls']
    assert len(deferred) == 256 and sum(len(phone.canonical(value)) for value in deferred.values()) <= 1024 * 1024
    retained = copy.deepcopy(next(iter(deferred.values())))
    changed = copy.deepcopy(retained); changed['body']['status'] = 'duplicate'
    service._receive_personal_actor(peer, channel, changed)
    assert deferred[retained['message_id']] == retained and len(deferred) == 256
    foreign = copy.deepcopy(ack); foreign['body']['message_id'] = str(uuid.uuid4())
    service._receive_personal_actor(peer, channel, foreign)
    assert len(deferred) == 256 and completion.summary()['saved'] == 0 and registry.read_completion_controls(handle) == []
    with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER peer_ack_bounded_fault')
    assert not channel.sent and not events


def test_deferred_peer_ack_sql_retry_still_requires_original_native_writer_and_source(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events, book, completion, ack, advance = fixture(tmp_path, monkeypatch, admitted=True)
    admission = service.personal_actor_admissions[handle.actor_id]
    admission.update(completion=completion, save_receipt=copy.deepcopy(completion.saved_book), phone_data_persisted=True,
        completion_ids=set(), completion_native_acks={})
    advance([])
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("CREATE TRIGGER peer_ack_source_fault BEFORE INSERT ON personal_actor_completion_wire BEGIN SELECT RAISE(ABORT,'synthetic metadata source fault'); END")
    service._receive_personal_actor(peer, channel, ack)
    with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER peer_ack_source_fault')
    assert admission['completion_deferred_controls'][ack['message_id']] == ack
    book.record_saved('native-completion-profile', True, 'b' * 64)
    with pytest.raises(PermissionError): service.advance_personal_actor_completion(registry, handle)
    assert completion.summary()['saved'] == 0 and not admission.get('phone_persisted')
    assert registry.status(handle)['phase'].startswith('cancelled')
    assert not channel.sent and not events


def test_peer_ack_database_begin_failure_cannot_defer_a_known_premature_result_scope(tmp_path, monkeypatch):
    from contextlib import contextmanager
    service, peer, channel, registry, handle, events, book, completion, ack, advance = fixture(tmp_path, monkeypatch, admitted=True)
    admission = service.personal_actor_admissions[handle.actor_id]
    admission.update(completion=completion, completion_deferred_controls={})
    assert completion.validate('put', ack) is None  # Known before-scope, not missing GUI writer proof.
    original_database = registry._database
    @contextmanager
    def short_busy_timeout():
        with original_database() as db:
            db.execute('PRAGMA busy_timeout=1')
            yield db
    monkeypatch.setattr(registry, '_database', short_busy_timeout)
    # Actual SQLite BEGIN failure occurs before the registry's completion guard.
    with sqlite3.connect(service.store.database_path) as blocker:
        blocker.execute('BEGIN IMMEDIATE')
        service._receive_personal_actor(peer, channel, ack)
        blocker.rollback()
    assert admission['completion_deferred_controls'] == {}
    assert registry.read_completion_controls(handle) == [] and completion.summary()['saved'] == 0
    assert not channel.sent and not events


def test_peer_ack_pending_sql_retry_does_not_attempt_to_resend_the_original_decision(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events, book, completion, ack, advance = fixture(tmp_path, monkeypatch, admitted=True)
    admission = service.personal_actor_admissions[handle.actor_id]
    original = copy.deepcopy(next(iter(completion.queued_frames.values())))
    admission.update(completion=completion, save_receipt=copy.deepcopy(completion.saved_book), phone_data_persisted=True,
        completion_ids={original['message_id']}, completion_native_acks={})
    advance([])
    attempts = []
    native_send = service._send_personal_actor_queued
    admission['outbound'].add(original['message_id'])
    monkeypatch.setattr(service.store, 'pending', lambda *args, **kwargs: [original])  # Native due-list fixture, not a wire-send claim.
    monkeypatch.setattr(service, '_send_personal_actor_queued', lambda *args, **kwargs: attempts.append(args) or False)
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("CREATE TRIGGER peer_ack_still_blocked BEFORE INSERT ON personal_actor_completion_wire BEGIN SELECT RAISE(ABORT,'synthetic persistent receipt fault'); END")
    try:
        service._receive_personal_actor(peer, channel, ack)
        def no_original_outbox_reentry(*args, **kwargs): raise AssertionError('Pending peer ACK re-entered original decision outbox send')
        monkeypatch.setattr(service.store, 'outbox_message', no_original_outbox_reentry)
        assert native_send(channel, peer['device_id'], original) is False
        state = service.advance_personal_actor_completion(registry, handle)
        assert state['phase'] == 'completion' and not state['phone_persisted']
        assert admission['completion_deferred_controls'][ack['message_id']] == ack
        assert not attempts, 'Pending receipt metadata retried an already acknowledged original decision'
    finally:
        with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER peer_ack_still_blocked')
    assert not channel.sent and not events


@pytest.mark.parametrize('fault',('none','send','metadata','post_send_book','scope_wait','missing_data_receipt','expired'))
def test_native_ack_dispatch_uses_real_channel_return_and_protected_write(tmp_path,monkeypatch,fault):
    service,peer,channel,registry,handle,events,book,completion,ack,advance = fixture(tmp_path,monkeypatch,own_ack=True,admitted=True)
    admission = service.personal_actor_admissions[handle.actor_id]
    admission.update(completion=completion,save_receipt=copy.deepcopy(completion.saved_book),phone_data_persisted=True,
        completion_native_acks={ack['message_id']:copy.deepcopy(ack)})
    if fault!='scope_wait': advance([])
    original = channel.send
    failures = [fault=='send']
    def send(wire):
        assert not service.lock._is_owned()
        if failures[0]:
            failures[0]=False
            raise OSError('Synthetic actual ACK channel failure')
        original(wire)
        if fault=='post_send_book': book.record_saved('native-completion-profile',True,'b'*64)
    channel.send = send
    if fault=='metadata':
        with sqlite3.connect(service.store.database_path) as db:
            db.execute("CREATE TRIGGER dispatch_ack_failure BEFORE INSERT ON personal_actor_completion_wire BEGIN SELECT RAISE(ABORT,'synthetic dispatch ACK persistence failure'); END")
    if fault=='missing_data_receipt': admission['phone_data_persisted']=False
    if fault=='expired': monkeypatch.setattr(phone,'now_ms',lambda:ack['expires_ms']+1)
    if fault in ('send','metadata'):
        with pytest.raises(OSError if fault=='send' else sqlite3.DatabaseError): service.advance_personal_actor_completion(registry,handle)
        assert completion.summary()['saved']==0 and not admission.get('phone_persisted')
        assert registry.read_completion_controls(handle)==[]
        if fault=='metadata':
            with sqlite3.connect(service.store.database_path) as db: db.execute('DROP TRIGGER dispatch_ack_failure')
        sent = len(channel.sent)
        service.advance_personal_actor_completion(registry,handle)
        assert len(channel.sent)==sent, 'Immediate retry bypassed native ACK backoff'
        admission['completion_native_ack_next']=0
    elif fault in ('post_send_book','expired'):
        service.advance_personal_actor_completion(registry,handle)
        assert completion.summary()['saved']==0 and not admission.get('phone_persisted')
        assert registry.status(handle)['phase']=='cancelled'
        with sqlite3.connect(service.store.database_path) as db:
            assert db.execute('SELECT COUNT(*) FROM personal_actor_completion_wire').fetchone()[0]==0
        assert len(channel.sent)==(1 if fault=='post_send_book' else 0) and not events
        return
    elif fault in ('scope_wait','missing_data_receipt'):
        service.advance_personal_actor_completion(registry,handle)
        assert not channel.sent and completion.summary()['saved']==0
        if fault=='scope_wait': advance([])
        else: admission['phone_data_persisted']=True
        admission['completion_native_ack_next']=0
    result = service.advance_personal_actor_completion(registry,handle)
    assert result['phase']=='completed' and admission['phone_persisted'] is True
    assert completion.summary()['saved']==1 and registry.read_completion_controls(handle)==[ack]
    assert all(wire==ack for wire in channel.sent) and not admission['completion_native_acks']
    assert book.save_state('native-completion-profile',True)==completion.saved_book and not events


def test_native_ack_partial_claim_retries_only_unsent_frame_and_fences_reentry(tmp_path,monkeypatch):
    book=NativeBookOwnerScope(); book.set_ready(True)
    service,peer,channel,registry,handle,events=owned_transport(tmp_path,monkeypatch,
        deletions=True,skip_deletions=False,book_source=lambda:book.current('partial-native-profile',True))
    service.start_personal_actor(registry,handle); channel.sent.clear()
    admission=service.personal_actor_admissions[handle.actor_id]
    fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32))
    targets=[]; frames=[]; acks=[]
    for kind,identifier in [('note','note-one'),('task','task-one')]:
        proposal=str(uuid.uuid4()); clock=[{'actor_id':peer['device_id'],'counter':2}]
        targets.append({'proposal_id':proposal,'kind':kind,'id':identifier,'parent_id':'','prior_hash':'a'*64,'clock':clock})
        wire=actor.wire_message(frame('personal_sync.deletion_decision',{'format':1,'run_id':handle.actor_id,
            'decision_id':str(uuid.uuid4()),'decisions':[{'proposal_id':proposal,'decision':'restore','expected_clock':clock}]}),handle.actor_id)
        frames.append(wire); acks.append(frame(actor.ACK_KIND,actor.ack(handle.actor_id,wire['message_id'])))
    book.record_saved('partial-native-profile',True,'a'*64)
    session=service.content_scope_sessions[channel]
    def current_scope():
        reference=session.current_reference((peer['device_id'],peer['static_public'],id(channel)))
        return service.current_content_scope(peer['device_id'],peer['static_public'],reference)
    completion=DecisionAckCompletion(handle.actor_id,targets,frames,
        current_authority=lambda:service.current_actor_completion_authority(peer['device_id'],fingerprint),current_scope=current_scope,
        current_saved_book=lambda:book.save_state('partial-native-profile',True),persisted_controls=lambda:registry.read_completion_controls(handle),
        native_sent_acknowledgments=acks)
    registry.begin_completion(handle,completion.validator)
    admission.update(completion=completion,save_receipt=copy.deepcopy(completion.saved_book),phone_data_persisted=True,
        completion_native_acks={wire['message_id']:copy.deepcopy(wire) for wire in acks})
    original=channel.send; calls=[]
    def send(wire):
        assert not service.lock._is_owned()
        calls.append(wire['message_id'])
        if len(calls)==1:
            # Reentrant due processing cannot claim the same private ACK queue.
            assert service.advance_personal_actor_completion(registry,handle)['phase']=='completion'
        if len(calls)==2: raise OSError('Synthetic second ACK flush failure')
        original(wire)
    channel.send=send
    with pytest.raises(OSError): service.advance_personal_actor_completion(registry,handle)
    assert completion.summary()['saved']==1 and registry.read_completion_controls(handle)==[acks[0]]
    assert list(admission['completion_native_acks'])==[acks[1]['message_id']] and channel.sent==[acks[0]]
    service.advance_personal_actor_completion(registry,handle)
    assert len(calls)==2, 'Immediate partial retry bypassed backoff'
    admission['completion_native_ack_next']=0
    assert service.advance_personal_actor_completion(registry,handle)['phase']=='completed'
    assert calls==[acks[0]['message_id'],acks[1]['message_id'],acks[1]['message_id']]
    assert channel.sent==acks and completion.summary()['saved']==2
    assert book.save_state('partial-native-profile',True)==completion.saved_book and not events
