"""Typed desktop video source ownership, before receiver/worker admission."""
import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_sources import request,response,ALBUM,CATALOG,RUN
from test_file_desktop_video_metadata import prepare,status
from test_file_desktop_media import manifest
from magnolie_file_desktop_connection import NativeDesktopFileConnection
from magnolie_file_offer import create_offer
from magnolie_file_transfer import TransferError
import magnolie_file_sources as sources


def begin(fixture,tmp_path,monkeypatch,*,batched=False):
    target=prepare(fixture,tmp_path,monkeypatch);status(fixture)
    monkeypatch.setattr(NativeDesktopFileConnection,'_video_data_handlers_ready',True)
    req=request(fixture,'discover',media_type='video')
    fixture[0]._payload(fixture[1],fixture[2],response(req,sources.CATALOG,version='3'*64,media_type='video',
        page=dict(format=1,catalog_id=CATALOG,after=0,next_cursor=None,coverage='full_videos',proves_deletion=False,
            albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)])))
    req=request(fixture,'batch_run' if batched else 'run',media_type='video',album_id=ALBUM,desktop_choice=True)
    run_reply(fixture,req)
    return target


def run_reply(fixture,req,state='snapshot_ready',**fields):
    old=fixture[3]._source_run
    if (req['body']['operation']=='batch_run' or old is not None and old.batched
            and req['body']['operation'] not in ('end_run','end_album')):fields.setdefault('batch_end',False)
    reply=response(req,sources.RUN_RESULT,version='3'*64,run_id=RUN,state=state,source_io_ended=True,
        media_type='video',**fields)
    reply['expires_ms']=min(reply['expires_ms'],req['expires_ms'])
    fixture[0]._payload(fixture[1],fixture[2],reply)
    return reply


def test_typed_video_source_owner_selects_video_token_for_offer_and_cannot_admit_unjoined_receiver(receiving,tmp_path,monkeypatch):
    target=begin(receiving,tmp_path,monkeypatch);connection=receiving[3]
    scope=connection._preferences.read()
    assert connection._source_run.media_type=='video'
    assert connection._receive_binding().destination_token==scope.policy.videos.destination_token
    with pytest.raises(TransferError,match='media_scope_changed'):connection._receive_binding(media_type='images')
    req=request(receiving,'media_page');full=manifest(receiving)
    assert req['body']['media_type']=='video'
    media=response(req,sources.MEDIA,version='3'*64,run_id=RUN,media_type='video',
        page=dict(format=1,manifest_sha256=full.fingerprint,source_epoch='c'*64,media_type='video',insertion_witness=False,
            after=0,next_cursor=None,total_files=1,entries=[dict(file_id=full.files[0].id,photo_id='d'*64,media_kind='video')]))
    media['expires_ms']=min(media['expires_ms'],req['expires_ms'])
    receiving[0]._payload(receiving[1],receiving[2],media)
    req=request(receiving,'offer_run');offered=create_offer(full)
    offered['expires_ms']=min(offered['expires_ms'],req['expires_ms'])
    receiving[0]._payload(receiving[1],receiving[2],offered)
    run_reply(receiving,req,offer_id=offered['message_id'],manifest_sha256=full.fingerprint)
    assert connection._offer_binding.destination_token==scope.policy.videos.destination_token
    with pytest.raises(TransferError,match='media_target_routing_unavailable'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    assert connection._run is None and connection._catalog is None
    assert not list(target.iterdir()) and not list(receiving[4].iterdir())


@pytest.mark.parametrize('withdrawal',['capability','local_consent','data_gate'])
def test_exact_video_status_cancel_end_can_finish_after_withdrawal_without_positive_read_or_root_fallback(
        receiving,tmp_path,monkeypatch,withdrawal):
    target=begin(receiving,tmp_path,monkeypatch);connection=receiving[3]
    if withdrawal=='capability':
        receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    elif withdrawal=='local_consent':
        prefs=connection._preferences;prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=False)
    else:monkeypatch.setattr(NativeDesktopFileConnection,'_video_data_handlers_ready',False)
    with pytest.raises(TransferError):request(receiving,'media_page')
    assert connection._source_pending is None
    sent=receiving[2].send.call_count
    with pytest.raises(TransferError,match='media_scope_changed'):request(receiving,'cancel_run',media_type='images')
    assert receiving[2].send.call_count==sent
    req=request(receiving,'run_status');assert req['body']['media_type']=='video';run_reply(receiving,req)
    req=request(receiving,'cancel_run');run_reply(receiving,req,state='canceled_held')
    req=request(receiving,'end_run')
    run_reply(receiving,req,state='canceled_held',run_ended=True)
    assert connection._source_run is None and connection._source_pending is None
    assert connection._receive_binding().destination_token==connection._preferences.read().policy.destination_token
    assert connection._run is None and connection._catalog is None
    assert not list(target.iterdir()) and not list(receiving[4].iterdir())


def test_pending_positive_video_command_rechecks_actual_data_gate_on_retry(receiving,tmp_path,monkeypatch):
    begin(receiving,tmp_path,monkeypatch)
    request(receiving,'media_page');sent=receiving[2].send.call_count
    monkeypatch.setattr(NativeDesktopFileConnection,'_video_data_handlers_ready',False)
    with pytest.raises(TransferError,match='video_data_join_unavailable'):receiving[3].retry_source_command()
    assert receiving[2].send.call_count==sent and receiving[3]._source_media_pages==()


@pytest.mark.parametrize('media_type',['',False,0,[],{}])
def test_explicit_invalid_binding_scope_never_defaults_to_photo_authority(receiving,media_type):
    with pytest.raises(TransferError,match='invalid_media_type'):receiving[3]._receive_binding(media_type=media_type)
    assert receiving[3]._run is None and receiving[3]._catalog is None


def test_video_batch_scan_end_after_capability_withdrawal_uses_exact_typed_ended_owner_without_next_read(receiving,tmp_path,monkeypatch):
    target=begin(receiving,tmp_path,monkeypatch,batched=True);connection=receiving[3]
    req=request(receiving,'cancel_run');run_reply(receiving,req,state='canceled_held')
    req=request(receiving,'end_run');run_reply(receiving,req,state='canceled_held',run_ended=True)
    assert connection._ended_batch.media_type=='video' and connection._source_run is None
    receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    with pytest.raises(TransferError,match='video_metadata_unavailable'):request(receiving,'next_batch')
    assert connection._source_pending is None
    req=request(receiving,'end_album');assert req['body']['media_type']=='video'
    run_reply(receiving,req,state='canceled_held',run_ended=True)
    assert connection._ended_batch is None and connection._source_pending is None
    assert connection._run is None and connection._catalog is None and not list(target.iterdir())
