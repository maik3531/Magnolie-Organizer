"""Fresh native desktop recovery of complete historical receipts only."""
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_file_saved_message import parse_saved
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,reconnect
from test_file_desktop_mapping_save import saved_messages
from test_photo_mappings import save
from test_file_desktop_catalog_witness import anchor_catalog


@pytest.mark.parametrize('change',['unchanged','edited','deleted','replaced'])
def test_fresh_native_recovery_repeats_only_original_saved_evidence_without_stage_journal_or_source(receiving,monkeypatch,change):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());job=receiver.job
    expected=receiver._index.saved_mapping_receipt();local=receiver._index.saved_receipts()
    target=receiving[4]/local[0].relative_path
    if change=='edited':target.write_bytes(b'preserve edited original')
    elif change=='deleted':target.unlink() # Explicit user deletion of fixture target only.
    elif change=='replaced':
        held=target.with_name('user-replacement.jpg');held.write_bytes(b'preserve replacement');held.replace(target)
    before=(target.read_bytes(),target.stat().st_ino) if target.exists() else None
    receiver._stage.cleanup() # Prove durable receipts do not require retained cache.
    def forbidden(*args,**kwargs):raise AssertionError('historical recovery must not reopen source/stage/journal/publisher')
    for name in ('EncryptedTransferStage','ProtectedPublicationJournal','NativeFilePublisher'):
        monkeypatch.setattr('magnolie_file_receive.'+name,forbidden)
    with reconnect(receiving) as fresh:
        reopened=fresh[3]
        monkeypatch.setattr(reopened._mappings,'commit_saved_history',forbidden)
        result=reopened.recover_saved_confirmation(reopened.issue_receive_action(),job.owner)
        assert result==expected and reopened._run is None and len(reopened._catalog.jobs())==1
        messages=saved_messages(fresh);assert len(messages)==1
        confirmation=parse_saved(messages[0],job.accepted.manifest)
        assert confirmation.acceptance_sha256==job.accepted.fingerprint
        assert confirmation.receipts[0].receipt_sha256==local[0].protected_record_sha256
        assert [call.args[0]['kind'] for call in fresh[2].send.call_args_list]==['file_transfer.saved']
        reopened.recover_saved_confirmation(reopened.issue_receive_action(),job.owner)
        assert len(reopened._catalog.jobs())==1
    assert ((target.read_bytes(),target.stat().st_ino) if target.exists() else None)==before


def test_unfinished_original_job_cannot_become_saved_by_recovery(receiving):
    receiver,_,_=save(receiving,publish=False);job=receiver.job
    with reconnect(receiving) as fresh:
        connection=fresh[3]
        with pytest.raises(TransferError,match='complete_evidence_required'):
            connection.recover_saved_confirmation(connection.issue_receive_action(),job.owner)
        assert not saved_messages(fresh) and connection._run is None and len(connection._catalog.jobs())==1


def test_complete_local_save_without_post_mapping_receipt_is_held_not_reconstructed(receiving,monkeypatch):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False);protect=receiver._index._protect
    def fail(value,label):
        if label=='mapping-receipt':raise OSError('fixture original mapping receipt not committed')
        return protect(value,label)
    monkeypatch.setattr(receiver._index,'_protect',fail)
    with pytest.raises(OSError):connection.publish_received(connection.issue_receive_action())
    assert receiver._index.saved_receipts() and connection._mappings.read().count==1
    with reconnect(receiving) as fresh:
        connection=fresh[3]
        def forbidden(*args,**kwargs):raise AssertionError('recovery must not manufacture missing proof')
        monkeypatch.setattr(connection._mappings,'commit_saved_history',forbidden)
        with pytest.raises(TransferError,match='complete_evidence_required'):
            connection.recover_saved_confirmation(connection.issue_receive_action(),receiver.job.owner)
        assert not saved_messages(fresh) and connection._mappings.read().count==1


def test_recovery_action_cannot_be_reused_to_send_again(receiving):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action())
    with reconnect(receiving) as fresh:
        connection=fresh[3];action=connection.issue_receive_action()
        connection.recover_saved_confirmation(action,receiver.job.owner)
        with pytest.raises(TransferError):connection.recover_saved_confirmation(action,receiver.job.owner)
        assert len(saved_messages(fresh))==1


def test_unknown_original_job_is_not_created_or_reconstructed_by_recovery(receiving):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action())
    with reconnect(receiving) as fresh:
        connection=fresh[3];before=tuple(Path(connection._authority.binding.native_directory).iterdir())
        with pytest.raises(TransferError,match='original_job_required'):
            connection.recover_saved_confirmation(connection.issue_receive_action(),'f'*32)
        assert tuple(Path(connection._authority.binding.native_directory).iterdir())==before
        assert not saved_messages(fresh) and len(connection._catalog.jobs())==1


def test_live_receiver_prevents_second_recovery_path_without_sending(receiving):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());before=len(saved_messages(receiving))
    with pytest.raises(TransferError,match='already_active'):
        connection.recover_saved_confirmation(connection.issue_receive_action(),receiver.job.owner)
    assert len(saved_messages(receiving))==before


def test_fresh_recovery_with_both_original_root_witnesses_does_not_reenter_os_locks(receiving):
    connection=receiving[3];anchor_catalog(receiving,mapping=True)
    receiver,_,_=save(receiving,publish=False);connection.publish_received(connection.issue_receive_action())
    job=receiver.job;expected=receiver._index.saved_mapping_receipt()
    with reconnect(receiving) as fresh:
        connection=fresh[3]
        assert connection.recover_saved_confirmation(connection.issue_receive_action(),job.owner)==expected
        assert connection._local().policy_ready and len(saved_messages(fresh))==1


def test_revocation_after_actual_mapping_lookup_prevents_any_recovery_socket_output(receiving,monkeypatch):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());job=receiver.job
    with reconnect(receiving) as fresh:
        connection=fresh[3];lookup=connection._mappings.lookup
        def revoke(associations,**selection):
            result=lookup(associations,**selection);connection._authority.revoke();return result
        monkeypatch.setattr(connection._mappings,'lookup',revoke)
        with pytest.raises(TransferError):connection.recover_saved_confirmation(connection.issue_receive_action(),job.owner)
        assert not saved_messages(fresh) and connection._run is None


@pytest.mark.parametrize('mode',['exit','revoke'])
def test_exit_during_recovery_output_retains_owned_descriptors_until_actual_end_and_returns_no_success(receiving,monkeypatch,mode):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());job=receiver.job
    with reconnect(receiving) as fresh:
        connection=fresh[3];entered=threading.Event();release=threading.Event();ended=threading.Event();results=[];errors=[]
        def blocked(message):
            assert message['kind']=='file_transfer.saved';entered.set();assert release.wait(10)
        fresh[2].send.side_effect=blocked
        action=connection.issue_receive_action()
        def work():
            try:results.append(connection.recover_saved_confirmation(action,job.owner))
            except Exception as error:errors.append(error)
            finally:ended.set()
        worker=threading.Thread(target=work);worker.start()
        try:
            assert entered.wait(15)
            if mode=='exit':assert not connection.close()
            else:connection._authority.revoke()
            assert not connection._catalog._closed
            release.set();assert ended.wait(10);worker.join(10)
            assert not results and len(errors)==1 and isinstance(errors[0],TransferError)
        finally:
            release.set();assert ended.wait(10);worker.join(10)
