"""Private native sender over actual encrypted sockets; no production release."""
import base64
from hashlib import sha256
import sqlite3
import threading
import uuid

import pytest

from test_media_source_cache import freeze
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_file_control import FileControlPacket,FileGrantState,KIND as CONTROL
from magnolie_file_transfer import TransferError
from magnolie_media_retention import NativeMediaRetention
from magnolie_telefon import now_ms


def message(kind,body,expires=None):
    at=now_ms()
    return dict(type='message',v=1,message_id=str(uuid.uuid4()),kind=kind,created_ms=at,
        expires_ms=expires or at+60000,body=body)


def deliver(h,sender,packet,*,controls=False):
    h.wire.send(packet);received=h.channel.receive()
    return sender.observe_controls(h.channel,received) if controls else sender.observe(h.channel,received)


def handshake(h,sender):
    first=sender.send_controls();assert h.wire.receive()==first
    local=FileControlPacket.parse(first['body'])
    remote=FileControlPacket(FileGrantState(1,'6'*64,False,True),'7'*64,1,local.challenge)
    deliver(h,sender,message(CONTROL,remote.wire()),controls=True)
    second=sender.send_controls();assert h.wire.receive()==second
    assert second['body']['echo']==remote.challenge


def offered(h,*,boundary=lambda _:None):
    cached=freeze(h);sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id,boundary=boundary)
    handshake(h,sender);offer=sender.send_offer();assert h.wire.receive()==offer
    return sender,cached,offer


def acceptance(sender,cached,offer):
    return message('file_transfer.accept',dict(format=1,offer_id=offer['message_id'],manifest_sha256=cached.manifest.fingerprint,
        transfer_id=cached.manifest.transfer_id,acceptance_sha256='8'*64,permission_epoch=sender._binding.permission_epoch,
        destination_token='9'*64),offer['expires_ms'])


def request(accepted,cached,index=0):
    body={key:value for key,value in accepted['body'].items() if key!='offer_id'}
    body.update(file_id=cached.manifest.files[0].id,chunk_index=index)
    return message('file_transfer.chunk.request',body,accepted['expires_ms'])


def saved(accepted,cached):
    body={key:value for key,value in accepted['body'].items() if key!='offer_id'}
    file=cached.manifest.files[0];body['receipts']=[dict(file_id=file.id,size=file.size,sha256=file.sha256,receipt_sha256='a'*64)]
    return message('file_transfer.saved',body,accepted['expires_ms'])


def test_actual_control_echo_offer_accept_chunk_and_peer_saved_are_correlated_without_native_saved_or_retirement(source):
    h=source;phases=[]
    sender,cached,offer=offered(h,boundary=phases.append)
    try:
        before=sender.observation();assert before.body['phase']=='offer_sent'
        accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
        requested=request(accepted,cached);deliver(h,sender,requested);chunk=h.wire.receive()
        assert chunk['body']['request_id']==requested['message_id']
        raw=base64.b64decode(chunk['body']['data_base64'],validate=True)
        assert raw==b'hello' and chunk['body']['data_sha256']==sha256(raw).hexdigest()
        deliver(h,sender,saved(accepted,cached));observation=sender.observation()
        assert observation.body['phase']=='peer_saved' and observation.body['sent_bits']==1
        assert not observation.grants_read_authority and not observation.is_saved_receipt and not observation.permits_retirement
        assert cached.directory.exists() and h.target.read_bytes()==b'hello'
        assert not h.preferences.local_grant(True).grants.send_files
        with pytest.raises(TransferError,match='existing_attempt_held'):_NativeMediaSourceSender(h.source,cached.manifest.source_id)
        assert phases==['source_offer_planned','source_offer_output','source_chunk_planned','source_chunk_output']
    finally:sender.close()


def test_positive_source_choices_and_sealed_cache_without_actual_control_output_echo_cannot_offer(source):
    h=source;cached=freeze(h);sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id)
    try:
        with pytest.raises(TransferError,match='control_agreement_required'):sender.send_offer()
        assert sender.observation() is None and h.wire.received==2 # Only prior shared-media settings/ACK.
        assert cached.directory.exists()
    finally:sender.close()


