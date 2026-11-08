"""Normal native Linux factory/dispatcher share one actual control session."""
from contextlib import contextmanager
from types import SimpleNamespace
import threading
import uuid
import pytest

from test_media_source_media_offer import source, native, receiving, mappings, png, readback
from test_media_source_sender import message, acceptance, request, saved
from test_media_source_backup import open_backup
from magnolie_file_control import FileControlPacket, FileGrantState, KIND as CONTROL
from magnolie_file_transfer import TransferError
from magnolie_media_source_backup import backup_prepared_source
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_media_retention import NativeMediaRetention


@contextmanager
def composition(h,service):
    connection=service.open_native_file_connection(h.peer['device_id'],h.peer['static_public'],h.channel,h.authority.binding.generation)
    scoped=SimpleNamespace(**dict(vars(h),authority=connection._authority,source=connection._media_source,
        controller=connection._media_transport,preferences=connection._preferences,mappings=connection._mappings,connection=connection))
    try:
        assert scoped.source is not None
        policy=scoped.preferences.read()
        if policy.policy.enabled:
            scoped.preferences.configure(scoped.preferences.issue_action(),policy,enabled=False,mode=policy.mode)
        yield scoped
    finally:service._end_native_file_connection(h.channel)


def dispatch(h,service,packet):
    h.wire.send(packet);return service._payload(h.peer,h.channel,h.channel.receive())


def agree(h,service):
    attempted=h.controller.send_settings();assert h.wire.receive()==attempted
    assert h.controller.intent_for('images',to_phone=True) is None
    dispatch(h,service,dict(type='ack',message_id=attempted['message_id'],status='accepted',error='none'))
    assert h.controller.intent_for('images',to_phone=True) is None
    dispatch(h,service,message('file_transfer.shared_settings',attempted['body']))
    assert h.wire.receive()['type']=='ack'
    assert h.controller.intent_for('images',to_phone=True) is not None
    assert h.connection.send_controls();first=FileControlPacket.parse(h.wire.receive()['body'])
    assert first.grants.send_files and not first.grants.receive_files
    remote=FileControlPacket(FileGrantState(1,'6'*64,False,True),'7'*64,1,first.challenge)
    dispatch(h,service,message(CONTROL,remote.wire()))
    echoed=FileControlPacket.parse(h.wire.receive()['body'])
    assert echoed.session_epoch==first.session_epoch and echoed.echo==remote.challenge
    return echoed


def prepare(h):
    h.target.write_bytes(png())
    cache=h.connection.prepare_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,h.record.protected_record_sha256)
    sender=h.connection.open_prepared_media_sender(cache.manifest.source_id)
    assert sender._controls is h.connection._controls and sender._source is h.source
    return sender,cache


def complete(h,service):
    sender,cache=prepare(h)
    offer=sender.send_media_offer();assert h.wire.receive()==offer
    accepted=acceptance(sender,cache,offer);dispatch(h,service,accepted)
    for index in range(cache.manifest.files[0].chunks):
        dispatch(h,service,request(accepted,cache,index));assert h.wire.receive()['kind']=='file_transfer.chunk'
    dispatch(h,service,saved(accepted,cache))
    dispatch(h,service,readback(sender,cache,offer))
    assert sender.observation().body['phase']=='peer_readback'
    return sender,cache


def test_normal_factory_and_dispatcher_complete_media_then_archive_without_rotating_the_shared_control_owner(source,native):
    with composition(source,native[0]) as h:
        controls=agree(h,native[0]);sender,cache=complete(h,native[0])
        owner=h.connection._local().owner
        with open_backup(h) as backups:
            backup=backup_prepared_source(backups,h.source,cache.manifest.source_id)
            result=_NativeSourceRetirement(sender,backups,backup).run()
            assert result.body['state']=='archived' and not cache.directory.exists()
        assert h.connection._media_sender is None and h.connection._local().owner is owner
        after=h.connection._controls.packet()
        assert after.session_epoch==controls.session_epoch and after.grants==controls.grants and after.sequence>controls.sequence
        assert h.target.read_bytes()==png()
        assert not h.connection.receive_media_ack(dict(type='ack',message_id=str(uuid.uuid4()),status='accepted',error='none'))


