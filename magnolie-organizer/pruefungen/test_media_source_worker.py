"""#429: bounded actual mapped source worker on the normal secure connection."""
from pathlib import Path
import threading
import os
from contextlib import contextmanager
import pytest

from test_media_source_connection import source,native,receiving,mappings,composition,agree,dispatch,png,acceptance,request,saved,readback
from test_media_source_sender import message


def start(h):return h.connection.start_mapped_media_worker(h.connection.issue_receive_action())


def test_actual_worker_skips_unchanged_mapped_file_without_cache_or_phone_read(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        controls=agree(h,native[0]);owner=h.connection._local().owner
        monkeypatch.setattr(h.connection,'request_source',lambda *a,**k:pytest.fail('PC pass requested phone READ'))
        worker=start(h)
        assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='complete',worker.progress()
        assert worker.progress()['known_files']==1 and worker.progress()['saved_files']==0
        assert not h.source._prepared and h.connection._mapped_worker is None
        assert h.connection._local().owner is owner and h.connection._controls.packet().grants==controls.grants
        assert not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))


def test_actual_worker_sends_changed_bytes_then_backs_up_archives_and_skips_second_pass(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        controls=agree(h,native[0]);owner=h.connection._local().owner;h.target.write_bytes(png())
        h.wire.sock.settimeout(30);worker=start(h)
        try:
            try:offer=h.wire.receive()
            except TimeoutError:pytest.fail(str(worker.progress()))
            sender=h.connection._media_sender
            assert sender is not None and sender._controls is h.connection._controls
            cache=sender._cache;accepted=acceptance(sender,cache,offer)
            try:dispatch(h,native[0],accepted)
            except Exception as error:raise AssertionError(worker.progress()) from error
            for index in range(cache.manifest.files[0].chunks):
                dispatch(h,native[0],request(accepted,cache,index));assert h.wire.receive()['kind']=='file_transfer.chunk'
            dispatch(h,native[0],saved(accepted,cache))
            assert worker.progress()['saved_files']==0 # Saved is not readback or native drain.
            entered=threading.Event();release=threading.Event();attempted=threading.Event();errors=[]
            original=sender._media_readback;archive=worker._archive
            def held_readback(packet):
                original(packet);entered.set();assert release.wait(15)
            def archive_after_hint(*args):attempted.set();return archive(*args)
            monkeypatch.setattr(sender,'_media_readback',held_readback)
            monkeypatch.setattr(worker,'_archive',archive_after_hint)
            def receive():
                try:dispatch(h,native[0],readback(sender,cache,offer))
                except BaseException as error:errors.append(error)
            thread=threading.Thread(target=receive,daemon=True);thread.start()
            try:
                assert entered.wait(10) and attempted.wait(10)
                assert worker.progress()['saved_files']==0 and cache.directory.exists()
                assert not worker.join(.1) # Protected readback exists, actual source I/O has NOT drained.
            finally:release.set();thread.join(30)
            assert not thread.is_alive() and not errors,errors
            assert worker.join(60),worker.progress()
            assert worker.progress()['state']=='complete',worker.progress()
            assert worker.progress()['saved_files']==1
            assert not cache.directory.exists() and not h.source._prepared and h.connection._media_sender is None
            assert list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.retired'))
            second=start(h);assert second.join(30),second.progress()
            assert second.progress()['state']=='complete' and second.progress()['known_files']==1,second.progress()
            assert second.progress()['saved_files']==0 and h.target.read_bytes()==png()
            assert h.connection._local().owner is owner and h.connection._controls.packet().grants==controls.grants
        finally:
            worker.stop();assert worker.join(30),worker.progress()


def test_worker_without_actual_send_control_holds_before_creating_cache(source,native):
    with composition(source,native[0]) as h:
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and not h.source._prepared
        assert h.connection._mapped_worker is None


def test_normal_session_pc_only_manual_pass_never_discovers_or_requests_phone_read(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        h.controller.change('direction','pc_to_phone');agree(h,native[0])
        session=h.connection.desktop_session()
        monkeypatch.setattr(h.connection,'request_source',lambda *a,**k:pytest.fail('PC-only session requested phone source/READ'))
        session.start('sync_shared');assert session.join(30),session.snapshot()
        assert session.snapshot()['state']=='complete',session.snapshot()
        assert session.snapshot()['known_files']==1 and session.snapshot()['enabled'] is False
        assert h.connection._mapped_worker is None and not h.source._prepared


def test_import_only_scope_cannot_export_even_with_pc_to_phone_direction_and_native_send_consent(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        h.controller.change('collection_mode','import_only');h.controller.change('direction','pc_to_phone')
        attempted=h.controller.send_settings();assert h.wire.receive()==attempted
        dispatch(h,native[0],dict(type='ack',message_id=attempted['message_id'],status='accepted',error='none'))
        dispatch(h,native[0],message('file_transfer.shared_settings',attempted['body']));assert h.wire.receive()['type']=='ack'
        assert h.controller.intent_for('images',to_phone=True) is None
        monkeypatch.setattr(h.source,'plan',lambda *a,**k:pytest.fail('Import-only worker entered source planning'))
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and worker.progress()['error']=='media_source_current_intent_required'
        assert not h.source._prepared


def test_entire_collection_holds_explicitly_instead_of_claiming_mapped_subset_complete(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        h.controller.change('collection_mode','entire_collection');agree(h,native[0])
        monkeypatch.setattr(h.source,'plan',lambda *a,**k:pytest.fail('Unsupported collection silently planned a subset'))
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and worker.progress()['error']=='media_source_entire_collection_review_required'
        assert not h.source._prepared


def test_stop_during_actual_source_read_retains_source_without_promoting_ready(source,native):
    with composition(source,native[0]) as h:
        agree(h,native[0]);h.target.write_bytes(png())
        def boundary(phase):
            if phase=='source_chunk_read':h.connection._mapped_worker.stop()
        h.source._boundary=boundary
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='stopped',worker.progress()
        assert not h.source._prepared and h.connection._media_sender is None and h.connection._mapped_worker is None
        assert h.target.read_bytes()==png()


@pytest.fixture
def two_sources(mappings,monkeypatch):
    import test_media_source as module
    original=module.save
    with monkeypatch.context() as patch:
        patch.setattr(module,'save',lambda fixture:original(fixture,count=2))
        generator=source.__wrapped__(mappings);h=next(generator)
    try:yield h
    finally:
        try:next(generator)
        except StopIteration:pass


def test_actual_two_mapping_pages_share_one_snapshot_without_a_filesystem_scan(two_sources,native,monkeypatch):
    from magnolie_media_source_worker import NativeMappedMediaWorker
    monkeypatch.setattr(NativeMappedMediaWorker,'PAGE_SIZE',1)
    with composition(two_sources,native[0]) as h:
        agree(h,native[0]);calls=[];original=h.mappings.candidate_page
        def page(*args,**kwargs):
            result=original(*args,**kwargs);calls.append((kwargs,result));return result
        monkeypatch.setattr(h.mappings,'candidate_page',page)
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='complete' and worker.progress()['known_files']==2,worker.progress()
        assert len(calls)==2 and calls[1][0]['expected']==calls[0][1][0]
        assert calls[1][0]['after']==calls[0][1][2] and calls[1][1][2] is None
        assert not h.source._prepared


def test_close_during_actual_source_io_does_not_report_release_or_close_foreign_descriptor_early(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        agree(h,native[0]);entered=threading.Event();release=threading.Event();fds=[]
        original=h.source._file
        @contextmanager
        def tracked(*args):
            with original(*args) as held:fds.append(held[0]);yield held
        monkeypatch.setattr(h.source,'_file',tracked)
        def boundary(phase):
            if phase=='source_chunk_read':entered.set();assert release.wait(15)
        h.source._boundary=boundary;worker=start(h)
        try:
            assert entered.wait(10)
            assert h.connection.close() is False
            assert not h.connection._release_reported and not worker.join(.1)
            assert os.fstat(fds[0]).st_ino==h.record.file_key[1]
        finally:release.set();assert worker.join(30),worker.progress()
        assert h.connection._mapped_worker is None and h.connection._release_reported
        assert h.target.read_bytes()==b'hello' and not h.source._prepared


def test_unjoined_wifi_automatic_path_holds_instead_of_exporting_under_manual_shared_intent(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        agree(h,native[0]);session=h.connection.desktop_session()
        monkeypatch.setattr(h.source,'plan',lambda *a,**k:pytest.fail('Manual shared intent exported automatically'))
        session._schedule.set_mode('automatic');run=session._schedule.take_due();assert run is not None
        session.start('automatic',schedule_run=run);assert session.join(30),session.snapshot()
        assert session.snapshot()['state']=='held'
        assert session.snapshot()['error']=='media_source_wifi_automatic_composition_required'
        assert not h.source._prepared
