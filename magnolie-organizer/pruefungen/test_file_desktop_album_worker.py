"""Real single album worker with authenticated native dispatch and actual files."""
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from queue import Queue
import sys
import threading
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_file_offer import create_offer
import magnolie_file_sources as sources
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, chunk
from test_file_desktop_sources import ready_source, ALBUM
from test_file_desktop_media import manifest, media, dispatch
from test_file_desktop_photo_batches import result
from test_file_desktop_photo_review import end_normal_source
from test_file_desktop_sources import response
from test_file_desktop_resume_lookup import history as resume_history
from test_file_desktop_resume_abandonment import receipt as abandonment_receipt


@contextmanager
def phone_batches(fixture, batches, *, block_chunk=None, block_source=False, metadata_handler=None,
        insertion_witness=False, content=b'hello', photo_ids=None, resume_job=None, resume_media=None,media_kinds=None):
    queue = Queue(); errors = []; chunks = []; saved = []
    saved_targets={}
    entered = threading.Event(); release = threading.Event()
    run_ids = [str(uuid.uuid4()) for _ in batches]
    def phone():
        index = 0; canceled = False; selected={};resume_id=str(uuid.uuid4());resume_canceled=False;resume_attempted=False
        try:
            while True:
                message = queue.get()
                if message is None: return
                kind = message['kind']; body = message['body']
                if kind == sources.REQUEST:
                    operation = body['operation']
                    if operation=='resume_lookup' and resume_job is not None:
                        dispatch(fixture,resume_history(message,resume_job,attempt_phase='accepted' if resume_attempted else None));continue
                    if operation=='abandon_resume' and resume_job is not None:
                        dispatch(fixture,abandonment_receipt(message));resume_attempted=False;continue
                    if operation in ('resume_run','resume_status','resume_media_page','offer_resume','cancel_resume','end_resume') and resume_job is not None:
                        original=resume_job.accepted.manifest
                        if operation=='cancel_resume':resume_canceled=True
                        if operation=='resume_media_page':
                            value=media(message,original,body['after']);value['body']['run_id']=resume_id
                            value['body']['page']['source_epoch']=resume_media.source_epoch
                            value['body']['page']['insertion_witness']=resume_media.insertion_witness
                            for entry in value['body']['page']['entries']:
                                entry['photo_id']=next(item.photo_id for item in resume_media.entries if item.file_id==entry['file_id'])
                                entry['media_kind']=next(item.media_kind for item in resume_media.entries if item.file_id==entry['file_id'])
                            dispatch(fixture,value);continue
                        options={}
                        if operation=='end_resume':options['run_ended']=True
                        if operation=='offer_resume':
                            resume_attempted=True
                            offered=create_offer(original);offered['expires_ms']=min(offered['expires_ms'],message['expires_ms'])
                            dispatch(fixture,offered);options=dict(offer_id=offered['message_id'],manifest_sha256=original.fingerprint)
                        value=response(message,sources.RUN_RESULT,version='b'*64,run_id=resume_id,
                            state='canceled_held' if resume_canceled else 'snapshot_ready',source_io_ended=True,**options)
                        value['expires_ms']=min(value['expires_ms'],message['expires_ms'])
                        dispatch(fixture,value);continue
                    if metadata_handler is not None and operation in ('status','configure','configure_videos','discover','catalog_page','request_read'):
                        metadata_handler(message);continue
                    if operation=='batch_run':
                        index=0;canceled=False
                        selected.clear()
                        run_ids[:]=[str(uuid.uuid4()) for _ in batches]
                    if block_source and operation == 'batch_run':
                        entered.set(); assert release.wait(10)
                        if fixture[3]._closed.is_set(): return
                    if operation == 'next_batch': index += 1; canceled = False
                    if operation == 'cancel_run': canceled = True
                    current = selected.get(index,batches[index]); run = run_ids[index]; final = index == len(batches)-1
                    if operation=='select_run':
                        files=tuple(file for file in current.files if file.id in body['file_ids'])
                        assert len(files)==len(body['file_ids'])
                        current=replace(current,source_id=uuid.uuid4().hex,transfer_id=uuid.uuid4().hex,files=files,
                            total_bytes=sum(file.size for file in files));selected[index]=current
                        run=str(uuid.uuid4());run_ids[index]=run;canceled=False
                    if operation == 'media_page':
                        value = media(message, current, body['after']); value['body']['run_id'] = run
                        value['body']['page']['insertion_witness']=insertion_witness
                        for entry in value['body']['page']['entries']:
                            path=next(file.path for file in current.files if file.id==entry['file_id'])
                            entry['photo_id'] = photo_ids[path] if photo_ids is not None else sha256(f'worker-photo-{index}'.encode()).hexdigest()
                            if media_kinds is not None:entry['media_kind']=media_kinds[path]
                        dispatch(fixture, value)
                    elif operation == 'offer_run':
                        offered = create_offer(current); offered['expires_ms'] = min(offered['expires_ms'], message['expires_ms'])
                        dispatch(fixture, offered)
                        value = result(message, run, final, offer_id=offered['message_id'], manifest_sha256=current.fingerprint)
                        value['expires_ms'] = min(value['expires_ms'], offered['expires_ms']); dispatch(fixture, value)
                    else:
                        state = 'canceled_held' if canceled else 'empty_ready' if current is None else 'snapshot_ready'
                        dispatch(fixture, result(message, run, final, state=state))
                elif kind == 'file_transfer.chunk.request':
                    chunks.append(body['file_id'])
                    if block_chunk is not None:
                        entered.set(); check = release.wait(10); assert check
                    dispatch(fixture, chunk(message, content))
                elif kind == 'file_transfer.saved':
                    accepted=saved_targets[message['message_id']]
                    assert all((Path(accepted.destination.path) / path).read_bytes() == content for _,path in accepted.targets)
                    saved.append(message)
        except BaseException as error:
            errors.append(error); fixture[3].close()
    def enqueue(message):
        if message['kind']=='file_transfer.saved':saved_targets[message['message_id']]=fixture[3]._run.accepted
        queue.put(message)
    fixture[2].send.side_effect = enqueue
    peer = threading.Thread(target=phone, name='fixture-native-album-peer', daemon=True); peer.start()
    try: yield chunks, saved, entered, release, errors
    finally:
        release.set()
        worker = fixture[3]._album_worker
        if worker is not None:
            worker.stop(); worker.join(10)
            if not worker.io_ended: fixture[3].close(); worker.join(10)
            assert worker.io_ended
        queue.put(None); peer.join(10); fixture[2].send.side_effect = None
        assert not peer.is_alive()
        if errors: raise errors[0]