def test_normal_connection_plans_actual_mapped_bytes_without_cache_output_or_send_owner_changes(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        controls=agree(h,native[0]);owner=h.connection._local().owner;output=[]
        monkeypatch.setattr(h.channel,'send',lambda packet:output.append(packet))
        def plan():
            return h.connection.plan_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,h.record.protected_record_sha256)
        unchanged=plan()
        assert not unchanged.changed and unchanged.basis=='original_mapping'
        h.target.write_bytes(png());changed=plan()
        assert changed.changed and not changed.grants_read_authority
        assert not output and not h.source._prepared and h.connection._media_sender is None
        after=h.connection._controls.packet()
        assert after.session_epoch==controls.session_epoch and after.grants==controls.grants
        assert h.connection._local().owner is owner


def test_conditional_normal_preparation_waits_for_actual_send_ack_and_skips_unchanged_source(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        def prepare():
            return h.connection.prepare_changed_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,h.record.protected_record_sha256)
        with pytest.raises(TransferError,match='current_send_control_required'):prepare()
        assert not h.source._prepared
        agree(h,native[0]);result=prepare()
        assert not result.plan.changed and result.cache is None and not result.grants_read_authority
        assert not h.source._prepared and h.connection._media_sender is None
        with monkeypatch.context() as patch:
            patch.setattr(h.source,'plan',lambda *args,**kwargs:pytest.fail('Ended native pass started source planning'))
            with pytest.raises(TransferError,match='native_operation_ended'):
                h.connection.prepare_changed_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,
                    h.record.protected_record_sha256,native_current=lambda:False)


def test_conditional_prepare_rejects_plan_freeze_file_change_before_creating_cache(source,native,monkeypatch):
    from pathlib import Path
    with composition(source,native[0]) as h:
        agree(h,native[0]);h.target.write_bytes(png());original=h.source.plan
        def changed(*args,**kwargs):
            result=original(*args,**kwargs);h.target.write_bytes(png(1));return result
        monkeypatch.setattr(h.source,'plan',changed)
        with pytest.raises(TransferError,match='observed_content_changed'):
            h.connection.prepare_changed_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,h.record.protected_record_sha256)
        assert not h.source._prepared and not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*'))
        assert h.target.read_bytes()==png(1)


def test_conditional_prepare_pins_catalog_between_plan_and_fresh_freeze(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        agree(h,native[0]);h.target.write_bytes(png());original=h.source.plan;created=[]
        def changed(*args,**kwargs):
            result=original(*args,**kwargs)
            created.append(h.source.freeze(h.preferences.issue_action(),h.preferences.read(),h.association,h.record.protected_record_sha256))
            return result
        monkeypatch.setattr(h.source,'plan',changed)
        with pytest.raises(TransferError,match='observed_history_changed'):
            h.connection.prepare_changed_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,h.record.protected_record_sha256)
        assert len(created)==1 and set(h.source._prepared)=={created[0].manifest.source_id}
        assert h.connection._media_sender is None and created[0].directory.exists()


def test_actual_conditional_prepare_uses_shared_sender_then_skips_completed_source_without_owner_changes(source,native):
    with composition(source,native[0]) as h:
        controls=agree(h,native[0]);owner=h.connection._local().owner;h.target.write_bytes(png())
        def prepare():
            return h.connection.prepare_changed_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,
                h.record.protected_record_sha256,native_current=lambda:True,mapping_snapshot=h.mappings.read())
        selected=prepare();cache=selected.cache
        assert selected.plan.changed and cache is not None and selected.plan.observation.sha256==cache.manifest.files[0].sha256
        sender=h.connection.open_prepared_media_sender(cache.manifest.source_id)
        assert sender._controls is h.connection._controls
        offer=sender.send_media_offer();assert h.wire.receive()==offer
        accepted=acceptance(sender,cache,offer);dispatch(h,native[0],accepted)
        for index in range(cache.manifest.files[0].chunks):
            dispatch(h,native[0],request(accepted,cache,index));assert h.wire.receive()['kind']=='file_transfer.chunk'
        dispatch(h,native[0],saved(accepted,cache));dispatch(h,native[0],readback(sender,cache,offer))
        with open_backup(h) as backups:
            backup=backup_prepared_source(backups,h.source,cache.manifest.source_id)
            archived=_NativeSourceRetirement(sender,backups,backup).run()
            assert archived.body['state']=='archived'
        skipped=prepare()
        assert not skipped.plan.changed and skipped.plan.basis=='latest_completed' and skipped.cache is None
        assert not h.source._prepared and h.connection._media_sender is None
        after=h.connection._controls.packet()
        assert after.session_epoch==controls.session_epoch and after.grants==controls.grants
        assert h.connection._local().owner is owner


