"""Persisted expected original store fences actual admission/publication/ACK."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_photo_mappings import ProtectedPhotoMappings
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,negotiate
from test_file_desktop_sources import ready_source
from test_file_desktop_media import manifest,collect,send_offer,dispatch
from test_photo_mappings import save
from test_file_desktop_mapping_save import saved_messages


def anchor(fixture):
    connection=fixture[3];owner=connection._mappings;prefs=connection._preferences
    choice=owner.bootstrap(owner.issue_action(),owner.read())
    saved=prefs.configure(prefs.issue_action(),prefs.read(),enabled=True,mode='manual',mapping_store_choice=choice)
    negotiate(*fixture[:4])
    return saved.policy.mapping_store


def displace(fixture):
    connection=fixture[3];owner=connection._mappings
    root=Path(fixture[0].store.root)/owner._name
    held=root.with_name(root.name+'-held-original')
    owner.close();root.rename(held)
    connection._mappings=ProtectedPhotoMappings(connection._authority)
    return root,held


def test_expected_missing_store_after_metadata_reopen_blocks_admission_before_reservation(receiving):
    connection=receiving[3];witness=anchor(receiving)
    ready_source(receiving);full=manifest(receiving);collect(receiving,full)
    offered,result=send_offer(receiving,full);dispatch(receiving,result)
    root,held=displace(receiving)
    try:
        with pytest.raises(TransferError,match='expected_missing'):
            connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
        assert connection._catalog is None and connection._run is None and not root.exists()
        assert not list(receiving[4].iterdir()) and connection.read_preferences().policy.mapping_store==witness
    finally:held.rename(root)


def test_expected_missing_store_blocks_first_media_publication_without_creating_empty_replacement(receiving):
    connection=receiving[3];anchor(receiving)
    receiver,_,_=save(receiving,publish=False)
    root,held=displace(receiving)
    try:
        with pytest.raises(TransferError,match='expected_missing'):
            connection.publish_received(connection.issue_receive_action())
        assert all(not (receiving[4]/path).exists() for _,path in receiver._accepted.targets)
        assert not root.exists() and held.is_dir() and not saved_messages(receiving)
    finally:held.rename(root)


def test_expected_missing_store_blocks_saved_retry_and_keeps_original_file_and_historical_metadata(receiving):
    connection=receiving[3];anchor(receiving)
    receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action())
    target=receiving[4]/receiver._index.saved_receipts()[0].relative_path
    target.write_bytes(b'keep edit after save')
    root,held=displace(receiving)
    try:
        with pytest.raises(TransferError,match='expected_missing'):connection.send_saved_confirmation()
        assert not root.exists() and held.is_dir() and len(saved_messages(receiving))==1
        assert target.read_bytes()==b'keep edit after save'
    finally:held.rename(root)