def prepared(fixture):
    ready_source(fixture); end_normal_source(fixture)
    old = manifest(fixture)
    return [replace(old, transfer_id=char * 32, source_id=char * 32,
        files=(replace(old.files[0], id=char * 32, path=f'Camera/{index}.jpg'),)) for index, char in enumerate(('a', 'b'))]


def test_actual_album_worker_saves_two_batches_then_repeat_preserves_pc_edit_without_download(receiving):
    connection = receiving[3]; batches = prepared(receiving); activity = []
    for cycle in range(2):
        if cycle:
            batches = [replace(full, source_id=char * 32, transfer_id=char * 32,
                files=(replace(full.files[0], id=char * 32),)) for full, char in zip(batches, ('c', 'd'))]
        with phone_batches(receiving, batches) as (chunks, saved, _, _, errors):
            worker = connection.start_album_worker(connection.issue_receive_action(), ALBUM, True,
                activity_changed=lambda owner, active: activity.append((owner, active)))
            assert worker.join(60), worker.progress()
            assert not errors and worker.progress()['state'] == 'complete', worker.progress()
            assert len(chunks) == len(saved) == (2 if cycle == 0 else 0)
            assert worker.progress()['saved_files'] == (2 if cycle == 0 else 0)
            assert worker.progress()['known_files'] == (0 if cycle == 0 else 2)
            assert activity[-2:] == [(worker, True), (worker, False)]
        target = receiving[4] / 'Camera/0.jpg'
        if cycle == 0:
            target.write_bytes(b'preserve PC crop'); before = (target.stat().st_ino, target.read_bytes())
        else:
            assert (target.stat().st_ino, target.read_bytes()) == before
    assert connection._album_worker is None and connection._run is None
    assert connection._mappings.read().count == 2
    assert all(job.reserved_bytes == 0 for job in connection._catalog.jobs())


