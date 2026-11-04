"""Actual original VIDEO stage resume; source END precedes cache retirement."""
import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,chunk
from test_file_desktop_video_receive import admit_video,end_source
from test_file_desktop_video_resume_lookup import lookup,reply
from test_file_desktop_video_source_owner import run_reply
from test_file_desktop_sources import request,response,ALBUM
from magnolie_file_offer import create_offer
from magnolie_file_transfer import TransferError
import magnolie_file_sources as sources

RESUMED='77777777-7777-4777-8777-777777777777'


def resume_video(fixture,tmp_path,monkeypatch,*,epoch='c'*64):
    target,full,old=admit_video(fixture,tmp_path,monkeypatch);connection=fixture[3]
    assert connection.request_normal_receive_stop(connection.issue_receive_action()).state=='stopped'
    end_source(fixture);job=old.job
    req=lookup(fixture,job);fixture[0]._payload(fixture[1],fixture[2],reply(req,job))
    req=request(fixture,'resume_run',album_id=ALBUM,desktop_choice=True)
    assert req['body']['media_type']=='video' and req['body']['original_job_id']=='b'*32
    run_reply(fixture,req,run_id=RESUMED)
    req=request(fixture,'resume_media_page')
    media=response(req,sources.MEDIA,version=req['body']['expected_version'],run_id=RESUMED,media_type='video',
        page=dict(format=1,manifest_sha256=full.fingerprint,source_epoch=epoch,media_type='video',insertion_witness=False,
            after=0,next_cursor=None,total_files=1,entries=[dict(file_id=full.files[0].id,photo_id='d'*64,media_kind='video')]))
    media['expires_ms']=min(media['expires_ms'],req['expires_ms']);fixture[0]._payload(fixture[1],fixture[2],media)
    req=request(fixture,'offer_resume');offered=create_offer(full)
    offered['expires_ms']=min(offered['expires_ms'],req['expires_ms']);fixture[0]._payload(fixture[1],fixture[2],offered)
    run_reply(fixture,req,run_id=RESUMED,offer_id=offered['message_id'],manifest_sha256=full.fingerprint)
    connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],job.owner)
    assert connection._run.job==job and connection._run.media_type=='video' and len(connection._catalog.jobs())==1
    return target,full,job,connection._run


def end_resume(fixture):
    req=request(fixture,'cancel_resume');run_reply(fixture,req,run_id=RESUMED,state='canceled_held')
    req=request(fixture,'end_resume');run_reply(fixture,req,run_id=RESUMED,state='canceled_held',run_ended=True)


def test_actual_original_video_resume_keeps_original_acceptance_saved_and_ends_source_before_retirement(receiving,tmp_path,monkeypatch):
    target,full,job,run=resume_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    receiving[0]._payload(receiving[1],receiving[2],chunk(connection.request_next_chunk(),b'hello'))
    connection.publish_received(connection.issue_receive_action())
    assert connection._catalog.jobs()==(job,) and job.cache_retirement_sha256 is None
    assert run.receiver._index.saved_mapping_receipt() is not None
    with pytest.raises(TransferError,match='resume_source_end_required'):
        connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True)
    assert connection._catalog.jobs()==(job,) and not run.receiver._closed
    end_resume(receiving)
    assert connection._source_run is None and connection._run is run and connection._catalog.jobs()==(job,)
    connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True)
    retired=connection._catalog.jobs()[0]
    assert retired.owner==job.owner and retired.reserved_bytes==0 and retired.cache_retirement_sha256
    assert (target/full.files[0].path).read_bytes()==b'hello' and not list(receiving[4].iterdir())


@pytest.mark.parametrize('withdrawal',['capability','local_consent','data_gate'])
def test_original_video_resume_withdrawal_blocks_read_but_drains_closes_and_ends_exact_owner_without_saved_or_retirement(
        receiving,tmp_path,monkeypatch,withdrawal):
    target,full,job,run=resume_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    connection.request_next_chunk()
    if withdrawal=='capability':
        receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    elif withdrawal=='local_consent':
        prefs=connection._preferences;prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=False)
    else:monkeypatch.setattr(type(connection),'_video_data_handlers_ready',False)
    with pytest.raises(TransferError):connection.request_next_chunk()
    state=connection.request_receive_stop(connection.issue_receive_action())
    assert state.state=='pending' and not run.receiver._closed
    end_resume(receiving)
    state=connection.receive_stop_state()
    assert state.state=='stopped' and state.resources_closed and state.checkpoint_committed
    assert run.receiver._closed and connection._run is None and connection._source_run is None
    assert connection._checkpoint_binding_owner is None and connection._catalog.jobs()==(job,)
    assert job.cache_retirement_sha256 is None and job.reserved_bytes>0
    assert not (target/full.files[0].path).exists() and not list(receiving[4].iterdir())
    assert not any(call.args[0]['kind']=='file_transfer.saved' for call in receiving[2].send.call_args_list)


