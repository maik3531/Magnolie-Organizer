"""Actual explicitly typed video worker; private gates remain OFF in product."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_album_worker import phone_batches
from test_file_desktop_album_worker import prepared as prepared_images
from test_file_desktop_video_source_owner import begin, run_reply
from test_file_desktop_video_metadata import prepare as prepare_video_preferences
from test_file_desktop_sources import request, ALBUM
from test_file_desktop_media import manifest
from magnolie_file_transfer import TransferError
import magnolie_file_sources as sources


def prepared_video(fixture, tmp_path, monkeypatch):
    target = begin(fixture, tmp_path, monkeypatch, storage=True)
    for operation in ('cancel_run', 'end_run'):
        command = request(fixture, operation)
        run_reply(fixture, command, state='canceled_held', **({'run_ended': True} if operation == 'end_run' else {}))
    # Same explicit positive metadata command required by the real native owner
    # after its base data ACK; saved positive status alone is not the handshake.
    command = request(fixture, 'configure_videos', enabled=True)
    from test_file_desktop_sources import response, CATALOG
    fixture[0]._payload(fixture[1],fixture[2],response(command,sources.RESULT,version='3'*64,revision=3,
        enabled=True,associated=True,repair_pending=False,kinds=['camera'],videos=dict(enabled=True,revision=1)))
    # Metadata configure invalidates old previews: rediscover the typed catalog.
    command = request(fixture, 'discover', media_type='video')
    fixture[0]._payload(fixture[1], fixture[2], response(command, sources.CATALOG, version='3'*64, media_type='video',
        page=dict(format=1,catalog_id=CATALOG,after=0,next_cursor=None,coverage='full_videos',proves_deletion=False,
            albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)])))
    base = manifest(fixture)
    batches = [replace(base, source_id=char*32, transfer_id=char*32,
        files=(replace(base.files[0],id=char*32,path=f'Camera/{index}.mp4'),)) for index,char in enumerate(('a','b'))]
    return target, batches


@contextmanager
def video_phone(fixture, target, batches, monkeypatch, **options):
    # Reuse the real encrypted/chunk/Saved/END fixture, changing ONLY the peer's
    # strict typed source reply fields. Product code still owns all actual I/O.
    service, connection = fixture[0], fixture[3]
    original = service._payload
    def typed(peer, channel, message):
        if message.get('kind') in (sources.RUN_RESULT,sources.MEDIA,sources.RESUME,sources.ABANDONED):
            message = deepcopy(message)
            pending = connection._source_pending
            assert pending is not None
            body = message['body']
            body['version'] = pending.command.expected_version
            if pending.command.media_type == 'video':
                body['media_type'] = 'video'
                if message['kind'] == sources.MEDIA:
                    body['page']['media_type'] = 'video'
                    for entry in body['page']['entries']: entry['media_kind'] = 'video'
        return original(peer,channel,message)
    with monkeypatch.context() as patch:
        patch.setattr(service,'_payload',typed)
        with phone_batches((*fixture[:4],target),batches,**options) as result:
            yield result


def test_actual_video_worker_two_batches_and_repeat_keep_video_root_token_edits_and_photo_root(receiving,tmp_path,monkeypatch):
    target,batches = prepared_video(receiving,tmp_path,monkeypatch)
    connection = receiving[3]; activity = []
    for cycle in range(2):
        with video_phone(receiving,target,batches,monkeypatch) as (chunks,saved,_,_,errors):
            worker = connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video',
                activity_changed=lambda owner,active:activity.append((owner,active)))
            assert worker.join(60),worker.progress()
            assert not errors and worker.progress()['state'] == 'complete',worker.progress()
            assert len(chunks) == len(saved) == (2 if cycle == 0 else 0)
            assert worker.progress()['known_files'] == (0 if cycle == 0 else 2)
            assert activity[-2:] == [(worker,True),(worker,False)]
        path=target/'Camera/0.mp4'
        if cycle == 0:
            path.write_bytes(b'keep local video edit'); before=(path.stat().st_ino,path.read_bytes())
        else: assert (path.stat().st_ino,path.read_bytes()) == before
    assert not list(receiving[4].iterdir())
    assert all(job.accepted.destination.path == str(target) and job.reserved_bytes == 0 for job in connection._catalog.jobs())


def test_actual_video_worker_stopped_original_job_resumes_without_redownload_and_ends_before_retirement(receiving,tmp_path,monkeypatch):
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);batches=batches[:1];connection=receiving[3]
    with video_phone(receiving,target,batches,monkeypatch,block_chunk=True) as (_,_,entered,release,_):
        first=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video')
        assert entered.wait(10)
        receiver=connection._run.receiver;job=receiver.job;history=receiver._index.media_history
        first.stop();release.set();assert first.join(30),first.progress()
        assert first.progress()['state']=='canceled',first.progress()
    assert not (target/'Camera/0.mp4').exists()
    with video_phone(receiving,target,batches,monkeypatch,resume_job=job,resume_media=history) as (chunks,saved,_,_,errors):
        second=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video')
        assert second.join(60),second.progress()
        assert not errors and second.progress()['state']=='complete',second.progress()
        assert not chunks and len(saved)==1
        assert (target/'Camera/0.mp4').read_bytes()==b'hello'
        jobs=connection._catalog.jobs()
        assert len(jobs)==1 and jobs[0].owner==job.owner and jobs[0].reserved_bytes==0
        assert connection._run is None and connection._resume_source_id is None


def test_video_worker_never_infers_scope_from_current_catalog_or_bypasses_private_gate(receiving,tmp_path,monkeypatch):
    prepared_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    with pytest.raises(TransferError,match='album_not_current'):
        connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
    monkeypatch.setattr(connection,'_video_data_handlers_ready',False)
    with pytest.raises(TransferError,match='video_data_join_unavailable'):
        connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video')
    assert connection._album_worker is None


def test_video_worker_mixed_known_and_new_members_uses_typed_selection_and_only_downloads_new_file(receiving,tmp_path,monkeypatch):
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    ids={full.files[0].path:sha256(full.files[0].path.encode()).hexdigest() for full in batches}
    with video_phone(receiving,target,batches[:1],monkeypatch,photo_ids=ids) as (chunks,saved,_,_,_):
        first=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video')
        assert first.join(45) and first.progress()['state']=='complete',first.progress()
        assert len(chunks)==len(saved)==1
    files=(batches[0].files[0],batches[1].files[0])
    mixed=replace(batches[0],source_id='e'*32,transfer_id='e'*32,files=files,total_bytes=sum(file.size for file in files))
    with video_phone(receiving,target,[mixed],monkeypatch,photo_ids=ids) as (chunks,saved,_,_,_):
        second=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video')
        assert second.join(60) and second.progress()['state']=='complete',second.progress()
        assert second.progress()['saved_files']==second.progress()['known_files']==1
        assert chunks==[files[1].id] and len(saved)==1
    selects=[call.args[0] for call in receiving[2].send.call_args_list
        if call.args[0].get('body',{}).get('operation')=='select_run']
    assert len(selects)==1 and selects[0]['body']['media_type']=='video'
    assert (target/files[0].path).read_bytes()==(target/files[1].path).read_bytes()==b'hello'
    assert not list(receiving[4].iterdir())


def test_image_worker_remains_independent_when_video_preference_is_enabled_but_video_data_gate_is_off(receiving,tmp_path,monkeypatch):
    monkeypatch.setattr(receiving[3],'_video_data_handlers_ready',False)
    batches=prepared_images(receiving)[:1]
    target=prepare_video_preferences(receiving,tmp_path,monkeypatch)
    connection=receiving[3]
    assert not connection._video_data_handlers_ready and connection._preferences.read().include_videos
    with phone_batches(receiving,batches) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(45) and worker.progress()['state']=='complete',worker.progress()
        assert not errors and len(chunks)==len(saved)==1
    assert (receiving[4]/batches[0].files[0].path).read_bytes()==b'hello'
    assert not list(target.iterdir())
