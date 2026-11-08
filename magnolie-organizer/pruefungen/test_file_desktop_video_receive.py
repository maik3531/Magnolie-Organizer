"""Actual native video receiver/stage/Saved and drained stop, no product gate ON."""
from dataclasses import replace
import threading

import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,chunk
from test_file_desktop_sources import request,response,RUN,ALBUM,CATALOG
from test_file_desktop_video_source_owner import begin,run_reply
from test_file_desktop_video_metadata import prepare
from test_file_desktop_media import manifest
from magnolie_file_offer import create_offer
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_index import ProtectedTransferJobIndex
import magnolie_file_sources as sources


def offer_video(fixture,*,epoch='c'*64,full=None):
    full=full or manifest(fixture)
    full=replace(full,files=tuple(replace(file,path='Camera/clip.mp4') for file in full.files))
    req=request(fixture,'media_page')
    reply=response(req,sources.MEDIA,version=req['body']['expected_version'],run_id=fixture[3]._source_run.run_id,media_type='video',page=dict(format=1,
        manifest_sha256=full.fingerprint,source_epoch=epoch,media_type='video',insertion_witness=False,
        after=0,next_cursor=None,total_files=1,entries=[dict(file_id=full.files[0].id,photo_id='d'*64,media_kind='video')]))
    reply['expires_ms']=min(reply['expires_ms'],req['expires_ms'])
    fixture[0]._payload(fixture[1],fixture[2],reply)
    req=request(fixture,'offer_run');offer=create_offer(full)
    offer['expires_ms']=min(offer['expires_ms'],req['expires_ms'])
    fixture[0]._payload(fixture[1],fixture[2],offer)
    run_reply(fixture,req,run_id=fixture[3]._source_run.run_id,offer_id=offer['message_id'],manifest_sha256=full.fingerprint)
    return full,offer


def admit_video(fixture,tmp_path,monkeypatch,*,default=False):
    target=begin(fixture,tmp_path,monkeypatch,storage=True,default=default)
    full,offer=offer_video(fixture)
    connection=fixture[3]
    connection.accept_pending_offer(connection.issue_receive_action(),offer['message_id'])
    return target,full,connection._run


def end_source(fixture):
    req=request(fixture,'cancel_run');run_reply(fixture,req,state='canceled_held')
    req=request(fixture,'end_run');run_reply(fixture,req,state='canceled_held',run_ended=True)


def test_actual_video_chunk_native_publication_saved_mapping_and_finish_never_touch_photo_root(receiving,tmp_path,monkeypatch):
    target,full,run=admit_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    assert run.media_type=='video' and run.accepted.destination.path==str(target)
    assert run.accepted.binding.destination_token==connection._preferences.read().policy.videos.destination_token
    req=connection.request_next_chunk();receiving[0]._payload(receiving[1],receiving[2],chunk(req,b'hello'))
    connection.publish_received(connection.issue_receive_action())
    history=run.receiver._index.media_history;receipt=run.receiver._index.saved_mapping_receipt()
    assert history.media_type=='video' and receipt is not None and run.saved_mapping_ready
    assert (target/full.files[0].path).read_bytes()==b'hello' and not list(receiving[4].iterdir())
    saved=receiving[2].send.call_args.args[0]
    assert saved['kind']=='file_transfer.saved' and saved['body']['destination_token']==run.accepted.binding.destination_token
    connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True)
    end_source(receiving)
    assert connection._run is None and connection._source_run is None
    retired=connection._catalog.jobs()[0]
    assert retired.reserved_bytes==0 and retired.cache_retirement_sha256 and retired.saved_mapping_sha256
    assert connection._receive_binding().destination_token==connection._preferences.read().policy.destination_token
    assert (target/full.files[0].path).read_bytes()==b'hello' and not list(receiving[4].iterdir())


