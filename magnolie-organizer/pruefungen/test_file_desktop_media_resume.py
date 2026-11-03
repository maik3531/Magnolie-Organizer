"""Resume checks old opaque associations, not equality of new request UUIDs."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_file_receive import NativeFileReceiveOperation
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,accept
from test_file_desktop_sources import request,ready_source
from test_file_desktop_media import media,dispatch,send_offer,collect
from test_file_media_history import admit,unpublished


def retry_offer(fixture,change=None):
    connection=fixture[3];receiver=admit(fixture)
    job=receiver.job;original=receiver._index.media_history
    receiver.close();connection._run=None
    connection._source_media_pages=();connection._source_media_entries=None
    connection._source_offer=None;connection._offer=None
    req=request(fixture,'media_page');reply=media(req,job.accepted.manifest)
    if change=='epoch':reply['body']['page']['source_epoch']='e'*64
    elif change=='id':reply['body']['page']['entries'][0]['photo_id']='f'*64
    elif change=='kind':reply['body']['page']['entries'][0]['media_kind']='unknown_image'
    dispatch(fixture,reply)
    offered,result=send_offer(fixture,job.accepted.manifest);dispatch(fixture,result)
    return receiver,job,original,offered


def test_new_exact_page_attempt_can_resume_same_original_association_without_rewriting_history(receiving):
    connection=receiving[3];receiver,job,original,offered=retry_offer(receiving)
    assert connection._source_media_pages[0].request_id!=original.attempts[0][0]
    connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],job.owner)
    assert connection._run.receiver._index.media_history==original
    assert connection._run.receiver.progress().owner==job.owner
    assert len(connection._catalog.jobs())==1
    unpublished(receiving,receiver)


@pytest.mark.parametrize('change',['epoch','id','kind'])
def test_changed_stable_media_association_is_held_before_native_receiver_resume(receiving,monkeypatch,change):
    connection=receiving[3];receiver,job,original,offered=retry_offer(receiving,change)
    def forbidden(*args,**kwargs):raise AssertionError('changed association must not reopen receive stage')
    monkeypatch.setattr('magnolie_file_desktop_connection.NativeFileReceiveOperation.resume',forbidden)
    before=receiving[2].send.call_count
    with pytest.raises(TransferError,match='resume_media_association_changed'):
        connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],job.owner)
    assert connection._run is None and receiving[2].send.call_count==before
    assert len(connection._catalog.jobs())==1
    unpublished(receiving,receiver)


def test_missing_fresh_media_cannot_resume_anchored_job_through_legacy_path(receiving):
    connection=receiving[3];receiver,job,original,offered=retry_offer(receiving)
    connection._source_media_pages=();connection._source_media_entries=None
    with pytest.raises(TransferError,match='resume_media_history_required'):
        connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],job.owner)
    assert connection._run is None
    unpublished(receiving,receiver)


def test_new_media_pages_do_not_invent_an_anchor_for_existing_legacy_job(receiving):
    connection=receiving[3];_,full=accept(receiving)
    receiver=connection._run.receiver;job=receiver.job
    assert receiver._index.media_history is None
    receiver.close();connection._run=None;connection._offer=None
    ready_source(receiving);collect(receiving,full)
    offered,result=send_offer(receiving,full);dispatch(receiving,result)
    with pytest.raises(TransferError,match='resume_media_history_required'):
        connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],job.owner)
    assert connection._run is None and len(connection._catalog.jobs())==1
    unpublished(receiving,receiver)


def test_native_history_resume_reader_does_not_renew_revoked_binding(receiving):
    connection=receiving[3];receiver=admit(receiving);job=receiver.job
    receiver.close();connection._authority.revoke()
    protection=connection._authority.protection
    with pytest.raises(TransferError):
        NativeFileReceiveOperation.read_media_history(connection._catalog,job,connection._receive_binding,
            protection.seal,protection.unseal)
    unpublished(receiving,receiver)
