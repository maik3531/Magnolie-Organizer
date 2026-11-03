"""Metadata readiness is not a same-revision rewrite of native consent."""
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_mapping_witness import anchor,displace
from test_file_desktop_mapping_save import saved_messages
from test_photo_mappings import save


def test_native_grant_and_mapping_expectation_use_one_fresh_protected_policy_read(receiving,monkeypatch):
    connection=receiving[3];anchor(receiving)
    read=connection._preferences.read;calls=[]
    def counted():
        calls.append(True);return read()
    monkeypatch.setattr(connection._preferences,'read',counted)
    assert connection._local().policy_ready and calls==[True]
    assert connection._local().policy_ready and calls==[True,True] # No availability Boolean cache.


def test_missing_expected_store_clamps_policy_readiness_without_permission_equivocation(receiving):
    connection=receiving[3];anchor(receiving);before=connection._local()
    root,held=displace(receiving)
    try:
        current=connection._local()
        assert current.grants==before.grants and current.handlers_ready and not current.policy_ready
        assert connection._controls.binding(connection.read_preferences().policy.destination_token) is None
        calls=receiving[2].send.call_count
        assert not connection.send_controls() and receiving[2].send.call_count==calls
        assert not connection._controls._faulted and not root.exists() and held.is_dir()
    finally:held.rename(root)


def test_corrupt_original_metadata_is_unready_and_preserved_without_rewriting_grants(receiving):
    connection=receiving[3];anchor(receiving);before=connection._local();owner=connection._mappings
    blob=owner._db.execute('SELECT payload FROM owner').fetchone()[0]
    broken=blob[:-1]+bytes([blob[-1]^1])
    with owner._db:owner._db.execute('UPDATE owner SET payload=?',(broken,))
    current=connection._local()
    assert current.grants==before.grants and not current.policy_ready and owner._uncertain
    assert not connection._controls._faulted and owner._db.execute('SELECT payload FROM owner').fetchone()[0]==broken


def test_actual_held_mapping_io_lease_is_thread_bound_and_does_not_fabricate_new_consent(receiving,monkeypatch):
    connection=receiving[3];anchor(receiving);receiver,_,_=save(receiving,publish=False)
    before=connection._local();owner=connection._mappings;protect=owner._protect;checked=[]
    def inspect(value,label):
        if label.startswith('mapping/'):
            assert owner._validation_lease is not None
            local=connection._local()
            assert local.policy_ready and local.grants==before.grants
            other=[];errors=[]
            def read_other():
                try:other.append(connection._local())
                except Exception as error:errors.append(error)
            worker=threading.Thread(target=read_other);worker.start();worker.join(5)
            assert not worker.is_alive() and not errors and len(other)==1
            assert not other[0].policy_ready and other[0].grants==before.grants
            assert connection._receive_binding()==receiver._accepted.binding
            assert not connection._controls._faulted
            checked.append(True)
        return protect(value,label)
    monkeypatch.setattr(owner,'_protect',inspect)
    connection.publish_received(connection.issue_receive_action())
    assert checked==[True] and owner._validation_lease is None
    assert connection._local().policy_ready and len(saved_messages(receiving))==1


def test_expired_metadata_action_cannot_keep_native_readiness_or_send_saved_but_new_retry_preserves_edit(receiving,monkeypatch):
    connection=receiving[3];anchor(receiving);receiver,_,_=save(receiving,publish=False)
    before=connection._local();owner=connection._mappings;clock=[100];owner._clock=lambda:clock[0]
    protect=owner._protect;expired=[]
    def inspect(value,label):
        if label.startswith('mapping/') and not expired:
            clock[0]+=60_000;expired.append(True)
            local=connection._local()
            assert local.grants==before.grants and not local.policy_ready
        return protect(value,label)
    monkeypatch.setattr(owner,'_protect',inspect)
    with pytest.raises(TransferError):connection.publish_received(connection.issue_receive_action())
    assert not saved_messages(receiving) and owner._validation_lease is None
    assert not connection._controls._faulted and connection._local().policy_ready
    target=receiving[4]/receiver._index.saved_receipts()[0].relative_path;target.write_bytes(b'preserve edit after expired metadata action')
    def forbidden(*args,**kwargs):raise AssertionError('metadata retry must not republish')
    monkeypatch.setattr(receiver._publisher,'publish',forbidden)
    connection.send_saved_confirmation()
    assert target.read_bytes()==b'preserve edit after expired metadata action' and len(saved_messages(receiving))==1


def test_connection_close_revokes_held_validation_lease_but_keeps_descriptors_until_actual_io_end(receiving,monkeypatch):
    connection=receiving[3];anchor(receiving);receiver,_,_=save(receiving,publish=False)
    owner=connection._mappings;protect=owner._protect
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[]
    def blocked(value,label):
        if label.startswith('mapping/'):
            entered.set();assert release.wait(10)
        return protect(value,label)
    monkeypatch.setattr(owner,'_protect',blocked)
    def publish():
        try:connection.publish_received(connection.issue_receive_action())
        except Exception as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=publish);worker.start()
    try:
        assert entered.wait(10)
        assert connection.close() is False and owner._db is not None and owner._validation_lease is not None
        assert not connection._authority.protection._closed
        with pytest.raises(TransferError):connection._local()
        release.set();assert ended.wait(10);worker.join(5)
        assert not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
        assert owner._validation_lease is None and owner._db is None and connection._authority.protection._closed
        assert not saved_messages(receiving)
    finally:
        release.set();worker.join(5)
        assert not worker.is_alive()
