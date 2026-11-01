"""Bound saved/scope/queued-control evidence, using the actual native adapters."""
import copy
import sqlite3
import uuid

import pytest
from test_personal_actor_transport import owned_transport, frame
from magnolie_personal_actor_store import NativeBookOwnerScope
from magnolie_personal_actor_completion import DecisionAckCompletion
import magnolie_personal_actor as actor
import magnolie_content_scope as scope
import magnolie_telefon as phone


def fixture(tmp_path, monkeypatch, decision='delete', own_ack=False):
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
