"""Independent native RECEIVE is required for shared incoming WLAN work (#429)."""
import pytest
import socket
from types import SimpleNamespace

from test_media_source_connection import source,receiving,mappings,composition,dispatch
from test_file_authenticated_desktop import native
from test_media_shared_settings_native import prime_receiving
from test_media_incoming_operation import agree_shared
from test_media_source_worker import warm_metadata
from test_file_desktop_sources import response,ALBUM,CATALOG,RUN
from test_file_desktop_photo_batches import result
import magnolie_file_sources as sources
from magnolie_file_desktop_connection import NativePhotoDesktopSession
from test_media_source_sender import message


def test_shared_incoming_wifi_uses_receive_without_send_or_implicit_phone_configuration(source,native,monkeypatch):
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',.02)
    with composition(source,native[0]) as h:
        h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
        c,session=prime_receiving(h,native[0])
        h.controller.change('direction','phone_to_pc');h.controller.change('auto_mode','wifi')
        before=h.preferences.read()
        monkeypatch.setattr(h.source,'plan',lambda *a,**k:pytest.fail('Incoming-only synchronization inspected PC source'))
        token=agree_shared(h,native[0]);assert token is not None
        assert session._shared_schedule_token is token and session._shared_automatic
        h.wire.sock.settimeout(30)
        status=h.wire.receive();assert status['body']['operation']=='status'
        dispatch(h,native[0],response(status,sources.RESULT,version='b'*64,revision=2,enabled=True,
            associated=True,repair_pending=False,kinds=sorted(sources.KINDS)))
        discover=h.wire.receive();assert discover['body']['operation']=='discover'
        dispatch(h,native[0],response(discover,sources.CATALOG,version='b'*64,page=dict(format=1,catalog_id=CATALOG,
            after=0,next_cursor=None,coverage='full_images',proves_deletion=False,
            albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=0,needs_choice=False)])))
        batch=h.wire.receive();assert batch['body']['operation']=='batch_run'
        dispatch(h,native[0],result(batch,RUN,True,state='empty_ready'))
        for operation in ('cancel_run','end_run'):
            closing=h.wire.receive();assert closing['body']['operation']==operation
            dispatch(h,native[0],result(closing,RUN,True,state='canceled_held'))
        assert session.join(30) and session.snapshot()['state']=='complete',session.snapshot()
        assert h.preferences.read()==before and c._run is None and c._source_run is None
        assert not h.source._prepared and h.target.read_bytes()==b'hello'
        session.start('stop');session.shared_settings_changed()
        assert session._automatic_paused


def test_shared_incoming_wifi_cannot_replace_absent_native_receive_with_shared_flags(source,native,monkeypatch):
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',60)
    with composition(source,native[0]) as h:
        warm_metadata(h,native[0]);c=h.connection;session=c.desktop_session()
        h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
        h.controller.change('direction','phone_to_pc');h.controller.change('auto_mode','wifi')
        before=h.preferences.read();assert not before.policy.enabled
        monkeypatch.setattr(c,'request_source',lambda *a,**k:pytest.fail('Shared flags bypassed native RECEIVE'))
        assert agree_shared(h,native[0]) is not None
        assert not session._shared_automatic and session._schedule.mode=='manual' and session._timer is None
        assert session._schedule.take_due() is None and h.preferences.read()==before


def test_incoming_automatic_status_cannot_survive_route_loss_and_later_wifi_repair(source,native,monkeypatch):
    from magnolie_file_transfer import TransferError
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',.02)
    with composition(source,native[0]) as h:
        h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
        c,session=prime_receiving(h,native[0])
        h.controller.change('direction','phone_to_pc');h.controller.change('auto_mode','wifi')
        agree_shared(h,native[0]);h.wire.sock.settimeout(30)
        status=h.wire.receive();assert status['body']['operation']=='status'
        pending=c._source_pending
        native[0].connection_transports[h.peer['device_id']]='bluetooth'
        reply=response(status,sources.RESULT,version='b'*64,revision=2,enabled=True,
            associated=True,repair_pending=False,kinds=sorted(sources.KINDS))
        try:
            with pytest.raises(TransferError,match='operation_ended'):dispatch(h,native[0],reply)
            assert session.join(15) and session.snapshot()['state']=='held',session.snapshot()
        finally:native[0].connection_transports[h.peer['device_id']]='wifi'
        with pytest.raises(TransferError,match='operation_ended'):dispatch(h,native[0],reply)
        assert c._source_pending is pending and c._source_run is None and c._run is None
        assert h.target.read_bytes()==b'hello' and not h.source._prepared
        session.start('stop')


