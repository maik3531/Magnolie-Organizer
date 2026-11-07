"""New private source attempts preserve history, not phone recovery rights."""
import sqlite3
from hashlib import sha256
import threading

import pytest

from test_media_source_sender import offered,handshake,acceptance,request,saved,deliver
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_media_source import NativeMappedMediaSource
from magnolie_file_transfer import TransferError
from magnolie_media_retention import NativeMediaRetention


def original_bytes(h,sender):
    with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
        return db.execute('SELECT value FROM meta WHERE key=?',(sender._journal._key,)).fetchone()[0]


def retry(h,old,cached,previous=None,owner=None):
    return _NativeMediaSourceSender.retry(owner or h.source,cached.manifest.source_id,old.observation().version,previous)


def fresh_acceptance(sender,cached,offer):
    value=acceptance(sender,cached,offer)
    value['body']['acceptance_sha256']=sha256(('native-test-retry-acceptance/'+offer['message_id']).encode()).hexdigest()
    value['body']['destination_token']=sha256(('native-test-retry-destination/'+offer['message_id']).encode()).hexdigest()
    return value


def test_actual_private_retry_uses_new_offer_acceptance_and_empty_sent_state_without_mutating_original_exchange(source):
    h=source;old,cached,offer=offered(h);accepted=acceptance(old,cached,offer)
    deliver(h,old,accepted);deliver(h,old,request(accepted,cached));h.wire.receive()
    before=original_bytes(h,old);cache={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    new=retry(h,old,cached)
    try:
        handshake(h,new);fresh_offer=new.send_offer();assert h.wire.receive()==fresh_offer
        assert fresh_offer['message_id']!=offer['message_id'] and fresh_offer['body']==offer['body']
        state=new.observation().body
        assert state['phase']=='offer_sent' and state['sent_bits']==0 and state['acceptance'] is None and state['peer_saved'] is None
        with pytest.raises(TransferError,match='newer_attempt_held'):old.send_controls()
        fresh_accept=fresh_acceptance(new,cached,fresh_offer);deliver(h,new,fresh_accept)
        requested=request(fresh_accept,cached);deliver(h,new,requested);assert h.wire.receive()['body']['request_id']==requested['message_id']
        deliver(h,new,saved(fresh_accept,cached));assert new.observation().body['phase']=='peer_saved'
        assert original_bytes(h,old)==before and {p.name:p.read_bytes() for p in cached.directory.iterdir()}==cache
        assert len(new._journal.history().body['attempts'])==1
        with pytest.raises(TransferError,match='completed_held'):retry(h,old,cached,new._journal.history().version)
        assert not h.preferences.local_grant(True).grants.send_files
    finally:new.close();old.close()


def test_copied_old_acceptance_cannot_acknowledge_actual_new_retry_offer(source):
    h=source;old,cached,offer=offered(h);accepted=acceptance(old,cached,offer);deliver(h,old,accepted)
    before=original_bytes(h,old);new=retry(h,old,cached)
    try:
        handshake(h,new);new.send_offer();h.wire.receive()
        with pytest.raises(TransferError,match='acceptance_changed'):deliver(h,new,accepted)
        assert new.observation().body['phase']=='offer_sent' and new.observation().body['acceptance'] is None
        assert original_bytes(h,old)==before and cached.directory.exists()
    finally:new.close();old.close()


def test_new_retry_after_fresh_complete_native_repreparation_preserves_earlier_attempt_snapshot(source):
    h=source;old,cached,offer=offered(h);first=retry(h,old,cached)
    handshake(h,first);first.send_offer();h.wire.receive();head=first._journal.history();snapshot=head.body['attempts'][0]
    first.close();h.source.close();fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    try:
        fresh.reprepare(h.preferences.issue_action(),h.preferences.read(),h.association,h.record.protected_record_sha256,
            cached.manifest.source_id,cached._job_version)
        second=retry(h,old,cached,head.version,fresh)
        try:
            handshake(h,second);second.send_offer();h.wire.receive();history=second._journal.history().body
            assert len(history['attempts'])==2 and history['attempts'][0]==snapshot
            assert history['attempts'][1]['previous_head']==head.version
            assert history['attempts'][1]['record']['sent_bits']==0
        finally:second.close()
    finally:old.close();fresh.close()


def test_old_chunk_request_cannot_be_replayed_after_new_offer_with_reused_acceptance_identity(source):
    h=source;old,cached,offer=offered(h);accepted=acceptance(old,cached,offer)
    deliver(h,old,accepted);old_request=request(accepted,cached);deliver(h,old,old_request);h.wire.receive()
    new=retry(h,old,cached)
    try:
        handshake(h,new);fresh_offer=new.send_offer();h.wire.receive()
        # Fresh offer_id alone is insufficient: the chunk codec has no offer_id.
        # The synthetic peer attempts to reuse its old acceptance/token identity.
        with pytest.raises(TransferError,match='retry_acceptance_reused|request_changed'):
            deliver(h,new,acceptance(new,cached,fresh_offer))
            deliver(h,new,old_request)
    finally:new.close();old.close()


@pytest.mark.parametrize('earlier',['original','retry'])
@pytest.mark.parametrize('field',['acceptance_sha256','destination_token'])
def test_new_acceptance_must_not_reuse_either_identity_from_any_earlier_native_attempt(source,earlier,field):
    h=source;old,cached,offer=offered(h);original_accept=acceptance(old,cached,offer);deliver(h,old,original_accept)
    first=retry(h,old,cached);handshake(h,first);first_offer=first.send_offer();h.wire.receive()
    first_accept=fresh_acceptance(first,cached,first_offer);deliver(h,first,first_accept)
    head=first._journal.history();first.close();second=retry(h,old,cached,head.version)
    try:
        handshake(h,second);second_offer=second.send_offer();h.wire.receive()
        accepted=fresh_acceptance(second,cached,second_offer)
        accepted['body'][field]=(original_accept if earlier=='original' else first_accept)['body'][field]
        with pytest.raises(TransferError,match='retry_acceptance_reused'):deliver(h,second,accepted)
        assert second.observation().body['phase']=='offer_sent'
        assert second._journal.history().body['attempts'][0]==head.body['attempts'][0]
    finally:second.close();old.close()


@pytest.mark.parametrize('change',['original_version','head_version','metadata_owner'])
def test_retry_selection_requires_exact_original_and_prior_head_and_actual_live_preparation(source,change):
    h=source;old,cached,_=offered(h);first=retry(h,old,cached);handshake(h,first);first.send_offer();h.wire.receive()
    head=first._journal.history();first.close();fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    try:
        with pytest.raises(TransferError):
            _NativeMediaSourceSender.retry(fresh if change=='metadata_owner' else h.source,cached.manifest.source_id,
                'f'*64 if change=='original_version' else old.observation().version,'e'*64 if change=='head_version' else head.version)
        assert first._journal.history()==head and fresh._prepared=={}
    finally:old.close();fresh.close()


@pytest.mark.parametrize('change',['missing_retry','resealed_retry','missing_original','orphan_retry'])
def test_changed_complete_membership_holds_retry_before_output_without_repair(source,change):
    h=source;old,cached,_=offered(h);first=retry(h,old,cached);handshake(h,first);first.send_offer();h.wire.receive()
    key=first._journal._key
    with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
        if change=='missing_retry':db.execute('DELETE FROM meta WHERE key=?',(key,))
        elif change=='missing_original':db.execute('DELETE FROM meta WHERE key=?',(old._journal._key,))
        else:
            blob=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()[0]
            if change=='resealed_retry':
                plain=h.authority.protection.unseal(blob,key)
                db.execute('UPDATE meta SET value=? WHERE key=?',(h.authority.protection.seal(plain,key),key))
            else:db.execute('INSERT INTO meta VALUES(?,?)',(key[:-32]+'f'*32,blob))
    frames=h.wire.received
    try:
        with pytest.raises(TransferError,match='catalog'):first.send_controls()
        assert h.wire.received==frames and cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:first.close();old.close()


def test_actual_retry_capacity_preserves_all_eight_prior_attempt_snapshots_and_never_evicts(source):
    h=source;old,cached,_=offered(h);owner=h.source;head=None;snapshots=[];senders=[];owners=[]
    try:
        for index in range(8):
            # Each explicit retry gets a real new action/full original preparation,
            # not an artificial renewal of the first action's fixed deadline.
            owner.close();owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller);owners.append(owner)
            owner.reprepare(h.preferences.issue_action(),h.preferences.read(),h.association,h.record.protected_record_sha256,
                cached.manifest.source_id,cached._job_version)
            sender=retry(h,old,cached,None if head is None else head.version,owner);senders.append(sender)
            handshake(h,sender);sender.send_offer();h.wire.receive();head=sender._journal.history()
            assert head.body['attempts'][:-1]==snapshots
            snapshots=head.body['attempts'];assert len(snapshots)==index+1
            sender.close()
        owner.close();owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller);owners.append(owner)
        owner.reprepare(h.preferences.issue_action(),h.preferences.read(),h.association,h.record.protected_record_sha256,
            cached.manifest.source_id,cached._job_version)
        denied=retry(h,old,cached,head.version,owner);senders.append(denied);handshake(h,denied)
        with pytest.raises(TransferError,match='retry_capacity'):denied.send_offer()
        assert denied._journal.history()==head and len(head.body['attempts'])==8
    finally:
        old.close()
        for sender in senders:sender.close()
        for value in owners:value.close()