@pytest.mark.parametrize('change',['offer','epoch','channel'])
def test_wrong_offer_epoch_or_native_channel_cannot_open_chunk_authority(source,change):
    h=source;sender,cached,offer=offered(h)
    try:
        accepted=acceptance(sender,cached,offer)
        if change=='offer':accepted['body']['offer_id']=str(uuid.uuid4())
        elif change=='epoch':accepted['body']['permission_epoch']='b'*64
        with pytest.raises(TransferError):
            if change=='channel':sender.observe(object(),accepted)
            else:deliver(h,sender,accepted)
        assert sender.observation().body['phase']=='offer_sent'
        assert cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:sender.close()


def test_saved_before_any_actual_chunk_output_never_creates_completion_or_native_receipt(source):
    h=source;sender,cached,offer=offered(h)
    try:
        accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
        with pytest.raises(TransferError,match='saved_changed'):deliver(h,sender,saved(accepted,cached))
        assert sender.observation().body['phase']=='accepted' and sender.observation().body['sent_bits']==0
    finally:sender.close()


@pytest.mark.parametrize('phase',['source_offer_planned','source_chunk_planned'])
def test_cancellation_before_actual_wire_output_retains_pending_intent_without_output_completion_or_adoption(source,phase):
    h=source;cached=freeze(h)
    def cancel(current):
        if current==phase:sender.close()
    sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id,boundary=cancel)
    try:
        handshake(h,sender)
        if phase=='source_offer_planned':
            with pytest.raises(TransferError,match='sender_retired'):sender.send_offer()
            assert sender.observation().body['phase']=='offer_planned'
        else:
            offer=sender.send_offer();assert h.wire.receive()==offer
            accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
            with pytest.raises(TransferError,match='sender_retired'):deliver(h,sender,request(accepted,cached))
            body=sender.observation().body
            assert body['phase']=='accepted' and body['sent_bits']==0 and body['pending_chunk'] is not None
        assert cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:sender.close()


@pytest.mark.parametrize('change',['acceptance','member','index'])
def test_chunk_request_must_match_exact_acceptance_manifest_member_and_bounds(source,change):
    h=source;sender,cached,offer=offered(h)
    try:
        accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted);requested=request(accepted,cached)
        if change=='acceptance':requested['body']['acceptance_sha256']='b'*64
        elif change=='member':requested['body']['file_id']='c'*32
        else:requested['body']['chunk_index']=cached.manifest.files[0].chunks
        with pytest.raises(TransferError,match='request_changed'):deliver(h,sender,requested)
        body=sender.observation().body
        assert body['phase']=='accepted' and body['sent_bits']==0 and body['pending_chunk'] is None
    finally:sender.close()


def test_actual_local_consent_withdrawal_prevents_any_chunk_output_and_preserves_history(source):
    h=source;sender,cached,offer=offered(h)
    try:
        accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
        h.preferences.configure_sending(h.preferences.issue_action(),h.policy,photos=False,videos=False)
        with pytest.raises(TransferError,match='local_consent_required'):deliver(h,sender,request(accepted,cached))
        assert sender.observation().body['sent_bits']==0 and cached.directory.exists()
    finally:sender.close()


def test_missing_exchange_cannot_be_recreated_by_a_live_chunk_request(source):
    h=source;sender,cached,offer=offered(h)
    try:
        accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
        with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
            db.execute('DELETE FROM meta WHERE key=?',(sender._journal._key,))
        with pytest.raises(TransferError,match='catalog_membership_changed'):deliver(h,sender,request(accepted,cached))
        with pytest.raises(TransferError,match='catalog_membership_changed'):sender.observation()
        assert cached.directory.exists()
    finally:sender.close()