def test_album_worker_cancel_waits_for_real_chunk_drain_and_close_without_publishing_or_freeing_quota(receiving, monkeypatch):
    connection = receiving[3]; batches = prepared(receiving); activity = []
    service = receiving[0]; native_activity = []
    def native_event(kind, payload):
        if kind == 'media_activity':
            assert not service.lock._is_owned()
            native_activity.append(service._native_media_activity())
    service.callback = native_event
    assert service.report()['media_activity'] == {'synchronizing': False, 'camera': False}
    with phone_batches(receiving, batches, block_chunk=True) as (chunks, saved, entered, release, errors):
        worker = connection.start_album_worker(connection.issue_receive_action(), ALBUM, True,
            activity_changed=lambda owner, active: activity.append((owner, active)))
        assert entered.wait(10)
        assert native_activity == [{'synchronizing': True, 'camera': False}]
        with pytest.raises(TransferError, match='busy'):
            connection.start_album_worker(connection.issue_receive_action(), ALBUM, True)
        assert connection._album_worker is worker
        assert sum(call.args[0].get('body', {}).get('operation') == 'batch_run' for call in receiving[2].send.call_args_list) == 1
        finishing_threads = []; finish = connection._finish_receive_stop
        def finish_on_io_lane():
            finishing_threads.append(threading.current_thread())
            return finish()
        monkeypatch.setattr(connection, '_finish_receive_stop', finish_on_io_lane)
        worker.stop()
        assert threading.current_thread() not in finishing_threads
        assert not worker.io_ended and activity == [(worker, True)]
        assert service._native_media_activity()['synchronizing'] is True
        release.set(); assert worker.join(30), worker.progress()
        assert not errors and worker.progress()['state'] == 'canceled', worker.progress()
        state = connection.receive_stop_state()
        assert state.state == 'stopped' and state.io_ended and state.resources_closed and state.checkpoint_committed
        assert not saved and not list(receiving[4].glob('**/*.jpg'))
        assert len(connection._catalog.jobs()) == 1 and connection._catalog.jobs()[0].reserved_bytes > 0
        assert connection._run is None and connection._album_worker is None
        assert activity == [(worker, True), (worker, False)]
        assert native_activity == [{'synchronizing': True, 'camera': False},
                                   {'synchronizing': False, 'camera': False}]
        assert finishing_threads and threading.current_thread() not in finishing_threads


def test_actual_worker_resumes_original_stopped_job_ends_saved_source_then_repeats_without_download(receiving):
    connection=receiving[3];batches=prepared(receiving)[:1]
    with phone_batches(receiving,batches,block_chunk=True) as (_,_,entered,release,_):
        first=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10)
        receiver=connection._run.receiver;job=receiver.job;history=receiver._index.media_history
        first.stop();release.set();assert first.join(30),first.progress()
        assert first.progress()['state']=='canceled',first.progress()
    assert not (receiving[4]/'Camera/0.jpg').exists()
    # Original first chunk was durably drained at stop; continuation must not
    # allocate a replacement job or download that chunk again.
    with phone_batches(receiving,batches,resume_job=job,resume_media=history) as (chunks,saved,_,_,errors):
        second=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert second.join(45),second.progress()
        assert not errors and second.progress()['state']=='complete',second.progress()
        assert second.progress()['saved_files']==1
        assert not chunks and len(saved)==1
        assert (receiving[4]/'Camera/0.jpg').read_bytes()==b'hello'
        jobs=connection._catalog.jobs()
        assert len(jobs)==1 and jobs[0].owner==job.owner and jobs[0].reserved_bytes==0
        assert connection._run is None and connection._resume_source_id is None
        events=connection._catalog._registry.attempts(jobs)
        assert [event['operation'] for event,_ in events]==['closed','consumed']
    with phone_batches(receiving,batches) as (chunks,saved,_,_,errors):
        repeat=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert repeat.join(30) and repeat.progress()['state']=='complete',repeat.progress()
        assert not errors and not chunks and not saved


