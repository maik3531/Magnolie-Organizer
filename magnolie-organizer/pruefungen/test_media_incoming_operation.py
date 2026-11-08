"""Deny-only original-operation constraints on real native receiving objects.

The established native dispatcher fixture is used, not an encrypted-phone or
installed GUI acceptance claim. Existing grants remain independently required.
"""
import pytest
from hashlib import sha256
from pathlib import Path
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,chunk
from test_file_desktop_album_worker import prepared
from test_file_desktop_photo_batches import result
from test_file_desktop_sources import RUN,ALBUM,request
from test_file_desktop_media import dispatch,collect
from magnolie_file_offer import create_offer
from magnolie_file_transfer import TransferError
from test_media_source_connection import source,mappings,composition
from test_media_source_connection import dispatch as secure_dispatch
from test_media_source_sender import message
from test_media_shared_settings_native import prime_receiving
from test_media_source_media_offer import png
from test_media_source_sender import acceptance,request as source_chunk_request,saved as source_saved
from test_media_source_media_offer import readback


def begin(fixture,current):
    c=fixture[3];full=prepared(fixture)[0]
    c.request_source(c.issue_receive_action(),'batch_run',album_id=ALBUM,desktop_choice=True,native_current=current)
    packet=fixture[2].send.call_args.args[0]
    return c,full,packet


def test_failed_original_source_request_cannot_adopt_later_positive_reply(receiving):
    allowed=[True];c,full,packet=begin(receiving,lambda:allowed[0])
    response=result(packet,RUN,True)
    allowed[0]=False
    with pytest.raises(TransferError,match='operation_ended'):dispatch(receiving,response)
    assert c._source_run is None and c._source_pending is not None and c._run is None
    allowed[0]=True
    with pytest.raises(TransferError,match='operation_ended'):dispatch(receiving,response)
    assert c._source_run is None and c._run is None


def test_original_constraint_reaches_actual_chunk_write_and_cannot_revive(receiving):
    allowed=[True];c,full,packet=begin(receiving,lambda:allowed[0])
    dispatch(receiving,result(packet,RUN,True))
    collect(receiving,full);offer_request=request(receiving,'offer_run')
    offered=create_offer(full);offered['expires_ms']=min(offered['expires_ms'],offer_request['expires_ms'])
    dispatch(receiving,offered)
    dispatch(receiving,result(offer_request,RUN,True,offer_id=offered['message_id'],manifest_sha256=full.fingerprint))
    c.accept_pending_offer(c.issue_receive_action(),offered['message_id'])
    c.request_next_chunk();chunk_request=receiving[2].send.call_args.args[0]
    reserved=c._catalog.jobs()[0].reserved_bytes
    allowed[0]=False
    with pytest.raises(TransferError,match='operation_ended'):dispatch(receiving,chunk(chunk_request,b'hello'))
    allowed[0]=True
    with pytest.raises(TransferError,match='operation_ended'):dispatch(receiving,chunk(chunk_request,b'hello'))
    assert not (receiving[4]/full.files[0].path).exists()
    assert c._run is not None and c._catalog.jobs()[0].reserved_bytes==reserved


def test_withdrawn_scope_still_allows_exact_owned_stop_checkpoint_not_more_chunks(receiving):
    allowed=[True];c,full,packet=begin(receiving,lambda:allowed[0])
    dispatch(receiving,result(packet,RUN,True));collect(receiving,full)
    offer_request=request(receiving,'offer_run')
    offered=create_offer(full);offered['expires_ms']=min(offered['expires_ms'],offer_request['expires_ms'])
    dispatch(receiving,offered)
    dispatch(receiving,result(offer_request,RUN,True,offer_id=offered['message_id'],manifest_sha256=full.fingerprint))
    c.accept_pending_offer(c.issue_receive_action(),offered['message_id'])
    c.request_next_chunk();chunk_request=receiving[2].send.call_args.args[0]
    receiver=c._run.receiver;reserved=c._catalog.jobs()[0].reserved_bytes
    allowed[0]=False
    c.request_normal_receive_stop(c.issue_receive_action(),finish=False)
    assert not c._finish_receive_stop() and not receiver._closed # Known request has not drained.
    cancel=request(receiving,'cancel_run')
    dispatch(receiving,result(cancel,RUN,True,state='canceled_held'))
    if c._run is not None:assert c._finish_receive_stop(),c.receive_stop_state()
    stopped=c.receive_stop_state()
    assert stopped.state=='stopped' and stopped.io_ended and stopped.checkpoint_committed and stopped.resources_closed
    assert stopped.verified_bytes==stopped.checkpoint_verified_bytes==0 and receiver._closed
    with pytest.raises(TransferError):dispatch(receiving,chunk(chunk_request,b'hello'))
    assert c._run is None and not (receiving[4]/full.files[0].path).exists()
    assert c._catalog.jobs()[0].reserved_bytes==reserved # Stop/END is not publication or quota release.