@pytest.mark.parametrize('withdrawal',['capability','local_consent','data_gate'])
def test_video_withdrawal_stops_exact_outstanding_request_only_after_ordered_cancel_barrier_and_keeps_original_job(
        receiving,tmp_path,monkeypatch,withdrawal):
    target,full,run=admit_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    request_chunk=connection.request_next_chunk()
    assert request_chunk is not None and run.request_output_started
    if withdrawal=='capability':
        receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    elif withdrawal=='local_consent':
        prefs=connection._preferences;prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=False)
    else:monkeypatch.setattr(type(connection),'_video_data_handlers_ready',False)
    with pytest.raises(TransferError):connection.request_next_chunk()
    state=connection.request_normal_receive_stop(connection.issue_receive_action())
    assert state.state=='pending' and not run.receiver._closed
    req=request(receiving,'cancel_run');run_reply(receiving,req,state='canceled_held')
    state=connection.receive_stop_state()
    assert state.state=='stopped' and state.io_ended and state.resources_closed and state.checkpoint_committed
    assert run.receiver._closed and connection._run is None and connection._checkpoint_binding_owner is None
    assert state.owner==run.job.owner and state.verified_bytes==state.checkpoint_verified_bytes==0
    assert connection._catalog.jobs()==(run.job,)
    protection=connection._authority.protection
    with connection._catalog.inspect_jobs() as (parent,_):
        with ProtectedTransferJobIndex(parent,full,run.accepted.binding,lambda:None,protection.seal,protection.unseal,
                owner=run.job.owner,accepted=run.accepted) as index:
            assert index.media_history.media_type=='video' and not index.saved_receipts()
            assert index.saved_mapping_receipt() is None
    req=request(receiving,'end_run');run_reply(receiving,req,state='canceled_held',run_ended=True)
    assert connection._catalog.jobs()==(run.job,) and connection._checkpoint_binding_owner is None
    assert not (target/full.files[0].path).exists() and not list(receiving[4].iterdir())
    assert not any(call.args[0]['kind']=='file_transfer.saved' for call in receiving[2].send.call_args_list)


def test_owned_video_checkpoint_binding_is_unavailable_outside_exact_checkpoint_stack_and_other_threads(
        receiving,tmp_path,monkeypatch):
    _,_,run=admit_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    with pytest.raises(TransferError,match='checkpoint_owner_changed'):connection._owned_video_checkpoint_binding(run)
    checked=[];checkpoint=run.receiver.checkpoint
    def guarded_checkpoint():
        def foreign_thread():
            try:connection._receive_binding()
            except TransferError:checked.append('refused')
        worker=threading.Thread(target=foreign_thread);worker.start();worker.join(5)
        assert not worker.is_alive() and checked==['refused']
        return checkpoint()
    monkeypatch.setattr(run.receiver,'checkpoint',guarded_checkpoint)
    state=connection.request_normal_receive_stop(connection.issue_receive_action())
    assert state.state=='stopped' and checked==['refused'] and connection._checkpoint_binding_owner is None
    end_source(receiving)


