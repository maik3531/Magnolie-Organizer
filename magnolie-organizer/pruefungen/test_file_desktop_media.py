"""Actual native desktop command owner, metadata is not target authority."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import FileManifest,ManifestFile,TransferError
from magnolie_file_offer import create_offer
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,chunk,negotiate
from test_file_desktop_sources import ready_source,request,response,RUN
from test_file_desktop_connection import forbid_legacy


def manifest(fixture,count=1):
    service,peer,_,_,_=fixture
    return FileManifest('1'*32,'2'*32,peer['device_id'],service.store.identity['device_id'],
        tuple(ManifestFile(f'{index+1:032x}',f'Camera/photo{index}.jpg',5,sha256(b'hello').hexdigest()) for index in range(count)),5*count)


def media(req,full,after=0,kind='images'):
    end=min(after+8,len(full.files))
    value=response(req,'file_transfer.sources.media',version='b'*64,run_id=RUN,page=dict(format=1,
        manifest_sha256=full.fingerprint,source_epoch='c'*64,media_type=kind,insertion_witness=False,after=after,
        next_cursor=end if end<len(full.files) else None,total_files=len(full.files),entries=[dict(file_id=full.files[index].id,
        photo_id=sha256(f'photo-{index}'.encode()).hexdigest(),media_kind='image' if kind=='images' else 'video') for index in range(after,end)]))
    value['expires_ms']=min(value['expires_ms'],req['expires_ms'])
    return value


def dispatch(fixture,value):
    fixture[0]._payload(fixture[1],fixture[2],value)


def send_offer(fixture,full):
    req=request(fixture,'offer_run')
    offered=create_offer(full);offered['expires_ms']=min(offered['expires_ms'],req['expires_ms'])
    dispatch(fixture,offered)
    result=response(req,'file_transfer.sources.run_result',version='b'*64,run_id=RUN,state='snapshot_ready',source_io_ended=True,
        offer_id=offered['message_id'],manifest_sha256=full.fingerprint)
    result['expires_ms']=min(result['expires_ms'],offered['expires_ms'])
    return offered,result


def collect(fixture,full,kind='images'):
    for after in range(0,len(full.files),8):
        req=request(fixture,'media_page')
        assert req['body']['after']==after and req['body']['run_id']==RUN
        dispatch(fixture,media(req,full,after,kind))


def test_exact_media_pages_join_actual_offer_before_native_admission_and_preserve_held_quota(receiving,monkeypatch):
    service,peer,channel,connection,target=receiving
    forbid_legacy(service,monkeypatch)
    ready_source(receiving);full=manifest(receiving)
    collect(receiving,full)
    assert not connection.source_state()['media_manifest_correlated']
    assert connection._catalog is None and connection._run is None and not list(target.iterdir())
    offered,result=send_offer(receiving,full)
    assert connection.source_state()['media_manifest_correlated']
    with pytest.raises(TransferError,match='not_confirmed'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    dispatch(receiving,result)
    connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    dispatch(receiving,chunk(connection.request_next_chunk(),b'hello'))
    connection.publish_received(connection.issue_receive_action())
    assert (target/full.files[0].path).read_bytes()==b'hello'
    assert len(connection._catalog.jobs())==1 and connection._source_run.run_id==RUN


def test_only_native_returned_page_cursor_is_used_and_partial_pages_cannot_trigger_offer(receiving):
    connection=receiving[3];ready_source(receiving);full=manifest(receiving,9)
    first=request(receiving,'media_page');dispatch(receiving,media(first,full))
    with pytest.raises(TransferError,match='pages_incomplete'):request(receiving,'offer_run')
    last=request(receiving,'media_page');assert last['body']['after']==8
    dispatch(receiving,media(last,full,8))
    with pytest.raises(TransferError,match='pages_complete'):request(receiving,'media_page')
    offered,result=send_offer(receiving,full);dispatch(receiving,result)
    assert len(connection._source_media_entries)==9 and connection._offer==offered
    assert connection._catalog is None and connection._run is None


@pytest.mark.parametrize('field',['file_id','photo_id'])
def test_crosspage_duplicate_preserves_pending_command_and_original_pages_until_exact_valid_reply(receiving,field):
    connection=receiving[3];ready_source(receiving);full=manifest(receiving,9)
    first=request(receiving,'media_page');first_result=media(first,full);dispatch(receiving,first_result)
    last=request(receiving,'media_page');bad=media(last,full,8)
    bad['body']['page']['entries'][0][field]=first_result['body']['page']['entries'][0][field]
    with pytest.raises(TransferError,match='duplicate_media'):dispatch(receiving,bad)
    assert connection._source_pending is not None and len(connection._source_media_pages)==1
    dispatch(receiving,media(last,full,8))
    assert connection._source_pending is None and len(connection._source_media_pages)==2


@pytest.mark.parametrize('field',['source_epoch','media_type','insertion_witness','total_files'])
def test_page_context_cannot_change_mid_native_source_run(receiving,field):
    connection=receiving[3];ready_source(receiving);full=manifest(receiving,9)
    req=request(receiving,'media_page');dispatch(receiving,media(req,full))
    req=request(receiving,'media_page');bad=media(req,full,8)
    if field=='source_epoch':bad['body']['page'][field]='d'*64
    elif field=='media_type':
        bad['body']['page'][field]='video';bad['body']['page']['entries'][0]['media_kind']='video'
    elif field=='insertion_witness':bad['body']['page'][field]=True
    else:bad['body']['page'][field]=10;bad['body']['page']['next_cursor']=9
    with pytest.raises(TransferError):dispatch(receiving,bad)
    assert len(connection._source_media_pages)==1 and connection._source_pending is not None


def test_failed_actual_media_command_output_retries_only_original_native_attempt(receiving):
    _,_,channel,connection,_=receiving
    ready_source(receiving);full=manifest(receiving)
    channel.send.side_effect=OSError('native media output failed')
    with pytest.raises(OSError):request(receiving,'media_page')
    req=channel.send.call_args.args[0]
    with pytest.raises(TransferError,match='not_requested'):dispatch(receiving,media(req,full))
    channel.send.side_effect=None;connection.retry_source_command()
    assert channel.send.call_args.args[0]==req
    dispatch(receiving,media(req,full))
    assert connection._source_pending is None and len(connection._source_media_pages)==1


def test_wrong_actual_offer_manifest_cannot_adopt_collected_media_metadata(receiving):
    connection=receiving[3];ready_source(receiving);full=manifest(receiving)
    collect(receiving,full)
    req=request(receiving,'offer_run')
    changed=FileManifest('4'*32,full.source_id,full.sender_id,full.receiver_id,full.files,full.total_bytes)
    offered=create_offer(changed);offered['expires_ms']=min(offered['expires_ms'],req['expires_ms'])
    with pytest.raises(TransferError,match='media_manifest_mismatch'):dispatch(receiving,offered)
    assert connection._offer is None and connection._catalog is None and connection._run is None
    assert connection._source_media_entries is None


def test_media_reply_cannot_extend_original_command_deadline(receiving):
    ready_source(receiving);full=manifest(receiving);req=request(receiving,'media_page')
    bad=media(req,full);bad['created_ms']=req['created_ms']+1;bad['expires_ms']=req['expires_ms']+1
    with pytest.raises(TransferError,match='deadline_changed'):dispatch(receiving,bad)
    assert receiving[3]._source_media_pages==() and receiving[3]._source_pending is not None


def test_malformed_media_deadline_is_a_strict_protocol_rejection_not_an_untyped_comparison(receiving):
    ready_source(receiving);full=manifest(receiving);req=request(receiving,'media_page')
    bad=media(req,full);bad['expires_ms']='future'
    with pytest.raises(TransferError):dispatch(receiving,bad)
    assert receiving[3]._source_media_pages==() and receiving[3]._source_pending is not None


def test_unsolicited_or_unready_media_metadata_never_falls_back_to_personal_actor(receiving,monkeypatch):
    service,_,_,connection,_=receiving
    forbid_legacy(service,monkeypatch)
    full=manifest(receiving)
    with pytest.raises(TransferError):request(receiving,'media_page')
    fake=dict(message_id=str(uuid.uuid4()),body=dict(operation='media_page'),expires_ms=2**53)
    with pytest.raises(TransferError,match='not_requested'):dispatch(receiving,media(fake,full))
    assert connection._source_media_pages==() and connection._catalog is None


def test_video_metadata_is_not_silently_received_in_photo_root_without_native_video_target_join(receiving):
    connection=receiving[3];ready_source(receiving);full=manifest(receiving)
    collect(receiving,full,'video');offered,result=send_offer(receiving,full);dispatch(receiving,result)
    with pytest.raises(TransferError,match='routing_unavailable'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    assert connection._catalog is None and connection._run is None


def test_animation_folder_selection_is_not_silently_ignored_by_unjoined_target_mapping(receiving):
    service,peer,channel,connection,_=receiving
    prefs=connection._preferences
    prefs.configure(prefs.issue_action(),prefs.read(),enabled=True,mode='manual',separate_animations=True)
    negotiate(service,peer,channel,connection)
    ready_source(receiving);full=manifest(receiving);req=request(receiving,'media_page')
    value=media(req,full);value['body']['page']['entries'][0]['media_kind']='animation';dispatch(receiving,value)
    offered,result=send_offer(receiving,full);dispatch(receiving,result)
    with pytest.raises(TransferError,match='routing_unavailable'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    assert connection._catalog is None and connection._run is None


def test_bidirectional_choice_is_not_silently_run_as_one_way_without_reverse_handlers(receiving):
    service,peer,channel,connection,_=receiving
    prefs=connection._preferences
    prefs.configure(prefs.issue_action(),prefs.read(),enabled=True,mode='manual',direction='bidirectional')
    negotiate(service,peer,channel,connection,receive_enabled=False)
    with pytest.raises(TransferError,match='not_ready'):request(receiving,'status')
    assert connection._catalog is None and connection._run is None
    assert not connection._preferences.local_grant(True).grants.send_files
    assert not connection._preferences.local_grant(True).grants.receive_files
    channel.send.assert_not_called()