def test_failed_actual_offer_socket_output_never_marks_sent_and_cannot_adopt_pending_history(source,monkeypatch):
    h=source;cached=freeze(h);sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id)
    try:
        handshake(h,sender);send=h.channel.send
        def fail(packet):
            if packet.get('kind')=='file_transfer.offer':raise OSError('explicit native offer socket failure')
            return send(packet)
        monkeypatch.setattr(h.channel,'send',fail)
        with pytest.raises(OSError,match='socket failure'):sender.send_offer()
        assert sender.observation().body['phase']=='offer_planned'
        with pytest.raises(TransferError,match='existing_attempt_held'):_NativeMediaSourceSender(h.source,cached.manifest.source_id)
        assert cached.directory.exists()
    finally:sender.close()


def test_cancel_during_actual_chunk_output_retains_original_os_lane_until_output_drains(source,monkeypatch):
    h=source;sender,cached,offer=offered(h);entered=threading.Event();release=threading.Event();ended=threading.Event();results=[]
    accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted);requested=request(accepted,cached)
    send=h.channel.send
    def blocked(packet):
        if packet.get('kind')=='file_transfer.chunk':entered.set();assert release.wait(8)
        return send(packet)
    monkeypatch.setattr(h.channel,'send',blocked)
    def work():
        try:deliver(h,sender,requested)
        except BaseException as error:results.append(error)
        finally:ended.set()
    worker=threading.Thread(target=work);worker.start()
    try:
        assert entered.wait(5);sender.close();assert not ended.is_set()
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is None
    finally:release.set();worker.join(5);sender.close()
    assert ended.is_set() and not worker.is_alive() and len(results)==1 and isinstance(results[0],TransferError)
    # Bytes may have left the socket before cancellation drained. History must
    # conservatively retain pending intent, never assert completed output.
    assert h.wire.receive()['kind']=='file_transfer.chunk'
    body=sender.observation().body;assert body['sent_bits']==0 and body['pending_chunk'] is not None
    with NativeMediaRetention(h.authority.binding.native_directory) as retention:
        with retention.activity() as lease:assert lease is not None


def test_multichunk_requests_read_the_frozen_original_in_requested_order_and_keep_bytes_after_peer_saved(source):
    h=source;raw=(b'native frozen original bytes\x00'*3000)+b'end';h.target.write_bytes(raw)
    sender,cached,offer=offered(h)
    try:
        assert cached.manifest.files[0].chunks==2
        h.target.write_bytes(b'a subsequent local version is independent')
        accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted);chunks={}
        for index in (1,0):
            requested=request(accepted,cached,index);deliver(h,sender,requested);chunk=h.wire.receive()
            assert chunk['body']['chunk_index']==index and chunk['body']['request_id']==requested['message_id']
            chunks[index]=base64.b64decode(chunk['body']['data_base64'],validate=True)
        assert b''.join(chunks[index] for index in (0,1))==raw
        deliver(h,sender,saved(accepted,cached));observation=sender.observation()
        assert observation.body['phase']=='peer_saved' and observation.body['sent_bits']==3
        assert h.target.read_bytes()==b'a subsequent local version is independent'
        assert cached.directory.exists() and not observation.permits_retirement
    finally:sender.close()


def test_immediate_positive_acceptance_waits_for_actual_offer_output_completion_instead_of_being_discarded(source):
    h=source;cached=freeze(h);entered=threading.Event();release=threading.Event();accepted_ended=threading.Event()
    results=[];errors=[]
    def hold(phase):
        if phase=='source_offer_output':entered.set();assert release.wait(8)
    sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id,boundary=hold);handshake(h,sender)
    def output():
        try:results.append(sender.send_offer())
        except BaseException as error:errors.append(error)
    def receive(accepted):
        try:deliver(h,sender,accepted)
        except BaseException as error:errors.append(error)
        finally:accepted_ended.set()
    writer=threading.Thread(target=output);reader=None;writer.start()
    try:
        assert entered.wait(5);offer=h.wire.receive();accepted=acceptance(sender,cached,offer)
        reader=threading.Thread(target=receive,args=(accepted,));reader.start()
        assert not accepted_ended.wait(0.05)
    finally:
        release.set();writer.join(5)
        if reader is not None:reader.join(5)
    try:
        assert not writer.is_alive() and reader is not None and not reader.is_alive() and not errors
        assert results==[offer] and accepted_ended.is_set() and sender.observation().body['phase']=='accepted'
    finally:sender.close()
