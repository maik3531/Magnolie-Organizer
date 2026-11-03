"""Future-only native animation grouping keeps original jobs and PC edits."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_sources import ALBUM
from test_file_desktop_album_worker import prepared,phone_batches
from test_photo_desktop_workflow import native_ui,converge_controls


def animation(fixture):
    base=prepared(fixture)[0]
    return replace(base,files=(replace(base.files[0],path='Camera/old.gif'),))


@pytest.mark.parametrize('capture',[False,True],ids=['animations_only','camera_and_animations'])
def test_gtk_layout_applies_only_to_new_animations_and_preserves_pc_edits_and_original_grants(receiving,request,capture):
    service,peer,channel,connection,target=receiving;converge_controls(service,peer,channel)
    first=animation(receiving)
    photos={'Camera/old.gif':sha256(b'old-photo').hexdigest(),'Camera/new.gif':sha256(b'new-photo').hexdigest(),
        'Camera/still.jpg':sha256(b'still-photo').hexdigest()}
    kinds={path:'animation' if path.endswith('.gif') else 'image' for path in photos}
    session=connection.desktop_session();session._local_enabled(True)
    action=native_ui(service,peer,request)
    with phone_batches(receiving,[first],photo_ids=photos,media_kinds=kinds):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(30) and worker.progress()['state']=='complete',worker.progress()
    original=target/'Camera/old.gif';original.write_bytes(b'keep PC animation edit')
    before=(original.stat().st_ino,original.read_bytes())
    binding=connection._receive_binding();grant=connection._preferences.local_grant(True).grants
    records=connection._mappings.read();jobs=connection._catalog.jobs()
    session._automatic_paused=True
    action(dict(action='animations_separate',historical_choice='keep_existing'))
    assert session.join(15) and session.snapshot()['separate_animations'],session.snapshot()
    if capture:
        action(dict(action='captures_separate',historical_choice='keep_existing'))
        assert session.join(15) and session.snapshot()['separate_own_recordings'],session.snapshot()
    assert session._automatic_paused
    assert connection._receive_binding()==binding and connection._preferences.local_grant(True).grants==grant
    assert connection._mappings.read()==records and connection._catalog.jobs()==jobs
    files=(first.files[0],replace(first.files[0],id='e'*32,path='Camera/new.gif'),
        replace(first.files[0],id='d'*32,path='Camera/still.jpg'))
    full=replace(first,source_id='f'*32,transfer_id='f'*32,files=files,total_bytes=15)
    with phone_batches(receiving,[full],photo_ids=photos,media_kinds=kinds,block_chunk=True) as (chunks,saved,entered,release,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10),worker.progress()
        with pytest.raises(TransferError,match='already_active'):
            worker._call(lambda:connection.set_future_animation_layout(connection.issue_receive_action(),separate=False,historical_choice='keep_existing'))
        release.set();assert worker.join(30),worker.progress()
        assert not errors and worker.progress()['state']=='complete',worker.progress()
        assert chunks==[files[1].id,files[2].id] and len(saved)==1
    prefix='Eigene Aufnahmen/' if capture else ''
    grouped=target/(prefix+'Animationen/Camera/new.gif');assert grouped.read_bytes()==b'hello'
    assert (target/(prefix+'Camera/still.jpg')).read_bytes()==b'hello' and not (target/(prefix+'Animationen/Camera/still.jpg')).exists()
    assert not (target/'Camera/new.gif').exists() and (original.stat().st_ino,original.read_bytes())==before
    grouped_before=(grouped.stat().st_ino,grouped.read_bytes())
    action(dict(action='animations_together',historical_choice='keep_existing'))
    assert session.join(15) and not session.snapshot()['separate_animations'],session.snapshot()
    assert connection._receive_binding()==binding and connection._preferences.local_grant(True).grants==grant
    with phone_batches(receiving,[full],photo_ids=photos,media_kinds=kinds) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(30) and worker.progress()['state']=='complete',worker.progress()
        assert not errors and not chunks and not saved
    assert (grouped.stat().st_ino,grouped.read_bytes())==grouped_before
    assert (original.stat().st_ino,original.read_bytes())==before


def test_layout_change_keeps_stopped_original_acceptance_and_resume_target(receiving):
    connection=receiving[3];full=animation(receiving);kinds={'Camera/old.gif':'animation'}
    with phone_batches(receiving,[full],media_kinds=kinds,block_chunk=True) as (_,_,entered,release,_):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10)
        receiver=connection._run.receiver;job=receiver.job;history=receiver._index.media_history
        worker.stop();release.set();assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='canceled',worker.progress()
    connection.set_future_animation_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    with phone_batches(receiving,[full],media_kinds=kinds,resume_job=job,resume_media=history) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(45),worker.progress()
        assert not errors and worker.progress()['state']=='complete',worker.progress()
        assert not chunks and len(saved)==1
        assert connection._catalog.jobs()[0].accepted==job.accepted
        assert (receiving[4]/'Camera/old.gif').read_bytes()==b'hello'
        assert not (receiving[4]/'Animationen/Camera/old.gif').exists()


@pytest.mark.parametrize('choice',[None,'move_existing','copy_existing',True])
def test_future_layout_requires_explicit_keep_existing_decision(receiving,choice):
    connection=receiving[3];before=connection._preferences.read();grant=connection._preferences.local_grant(True).grants
    with pytest.raises(TransferError,match='historical_layout_choice_required'):
        connection.set_future_animation_layout(connection.issue_receive_action(),separate=True,historical_choice=choice)
    assert connection._preferences.read()==before and connection._preferences.local_grant(True).grants==grant


@pytest.mark.parametrize('body',[dict(action='animations_separate'),
    dict(action='animations_together',historical_choice='move_existing'),
    dict(action='inspect_recovery',historical_choice='keep_existing'),
    dict(action='animations_separate',historical_choice='keep_existing',album_id='other')])
def test_layout_service_refuses_implicit_or_unimplemented_historical_decisions(receiving,body):
    from magnolie_telefon import fingerprint,unb64
    service,peer,_,connection,_=receiving
    with pytest.raises(ValueError,match='invalid_action'):
        service.photo_sync_action(peer['device_id'],fingerprint(unb64(peer['static_public'],32)),body)
    assert connection._desktop_session is None and connection._album_worker is None


def test_idempotent_layout_still_requires_live_explicit_native_action(receiving,monkeypatch):
    from magnolie_photo_destination import NativePhotoDestinationAction
    prefs=receiving[3]._preferences
    before=prefs.set_animation_layout(prefs.issue_action(),prefs.read(),separate=False,historical_choice='keep_existing')
    clock=[1000];action=NativePhotoDestinationAction(prefs,lambda:clock[0]);snapshot=prefs._snapshot
    def expired_readback():
        result=snapshot();clock[0]+=60_000;return result
    with monkeypatch.context() as patch:
        patch.setattr(prefs,'_snapshot',expired_readback)
        with pytest.raises(TransferError,match='action_not_current'):
            prefs.set_animation_layout(action,before,separate=False,historical_choice='keep_existing')
    assert prefs.read()==before