def test_retry_cannot_supersede_actual_blocked_original_socket_io_or_release_its_os_lane(source,monkeypatch):
    h=source;old,cached,offer=offered(h);accepted=acceptance(old,cached,offer);deliver(h,old,accepted)
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[];send=h.channel.send
    def blocked(message):
        if message.get('kind')=='file_transfer.chunk':entered.set();assert release.wait(8)
        return send(message)
    monkeypatch.setattr(h.channel,'send',blocked)
    requested=request(accepted,cached)
    def work():
        try:deliver(h,old,requested)
        except BaseException as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=work);worker.start();new=None
    try:
        assert entered.wait(5);new=retry(h,old,cached)
        with pytest.raises(TransferError,match='source_busy'):new.send_controls()
        assert new._journal.history() is None
        old.close();assert not ended.is_set()
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is None
    finally:release.set();worker.join(5);old.close();new and new.close()
    assert ended.is_set() and not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
    assert old.observation().body['pending_chunk'] is not None and old.observation().body['sent_bits']==0
    assert cached.directory.exists() and h.target.read_bytes()==b'hello'


def test_retry_completion_requires_distinct_retry_pins_instead_of_original_exchange_approval(source):
    from test_media_source_backup import open_backup
    from magnolie_media_source_backup import backup_prepared_source
    from magnolie_media_source_retirement import _NativeSourceRetirement
    h=source;old,cached,_=offered(h);new=retry(h,old,cached)
    try:
        handshake(h,new);offer=new.send_offer();h.wire.receive();accepted=fresh_acceptance(new,cached,offer)
        deliver(h,new,accepted);deliver(h,new,request(accepted,cached));h.wire.receive();deliver(h,new,saved(accepted,cached))
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            result=_NativeSourceRetirement(new,backups,version).run()
            assert result.body['format']==2 and result.body['exchange_version']==old.observation().version
            assert result.body['retry_version']==new.observation().version and result.body['retry_attempt_id']==new._journal._attempt
        assert not cached.directory.exists() and (cached.directory.parent/result.body['archive']).exists()
    finally:new.close();old.close()