def test_saved_video_off_on_with_fresh_source_epoch_holds_known_native_id_without_new_job_or_pc_edit_loss(
        receiving,tmp_path,monkeypatch):
    target,full,run=admit_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    receiving[0]._payload(receiving[1],receiving[2],chunk(connection.request_next_chunk(),b'hello'))
    connection.publish_received(connection.issue_receive_action())
    connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True);end_source(receiving)
    path=target/full.files[0].path;path.write_bytes(b'preserve user-edited video')
    before=(path.stat().st_ino,path.read_bytes());jobs=connection._catalog.jobs()
    prefs=connection._preferences;original=prefs.read();photo_binding=connection._receive_binding()
    for enabled,revision,video_revision in ((False,4,2),(True,5,3)):
        prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=enabled)
        req=request(receiving,'configure_videos',enabled=enabled)
        receiving[0]._payload(receiving[1],receiving[2],response(req,sources.RESULT,version=f'{revision:x}'*64,revision=revision,
            enabled=True,associated=True,repair_pending=False,kinds=['camera'],videos=dict(enabled=enabled,revision=video_revision)))
    assert prefs.read().policy.videos.destination_token==original.policy.videos.destination_token
    assert connection._receive_binding()==photo_binding and not connection.send_controls()
    req=request(receiving,'discover',media_type='video')
    receiving[0]._payload(receiving[1],receiving[2],response(req,sources.CATALOG,version='5'*64,media_type='video',
        page=dict(format=1,catalog_id=CATALOG,after=0,next_cursor=None,coverage='full_videos',proves_deletion=False,
            albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)])))
    req=request(receiving,'run',media_type='video',album_id=ALBUM,desktop_choice=True)
    renewed='55555555-5555-4555-8555-555555555555';run_reply(receiving,req,run_id=renewed)
    fresh,offered=offer_video(receiving,epoch='e'*64,full=replace(full,source_id='6'*32,transfer_id='5'*32))
    chunks=sum(call.args[0]['kind']=='file_transfer.chunk.request' for call in receiving[2].send.call_args_list)
    with pytest.raises(TransferError,match='video_source_reassociation_required'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    assert connection._run is None and connection._catalog.jobs()==jobs
    assert (path.stat().st_ino,path.read_bytes())==before and not list(receiving[4].iterdir())
    assert sum(call.args[0]['kind']=='file_transfer.chunk.request' for call in receiving[2].send.call_args_list)==chunks==1


@pytest.mark.parametrize('failure',['checkpoint','close'])
def test_uncertain_video_stop_keeps_failed_original_owner_and_always_removes_checkpoint_only_authority(
        receiving,tmp_path,monkeypatch,failure):
    _,_,run=admit_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    original=run.receiver.close
    def failed():
        if failure=='close':original()
        raise OSError('fixture uncertain native video '+failure)
    monkeypatch.setattr(run.receiver,failure,failed)
    state=connection.request_normal_receive_stop(connection.issue_receive_action())
    assert state.state=='failed' and connection._run is run and run.receiver._closed
    assert connection._checkpoint_binding_owner is None and connection._catalog.jobs()==(run.job,)
    assert run.job.reserved_bytes>0 and run.job.cache_retirement_sha256 is None
    with pytest.raises(TransferError):connection._receive_binding()
    with pytest.raises(TransferError):request(receiving,'end_run')
    assert not any(call.args[0]['kind']=='file_transfer.saved' for call in receiving[2].send.call_args_list)


def test_photo_receiver_stays_independent_when_video_scope_is_enabled_but_video_data_gate_is_off(receiving,tmp_path,monkeypatch):
    from test_file_desktop_sources import ready_source
    from test_file_desktop_media import collect,send_offer,dispatch
    monkeypatch.setattr(receiving[3],'_video_data_handlers_ready',False)
    target=prepare(receiving,tmp_path,monkeypatch);connection=receiving[3]
    assert not connection._video_data_handlers_ready and connection._preferences.read().include_videos
    ready_source(receiving);full=manifest(receiving);collect(receiving,full)
    offered,result=send_offer(receiving,full);dispatch(receiving,result)
    connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    assert connection._run.media_type=='images' and connection._run.accepted.destination.path==str(receiving[4])
    dispatch(receiving,chunk(connection.request_next_chunk(),b'hello'))
    connection.publish_received(connection.issue_receive_action())
    assert (receiving[4]/full.files[0].path).read_bytes()==b'hello' and not list(target.iterdir())


def test_actual_video_receiver_uses_native_videos_default_phone_named_root_not_pictures_or_account_guess(
        receiving,tmp_path,monkeypatch):
    from gi.repository import GLib
    from magnolie_photo_destination import video_folder_component
    native_videos=tmp_path/'native-Videos';native_videos.mkdir(mode=0o700)
    def directory(kind):
        assert kind==GLib.UserDirectory.DIRECTORY_VIDEOS
        return str(native_videos)
    monkeypatch.setattr(GLib,'get_user_special_dir',directory)
    target,full,run=admit_video(receiving,tmp_path,monkeypatch,default=True)
    assert target==native_videos/video_folder_component(receiving[1]['display_name'])
    connection=receiving[3]
    receiving[0]._payload(receiving[1],receiving[2],chunk(connection.request_next_chunk(),b'hello'))
    connection.publish_received(connection.issue_receive_action())
    assert (target/full.files[0].path).read_bytes()==b'hello' and not list(receiving[4].iterdir())
    assert run.accepted.destination==connection._preferences.read().policy.videos.destination


def test_video_original_resume_cannot_fall_back_to_a_new_normal_source_run_or_reopen_the_old_stage(
        receiving,tmp_path,monkeypatch):
    _,full,run=admit_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    state=connection.request_normal_receive_stop(connection.issue_receive_action())
    assert state.state=='stopped';end_source(receiving)
    jobs=connection._catalog.jobs()
    req=request(receiving,'run',media_type='video',album_id=ALBUM,desktop_choice=True)
    run_reply(receiving,req,run_id='55555555-5555-4555-8555-555555555555')
    _,offered=offer_video(receiving,full=full)
    def forbidden(*args,**kwargs):raise AssertionError('unjoined VIDEO resume reopened old native stage')
    monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.resume',forbidden)
    sent=receiving[2].send.call_count
    with pytest.raises(TransferError,match='video_original_resume_join_unavailable'):
        connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],run.job.owner)
    assert connection._run is None and connection._catalog.jobs()==jobs and receiving[2].send.call_count==sent