def test_close_during_actual_borrowed_sender_output_retains_connection_cleanup_and_os_lane_until_drain(source,native,monkeypatch):
    with composition(source,native[0]) as h:
        agree(h,native[0]);sender,cache=prepare(h)
        entered=threading.Event();release=threading.Event();errors=[];original=h.channel.send
        def blocked(packet):
            if packet.get('kind')=='file_transfer.media_offer':entered.set();assert release.wait(8)
            return original(packet)
        monkeypatch.setattr(h.channel,'send',blocked)
        def output():
            try:sender.send_media_offer()
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=output);worker.start()
        try:
            assert entered.wait(5)
            assert not h.connection.receive_media_ack(dict(type='ack',message_id=str(uuid.uuid4()),status='accepted',error='none'))
            assert h.connection.close() is False
            assert not h.connection._release_reported and not h.preferences._closed.is_set()
            with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                with retention.activity(lambda:True) as permit:assert permit is None
            assert cache.directory.exists() and h.target.read_bytes()==png()
        finally:release.set();worker.join(10)
        assert not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
        assert h.connection._release_reported and h.preferences._closed.is_set() and cache.directory.exists()


def test_close_during_actual_borrowed_native_archive_move_keeps_connection_owner_until_real_io_end(source,native,monkeypatch):
    import magnolie_media_source_retirement as retirement
    from test_media_source_retirement import archive_path
    with composition(source,native[0]) as h:
        agree(h,native[0]);sender,cache=complete(h,native[0])
        entered=threading.Event();release=threading.Event();errors=[];move=retirement._move_no_replace
        before={path.name:path.read_bytes() for path in cache.directory.iterdir()}
        with open_backup(h) as backups:
            backup=backup_prepared_source(backups,h.source,cache.manifest.source_id)
            owner=_NativeSourceRetirement(sender,backups,backup)
            def blocked(*args,**kwargs):
                entered.set();assert release.wait(8);return move(*args,**kwargs)
            monkeypatch.setattr(retirement,'_move_no_replace',blocked)
            def archive():
                try:owner.run()
                except BaseException as error:errors.append(error)
            worker=threading.Thread(target=archive);worker.start()
            try:
                assert entered.wait(5) and h.connection.close() is False
                assert not h.connection._release_reported and not h.preferences._closed.is_set()
                with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                    with retention.activity(lambda:True) as permit:assert permit is None
            finally:release.set();worker.join(10)
            assert not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
            assert h.connection._release_reported
            retained=cache.directory if cache.directory.exists() else archive_path(h,sender,cache)
            assert {path.name:path.read_bytes() for path in retained.iterdir()}==before and h.target.read_bytes()==png()


def test_factory_source_grant_requires_independent_consent_and_does_not_rotate_owner_when_it_changes(source,native):
    with composition(source,native[0]) as h:
        before=h.connection._local();assert before.grants.send_files
        policy=h.preferences.read()
        h.preferences.configure_sending(h.preferences.issue_action(),policy,photos=False,videos=False)
        denied=h.connection._local()
        assert denied.owner is before.owner and not denied.grants.send_files and denied.grants.revision>before.grants.revision
        packet=h.connection._controls.packet()
        assert packet.grants==denied.grants
        with pytest.raises(TransferError):
            h.connection.prepare_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,h.record.protected_record_sha256)
        assert not h.source._prepared and h.target.read_bytes()==b'hello'
