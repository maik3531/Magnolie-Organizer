"""#429: bounded actual mapped source worker on the normal secure connection."""
from pathlib import Path
import threading
import os
import socket
from types import SimpleNamespace
from contextlib import contextmanager
import pytest

from test_media_source_connection import source,native,receiving,mappings,composition,agree,dispatch,png,acceptance,request,saved,readback
from test_media_source_sender import message


def start(h):
    if not h.connection._native_metadata_current():warm_metadata(h,h.service)
    return h.connection.start_mapped_media_worker(h.connection.issue_receive_action())


def warm_metadata(h,service):
    from copy import deepcopy
    for kind,body in (('capabilities.update',deepcopy(h.peer['capabilities'])),
            ('grants.update',deepcopy(h.peer['grants'])),('personal_sync.settings',dict(format=1,own_device=True))):
        if kind!='personal_sync.settings':body['revision']+=1
        packet=message(kind,body);dispatch(h,service,packet)
        for _ in range(16):
            reply=h.wire.receive()
            if reply['type']=='ack' and reply['message_id']==packet['message_id']:
                assert reply['status']=='accepted',reply
                break
            assert reply['type']=='message',reply
        else:pytest.fail('Current-channel native metadata ACK missing')


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


@pytest.mark.parametrize('trigger',['manual','wifi'])
def test_actual_worker_sends_changed_bytes_then_backs_up_archives_and_skips_second_pass(source,native,monkeypatch,trigger):
    with composition(source,native[0]) as h:
        owner=h.connection._local().owner;h.target.write_bytes(png())
        if trigger=='wifi':
            from magnolie_file_desktop_connection import NativePhotoDesktopSession
            monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',.1)
            warm_metadata(h,native[0])
            h.controller.change('direction','pc_to_phone');h.controller.change('auto_mode','wifi')
        controls=agree(h,native[0])
        h.wire.sock.settimeout(30);worker=start(h) if trigger=='manual' else None
        try:
            try:offer=h.wire.receive()
            except TimeoutError:pytest.fail(str(worker.progress() if worker is not None else h.connection.desktop_session().snapshot()))
            if worker is None:worker=h.connection._mapped_worker
            assert worker is not None
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
                try:
                    # This peer-fixture builder consults the desktop controls.
                    # Serialize that synthetic lookup like every real caller;
                    # do not race an idle consent poll outside the native lane.
                    with h.connection._operation(incoming=True):packet=readback(sender,cache,offer)
                    dispatch(h,native[0],packet)
                except BaseException as error:errors.append(error)
            thread=threading.Thread(target=receive,daemon=True);thread.start()
            try:
                assert entered.wait(10) and attempted.wait(10),(errors,worker.progress())
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
            if worker is not None:worker.stop();assert worker.join(30),worker.progress()


def test_worker_without_actual_send_control_holds_before_creating_cache(source,native):
    with composition(source,native[0]) as h:
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and not h.source._prepared
        assert h.connection._mapped_worker is None


@pytest.mark.parametrize('withdrawal',['remote_receive','local_send'])
def test_idle_offered_worker_observes_consent_withdrawal_without_more_phone_requests(source,native,withdrawal):
    from magnolie_file_control import FileControlPacket,FileGrantState,KIND as CONTROL
    from magnolie_file_transfer import TransferError
    with composition(source,native[0]) as h:
        controls=agree(h,native[0]);h.target.write_bytes(png())
        h.wire.sock.settimeout(30);worker=start(h)
        try:
            offer=h.wire.receive();assert offer['kind']=='file_transfer.media_offer'
            sender=h.connection._media_sender;cache=sender._cache
            if withdrawal=='remote_receive':
                withdrawn=FileControlPacket(FileGrantState(2,'8'*64,False,False),'7'*64,2,controls.challenge)
                dispatch(h,native[0],message(CONTROL,withdrawn.wire()))
                assert h.wire.receive()['kind']==CONTROL
            else:
                with h.connection._operation(incoming=True):
                    prefs=h.preferences
                    prefs.configure_sending(prefs.issue_action(),prefs.read(),photos=False,videos=False)
            assert worker.join(5),'Idle source ignored current consent withdrawal: '+str(worker.progress())
            assert worker.progress()['state']=='held' and worker.progress()['saved_files']==0,worker.progress()
            assert cache.directory.exists() and h.target.read_bytes()==png()
            assert sender._closed.is_set() and h.connection._media_sender is None and h.connection._mapped_worker is None
            assert not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.retired'))
            if withdrawal=='remote_receive':
                renewed=FileControlPacket(FileGrantState(3,'9'*64,False,True),'7'*64,3,controls.challenge)
                dispatch(h,native[0],message(CONTROL,renewed.wire()))
                assert h.wire.receive()['kind']==CONTROL
                assert h.connection._controls.binding('0'*64,sender_is_local=True) is not None
                assert sender._closed.is_set() and h.connection._mapped_worker is None
            with pytest.raises(TransferError,match='native_operation_ended'):worker._current()
        finally:
            worker.stop();assert worker.join(15),worker.progress()