def test_new_retry_head_fences_still_live_earlier_retry_without_inheriting_its_sent_bits(source):
    h=source;old,cached,_=offered(h);first=retry(h,old,cached);handshake(h,first)
    offer=first.send_offer();h.wire.receive();accepted=fresh_acceptance(first,cached,offer)
    deliver(h,first,accepted);deliver(h,first,request(accepted,cached));h.wire.receive()
    previous=first._journal.history();second=retry(h,old,cached,previous.version)
    try:
        handshake(h,second);second.send_offer();h.wire.receive()
        assert second._journal.history().body['attempts'][0]==previous.body['attempts'][0]
        assert second.observation().body['sent_bits']==0
        with pytest.raises(TransferError,match='retry_head_changed'):first.send_controls()
        assert second.observation().body['phase']=='offer_sent'
    finally:second.close();first.close();old.close()


@pytest.mark.parametrize('change',['consent','intent','cancel'])
def test_withdrawal_after_retry_intent_never_outputs_offer_or_loses_original_history(source,change):
    h=source;old,cached,_=offered(h);before=original_bytes(h,old);phases=[]
    def withdraw(phase):
        phases.append(phase)
        if phase=='source_offer_planned':
            if change=='consent':h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
            elif change=='intent':h.controller.change('enabled',False)
            else:new.close()
    new=_NativeMediaSourceSender.retry(h.source,cached.manifest.source_id,old.observation().version,boundary=withdraw)
    try:
        handshake(h,new)
        with pytest.raises(TransferError):new.send_offer()
        assert 'source_offer_output' not in phases and new.observation().body['phase']=='offer_planned'
        assert original_bytes(h,old)==before and cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:new.close();old.close()