def agree_shared(h,service):
    packet=h.controller.send_settings();assert h.wire.receive()==packet
    secure_dispatch(h,service,dict(type='ack',message_id=packet['message_id'],status='accepted',error='none'))
    secure_dispatch(h,service,message('file_transfer.shared_settings',packet['body']));assert h.wire.receive()['type']=='ack'
    return h.controller.intent_for('images')


def test_actual_encrypted_shared_run_keeps_original_scope_after_new_positive_agreement(source,native):
    import magnolie_media_sync as media
    with composition(source,native[0]) as h:
        c,session=prime_receiving(h,native[0])
        original=agree_shared(h,native[0]);assert original is not None
        session.start('sync',ALBUM)
        h.wire.sock.settimeout(30)
        batch=h.wire.receive();assert batch['body']['operation']=='batch_run'
        pending=c._source_pending;constraint=pending.native_constraint
        assert constraint is not None and c._album_worker is not None
        # A real current-channel shared-settings message invalidates the old
        # witness. No native receiving or sending permission is toggled.
        local=c._authority.identity.receiver_id;peer=h.peer['device_id']
        changed=media.change(original.body,peer,local,'direction','pc_to_phone')
        secure_dispatch(h,native[0],message('file_transfer.shared_settings',changed))
        assert h.wire.receive()['type']=='ack'
        offered=h.wire.receive();assert offered['kind']=='file_transfer.shared_settings'
        secure_dispatch(h,native[0],dict(type='ack',message_id=offered['message_id'],status='accepted',error='none'))
        secure_dispatch(h,native[0],message('file_transfer.shared_settings',offered['body']));assert h.wire.receive()['type']=='ack'
        assert session.join(15),session.snapshot()
        assert session.snapshot()['state']=='held',session.snapshot()
        with pytest.raises(TransferError,match='operation_ended'):constraint.require_current()
        # A later genuinely acknowledged agreement cannot revive the pending
        # original source command, even when its incoming direction is positive.
        h.controller.change('direction','two_way')
        renewed=agree_shared(h,native[0]);assert renewed is not None and renewed is not original
        with pytest.raises(TransferError,match='operation_ended'):
            secure_dispatch(h,native[0],result(batch,RUN,True))
        assert c._source_run is None and c._run is None and h.target.read_bytes()==b'hello'


