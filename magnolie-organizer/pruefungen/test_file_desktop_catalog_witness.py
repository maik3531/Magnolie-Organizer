"""Persisted catalog expectation is not a fresh empty catalog after metadata loss."""
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_photo_preferences import ProtectedPhotoPreferences,PhotoPreferences
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,negotiate
from test_file_desktop_sources import ready_source
from test_file_desktop_media import manifest,collect,send_offer,dispatch
from test_photo_mappings import save
from test_file_desktop_mapping_save import saved_messages
from test_file_desktop_mapping_witness import anchor


def anchor_catalog(fixture,*,mapping=False):
    connection=fixture[3]
    if mapping:anchor(fixture)
    authority=connection._authority;protection=authority.protection
    parent=Path(authority.binding.native_directory)
    with ProtectedTransferJobCatalog(parent,authority.identity,protection.seal,protection.unseal,
            create=not (parent/ProtectedTransferJobCatalog.NAME).exists()) as catalog:
        choice=catalog.choice();prefs=connection._preferences
        saved=prefs.configure(prefs.issue_action(),prefs.read(),enabled=True,mode='manual',job_catalog_choice=choice)
    negotiate(*fixture[:4])
    return saved.policy.job_catalog


def displace_catalog(fixture):
    connection=fixture[3]
    if connection._catalog is not None:connection._catalog.close();connection._catalog=None
    root=Path(connection._authority.binding.native_directory)/ProtectedTransferJobCatalog.NAME
    held=root.with_name(root.name+'-held-original');root.rename(held)
    return root,held


def test_catalog_marker_reopens_encrypted_and_cannot_be_rebound_to_new_empty_root(receiving):
    connection=receiving[3];witness=anchor_catalog(receiving);prefs=connection._preferences;saved=prefs.read()
    reopened=ProtectedPhotoPreferences(connection._authority)
    try:assert reopened.read()==saved and reopened.read().policy.job_catalog==witness
    finally:reopened.close()
    assert PhotoPreferences.parse(saved.policy.wire())==saved.policy
    root,held=displace_catalog(receiving);authority=connection._authority;protection=authority.protection
    with ProtectedTransferJobCatalog(root.parent,authority.identity,protection.seal,protection.unseal,create=True) as replacement:
        with pytest.raises(TransferError,match='original_job_catalog_required'):
            prefs.configure(prefs.issue_action(),saved,enabled=True,mode='manual',job_catalog_choice=replacement.choice())
    assert prefs.read()==saved and held.is_dir() and root.is_dir() # Both are preserved, not reset.


def test_catalog_witness_and_mapping_io_lease_allow_actual_save_without_recursive_catalog_lock(receiving):
    connection=receiving[3];witness=anchor_catalog(receiving,mapping=True)
    receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action())
    connection.send_saved_confirmation()
    assert connection._local().policy_ready and connection.read_preferences().policy.job_catalog==witness
    assert len(saved_messages(receiving))==2 and len(connection._catalog.jobs())==1


def test_whole_expected_catalog_missing_before_admission_is_not_first_use_after_observer_reopen(receiving):
    connection=receiving[3];anchor_catalog(receiving)
    ready_source(receiving);full=manifest(receiving);collect(receiving,full)
    offered,result=send_offer(receiving,full);dispatch(receiving,result)
    before=connection._local().grants;root,held=displace_catalog(receiving)
    try:
        current=connection._local()
        assert current.grants==before and not current.policy_ready
        with pytest.raises(TransferError):connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
        assert connection._catalog is None and connection._run is None and not root.exists() and held.is_dir()
        assert not list(receiving[4].iterdir()) and not connection._controls._faulted
    finally:held.rename(root)
    assert not connection._local().policy_ready # Observed uncertainty is sticky in this native owner.


@pytest.mark.parametrize('phase',['publication','saved-retry'])
def test_expected_catalog_loss_does_not_create_replacement_or_publish_or_confirm(receiving,phase):
    connection=receiving[3];anchor_catalog(receiving,mapping=True)
    receiver,_,_=save(receiving,publish=False)
    if phase=='saved-retry':connection.publish_received(connection.issue_receive_action())
    target=receiving[4]/dict(receiver._accepted.targets)[receiver._accepted.manifest.files[0].id]
    before=target.read_bytes() if target.exists() else None;sent=len(saved_messages(receiving))
    root,held=displace_catalog(receiving)
    try:
        with pytest.raises(TransferError):
            if phase=='publication':connection.publish_received(connection.issue_receive_action())
            else:connection.send_saved_confirmation()
        assert not root.exists() and held.is_dir() and len(saved_messages(receiving))==sent
        assert (target.read_bytes() if target.exists() else None)==before
    finally:held.rename(root)


