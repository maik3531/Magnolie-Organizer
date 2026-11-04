"""Actual reserved desktop video metadata lane, with data admission still shut."""
import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_sources import request,response,ALBUM,CATALOG
from test_file_video_authority import ack_all
import magnolie_file_sources as sources
from magnolie_file_transfer import TransferError
from magnolie_photo_destination import NativeVideoDestinationController


def prepare(fixture,tmp_path,monkeypatch):
    service,peer,channel,connection,_=fixture
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    peer['capabilities']['items']['device_status']['versions'].append(22)
    service.store.save_peers();ack_all(service,peer,channel)
    target=tmp_path/'native-independent-videos';target.mkdir(mode=0o700)
    chooser=NativeVideoDestinationController(connection._authority)
    try:
        selected=chooser.choose_custom(chooser.issue_action(),target)
        prefs=connection._preferences
        prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=True,destination_choice=selected)
    finally:chooser.close()
    return target


def status(fixture,operation='status',revision=3,enabled=True,video_revision=1,**options):
    req=request(fixture,operation,**options)
    reply=response(req,sources.RESULT,version=f'{revision:x}'*64,revision=revision,enabled=True,associated=True,
        repair_pending=False,kinds=['camera'],videos=dict(enabled=enabled,revision=video_revision))
    fixture[0]._payload(fixture[1],fixture[2],reply)
    return req,reply


def test_separate_video_config_and_catalog_require_current_native_scope_without_rotating_photo_controls(receiving,tmp_path,monkeypatch):
    target=prepare(receiving,tmp_path,monkeypatch)
    connection=receiving[3];binding=connection._receive_binding();grant=connection._preferences.local_grant(True).grants
    status(receiving,enabled=False,video_revision=0)
    req=request(receiving,'configure_videos',enabled=True)
    assert 'media_type' not in req['body'] and req['body']['enabled'] is True
    receiving[0]._payload(receiving[1],receiving[2],response(req,sources.RESULT,version='4'*64,revision=4,
        enabled=True,associated=True,repair_pending=False,kinds=['camera'],videos=dict(enabled=True,revision=1)))
    assert connection._source_control_required is None
    assert not connection.send_controls() and connection._receive_binding()==binding
    assert connection._preferences.local_grant(True).grants==grant
    discover=request(receiving,'discover',media_type='video')
    assert discover['body']['media_type']=='video'
    receiving[0]._payload(receiving[1],receiving[2],response(discover,sources.CATALOG,version='4'*64,media_type='video',
        page=dict(format=1,catalog_id=CATALOG,after=0,next_cursor=None,coverage='full_videos',proves_deletion=False,
            albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)])))
    assert connection._source_catalog.media_type=='video'
    for options,error in (({},'album_not_current'),(dict(media_type='video'),'video_data_join_unavailable')):
        with pytest.raises(TransferError,match=error):request(receiving,'run',album_id=ALBUM,desktop_choice=True,**options)
    assert connection._source_pending is None and connection._run is None and connection._catalog is None
    assert not list(target.iterdir()) and not list(receiving[4].iterdir())


def test_video_permission_metadata_echo_is_typed_and_withdrawal_prevents_pending_output(receiving,tmp_path,monkeypatch):
    prepare(receiving,tmp_path,monkeypatch);status(receiving)
    req=request(receiving,'request_read',media_type='video')
    reply=response(req,sources.PERMISSION_RESULT,version='3'*64,state='requested',media_type='video')
    receiving[0]._payload(receiving[1],receiving[2],reply)
    assert receiving[3]._source_result.media_type=='video' and receiving[3]._run is None
    req=request(receiving,'discover',media_type='video')
    peer=receiving[1];peer['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    sent=receiving[2].send.call_count
    with pytest.raises(TransferError,match='video_metadata_unavailable'):receiving[3].retry_source_command()
    assert receiving[2].send.call_count==sent and receiving[3]._source_pending.command.media_type=='video'
    assert receiving[3]._authority.current_peer().metadata_supported


def test_explicit_video_off_after_capability_withdrawal_accepts_legacy_metadata_reply_without_control_churn(receiving,tmp_path,monkeypatch):
    prepare(receiving,tmp_path,monkeypatch);status(receiving)
    connection=receiving[3];binding=connection._receive_binding()
    receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    req=request(receiving,'configure_videos',enabled=False)
    receiving[0]._payload(receiving[1],receiving[2],response(req,sources.RESULT,version='4'*64,revision=4,
        enabled=True,associated=True,repair_pending=False,kinds=['camera']))
    assert connection._source_status.videos is None and connection._source_pending is None
    assert connection._receive_binding()==binding and not connection.send_controls()


@pytest.mark.parametrize('failure',['no_consent','no_capability','missing_root'])
def test_video_metadata_refusal_happens_before_command_ticket_or_output(receiving,tmp_path,monkeypatch,failure):
    target=prepare(receiving,tmp_path,monkeypatch);status(receiving,enabled=False,video_revision=0)
    connection=receiving[3]
    if failure=='no_consent':
        prefs=connection._preferences;prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=False)
    elif failure=='no_capability':
        receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    else:target.rmdir()
    sent=receiving[2].send.call_count
    with pytest.raises((TransferError,FileNotFoundError)):request(receiving,'configure_videos',enabled=True)
    assert connection._source_pending is None and not connection._controls._receiver_commands
    assert receiving[2].send.call_count==sent


def test_pending_video_metadata_cannot_resume_after_local_off_on_with_new_consent_revision(receiving,tmp_path,monkeypatch):
    prepare(receiving,tmp_path,monkeypatch);status(receiving)
    request(receiving,'discover',media_type='video')
    connection=receiving[3];prefs=connection._preferences
    original=prefs.read();off=prefs.set_video_scope(prefs.issue_action(),original,enabled=False)
    prefs.set_video_scope(prefs.issue_action(),off,enabled=True)
    sent=receiving[2].send.call_count
    with pytest.raises(TransferError,match='video_policy_changed'):connection.retry_source_command()
    assert receiving[2].send.call_count==sent and connection._run is None


@pytest.mark.parametrize('revision,video_revision,enabled',[(2,1,True),(3,2,True),(4,0,False),(4,1,False)])
def test_video_status_rejects_global_or_independent_counter_rollback_and_same_revision_mutation(
        receiving,tmp_path,monkeypatch,revision,video_revision,enabled):
    prepare(receiving,tmp_path,monkeypatch);status(receiving)
    connection=receiving[3];before=connection._source_status
    req=request(receiving,'status')
    reply=response(req,sources.RESULT,version=f'{revision:x}'*64,revision=revision,enabled=True,associated=True,
        repair_pending=False,kinds=['camera'],videos=dict(enabled=enabled,revision=video_revision))
    with pytest.raises(TransferError,match='status_rollback'):receiving[0]._payload(receiving[1],receiving[2],reply)
    assert connection._source_status==before and connection._source_pending is not None


@pytest.mark.parametrize('operation',[[],{},True])
def test_native_video_metadata_api_rejects_non_string_operations_before_ticket_or_send(receiving,operation):
    sent=receiving[2].send.call_count
    with pytest.raises(TransferError,match='invalid_options'):request(receiving,operation,media_type='video')
    assert receiving[3]._source_pending is None and receiving[2].send.call_count==sent
