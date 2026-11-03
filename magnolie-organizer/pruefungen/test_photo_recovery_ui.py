"""Explicit Organizer recovery through GTK/IPC; no target reconstruction."""
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,reconnect
from test_file_desktop_mapping_save import saved_messages
from test_photo_mappings import save
from test_saved_mapping_repair import interrupted_save
from test_photo_desktop_workflow import native_ui,converge_controls


@pytest.mark.parametrize('repair',[False,True])
def test_gtk_ipc_recovery_rechecks_original_saved_evidence_without_restoring_user_deleted_file(receiving,monkeypatch,request,repair):
    connection=receiving[3]
    if repair:receiver=interrupted_save(receiving,monkeypatch)
    else:
        receiver,_,_=save(receiving,publish=False)
        connection.publish_received(connection.issue_receive_action())
    job=receiver.job;target=receiving[4]/receiver._index.saved_receipts()[0].relative_path
    target.unlink() # Explicit user deletion in this fixture, never recovered.
    receiver._stage.cleanup()
    def forbidden(*args,**kwargs):raise AssertionError('Recovery must not open a stage, publisher or journal')
    for name in ('EncryptedTransferStage','ProtectedPublicationJournal','NativeFilePublisher'):
        monkeypatch.setattr('magnolie_file_receive.'+name,forbidden)
    with reconnect(receiving) as fresh:
        service,peer,channel,connection,_=fresh
        converge_controls(service,peer,channel)
        session=connection.desktop_session();session._local_enabled(True)
        action=native_ui(service,peer,request)
        channel.send.reset_mock()
        before=connection._mappings.read()
        session._automatic_paused=True
        action(dict(action='inspect_recovery'));assert session.join(15),session.snapshot()
        assert session._automatic_paused # Metadata review never resumes paused automatic I/O.
        overview=session.snapshot()
        assert overview['state']=='recovery' and overview['recovery_result'] is None,overview
        assert overview['recovery']==[dict(job_owner=job.owner,state='mapping_receipt_repair' if repair else 'saved_confirmation',files=1)]
        assert not saved_messages(fresh)
        if repair:
            action(dict(action='repair_receipt',job_owner=job.owner));assert session.join(15),session.snapshot()
            assert session.snapshot()['recovery_result']=='receipt_repaired',session.snapshot()
            assert session.snapshot()['recovery'][0]['state']=='saved_confirmation'
            assert not saved_messages(fresh)
        action(dict(action='recover_saved',job_owner=job.owner));assert session.join(15),session.snapshot()
        assert session.snapshot()['state']=='recovery',session.snapshot()
        assert session._automatic_paused
        assert session.snapshot()['recovery_result']=='confirmation_sent'
        assert len(saved_messages(fresh))==1
        assert connection._catalog.jobs()==(job,) and connection._mappings.read()==before
        assert not target.exists() and connection._run is None


def test_recovery_inspection_is_inert_and_live_receiver_prevents_metadata_bypass(receiving):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    with pytest.raises(TransferError,match='already_active'):
        connection.inspect_photo_recovery(connection.issue_receive_action())
    job=receiver.job
    with reconnect(receiving) as fresh:
        connection=fresh[3];before=fresh[2].send.call_count
        overview=connection.inspect_photo_recovery(connection.issue_receive_action())
        assert overview==(dict(job_owner=job.owner,state='resumable',files=1),)
        assert fresh[2].send.call_count==before and not saved_messages(fresh)
        assert connection._run is None and connection._source_run is None


def test_gtk_recovery_rejects_stale_unknown_original_without_sending_or_creating_job(receiving,request):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());job=receiver.job
    with reconnect(receiving) as fresh:
        service,peer,channel,connection,_=fresh;converge_controls(service,peer,channel)
        session=connection.desktop_session();session._local_enabled(True)
        action=native_ui(service,peer,request);channel.send.reset_mock()
        action(dict(action='recover_saved',job_owner='f'*32));assert session.join(15),session.snapshot()
        assert session.snapshot()['state']=='held' and session.snapshot()['recovery_result'] is None
        assert 'original_job_required' in session.snapshot()['error']
        assert not saved_messages(fresh) and connection._catalog.jobs()==(job,)


def test_actual_source_owner_blocks_inspection_and_both_receipt_actions(receiving):
    from test_file_desktop_sources import ready_source
    ready_source(receiving);connection=receiving[3]
    before=receiving[2].send.call_count
    for method in (connection.inspect_photo_recovery,connection.recover_saved_confirmation,connection.repair_saved_mapping_receipt):
        args=() if method==connection.inspect_photo_recovery else ('f'*32,)
        with pytest.raises(TransferError,match='already_active'):
            method(connection.issue_receive_action(),*args)
    assert receiving[2].send.call_count==before and connection._run is None


def test_recovery_lane_retains_busy_until_actual_ack_output_end_and_rejects_overlap(receiving,request):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());job=receiver.job
    with reconnect(receiving) as fresh:
        service,peer,channel,connection,_=fresh;converge_controls(service,peer,channel)
        session=connection.desktop_session();session._local_enabled(True)
        action=native_ui(service,peer,request)
        entered=threading.Event();release=threading.Event()
        def blocked(message):
            assert message['kind']=='file_transfer.saved';entered.set();assert release.wait(10)
        channel.send.side_effect=blocked
        try:
            action(dict(action='recover_saved',job_owner=job.owner));assert entered.wait(10)
            with pytest.raises(TransferError,match='busy'):
                session.start('repair_receipt',job_owner=job.owner)
            action(dict(action='stop'))
            assert session.snapshot()['busy'] and not session.join(.05)
            assert session.snapshot()['recovery_result'] is None
        finally:
            release.set();assert session.join(15),session.snapshot();channel.send.side_effect=None
        assert session.snapshot()['state']=='held' and session.snapshot()['recovery_result'] is None
        assert connection._catalog.jobs()==(job,) and connection._run is None


@pytest.mark.parametrize('kind',['missing_mapping','corrupt_index'])
def test_recovery_overview_holds_unproven_or_corrupt_history_without_repair_or_output(receiving,monkeypatch,kind):
    connection=receiving[3]
    if kind=='missing_mapping':receiver=interrupted_save(receiving,monkeypatch,missing='mapping')
    else:
        receiver,_,_=save(receiving,publish=False)
        blob=receiver._index._db.execute('SELECT payload FROM meta WHERE id=1').fetchone()[0]
        with receiver._index._db:
            receiver._index._db.execute('UPDATE meta SET payload=? WHERE id=1',(blob[:-1]+bytes([blob[-1]^1]),))
    job=receiver.job
    with reconnect(receiving) as fresh:
        connection=fresh[3];before=fresh[2].send.call_count
        assert connection.inspect_photo_recovery(connection.issue_receive_action())==(dict(job_owner=job.owner,state='held',files=1),)
        assert fresh[2].send.call_count==before and connection._catalog.jobs()==(job,)
        assert not saved_messages(fresh) and connection._run is None


@pytest.mark.parametrize('body',[dict(action='recover_saved'),dict(action='repair_receipt',job_owner='../other'),
    dict(action='inspect_recovery',job_owner='a'*32),dict(action='sync',album_id='album',job_owner='a'*32)])
def test_service_rejects_malformed_recovery_selection_before_starting_native_lane(receiving,body):
    service,peer,_,connection,_=receiving
    from magnolie_telefon import fingerprint,unb64
    with pytest.raises(ValueError,match='invalid_action'):
        service.photo_sync_action(peer['device_id'],fingerprint(unb64(peer['static_public'],32)),body)
    assert connection._desktop_session is None and connection._run is None