def test_wire_catalog_choice_or_null_persisted_expectation_does_not_replace_policy(receiving):
    connection=receiving[3];witness=anchor_catalog(receiving);prefs=connection._preferences;saved=prefs.read()
    with pytest.raises(TransferError,match='foreign_job_catalog_choice'):
        prefs.configure(prefs.issue_action(),saved,enabled=True,mode='manual',job_catalog_choice=witness.wire())
    wire=saved.policy.wire();wire['job_catalog']=None
    with pytest.raises(TransferError):PhotoPreferences.parse(wire)
    assert prefs.read()==saved


def test_catalog_owner_corruption_is_sticky_unready_without_grant_rewrite_or_default_repair(receiving):
    connection=receiving[3];anchor_catalog(receiving);before=connection._local().grants
    path=Path(connection._authority.binding.native_directory)/ProtectedTransferJobCatalog.NAME/'owner.enc'
    original=path.read_bytes();broken=original[:-1]+bytes([original[-1]^1]);path.write_bytes(broken)
    current=connection._local()
    assert current.grants==before and not current.policy_ready and connection._catalog_expectation_uncertain
    assert path.read_bytes()==broken and not connection._controls._faulted
    path.write_bytes(original)
    assert not connection._local().policy_ready


def test_catalog_busy_is_transient_not_corruption_or_permission_equivocation(receiving):
    connection=receiving[3];anchor_catalog(receiving,mapping=True);save(receiving,publish=False)
    before=connection._local().grants;entered=threading.Event();release=threading.Event()
    def hold():
        with connection._catalog._gate:entered.set();assert release.wait(10)
    worker=threading.Thread(target=hold);worker.start()
    try:
        assert entered.wait(10)
        current=connection._local()
        assert current.grants==before and not current.policy_ready
        assert not connection._catalog_expectation_uncertain and not connection._controls._faulted
    finally:release.set();worker.join(5);assert not worker.is_alive()
    assert connection._local().policy_ready


@pytest.mark.parametrize('failure_call',[2,3])
def test_catalog_loss_during_policy_commit_or_readback_never_returns_success(receiving,monkeypatch,failure_call):
    connection=receiving[3];authority=connection._authority;protection=authority.protection;prefs=connection._preferences
    root=Path(authority.binding.native_directory)/ProtectedTransferJobCatalog.NAME
    catalog=ProtectedTransferJobCatalog(root.parent,authority.identity,protection.seal,protection.unseal,create=True)
    choice=catalog.choice();before=prefs.read();held=root.with_name(root.name+'-held-original')
    verify=catalog.verify_choice;calls=[]
    def interrupted(value):
        calls.append(True)
        if len(calls)==failure_call:root.rename(held)
        return verify(value)
    monkeypatch.setattr(catalog,'verify_choice',interrupted)
    try:
        with pytest.raises((TransferError,OSError)):
            prefs.configure(prefs.issue_action(),before,enabled=True,mode='manual',job_catalog_choice=choice)
        assert prefs._uncertain and not root.exists() and held.is_dir()
        reopened=ProtectedPhotoPreferences(authority)
        try:
            recovered=reopened.read()
            if failure_call==2:assert recovered==before
            else:assert recovered.policy.job_catalog==choice.witness
        finally:reopened.close()
    finally:catalog.close();held.rename(root)


@pytest.mark.parametrize('revoke_only',[False,True])
def test_exit_during_owner_only_observation_never_returns_stale_native_readiness(receiving,monkeypatch,revoke_only):
    connection=receiving[3];anchor_catalog(receiving)
    protection=connection._authority.protection;unseal=protection.unseal
    entered=threading.Event();release=threading.Event();ended=threading.Event();states=[];errors=[]
    def blocked(blob,domain):
        if domain.startswith('magnolie-file-job-catalog-v1/') and domain.endswith('/owner.enc'):
            entered.set();assert release.wait(10)
        return unseal(blob,domain)
    monkeypatch.setattr(protection,'unseal',blocked)
    def observe():
        try:
            with connection._operation():states.append(connection._local())
        except Exception as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=observe);worker.start()
    try:
        assert entered.wait(10)
        if revoke_only:connection._authority.revoke()
        else:assert connection.close() is False
        assert not protection._closed
        release.set();assert ended.wait(10);worker.join(5)
        assert not worker.is_alive() and not states
        assert len(errors)==1 and isinstance(errors[0],TransferError)
        assert str(errors[0])==('file_desktop_native_authority_changed' if revoke_only else 'file_desktop_connection_closed')
        if revoke_only:assert connection.close() is True
        assert protection._closed
    finally:release.set();worker.join(5);assert not worker.is_alive()
