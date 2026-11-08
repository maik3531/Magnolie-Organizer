"""Actual native session actions, typed metadata, worker bytes and no overlap."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace

import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, negotiate
from test_file_desktop_video_album_worker import prepared_video, video_phone
from test_file_desktop_album_worker import prepared as prepared_images
from test_file_desktop_sources import response, CATALOG, ALBUM
from test_file_video_authority import ack_all
from magnolie_file_desktop_connection import NativeDesktopFileConnection, NativePhotoDesktopSession
from magnolie_file_transfer import TransferError
import magnolie_file_sources as sources


@contextmanager
def session_phone(fixture,target,batches,monkeypatch,*,video_enabled=True,read_allowed=True,grant_on_read=True,image_batches=None,**options):
    commands=[];revision=3;video_revision=1 if video_enabled else 0;armed=False
    video_batches=tuple(batches)
    def metadata(message):
        nonlocal revision,video_revision,video_enabled,armed,read_allowed
        body=message['body'];operation=body['operation'];scope=body.get('media_type','images')
        commands.append(deepcopy(body))
        def dispatch(value):fixture[0]._payload(fixture[1],fixture[2],value)
        version=f'{revision:x}'*64
        if operation in ('status','configure_videos'):
            if operation=='configure_videos':
                wanted=body['enabled']
                if wanted!=video_enabled:revision+=1;video_revision+=1;video_enabled=wanted
                armed=wanted
            dispatch(response(message,sources.RESULT,version=f'{revision:x}'*64,revision=revision,enabled=True,
                associated=True,repair_pending=False,kinds=['camera'],videos=dict(enabled=video_enabled,revision=video_revision)))
        elif operation=='discover':
            if scope=='video':assert armed and video_enabled,'Saved ON alone cannot arm the real source session'
            if image_batches is not None:batches[:]=video_batches if scope=='video' else image_batches
            dispatch(response(message,sources.CATALOG,version=version,**({'media_type':'video'} if scope=='video' else {}),
                page=dict(format=1,catalog_id=CATALOG,after=0,next_cursor=None,proves_deletion=False,
                    coverage=('full_videos' if scope=='video' else 'full_images') if read_allowed else 'none',
                    albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)] if read_allowed else [])))
        elif operation=='request_read':
            assert scope=='video' and armed
            dispatch(response(message,sources.PERMISSION_RESULT,version=version,state='notification_posted',media_type='video'))
            read_allowed=grant_on_read
        else:raise AssertionError(operation)
    with video_phone(fixture,target,batches,monkeypatch,metadata_handler=metadata,**options) as io:
        yield commands,io


def action(fixture,operation,**options):
    from magnolie_telefon import fingerprint,unb64
    service,peer=fixture[:2]
    return service.photo_sync_action(peer['device_id'],fingerprint(unb64(peer['static_public'],32)),dict(action=operation,**options))


def test_native_video_session_fresh_positive_handshake_typed_catalog_actual_sync_repeat_and_disable(receiving,tmp_path,monkeypatch):
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);connection=receiving[3];session=connection.desktop_session()
    grants=deepcopy(receiving[1]['grants']);local_grant=connection._preferences.local_grant(True).grants
    photo_root=connection._preferences.read().policy.destination
    sent=receiving[2].send.call_count
    assert 'video_supported' not in session.snapshot() and receiving[2].send.call_count==sent
    with session_phone(receiving,target,batches,monkeypatch) as (commands,(chunks,saved,_,_,errors)):
        action(receiving,'videos_enable');assert session.join(20),session.snapshot()
        assert session.snapshot()['state']=='albums' and session.snapshot()['video_enabled'],session.snapshot()
        assert [body['operation'] for body in commands]==['status','configure_videos','discover']
        assert commands[-1]['media_type']=='video' and not chunks and not saved
        assert session.snapshot()['video_destination']==str(target)
        for cycle in range(2):
            action(receiving,'videos_sync',album_id=ALBUM);assert session.join(60),session.snapshot()
            assert session.snapshot()['state']=='complete',session.snapshot()
            assert len(chunks)==len(saved)==2
            if cycle==0:
                path=target/batches[0].files[0].path;path.write_bytes(b'keep user video edit');before=(path.stat().st_ino,path.read_bytes())
            else:assert (path.stat().st_ino,path.read_bytes())==before
        action(receiving,'videos_disable');assert session.join(20),session.snapshot()
        assert session.snapshot()['state']=='videos_off' and not session.snapshot()['video_enabled']
        assert not connection._preferences.read().include_videos and commands[-1]['enabled'] is False
        assert not errors and not list(receiving[4].iterdir())
    assert receiving[1]['grants']==grants and connection._preferences.local_grant(True).grants==local_grant
    assert connection._preferences.read().policy.destination==photo_root


def test_native_video_session_default_uses_native_videos_and_does_not_create_photo_choice_or_request_read_on_inspection(receiving,tmp_path,monkeypatch):
    batches=prepared_images(receiving)[:1];connection=receiving[3];service,peer,channel=receiving[:3]
    peer['capabilities']['items']['device_status']['versions'].append(22);service.store.save_peers();ack_all(service,peer,channel)
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    monkeypatch.setattr(NativeDesktopFileConnection,'_video_data_handlers_ready',True)
    from gi.repository import GLib
    videos=tmp_path/'Native-Videos';videos.mkdir(mode=0o700);seen=[]
    def native_dir(kind):
        seen.append(kind);assert kind==GLib.UserDirectory.DIRECTORY_VIDEOS;return str(videos)
    monkeypatch.setattr(GLib,'get_user_special_dir',native_dir)
    session=connection.desktop_session();assert not seen
    with session_phone(receiving,videos,batches,monkeypatch,video_enabled=False,read_allowed=False,grant_on_read=False) as (commands,(chunks,saved,_,_,_)):
        action(receiving,'videos_enable');assert session.join(20),session.snapshot()
        state=session.snapshot();assert state['state']=='permission_required',state
        from pathlib import Path
        target=Path(state['video_destination']);assert target.parent==videos and target.name.endswith('-Videos')
        assert seen and not chunks and not saved and not any(body['operation']=='request_read' for body in commands)
        action(receiving,'videos_request_read');assert session.join(20),session.snapshot()
        assert session.snapshot()['state']=='permission_required' and not chunks and not saved
        assert commands[-2]['operation']=='request_read' and commands[-2]['media_type']=='video'
        assert session.snapshot()['video_albums']==[] and not list(target.iterdir())


def test_video_session_busy_disable_waits_for_actual_worker_end_and_keeps_original_job(receiving,tmp_path,monkeypatch):
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);connection=receiving[3];session=connection.desktop_session()
    with session_phone(receiving,target,batches,monkeypatch,block_chunk=True) as (commands,(_,saved,entered,release,errors)):
        action(receiving,'videos_enable');assert session.join(20)
        action(receiving,'videos_sync',album_id=ALBUM);assert entered.wait(15),session.snapshot()
        worker=session._worker;job=connection._run.receiver.job
        with pytest.raises(TransferError,match='busy'):action(receiving,'videos_sync',album_id=ALBUM)
        action(receiving,'videos_disable')
        assert session.snapshot()['busy'] and not worker.io_ended and session.snapshot()['state']=='stopping'
        release.set();assert session.join(45),session.snapshot()
        assert worker.io_ended and session.snapshot()['state']=='videos_off',session.snapshot()
        assert not errors and not saved and not connection._preferences.read().include_videos
        assert not list(target.rglob('*.mp4')) and connection._run is None
        assert connection._catalog.jobs()==(job,)
        assert commands[-1]['operation']=='configure_videos' and commands[-1]['enabled'] is False


def test_explicit_native_video_default_preserves_old_files_history_and_idempotent_choice(receiving,tmp_path,monkeypatch):
    old,_=prepared_video(receiving,tmp_path,monkeypatch);connection=receiving[3];prefs=connection._preferences
    before=prefs.read();prefs.set_video_scope(prefs.issue_action(),before,enabled=False)
    photo=prefs.read().policy.destination;history=(prefs.read().policy.job_catalog,connection._catalog)
    original=old/'keep-existing.mp4';original.write_bytes(b'keep this old destination untouched')
    from magnolie_media_backups import NativeMediaBackupLocations
    from magnolie_file_acceptance import NativeAcceptedDestination
    from magnolie_telefon import canonical
    from hashlib import sha256
    scope=sha256(canonical(dict(subject=prefs._subject,media_type='video'))).hexdigest()
    first_root=tmp_path/'former-default';first_root.mkdir(mode=0o700)
    with NativeMediaBackupLocations(connection._authority.binding.native_directory,scope,lambda:True) as locations:
        locations.choose(locations.issue_action(),locations.read(),NativeAcceptedDestination.capture(first_root),None)
    from gi.repository import GLib
    videos=tmp_path/'Native-Videos';videos.mkdir(mode=0o700)
    def directory(kind):
        assert kind==GLib.UserDirectory.DIRECTORY_VIDEOS;return str(videos)
    monkeypatch.setattr(GLib,'get_user_special_dir',directory)
    session=connection.desktop_session();session._automatic_paused=True
    sent=receiving[2].send.call_count
    action(receiving,'videos_default_destination');assert session.join(15),session.snapshot()
    state=session.snapshot();saved=prefs.read()
    assert state['state']=='videos_off',state.get('error')
    assert not state['video_enabled'] and session._automatic_paused
    assert saved.policy.videos.destination.path.startswith(str(videos)+'/') and not saved.policy.videos.enabled
    assert saved.policy.destination==photo and (saved.policy.job_catalog,connection._catalog)==history and original.read_bytes()==b'keep this old destination untouched'
    with NativeMediaBackupLocations(connection._authority.binding.native_directory,scope,lambda:True) as locations:
        paths={str(parent.path) for _,parent in locations.sources(saved.policy.videos.destination)}
        assert {str(old),str(first_root),saved.policy.videos.destination.path}<=paths
    assert receiving[2].send.call_count==sent # Choosing storage is not a READ, data grant or synchronization.
    action(receiving,'videos_default_destination');assert session.join(15),session.snapshot()
    assert prefs.read()==saved and session._automatic_paused # No token/revision rotation for an already selected default.
    enabled=prefs.set_video_scope(prefs.issue_action(),saved,enabled=True)
    action(receiving,'videos_default_destination');assert session.join(15),session.snapshot()
    assert session.snapshot()['state']=='held' and prefs.read()==enabled


def test_unsupported_video_session_action_cannot_create_destination_or_emit_positive_metadata(receiving,tmp_path,monkeypatch):
    prepared_images(receiving);connection=receiving[3];session=connection.desktop_session();before=connection._preferences.read()
    monkeypatch.setattr(receiving[0],'_resume_automatic_photos',lambda *args:None)
    ack_all(*receiving[:3])
    sent=receiving[2].send.call_count
    action(receiving,'videos_enable');assert session.join(10)
    assert session.snapshot()['state']=='held' and 'video_supported' not in session.snapshot()
    assert connection._preferences.read()==before and receiving[2].send.call_count==sent


def test_explicit_automatic_session_runs_photo_then_video_serially_with_fresh_video_handshake(receiving,tmp_path,monkeypatch):
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);batches=batches[:1];connection=receiving[3]
    images=[replace(batches[0],source_id='f'*32,transfer_id='f'*32,
        files=(replace(batches[0].files[0],id='e'*32,path='Camera/0.jpg'),))]
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',60)
    session=connection.desktop_session();events=[];observer=connection._activity_changed
    def activity(owner,active):
        if hasattr(owner,'_media_type'):
            if active:assert all(previous.io_ended for previous,started in events if started)
            else:assert owner.io_ended
            events.append((owner,active))
        if observer is not None:observer(owner,active)
    monkeypatch.setattr(connection,'_activity_changed',activity)
    with session_phone(receiving,target,batches,monkeypatch,image_batches=images) as (commands,(chunks,saved,_,_,errors)):
        action(receiving,'videos_enable');assert session.join(20),session.snapshot()
        assert session.snapshot()['mode']=='manual' and not chunks and not saved
        action(receiving,'mode_automatic');assert session.join(20),session.snapshot()
        due=session._schedule.take_due();assert due is not None
        session.start('automatic',schedule_run=due);assert session.join(60),session.snapshot()
        assert session.snapshot()['state']=='complete' and not errors,(session.snapshot()['state'],session.snapshot()['error'])
        assert len(chunks)==len(saved)==2 and session._schedule.active is None
        assert [owner._media_type for owner,started in events if started]==['images','video']
        assert [active for _,active in events]==[True,False,True,False]
        assert (receiving[4]/'Camera/0.jpg').read_bytes()==(target/'Camera/0.mp4').read_bytes()==b'hello'
        discoveries=[body.get('media_type','images') for body in commands if body['operation']=='discover']
        assert discoveries==['video','images','video']
        assert sum(body['operation']=='configure_videos' and body['enabled'] for body in commands)==2
        action(receiving,'mode_manual');assert session.join(20)


def test_metadata_only_control_agreement_cannot_send_positive_video_configuration_without_source_data_grant(receiving,tmp_path,monkeypatch):
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    from magnolie_file_control import FileControlPacket
    from magnolie_telefon import now_ms
    import uuid
    old=connection._controls._remote
    packet=FileControlPacket(replace(old.grants,revision=old.grants.revision+1,epoch='e'*64,send_files=False),
        old.session_epoch,old.sequence+1,old.echo)
    now=now_ms()
    receiving[0]._payload(receiving[1],receiving[2],dict(type='message',v=1,message_id=str(uuid.uuid4()),
        kind='file_transfer.control',created_ms=now,expires_ms=now+60000,body=packet.wire()))
    session=connection.desktop_session()
    with session_phone(receiving,target,batches,monkeypatch) as (commands,(chunks,saved,_,_,errors)):
        action(receiving,'videos_enable');assert session.join(20),session.snapshot()
        assert session.snapshot()['state']=='held' and session.snapshot()['error']=='file_desktop_receive_controls_not_agreed'
        assert [body['operation'] for body in commands]==['status']
        assert not chunks and not saved and not errors and not list(target.iterdir())


def test_failed_remote_disable_cannot_restore_saved_local_video_consent(receiving,tmp_path,monkeypatch):
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);connection=receiving[3];session=connection.desktop_session()
    with session_phone(receiving,target,batches,monkeypatch) as (commands,(_,saved,_,_,_)):
        action(receiving,'videos_enable');assert session.join(20)
        command=session._command
        def fail_remote(operation,**options):
            if operation=='configure_videos' and options.get('enabled') is False:
                assert not connection._preferences.read().include_videos
                raise TransferError('fixture_native_disable_failure')
            return command(operation,**options)
        monkeypatch.setattr(session,'_command',fail_remote)
        action(receiving,'videos_disable');assert session.join(20)
        assert session.snapshot()['state']=='held' and session.snapshot()['error']=='fixture_native_disable_failure'
        assert not session.snapshot()['video_enabled'] and not connection._preferences.read().include_videos
        assert not saved and not list(target.iterdir())


def test_video_controls_projection_uses_current_acknowledged_capability_not_cached_session_support(receiving,tmp_path,monkeypatch):
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);service,peer,channel,connection=receiving[:4]
    session=connection.desktop_session();sent=channel.send.call_count;before=connection._preferences.read()
    state=service.photo_sync_state(peer['device_id'])
    assert state['video_supported'] is True and state['video_enabled'] is False
    assert channel.send.call_count==sent and connection._preferences.read()==before
    with session_phone(receiving,target,batches,monkeypatch) as (_,(_,_,_,_,_)):
        action(receiving,'videos_enable');assert session.join(20)
        assert service.photo_sync_state(peer['device_id'])['video_enabled']
    peer['capabilities']['items']['device_status']['versions'].remove(22);peer['capabilities']['revision']+=1
    service.store.save_peers();ack_all(service,peer,channel)
    state=service.photo_sync_state(peer['device_id'])
    assert state is not None and not any(field.startswith('video_') for field in state)
    assert connection._preferences.read().include_videos and session.snapshot()['video_supported']


def test_actual_organizer_gtk_ipc_video_actions_reach_typed_session_and_saved_bytes(receiving,tmp_path,monkeypatch,request):
    from test_photo_desktop_workflow import native_ui
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);batches=batches[:1]
    service,peer,_,connection=receiving[:4];session=connection.desktop_session()
    ui=native_ui(service,peer,request)
    with session_phone(receiving,target,batches,monkeypatch) as (commands,(chunks,saved,_,_,errors)):
        ui(dict(action='videos_enable'));assert session.join(20),session.snapshot()
        assert session.snapshot()['state']=='albums',session.snapshot()
        ui(dict(action='videos_sync',album_id=ALBUM));assert session.join(45),session.snapshot()
        assert session.snapshot()['state']=='complete' and session.snapshot()['active_media']=='video',session.snapshot()
        assert not errors and len(chunks)==len(saved)==1
        assert (target/batches[0].files[0].path).read_bytes()==b'hello'
        assert not list(receiving[4].iterdir())
        assert sum(body['operation']=='configure_videos' and body['enabled'] for body in commands)==2
