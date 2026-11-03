"""Existing native job identities fence new copies before mapping recovery."""
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_photo_mappings import ProtectedPhotoMappings
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,accept
from test_file_desktop_sources import ready_source
from test_file_desktop_media import manifest,collect,send_offer,dispatch
from test_photo_mappings import save


@pytest.mark.parametrize('phase',['staged','unreceipted','edited','deleted','map-missing'])
def test_actual_job_anchor_prevents_new_admission_when_mapping_is_not_yet_committed_or_missing(receiving,phase):
    connection=receiving[3];receiver,pages,association=save(receiving,publish=phase in ('edited','deleted'))
    full=receiver._accepted.manifest;target=receiving[4]/dict(receiver._accepted.targets)[full.files[0].id]
    held=root=None
    if phase=='unreceipted':
        action=connection.issue_receive_action();connection._take_action(action);connection._mutation_action=action
        try:receiver.publish_completed()
        finally:connection._mutation_action=None
        assert not receiver._index.saved_receipts() and target.read_bytes()==b'hello'
    elif phase=='edited':target.write_bytes(b'preserve earlier PC crop')
    elif phase=='deleted':target.unlink() # Explicit fixture user action only.
    elif phase=='map-missing':
        connection.publish_received(connection.issue_receive_action())
        owner=connection._mappings;root=Path(receiving[0].store.root)/owner._name
        held=root.with_name(root.name+'-held-original');owner.close();root.rename(held)
        connection._mappings=ProtectedPhotoMappings(connection._authority)
    receiver.close();connection._run=None
    before=target.read_bytes() if target.exists() else None;jobs=connection._catalog.jobs()
    try:
        mapping=connection._mappings.read()
        assert mapping.count==0 and mapping.revision==(0 if phase=='map-missing' else 1)
        # Missing previously bound roots now fence current native availability
        # before history inspection; uncommitted mappings still hit job history.
        error='receive_controls_not_agreed' if phase=='map-missing' else 'photo_job_requires_reconcile'
        with pytest.raises(TransferError,match=error):
            connection.accept_pending_offer(connection.issue_receive_action(),connection._offer['message_id'])
        assert connection._run is None and connection._catalog.jobs()==jobs
        assert (target.read_bytes() if target.exists() else None)==before
        assert (Path(receiving[0].store.root)/connection._mappings._name).exists()==(phase!='map-missing')
    finally:
        if held is not None:held.rename(root)


def test_missing_existing_job_index_is_repair_not_empty_history_or_new_reservation(receiving):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    index=receiver._index;original=index._parent/index._name/'index.sqlite'
    held=original.with_name('index.sqlite-held-original')
    receiver.close();connection._run=None;original.rename(held)
    jobs=connection._catalog.jobs()
    try:
        with pytest.raises(TransferError,match='photo_job_repair_pending'):
            connection.accept_pending_offer(connection.issue_receive_action(),connection._offer['message_id'])
        assert not original.exists() and held.exists() and connection._catalog.jobs()==jobs and connection._run is None
    finally:held.rename(original)


def test_reservation_changed_after_empty_history_probe_fences_before_own_cache_or_accept_output(receiving,monkeypatch):
    connection=receiving[3];ready_source(receiving);full=manifest(receiving);collect(receiving,full)
    offered,result=send_offer(receiving,full);dispatch(receiving,result)
    open_catalog=connection._open_catalog;inserted=[]
    def concurrent(*,allow_create=True):
        result=open_catalog(allow_create=allow_create)
        if allow_create and not inserted:
            inserted.append(connection._catalog.reserve(connection._run.accepted,connection._receive_binding))
        return result
    monkeypatch.setattr(connection,'_open_catalog',concurrent)
    with pytest.raises(TransferError,match='file_job_catalog_history_changed'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    assert connection._catalog.jobs()==tuple(inserted) and len(inserted)==1
    assert connection._run.receiver is None and not list(receiving[4].iterdir())
    assert all(call.args[0]['kind']!='file_transfer.accept' for call in receiving[2].send.call_args_list)


def test_legacy_job_without_original_media_ids_requires_repair_before_new_media_admission(receiving):
    connection=receiving[3];_,full=accept(receiving)
    receiver=connection._run.receiver;receiver.close();connection._run=None;connection._offer=None
    ready_source(receiving);collect(receiving,full)
    offered,result=send_offer(receiving,full);dispatch(receiving,result)
    before=connection._catalog.jobs()
    with pytest.raises(TransferError,match='photo_job_history_required'):
        connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    assert connection._run is None and connection._catalog.jobs()==before


def test_missing_current_media_pages_do_not_bypass_existing_job_identity(receiving):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    receiver.close();connection._run=None
    connection._source_media_pages=();connection._source_media_entries=None
    before=connection._catalog.jobs()
    with pytest.raises(TransferError,match='source_media_history_required'):
        connection.accept_pending_offer(connection.issue_receive_action(),connection._offer['message_id'])
    assert connection._run is None and connection._catalog.jobs()==before


def test_historical_job_identity_is_read_without_target_verification_binding_renewal_or_sealing(receiving):
    connection=receiving[3];receiver,_,_=save(receiving)
    history=receiver._index.media_history;receiver.close();connection._run=None
    original=receiving[4];held=original.with_name(original.name+'-held-original');original.rename(held)
    protection=connection._authority.protection
    def forbidden(*args):raise AssertionError('historical inspection must not renew bindings or seal')
    try:
        with connection._catalog.inspect_jobs() as (parent,jobs):
            assert len(jobs)==1
            job=jobs[0]
            with ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,forbidden,
                    forbidden,protection.unseal,owner=job.owner) as index:
                assert index.media_history==history
                assert not index.media_history.grants_write_authority and not index.media_history.is_saved_receipt
        assert not original.exists() and (held/dict(job.accepted.targets)[job.accepted.manifest.files[0].id]).read_bytes()==b'hello'
    finally:held.rename(original)


def test_exit_during_historical_index_read_keeps_key_until_io_end_and_starts_no_new_receiver(receiving,monkeypatch):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    receiver.close();connection._run=None
    protection=connection._authority.protection;unseal=protection.unseal
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[]
    def blocked(blob,domain):
        if domain.startswith('magnolie-transfer-job-index-v1/') and domain.endswith('/owner'):
            entered.set();assert release.wait(10)
        return unseal(blob,domain)
    monkeypatch.setattr(protection,'unseal',blocked)
    def inspect():
        try:connection.accept_pending_offer(connection.issue_receive_action(),connection._offer['message_id'])
        except Exception as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=inspect);worker.start()
    try:
        assert entered.wait(10)
        assert connection.close() is False and not protection._closed
        release.set();assert ended.wait(10);worker.join(5)
        assert not worker.is_alive() and len(errors)==1
        assert isinstance(errors[0],TransferError) and str(errors[0])=='file_desktop_connection_closed'
        assert protection._closed and connection._run is None
    finally:
        release.set();worker.join(5)
        assert not worker.is_alive()