def test_stop_during_original_resume_drains_missing_chunk_and_abandons_only_ended_attempt(receiving,monkeypatch):
    connection=receiving[3];base=prepared(receiving)[0]
    files=(base.files[0],replace(base.files[0],id='d'*32,path='Camera/second.jpg'))
    batches=[replace(base,files=files,total_bytes=sum(file.size for file in files))]
    photos={file.path:sha256(file.path.encode()).hexdigest() for file in files}
    with phone_batches(receiving,batches,block_chunk=True,photo_ids=photos) as (_,_,entered,release,_):
        first=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10)
        receiver=connection._run.receiver;job=receiver.job;history=receiver._index.media_history
        first.stop();release.set();assert first.join(30),first.progress()
        assert first.progress()['state']=='canceled',first.progress()
    finishing=[];finish=connection._finish_receive_stop
    def observed():
        finishing.append(threading.current_thread());return finish()
    monkeypatch.setattr(connection,'_finish_receive_stop',observed)
    with phone_batches(receiving,batches,block_chunk=True,photo_ids=photos,resume_job=job,resume_media=history) as (chunks,saved,entered,release,errors):
        second=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(15),second.progress()
        assert connection._resume_source_id is not None
        state=connection.source_state;busy=[]
        def dispatch_still_owns_gate():
            if second._stop.is_set() and not busy:
                busy.append(True);raise TransferError('file_desktop_connection_busy')
            return state()
        monkeypatch.setattr(connection,'source_state',dispatch_still_owns_gate)
        second.stop()
        assert threading.current_thread() not in finishing and not second.io_ended
        release.set();assert second.join(30),second.progress()
        assert not errors and second.progress()['state']=='canceled',second.progress()
        assert busy
        assert chunks==[files[1].id] and not saved
        assert connection._resume_abandonment is not None
        assert connection.receive_stop_state().resources_closed
        assert connection._catalog.jobs()==(job,)
        events=connection._catalog._registry.attempts((job,))
        assert [event['operation'] for event,_ in events]==['closed','consumed','closed']
        assert not list(receiving[4].glob('**/*.jpg'))


@pytest.mark.parametrize('change',['content','partial','proof'])
def test_fresh_album_cannot_resume_changed_partial_or_unproven_original(receiving,change):
    connection=receiving[3];batches=prepared(receiving)[:1]
    base=batches[0];files=(base.files[0],replace(base.files[0],id='d'*32,path='Camera/second.jpg'))
    batches=[replace(base,files=files,total_bytes=sum(file.size for file in files))]
    photos={file.path:sha256(file.path.encode()).hexdigest() for file in files}
    with phone_batches(receiving,batches,block_chunk=True,photo_ids=photos) as (_,_,entered,release,_):
        first=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10)
        receiver=connection._run.receiver;job=receiver.job
        if change=='proof':
            # An actual attempted publication (even one rejected as incomplete)
            # cannot earn a positive unpublished END proof.
            with pytest.raises(TransferError):
                receiver._publisher.publish(files[1].id,receiver._ledger,receiver._stage.read_chunk)
        first.stop();release.set();assert first.join(30),first.progress()
        assert first.progress()['state']=='canceled',first.progress()
    if change=='content':
        files=(replace(files[0],sha256=sha256(b'other').hexdigest()),files[1])
    elif change=='partial':files=files[:1]
    fresh=[replace(base,files=files,total_bytes=sum(file.size for file in files))]
    with phone_batches(receiving,fresh,photo_ids=photos) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(30),worker.progress()
        assert not errors and worker.progress()['state']=='held',worker.progress()
        expected={'content':'source_changed','partial':'membership_unproven','proof':'publication_repair_required'}[change]
        assert expected in worker.progress()['error']
        assert not chunks and not saved and connection._catalog.jobs()==(job,)
        assert not list(receiving[4].glob('**/*.jpg'))


def test_resume_ending_needs_real_saved_receipt_not_a_cached_flag_or_stop_request(receiving):
    from test_file_desktop_receive_stop import resumed
    from test_file_desktop_resume_sources import cancel
    with resumed(receiving) as (fresh,job,history):
        connection=fresh[3];run=connection._run
        run.saved_mapping_ready=True
        count=fresh[2].send.call_count
        for operation in ('resume_status','end_resume','offer_resume','resume_media_page'):
            with pytest.raises(TransferError):connection.request_source(connection.issue_receive_action(),operation)
        assert fresh[2].send.call_count==count
        run.saved_mapping_ready=False
        connection.request_receive_stop(connection.issue_receive_action(),finish=False)
        cancel(fresh)
        # A source's cancel barrier does not close the desktop stage/index.
        if connection._run is not None:
            with pytest.raises(TransferError):connection.request_source(connection.issue_receive_action(),'end_resume')
        assert connection._catalog.jobs()==(job,)


def test_empty_actual_worker_allocates_no_receiver_or_file_and_finishes_only_after_source_end(receiving):
    connection = receiving[3]; prepared(receiving); activity = []
    with phone_batches(receiving, [None]) as (chunks, saved, _, _, errors):
        worker = connection.start_album_worker(connection.issue_receive_action(), ALBUM, True,
            activity_changed=lambda owner, active: activity.append((owner, active)))
        assert worker.join(30), worker.progress()
        assert not errors and worker.progress()['state'] == 'complete'
        assert connection._open_catalog(allow_create=False)
        assert not chunks and not saved and not connection._catalog.jobs()
        assert connection._source_run is None and connection._run is None
        assert not list(receiving[4].glob('**/*.jpg'))
        assert activity == [(worker, True), (worker, False)]