@pytest.mark.parametrize('phone_enabled',[True,False,None])
def test_new_channel_adopts_saved_native_receive_only_after_fresh_agreements_without_reconfiguring_phone(source,native,monkeypatch,phone_enabled):
    import magnolie_telefon as phone
    from magnolie_file_native_authority import capture_authenticated_binding
    from magnolie_file_control import FileControlPacket,FileGrantState,KIND as CONTROL
    from test_media_transport import PeerWire
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',.02)
    service=native[0]
    with composition(source,service) as old:
        old.preferences.configure_sending(old.preferences.issue_action(),old.preferences.read(),photos=False,videos=False)
        prime_receiving(old,service)
        old.controller.change('direction','phone_to_pc');old.controller.change('auto_mode','wifi')
        if phone_enabled is None:old.preferences.set_mode(old.preferences.issue_action(),old.preferences.read(),'automatic')
        before=old.preferences.read();shared=old.controller._store.read()
        assert before.policy.enabled and before.mode==('automatic' if phone_enabled is None else 'manual') and not before.policy.sending.photos
    if phone_enabled is None:
        source.peer['capabilities']['items']['device_status']['versions'].remove(23);service.store.save_peers()
    left,right=socket.socketpair();left.settimeout(2);right.settimeout(30)
    channel=phone.SecureChannel(left,bytes([3])*16,bytes([1])*32,bytes([1])*4,bytes([2])*32,bytes([2])*4)
    h=SimpleNamespace(peer=source.peer,channel=channel,wire=PeerWire(right))
    binding=capture_authenticated_binding(dict(service.store.identity),dict(h.peer),service._generation,service.store)
    service._activate_connection(h.peer['device_id'],channel,'wifi',file_binding=binding)
    c=None
    try:
        assert channel not in service._native_file_connections
        warm_metadata(h,service)
        c=service._native_file_connections.get(channel)
        if phone_enabled is None:
            assert c is None,'Media capability withdrawal fell back to legacy automatic phone configuration'
            h.wire.sock.settimeout(.1)
            with pytest.raises(TimeoutError):h.wire.receive()
            return
        assert c is not None,'Saved native RECEIVE/shared Wi-Fi did not compose after actual fresh metadata ACKs'
        assert c._preferences.read()==before and c._source_pending is None and c._source_status is None
        session=c.desktop_session()
        announced=[h.wire.receive(),h.wire.receive()]
        assert {p['kind'] for p in announced}=={CONTROL,'file_transfer.shared_settings'}
        setting=next(p for p in announced if p['kind']=='file_transfer.shared_settings')
        local=FileControlPacket.parse(next(p for p in announced if p['kind']==CONTROL)['body'])
        assert not local.grants.send_files and local.grants.receive_files and setting['body']==shared
        assert c._media_transport.intent_for('images') is None
        dispatch(h,service,dict(type='ack',message_id=setting['message_id'],status='accepted',error='none'))
        dispatch(h,service,message('file_transfer.shared_settings',setting['body']));assert h.wire.receive()['type']=='ack'
        assert c._source_pending is None and session._schedule.active is None # Shared flags alone lack file-control ACK.
        remote=FileControlPacket(FileGrantState(1,'6'*64,True,False),'7'*64,1,local.challenge)
        dispatch(h,service,message(CONTROL,remote.wire()));assert h.wire.receive()['kind']==CONTROL
        status=h.wire.receive();assert status['body']['operation']=='status'
        dispatch(h,service,response(status,sources.RESULT,version='b'*64,revision=2,enabled=phone_enabled,
            associated=True,repair_pending=False,kinds=sorted(sources.KINDS)))
        if phone_enabled:
            discover=h.wire.receive();assert discover['body']['operation']=='discover'
            dispatch(h,service,response(discover,sources.CATALOG,version='b'*64,page=dict(format=1,catalog_id=CATALOG,
                after=0,next_cursor=None,coverage='full_images',proves_deletion=False,
                albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=0,needs_choice=False)])))
            batch=h.wire.receive();assert batch['body']['operation']=='batch_run'
            dispatch(h,service,result(batch,RUN,True,state='empty_ready'))
            for operation in ('cancel_run','end_run'):
                closing=h.wire.receive();assert closing['body']['operation']==operation
                dispatch(h,service,result(closing,RUN,True,state='canceled_held'))
        assert session.join(30),session.snapshot()
        assert session.snapshot()['state']==('complete' if phone_enabled else 'held'),session.snapshot()
        if not phone_enabled:assert session.snapshot()['error']=='media_source_shared_incoming_review_required'
        assert c._preferences.read()==before and c._source_pending is None and c._run is None
        assert source.target.read_bytes()==b'hello'
        session.start('stop')
    finally:
        service._end_native_file_connection(channel)
        if c is not None:assert c.desktop_session().join(15)
        left.close();right.close()
