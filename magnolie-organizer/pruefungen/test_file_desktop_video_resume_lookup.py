"""Explicit original VIDEO selection grants only a typed historical lookup."""
import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_video_receive import admit_video,end_source
from test_file_desktop_resume_lookup import history
from test_file_desktop_sources import request,ALBUM
from magnolie_file_transfer import TransferError


def original(fixture,tmp_path,monkeypatch):
    _,_,run=admit_video(fixture,tmp_path,monkeypatch);connection=fixture[3]
    assert connection.request_normal_receive_stop(connection.issue_receive_action()).state=='stopped'
    end_source(fixture)
    def forbidden(*args,**kwargs):raise AssertionError('VIDEO lookup attempted native stage admission/resume')
    monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.resume',forbidden)
    monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.accept',forbidden)
    return connection,run.job


def lookup(fixture,job):
    connection=fixture[3]
    connection.request_resume_lookup(connection.issue_receive_action(),job.owner,media_type='video')
    return fixture[2].send.call_args.args[0]


def reply(req,job):
    result=history(req,job,attempt_phase=None)
    result['body'].update(version=req['body']['expected_version'],media_type='video')
    return result


def test_explicit_video_lookup_uses_current_video_scope_and_projects_only_original_history_without_stage_read(
        receiving,tmp_path,monkeypatch):
    connection,job=original(receiving,tmp_path,monkeypatch)
    sent=receiving[2].send.call_count
    with pytest.raises(TransferError):connection.request_resume_lookup(connection.issue_receive_action(),job.owner)
    assert receiving[2].send.call_count==sent
    req=lookup(receiving,job)
    assert req['body']['media_type']=='video' and req['body']['manifest_sha256']==job.accepted.manifest.fingerprint
    assert connection._receive_binding()==job.accepted.binding
    receiving[0]._payload(receiving[1],receiving[2],reply(req,job))
    assert connection._resume_history.media_type=='video' and connection._resume_lookup_selection.media_type=='video'
    assert connection._catalog.jobs()==(job,) and connection._run is None and connection._source_run is None
    resumed=request(receiving,'resume_run',media_type='video',album_id=ALBUM,desktop_choice=True)
    assert resumed['body']['media_type']=='video' and resumed['body']['original_job_id']=='b'*32


def test_video_lookup_cannot_consume_legacy_image_reply_or_silently_relabel_it(receiving,tmp_path,monkeypatch):
    connection,job=original(receiving,tmp_path,monkeypatch);req=lookup(receiving,job)
    wrong=reply(req,job);wrong['body'].pop('media_type')
    with pytest.raises(TransferError,match='media_scope_changed'):receiving[0]._payload(receiving[1],receiving[2],wrong)
    assert connection._resume_history is None and connection._source_pending is not None
    assert connection._catalog.jobs()==(job,) and connection._run is None


@pytest.mark.parametrize('withdrawal',['capability','consent','data_gate'])
def test_video_lookup_refuses_withdrawn_current_scope_before_command_or_stage(receiving,tmp_path,monkeypatch,withdrawal):
    connection,job=original(receiving,tmp_path,monkeypatch)
    if withdrawal=='capability':
        receiving[1]['capabilities']['items']['device_status']['versions'].remove(22);receiving[0].store.save_peers()
    elif withdrawal=='consent':
        prefs=connection._preferences;prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=False)
    else:monkeypatch.setattr(type(connection),'_video_data_handlers_ready',False)
    sent=receiving[2].send.call_count
    with pytest.raises(TransferError):lookup(receiving,job)
    assert receiving[2].send.call_count==sent and connection._source_pending is None
    assert connection._run is None and connection._catalog.jobs()==(job,)


def test_pending_video_lookup_cannot_reuse_an_off_on_local_policy_revision(receiving,tmp_path,monkeypatch):
    connection,job=original(receiving,tmp_path,monkeypatch);req=lookup(receiving,job)
    prefs=connection._preferences
    off=prefs.set_video_scope(prefs.issue_action(),prefs.read(),enabled=False)
    prefs.set_video_scope(prefs.issue_action(),off,enabled=True)
    with pytest.raises(TransferError,match='video_policy_changed'):
        receiving[0]._payload(receiving[1],receiving[2],reply(req,job))
    assert connection._resume_history is None and connection._catalog.jobs()==(job,)


def test_original_video_lookup_requires_current_enabled_native_video_policy_not_only_an_old_job(receiving,tmp_path,monkeypatch):
    from test_file_desktop_video_metadata import status
    connection,job=original(receiving,tmp_path,monkeypatch)
    status(receiving,revision=4,enabled=False,video_revision=2)
    sent=receiving[2].send.call_count
    with pytest.raises(TransferError,match='video_source_not_configured'):lookup(receiving,job)
    assert receiving[2].send.call_count==sent and connection._source_pending is None
    assert connection._run is None and connection._catalog.jobs()==(job,)