def test_failing_frontend_observer_cannot_replace_native_owner_activity_or_prevent_end(receiving):
    connection = receiving[3]; service = receiving[0]; prepared(receiving); states = []
    service.callback = lambda event, payload: states.append(service._native_media_activity()) if event == 'media_activity' else None
    def broken_frontend(owner, active):
        raise RuntimeError('fixture frontend unavailable')
    with phone_batches(receiving, [None]):
        worker = connection.start_album_worker(connection.issue_receive_action(), ALBUM, True,
            activity_changed=broken_frontend)
        assert worker.join(30), worker.progress()
        assert worker.progress()['state'] == 'complete'
        assert worker.progress()['activity_error'] == 'RuntimeError'
        assert states == [{'synchronizing': True, 'camera': False}, {'synchronizing': False, 'camera': False}]


def test_phone_change_is_reported_as_conflict_not_overwritten_or_claimed_complete(receiving):
    connection = receiving[3]; batches = prepared(receiving)[:1]
    with phone_batches(receiving, batches):
        first = connection.start_album_worker(connection.issue_receive_action(), ALBUM, True)
        assert first.join(30) and first.progress()['state'] == 'complete', first.progress()
    target = receiving[4] / 'Camera/0.jpg'; before = (target.stat().st_ino, target.read_bytes())
    changed = replace(batches[0], source_id='e' * 32, transfer_id='f' * 32,
        files=(replace(batches[0].files[0], id='c' * 32, size=3, sha256=sha256(b'new').hexdigest()),), total_bytes=3)
    with phone_batches(receiving, [changed]) as (chunks, saved, _, _, errors):
        worker = connection.start_album_worker(connection.issue_receive_action(), ALBUM, True)
        assert worker.join(30), worker.progress()
        assert not errors and worker.progress()['state'] == 'conflicts'
        assert len(worker.progress()['conflicts']) == 1 and worker.progress()['saved_files'] == 0
        assert not chunks and not saved and (target.stat().st_ino, target.read_bytes()) == before
        assert len(connection._catalog.jobs()) == 1


def test_connection_close_ends_waiting_worker_without_allocating_receiver_or_leaving_thread(receiving):
    connection = receiving[3]; batches = prepared(receiving); activity = []
    with phone_batches(receiving, batches, block_source=True) as (_, _, entered, release, errors):
        worker = connection.start_album_worker(connection.issue_receive_action(), ALBUM, True,
            activity_changed=lambda owner, active: activity.append((owner, active)))
        assert entered.wait(10); connection.close(); release.set()
        assert worker.join(10), worker.progress()
        assert not errors and worker.progress()['state'] == 'held'
        assert worker.progress()['error'] == 'file_desktop_connection_closed'
        assert connection._album_worker is None and connection._run is None
        assert activity == [(worker, True), (worker, False)]


def test_unready_production_gate_cannot_start_native_album_worker(receiving, monkeypatch):
    connection = receiving[3]; prepared(receiving)
    monkeypatch.setattr(type(connection), '_data_handlers_ready', False)
    count = receiving[2].send.call_count
    with pytest.raises(TransferError, match='data_handlers_unavailable'):
        connection.start_album_worker(connection.issue_receive_action(), ALBUM, True)
    assert connection._album_worker is None and receiving[2].send.call_count == count


def test_unknown_batch_end_can_abort_a_confirmed_stopped_scan_but_cannot_advance_it(receiving):
    from test_file_desktop_sources import status, catalog, request, RUN
    status(receiving); catalog(receiving)
    message = request(receiving, 'batch_run', album_id=ALBUM, desktop_choice=True)
    dispatch(receiving, result(message, final=None, state='preparing'))
    message = request(receiving, 'cancel_run')
    dispatch(receiving, result(message, final=None, state='canceled_held'))
    with pytest.raises(TransferError): request(receiving, 'end_album') # No actual END confirmation yet.
    message = request(receiving, 'end_run')
    dispatch(receiving, result(message, state='canceled_held'))
    count = receiving[2].send.call_count
    with pytest.raises(TransferError): request(receiving, 'next_batch')
    assert receiving[2].send.call_count == count
    message = request(receiving, 'end_album'); assert message['body']['run_id'] == RUN
    dispatch(receiving, result(message, state='canceled_held'))
    assert receiving[3]._ended_batch is None and receiving[3]._album_worker is None
    assert not list(receiving[4].glob('**/*.jpg'))
