"""Native selected album kind, never a filename heuristic, routes new photos."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
import magnolie_file_sources as sources
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,chunk
from test_file_desktop_sources import ALBUM,CATALOG,request,response,ready_source
from test_file_desktop_media import dispatch,collect,send_offer
from test_file_desktop_album_worker import prepared,phone_batches
from test_file_desktop_photo_review import end_normal_source
from test_photo_desktop_workflow import native_ui,converge_controls


def album_kind(fixture,kind):
    message=request(fixture,'discover')
    dispatch(fixture,response(message,sources.CATALOG,version='b'*64,page=dict(format=1,catalog_id=CATALOG,
        after=0,next_cursor=None,coverage='full_images',proves_deletion=False,
        albums=[dict(album_id=ALBUM,kind=kind,display_name='Camera',visible_images=2,needs_choice=False)])))


@pytest.mark.parametrize('kind',['camera','downloads','screenshots','whatsapp_received'])
def test_actual_batch_targets_use_native_album_kind_and_keep_old_targets_on_toggle(receiving,kind):
    connection=receiving[3];batches=prepared(receiving)
    batches[0]=replace(batches[0],files=(replace(batches[0].files[0],path='Camera/0.gif'),))
    kinds={'Camera/0.gif':'animation','Camera/1.jpg':'image'}
    album_kind(receiving,kind)
    binding=connection._receive_binding();grant=connection._preferences.local_grant(True).grants
    connection.set_future_capture_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    connection.set_future_animation_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    with phone_batches(receiving,batches,media_kinds=kinds) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(45),worker.progress()
        assert not errors and worker.progress()['state']=='complete',worker.progress()
        assert len(chunks)==len(saved)==2
    prefix='Eigene Aufnahmen/' if kind=='camera' else ''
    gif=receiving[4]/(prefix+'Animationen/Camera/0.gif');still=receiving[4]/(prefix+'Camera/1.jpg')
    assert gif.read_bytes()==still.read_bytes()==b'hello'
    assert connection._source_album_kind is None
    still.write_bytes(b'keep original PC crop');before=(still.stat().st_ino,still.read_bytes())
    jobs=connection._catalog.jobs();mappings=connection._mappings.read()
    connection.set_future_capture_layout(connection.issue_receive_action(),separate=False,historical_choice='keep_existing')
    assert connection._catalog.jobs()==jobs and connection._mappings.read()==mappings
    assert connection._receive_binding()==binding and connection._preferences.local_grant(True).grants==grant
    with phone_batches(receiving,batches,media_kinds=kinds) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(30),worker.progress()
        assert not errors and worker.progress()['state']=='complete',worker.progress()
        assert not chunks and not saved
    assert (still.stat().st_ino,still.read_bytes())==before


def test_started_native_album_kind_does_not_change_with_later_discovery(receiving):
    connection=receiving[3];full=prepared(receiving)[0]
    connection.set_future_capture_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    ready_source(receiving)
    assert connection._source_album_kind=='camera'
    album_kind(receiving,'whatsapp_received')
    assert connection._source_albums[ALBUM].kind=='whatsapp_received' and connection._source_album_kind=='camera'
    collect(receiving,full);offered,result=send_offer(receiving,full);dispatch(receiving,result)
    connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    assert dict(connection._run.accepted.targets)=={full.files[0].id:'Eigene Aufnahmen/'+full.files[0].path}
    dispatch(receiving,chunk(connection.request_next_chunk(),b'hello'))
    connection.publish_received(connection.issue_receive_action())
    connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True)
    end_normal_source(receiving)
    assert (receiving[4]/('Eigene Aufnahmen/'+full.files[0].path)).read_bytes()==b'hello'
    assert connection._source_album_kind is None


def test_capture_layout_change_keeps_original_stopped_target_on_native_resume(receiving):
    connection=receiving[3];batches=prepared(receiving)[:1]
    with phone_batches(receiving,batches,block_chunk=True) as (_,_,entered,release,_):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10)
        receiver=connection._run.receiver;job=receiver.job;history=receiver._index.media_history
        worker.stop();release.set();assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='canceled',worker.progress()
    connection.set_future_capture_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    with phone_batches(receiving,batches,resume_job=job,resume_media=history) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(45),worker.progress()
        assert not errors and worker.progress()['state']=='complete',worker.progress()
        assert not chunks and len(saved)==1
        assert connection._catalog.jobs()[0].accepted==job.accepted
        assert (receiving[4]/'Camera/0.jpg').read_bytes()==b'hello'
        assert not (receiving[4]/'Eigene Aufnahmen/Camera/0.jpg').exists()


@pytest.mark.parametrize('choice',[None,'move_existing','copy_existing',True])
def test_capture_future_layout_requires_literal_historical_keep_choice(receiving,choice):
    connection=receiving[3];before=connection._preferences.read()
    with pytest.raises(TransferError,match='historical_layout_choice_required'):
        connection.set_future_capture_layout(connection.issue_receive_action(),separate=True,historical_choice=choice)
    assert connection._preferences.read()==before and connection._album_worker is None


def test_capture_future_layout_uses_actual_gtk_ipc_and_preserves_paused_grants(receiving,request):
    service,peer,channel,connection,_=receiving;converge_controls(service,peer,channel)
    prepared(receiving) # Real storage bootstrap and dedicated control agreement first.
    session=connection.desktop_session();session._local_enabled(True);session._automatic_paused=True
    binding=connection._receive_binding();grant=connection._preferences.local_grant(True).grants
    action=native_ui(service,peer,request);channel.send.reset_mock()
    for operation,separate in (('captures_separate',True),('captures_together',False)):
        action(dict(action=operation,historical_choice='keep_existing'))
        assert session.join(15),session.snapshot()
        assert session.snapshot()['state']=='layout' and session.snapshot()['separate_own_recordings'] is separate,session.snapshot()
        assert session._automatic_paused
        assert connection._receive_binding()==binding and connection._preferences.local_grant(True).grants==grant
    assert not channel.send.call_args_list and connection._album_worker is None


def test_lost_native_album_kind_cannot_be_reconstructed_from_offer_filename(receiving,monkeypatch):
    connection=receiving[3];full=prepared(receiving)[0]
    connection.set_future_capture_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    ready_source(receiving)
    monkeypatch.setattr(connection,'_source_album_kind',None)
    collect(receiving,full);offered,result=send_offer(receiving,full);dispatch(receiving,result)
    with pytest.raises(TransferError,match='source_album_kind_required'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    assert connection._run is None and connection.native_receive_jobs()==()
    assert not list(receiving[4].glob('**/*.jpg'))


def test_future_camera_grouping_cannot_retarget_existing_phone_version_chain(receiving):
    from hashlib import sha256
    from magnolie_photo_mappings import PhotoMappingAssociation,photo_version_path
    from test_photo_version_workflow import cycle,changed
    connection=receiving[3];full=prepared(receiving)[0]
    assert cycle(receiving,full)[0]['state']=='complete'
    association=PhotoMappingAssociation('c'*64,sha256(b'worker-photo-0').hexdigest(),'images')
    _,(original,)=connection._mappings.lookup((association,))
    target=receiving[4]/full.files[0].path;before=(target.stat().st_ino,target.read_bytes())
    connection.set_future_capture_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    version=changed(full,'c',b'world');state,chunks,saved=cycle(receiving,version,b'world')
    assert state['state']=='complete' and len(chunks)==len(saved)==1,state
    version_path=photo_version_path(association,version.files[0])
    assert (receiving[4]/version_path).read_bytes()==b'world'
    assert not (receiving[4]/('Eigene Aufnahmen/'+version_path)).exists()
    assert (target.stat().st_ino,target.read_bytes())==before
    _,(historical,)=connection._mappings.lookup_saved((association,),(original.receipt_sha256,))
    assert historical==original
    state,chunks,saved=cycle(receiving,changed(version,'d',b'world'),b'world')
    assert state['state']=='complete' and not chunks and not saved,state