def test_saved_original_video_resume_can_end_after_capability_withdrawal_but_cannot_retire_without_current_scope(
        receiving,tmp_path,monkeypatch):
    from test_file_video_authority import ack_all
    _,_,job,run=resume_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    receiving[0]._payload(receiving[1],receiving[2],chunk(connection.request_next_chunk(),b'hello'))
    connection.publish_received(connection.issue_receive_action())
    receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    end_resume(receiving)
    assert connection._source_run is None and connection._run is run and connection._catalog.jobs()==(job,)
    with pytest.raises(TransferError):connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True)
    assert connection._catalog.jobs()==(job,)
    receiving[1]['capabilities']['items']['device_status']['versions'].append(22);receiving[0].store.save_peers()
    ack_all(*receiving[:3])
    connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True)
    assert connection._catalog.jobs()[0].reserved_bytes==0


def test_original_video_resume_end_output_loss_keeps_owner_and_quota_until_exact_typed_retry(receiving,tmp_path,monkeypatch):
    _,_,job,run=resume_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    receiving[0]._payload(receiving[1],receiving[2],chunk(connection.request_next_chunk(),b'hello'))
    connection.publish_received(connection.issue_receive_action())
    req=request(receiving,'cancel_resume');run_reply(receiving,req,run_id=RESUMED,state='canceled_held')
    receiving[2].send.side_effect=OSError('fixture resumed VIDEO END output uncertain')
    with pytest.raises(OSError):request(receiving,'end_resume')
    pending=connection._source_pending;original=pending.message
    assert original['body']['media_type']=='video' and connection._catalog.jobs()==(job,)
    with pytest.raises(TransferError,match='resume_source_end_required'):
        connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True)
    receiving[2].send.side_effect=None;connection.retry_source_command()
    assert connection._source_pending is pending and receiving[2].send.call_args.args[0]==original
    run_reply(receiving,original,run_id=RESUMED,state='canceled_held',run_ended=True)
    connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True)
    assert connection._catalog.jobs()[0].owner==job.owner and connection._catalog.jobs()[0].reserved_bytes==0


def test_ended_unsaved_original_video_attempt_requires_explicit_typed_abandonment_and_keeps_job_and_cache(receiving,tmp_path,monkeypatch):
    from test_file_desktop_resume_lookup import history
    _,_,job,run=resume_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    assert connection.request_receive_stop(connection.issue_receive_action()).state=='stopped'
    end_resume(receiving)
    req=lookup(receiving,job)
    hint=history(req,job,attempt_phase='accepted');hint['body'].update(version='3'*64,media_type='video')
    receiving[0]._payload(receiving[1],receiving[2],hint)
    sent=receiving[2].send.call_count
    assert connection._resume_abandonment is None and connection._catalog.jobs()==(job,)
    connection.request_resume_abandonment(connection.issue_receive_action())
    command=receiving[2].send.call_args.args[0]
    assert receiving[2].send.call_count==sent+1 and command['body']['media_type']=='video'
    result=response(command,sources.ABANDONED,version='3'*64,run_id=RESUMED,media_type='video',job_id='b'*32,
        job_version='c'*64,attempt_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',attempt_sha256='d'*64,receipt_sha256='e'*64)
    result['expires_ms']=min(result['expires_ms'],command['expires_ms'])
    receiving[0]._payload(receiving[1],receiving[2],result)
    assert connection._resume_abandonment.media_type=='video' and connection._catalog.jobs()==(job,)
    assert run.receiver._closed and connection._run is None and job.cache_retirement_sha256 is None


def test_changed_video_source_epoch_is_held_before_reopening_the_original_receive_stage(receiving,tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('new VIDEO epoch reopened original stage')
    monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.resume',forbidden)
    with pytest.raises(TransferError,match='resume_media_association_changed'):
        resume_video(receiving,tmp_path,monkeypatch,epoch='e'*64)
    connection=receiving[3]
    assert connection._run is None and len(connection._catalog.jobs())==1
    assert connection._catalog.jobs()[0].reserved_bytes>0
    assert not any(call.args[0]['kind']=='file_transfer.chunk.request' for call in receiving[2].send.call_args_list)