def test_schedule_scope_does_not_probe_controls_while_connection_io_is_owned(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        agree(h,native[0]);session=h.connection.desktop_session()
        with monkeypatch.context() as patch:
            patch.setattr(h.connection._controls,'binding',lambda *a,**k:pytest.fail('Scheduler entered controls during owned connection I/O'))
            with h.connection._operation():assert session._schedule_scope() is None


def test_normal_session_pc_only_manual_pass_never_discovers_or_requests_phone_read(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        import magnolie_telefon as phone
        # The high-level Organizer action additionally requires real current-
        # channel metadata ACKs, not the source fixture's persisted capabilities.
        warm_metadata(h,native[0])
        h.controller.change('direction','pc_to_phone');agree(h,native[0])
        with monkeypatch.context() as patch:
            patch.setattr(h.preferences,'read',lambda:pytest.fail('Passive UI snapshot performed protected preference I/O'))
            state=h.connection.desktop_snapshot()
            assert state['mapped_outgoing'] is True and state['mapped_direction']=='pc_to_phone'
        session=h.connection.desktop_session()
        monkeypatch.setattr(h.connection,'request_source',lambda *a,**k:pytest.fail('PC-only session requested phone source/READ'))
        native[0].photo_sync_action(h.peer['device_id'],phone.fingerprint(phone.unb64(h.peer['static_public'],32)),{'action':'sync_shared'})
        assert session.join(30),session.snapshot()
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
        assert h.connection.desktop_snapshot().get('mapped_outgoing') is False
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


def test_actual_shared_wifi_arms_native_pc_only_automatic_pass_without_receiving_or_phone_read(source,native,monkeypatch):
    from magnolie_file_desktop_connection import NativePhotoDesktopSession
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',.02)
    with composition(source,native[0]) as h:
        warm_metadata(h,native[0])
        session=h.connection.desktop_session();completed=threading.Event()
        h.connection._status_changed=lambda:completed.set() if session.snapshot()['state']=='complete' else None
        monkeypatch.setattr(h.connection,'request_source',lambda *a,**k:pytest.fail('Automatic PC-only pass requested phone READ'))
        h.controller.change('direction','pc_to_phone');h.controller.change('auto_mode','wifi')
        controls=agree(h,native[0]);owner=h.connection._local().owner
        assert completed.wait(30),session.snapshot()
        assert session.join(10),session.snapshot()
        state=session.snapshot()
        assert state['state']=='complete' and state['known_files']==1 and state['mode']=='automatic',state
        assert state['enabled'] is False and not h.source._prepared
        assert h.connection._local().owner is owner and h.connection._controls.packet().grants==controls.grants
        session.start('stop');assert session._automatic_paused
        session.shared_settings_changed();assert session._automatic_paused # duplicate matched echo cannot revive Stop.
        session._apply_mode('manual');session.shared_settings_changed()
        pending=h.wire.receive();assert pending['kind']=='file_transfer.shared_settings'
        dispatch(h,native[0],dict(type='ack',message_id=pending['message_id'],status='accepted',error='none'))
        dispatch(h,native[0],message('file_transfer.shared_settings',pending['body']));assert h.wire.receive()['type']=='ack'
        assert session.snapshot()['mode']=='manual' and session._schedule.mode=='manual'
        assert h.preferences.read().policy.enabled is False


def test_actual_wifi_automatic_worker_denies_route_change_during_source_read(source,native,monkeypatch):
    from magnolie_file_desktop_connection import NativePhotoDesktopSession
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',60)
    with composition(source,native[0]) as h:
        warm_metadata(h,native[0])
        h.controller.change('direction','pc_to_phone');h.controller.change('auto_mode','wifi');agree(h,native[0])
        def boundary(phase):
            if phase=='source_chunk_read':native[0].connection_transports[h.peer['device_id']]='bluetooth'
        h.source._boundary=boundary
        worker=h.connection.start_mapped_media_worker(h.connection.issue_receive_action(),automatic=True)
        try:
            assert worker.join(30),worker.progress()
            assert worker.progress()['state']=='held' and worker.progress()['error']=='media_source_native_wifi_required',worker.progress()
            assert not h.source._prepared and h.target.read_bytes()==b'hello'
        finally:native[0].connection_transports[h.peer['device_id']]='wifi'


def test_automatic_worker_requires_shared_wifi_mode_even_on_real_wifi_channel(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        warm_metadata(h,native[0])
        agree(h,native[0]);assert h.connection._native_wifi_current() is True
        monkeypatch.setattr(h.source,'plan',lambda *a,**k:pytest.fail('Shared manual mode started automatic export'))
        worker=h.connection.start_mapped_media_worker(h.connection.issue_receive_action(),automatic=True)
        assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and worker.progress()['error']=='media_source_native_wifi_required'
        assert not h.source._prepared


def test_matched_wifi_and_peer_receive_do_not_arm_sending_without_independent_native_consent(source,native,monkeypatch):
    from magnolie_file_control import FileControlPacket,FileGrantState,KIND as CONTROL
    with composition(source,native[0]) as h:
        h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
        monkeypatch.setattr(h.source,'plan',lambda *a,**k:pytest.fail('Shared settings replaced native sending consent'))
        h.controller.change('direction','pc_to_phone');h.controller.change('auto_mode','wifi')
        attempted=h.controller.send_settings();assert h.wire.receive()==attempted
        dispatch(h,native[0],dict(type='ack',message_id=attempted['message_id'],status='accepted',error='none'))
        dispatch(h,native[0],message('file_transfer.shared_settings',attempted['body']));assert h.wire.receive()['type']=='ack'
        assert h.connection.send_controls();first=FileControlPacket.parse(h.wire.receive()['body'])
        assert not first.grants.send_files and not first.grants.receive_files
        remote=FileControlPacket(FileGrantState(1,'6'*64,False,True),'7'*64,1,first.challenge)
        dispatch(h,native[0],message(CONTROL,remote.wire()));h.wire.receive()
        session=h.connection.desktop_session()
        assert not session._shared_automatic and session._timer is None
        assert session._schedule_scope() is None and not h.source._prepared


@pytest.mark.parametrize('mode',['manual','wifi'])
def test_new_channel_recomposes_existing_native_send_only_without_reenabling_receive_or_read(source,native,monkeypatch,mode):
    import magnolie_telefon as phone
    from magnolie_file_native_authority import capture_authenticated_binding
    from test_media_transport import PeerWire
    from magnolie_file_control import FileControlPacket,FileGrantState,KIND as CONTROL
    from magnolie_media_source import NativeMappedMediaSource
    from magnolie_file_desktop_connection import NativePhotoDesktopSession
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',.02)
    service=native[0]
    with composition(source,service) as old:
        old.controller.change('direction','pc_to_phone');old.controller.change('auto_mode',mode)
        before=old.preferences.read();assert not before.policy.enabled and before.policy.sending.photos
        shared=old.controller._store.read()
    left,right=socket.socketpair();left.settimeout(2);right.settimeout(10)
    channel=phone.SecureChannel(left,bytes([3])*16,bytes([1])*32,bytes([1])*4,bytes([2])*32,bytes([2])*4)
    h=SimpleNamespace(peer=source.peer,channel=channel,wire=PeerWire(right))
    binding=capture_authenticated_binding(dict(service.store.identity),dict(h.peer),service._generation,service.store)
    service._activate_connection(h.peer['device_id'],channel,'wifi',file_binding=binding)
    try:
        assert channel not in service._native_file_connections
        with monkeypatch.context() as patch:
            patch.setattr(NativeMappedMediaSource,'_file',lambda *a,**k:pytest.fail('Reconnection read media before fresh agreement'))
            warm_metadata(h,service)
        connection=service._native_file_connections.get(channel)
        assert connection is not None,'Current metadata ACKs did not compose the saved SEND-only backend'
        assert connection._media_source is not None and not connection._preferences.read().policy.enabled
        assert connection._preferences.read()==before # Reconnection must not rewrite native consent/settings.
        assert not connection._media_source._prepared and connection._mapped_worker is None
        assert connection._source_pending is None # No phone READ/discovery or incoming activation.
        assert connection._media_transport.intent_for('images',to_phone=True) is None # Fresh shared ACK/echo still missing.
        announced=[h.wire.receive(),h.wire.receive()]
        assert {packet['kind'] for packet in announced}=={'file_transfer.shared_settings',CONTROL}
        settings=next(packet for packet in announced if packet['kind']=='file_transfer.shared_settings')
        local=FileControlPacket.parse(next(packet for packet in announced if packet['kind']==CONTROL)['body'])
        assert settings['body']==shared and local.grants.send_files and not local.grants.receive_files
        completed=threading.Event()
        connection._status_changed=lambda:completed.set() if connection.desktop_snapshot()['state']=='complete' else None
        with monkeypatch.context() as patch:
            patch.setattr(NativeMappedMediaSource,'_file',lambda *a,**k:pytest.fail('Shared echo replaced current file-control ACK'))
            dispatch(h,service,dict(type='ack',message_id=settings['message_id'],status='accepted',error='none'))
            dispatch(h,service,message('file_transfer.shared_settings',settings['body']));assert h.wire.receive()['type']=='ack'
            assert connection._mapped_worker is None and connection.desktop_session()._schedule.active is None
        remote=FileControlPacket(FileGrantState(1,'6'*64,False,True),'7'*64,1,local.challenge)
        dispatch(h,service,message(CONTROL,remote.wire()));assert h.wire.receive()['kind']==CONTROL
        if mode=='wifi':
            assert completed.wait(30),connection.desktop_snapshot()
            assert connection.desktop_session().join(10)
            assert connection.desktop_snapshot()['known_files']==1 and not connection._media_source._prepared
        else:
            assert connection._mapped_worker is None and connection.desktop_session()._timer is None
        assert connection._preferences.read()==before and connection._source_pending is None
    finally:
        service._end_native_file_connection(channel)
        connection=service._native_file_connections.get(channel)
        if connection is not None:assert connection.desktop_session().join(15)
        left.close();right.close()


def test_lost_current_metadata_stops_live_source_and_later_real_ack_cannot_revive_ended_worker(source,native):
    from magnolie_file_transfer import TransferError
    with composition(source,native[0]) as h:
        agree(h,native[0])
        def boundary(phase):
            if phase=='source_chunk_read':native[0]._native_file_controls[h.channel].pop('grants.update',None)
        h.source._boundary=boundary
        worker=start(h);assert worker.join(30),worker.progress()
        assert worker.progress()['state']=='held' and worker.progress()['error']=='media_source_current_metadata_required',worker.progress()
        assert not h.source._prepared and h.target.read_bytes()==b'hello'
        h.source._boundary=lambda phase:None
        warm_metadata(h,native[0]);assert h.connection._native_metadata_current() is True
        with pytest.raises(TransferError,match='native_operation_ended'):worker._current()


def test_shared_two_way_automatic_does_not_invent_an_unjoined_phone_read_path(source,native,monkeypatch):
    from magnolie_file_desktop_connection import NativePhotoDesktopSession
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',.02)
    with composition(source,native[0]) as h:
        warm_metadata(h,native[0]);session=h.connection.desktop_session();held=threading.Event()
        h.connection._status_changed=lambda:held.set() if session.snapshot()['state']=='held' else None
        monkeypatch.setattr(h.connection,'request_source',lambda *a,**k:pytest.fail('Unjoined shared receiving path requested phone READ'))
        h.controller.change('auto_mode','wifi');agree(h,native[0]) # Existing two-way shared choice, receiving remains OFF.
        assert held.wait(30),session.snapshot()
        assert session.join(10),session.snapshot()
        assert session.snapshot()['error']=='media_source_shared_incoming_review_required'
        assert session.snapshot()['known_files']==1 and session._automatic_paused
        assert not h.source._prepared and h.connection._source_pending is None