@pytest.mark.parametrize('pc_change,withdraw_at,automatic',[(False,None,False),(True,None,False),(False,0,False),(False,1,False),(False,None,True)])
def test_actual_encrypted_shared_incoming_png_is_saved_then_ends_without_changing_original(source,native,monkeypatch,pc_change,withdraw_at,automatic):
    from magnolie_file_transfer import FileManifest,ManifestFile,CHUNK_BYTES
    from test_file_desktop_media import media
    import magnolie_media_sync as settings
    import io
    from PIL import Image
    from magnolie_file_desktop_connection import NativePhotoDesktopSession
    from test_file_desktop_sources import response,CATALOG
    import magnolie_file_sources as sources
    if automatic:monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',.02)
    with composition(source,native[0]) as h:
        if automatic:h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
        c,session=prime_receiving(h,native[0])
        if automatic:
            h.controller.change('direction','phone_to_pc');h.controller.change('auto_mode','wifi')
        original=agree_shared(h,native[0])
        content=png();path='Camera/shared-native.png'
        image=Image.open(io.BytesIO(content));image.load();assert image.format=='PNG' and image.size==(1,1)
        full=FileManifest('e'*32,'f'*32,h.peer['device_id'],c._authority.identity.receiver_id,
            (ManifestFile('a'*32,path,len(content),sha256(content).hexdigest()),),len(content))
        pc_content=png(1) if pc_change else b'hello'
        if pc_change:h.target.write_bytes(pc_content)
        if not automatic:session.start('sync',ALBUM)
        h.wire.sock.settimeout(30)
        if automatic:
            status=h.wire.receive();assert status['body']['operation']=='status'
            secure_dispatch(h,native[0],response(status,sources.RESULT,version='b'*64,revision=2,enabled=True,
                associated=True,repair_pending=False,kinds=sorted(sources.KINDS)))
            discover=h.wire.receive();assert discover['body']['operation']=='discover'
            secure_dispatch(h,native[0],response(discover,sources.CATALOG,version='b'*64,page=dict(format=1,catalog_id=CATALOG,
                after=0,next_cursor=None,coverage='full_images',proves_deletion=False,
                albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)])))
        first=h.wire.receive()
        if pc_change:
            assert first['kind']=='file_transfer.media_offer'
            sender=c._media_sender;cache=sender._cache;accepted=acceptance(sender,cache,first)
            secure_dispatch(h,native[0],accepted)
            for index in range(cache.manifest.files[0].chunks):
                secure_dispatch(h,native[0],source_chunk_request(accepted,cache,index))
                assert h.wire.receive()['kind']=='file_transfer.chunk'
            secure_dispatch(h,native[0],source_saved(accepted,cache))
            with c._operation(incoming=True):verified=readback(sender,cache,first)
            secure_dispatch(h,native[0],verified)
            first=h.wire.receive() # The incoming phase follows real backup/retirement, never Saved alone.
            assert not cache.directory.exists() and list(Path(c._authority.binding.native_directory).glob('.magnolie-source-*.retired'))
        batch=first;assert batch['body']['operation']=='batch_run'
        assert session.snapshot()['saved_files']==(1 if pc_change else 0)
        secure_dispatch(h,native[0],result(batch,RUN,True))
        page_request=h.wire.receive();assert page_request['body']['operation']=='media_page'
        page=media(page_request,full)
        page['body']['page']['entries'][0]['photo_id']=sha256(b'shared-new-native-photo').hexdigest()
        secure_dispatch(h,native[0],page)
        offer_request=h.wire.receive();assert offer_request['body']['operation']=='offer_run'
        offered=create_offer(full);offered['expires_ms']=min(offered['expires_ms'],offer_request['expires_ms'])
        secure_dispatch(h,native[0],offered)
        secure_dispatch(h,native[0],result(offer_request,RUN,True,offer_id=offered['message_id'],manifest_sha256=full.fingerprint))
        accepted=h.wire.receive();assert accepted['kind']=='file_transfer.accept'
        for index in range(full.files[0].chunks):
            chunk_request=h.wire.receive();assert chunk_request['kind']=='file_transfer.chunk.request'
            assert chunk_request['body']['chunk_index']==index
            if withdraw_at is not None and index==withdraw_at:
                run=c._run;receiver=run.receiver;owner=run.job.owner
                reserved=next(job for job in c._catalog.jobs() if job.owner==owner).reserved_bytes
                body=settings.change(original.body,h.peer['device_id'],c._authority.identity.receiver_id,'enabled',False)
                secure_dispatch(h,native[0],message('file_transfer.shared_settings',body))
                assert h.wire.receive()['type']=='ack'
                assert h.wire.receive()['kind']=='file_transfer.shared_settings' # Not yet acknowledged; never a new read grant.
                with pytest.raises(TransferError,match='operation_ended'):
                    secure_dispatch(h,native[0],chunk(chunk_request,content[index*CHUNK_BYTES:(index+1)*CHUNK_BYTES]))
                assert not receiver._closed and not (Path(h.record.destination.path)/path).exists()
                for operation in ('cancel_run','end_run'):
                    closing=h.wire.receive();assert closing['body']['operation']==operation
                    secure_dispatch(h,native[0],result(closing,RUN,True,state='canceled_held'))
                assert session.join(30),session.snapshot()
                assert session.snapshot()['state']=='held' and receiver._closed
                stopped=c.receive_stop_state()
                assert stopped.io_ended and stopped.checkpoint_committed and stopped.resources_closed
                assert stopped.verified_bytes==stopped.checkpoint_verified_bytes==index*CHUNK_BYTES
                assert next(job for job in c._catalog.jobs() if job.owner==owner).reserved_bytes==reserved
                assert h.target.read_bytes()==pc_content and c._run is None and c._source_run is None
                return
            secure_dispatch(h,native[0],chunk(chunk_request,content[index*CHUNK_BYTES:(index+1)*CHUNK_BYTES]))
        saved=h.wire.receive();assert saved['kind']=='file_transfer.saved'
        for operation in ('cancel_run','end_run'):
            request=h.wire.receive();assert request['body']['operation']==operation
            secure_dispatch(h,native[0],result(request,RUN,True,state='canceled_held'))
        assert session.join(30),session.snapshot()
        assert session.snapshot()['state']=='complete',session.snapshot()
        assert session.snapshot()['saved_files']==(2 if pc_change else 1)
        assert session.snapshot()['saved_files']==(2 if pc_change else 1) and session._worker is None
        assert (Path(h.record.destination.path)/path).read_bytes()==content
        assert h.target.read_bytes()==pc_content and c._run is None and c._source_run is None
        if automatic:
            assert not h.preferences.read().policy.sending.photos
            session.start('stop')
